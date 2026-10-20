"""
AnnaRakshak — Background Product Image Discovery & Queue Reliability Tests
==========================================================================
Validates the 20 core backend requirements for background product image discovery:
  1. Confirmed product is saved before image discovery completes.
  2. Background job is created for the correct product.
  3. Suitable catalog image is discovered, validated, and saved.
  4. Search queries broaden appropriately when initial searches fail.
  5. Transient errors schedule bounded retries (0s, 30s, 120s, 600s).
  6. HTTP 429 handling respects retry guidance (Retry-After).
  7. Permanent failures do not trigger endless retries.
  8. Exhausted retries leave the product intact.
  9. No-match results do not cause endless searches.
  10. Duplicate jobs are handled idempotently.
  11. Concurrent workers cannot corrupt the same product's image state.
  12. Deleted products are not recreated by old jobs.
  13. Stale jobs cannot overwrite newer identity information.
  14. Manual image selections are never overwritten.
  15. Existing valid images survive failed discovery.
  16. Unrelated product fields remain unchanged (dates, categories, notes).
  17. Job recovery works after an interrupted/stalled worker attempt.
  18. Existing image-fetching security controls remain intact.
  19. Unsafe URLs, private IPs, and invalid image formats remain rejected.
  20. Existing barcode and catalog matching behavior is preserved.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import httpx
import numpy as np
from starlette.testclient import TestClient

from api import app, get_analyzer, get_db
from gemini_analyzer import FoodAnalysisResult
from image_job_worker import (
    calculate_retry_delay,
    is_transient_error,
    process_due_image_jobs,
    process_image_discovery_job,
)
from inventory_db import InventoryDatabase, ProductRecord
from product_image_resolver import (
    ImageMetadata,
    ImageResolutionStatus,
    ProductImageResolver,
    generate_search_queries,
    score_candidate,
)


class TestBackgroundImageDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="annarakshak_test_bg_img_")
        self.db_path = Path(self.temp_dir) / "test.db"
        self.cache_dir = Path(self.temp_dir) / "image_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.db = InventoryDatabase(db_path=self.db_path)
        self.resolver = ProductImageResolver(cache_dir=self.cache_dir)

        # Wire dependency overrides for FastAPI TestClient
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

        # Generate dummy 100x100 JPEG test image
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:] = (120, 180, 240)
        _, buf = cv2.imencode(".jpg", img)
        self.dummy_jpeg = buf.tobytes()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Requirement 1: Confirmed product is saved before image discovery completes
    # -------------------------------------------------------------------------
    @patch("api.process_image_discovery_job")
    def test_01_confirmed_product_saved_promptly_before_discovery_completes(self, mock_bg_worker):
        # Even if background discovery worker is slow or delayed, product is immediately created
        payload = {
            "product_name": "Organic Rolled Oats",
            "brand": "True Elements",
            "food_category": "Grains & Cereals",
            "date_type": "expiry",
            "normalized_date": "2026-12-31",
            "date_status": "confirmed",
            "quantity": "500g",
        }
        resp = self.client.post("/api/products", json=payload)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("id", data)
        prod_id = data["id"]

        # Product is immediately in inventory
        prod = self.db.get_product(prod_id)
        self.assertIsNotNone(prod)
        self.assertEqual(prod.product_name, "Organic Rolled Oats")
        self.assertEqual(prod.normalized_date, "2026-12-31")

    # -------------------------------------------------------------------------
    # Requirement 2: Background job is created for the correct product
    # -------------------------------------------------------------------------
    def test_02_background_job_created_for_correct_product(self):
        prod_id = self.db.add_product(
            product_name="Greek Yogurt",
            brand="Epigamia",
            food_category="Dairy & Eggs",
            normalized_date="2026-11-15",
        )
        job_id = self.db.create_image_job(
            product_id=prod_id,
            normalized_identity="Epigamia Greek Yogurt",
        )
        self.assertGreater(job_id, 0)
        job = self.db.get_image_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.product_id, prod_id)
        self.assertEqual(job.normalized_identity, "Epigamia Greek Yogurt")
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.attempt_count, 0)

    # -------------------------------------------------------------------------
    # Requirement 3: Suitable catalog image is discovered, validated, and saved
    # -------------------------------------------------------------------------
    def test_03_suitable_catalog_image_discovered_validated_and_saved(self):
        prod_id = self.db.add_product(
            product_name="Whole Milk",
            brand="Amul",
            food_category="Dairy & Eggs",
            notes="Barcode: 8901262010053",
        )
        job_id = self.db.create_image_job(prod_id, "Amul Whole Milk")

        # Mock resolver finding a verified catalog image
        mock_resolver = MagicMock(spec=ProductImageResolver)
        mock_resolver.resolve_product_image.return_value = ImageMetadata(
            source="open_food_facts_barcode",
            original_url="https://images.openfoodfacts.org/images/products/amul_milk.jpg",
            cached_path="/cache/amul_milk.jpg",
            status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
            barcode="8901262010053",
            product_identity="Amul Whole Milk",
        )

        success = process_image_discovery_job(job_id, self.db, resolver=mock_resolver)
        self.assertTrue(success)

        # Verify job and product state
        job = self.db.get_image_job(job_id)
        self.assertEqual(job.status, "resolved")

        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_status, "resolved")
        self.assertEqual(prod.image_path, "https://images.openfoodfacts.org/images/products/amul_milk.jpg")
        self.assertEqual(prod.image_source_type, "catalog")
        self.assertIsNotNone(prod.image_metadata)
        self.assertEqual(prod.image_metadata.get("source"), "open_food_facts_barcode")

    # -------------------------------------------------------------------------
    # Requirement 4: Search queries broaden appropriately when initial searches fail
    # -------------------------------------------------------------------------
    def test_04_search_queries_broaden_appropriately(self):
        queries = generate_search_queries("Dairy Milk Silk Brownie 130g", "Cadbury")
        # Starts specific with brand + name, then progressive variants
        self.assertIn("Cadbury Dairy Milk Silk Brownie 130g", queries)
        # Contains brand + flavor or subset tokens
        self.assertTrue(any("cadbury" in q.lower() and "brownie" in q.lower() for q in queries))

        # Brandless item
        queries_brandless = generate_search_queries("Bhajani Chakli", "")
        self.assertEqual(queries_brandless, ["Bhajani Chakli"])

    # -------------------------------------------------------------------------
    # Requirement 5: Transient errors schedule bounded retries (0s, 30s, 120s, 600s)
    # -------------------------------------------------------------------------
    def test_05_transient_errors_schedule_bounded_retries(self):
        self.assertEqual(calculate_retry_delay(0), 0.0)
        self.assertEqual(calculate_retry_delay(1), 30.0)
        self.assertEqual(calculate_retry_delay(2), 120.0)
        self.assertEqual(calculate_retry_delay(3), 600.0)
        self.assertEqual(calculate_retry_delay(4), 600.0)

        prod_id = self.db.add_product("Choco Cookies", brand="Britannia")
        job_id = self.db.create_image_job(prod_id, "Britannia Choco Cookies")

        mock_resolver = MagicMock(spec=ProductImageResolver)
        mock_resolver.resolve_product_image.side_effect = httpx.ConnectTimeout("Connection timed out")

        # Attempt 1 fails with transient timeout -> schedules retry attempt 2 (~30s)
        success = process_image_discovery_job(job_id, self.db, resolver=mock_resolver)
        self.assertFalse(success)

        job = self.db.get_image_job(job_id)
        self.assertEqual(job.status, "retry_scheduled")
        self.assertEqual(job.attempt_count, 1)
        self.assertIn("ConnectTimeout", job.last_error)

        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_status, "retry_scheduled")

    # -------------------------------------------------------------------------
    # Requirement 6: HTTP 429 handling respects retry guidance (Retry-After)
    # -------------------------------------------------------------------------
    def test_06_http_429_respects_retry_after(self):
        req = httpx.Request("GET", "https://world.openfoodfacts.org/api/v2/test")
        resp = httpx.Response(429, headers={"Retry-After": "45"}, request=req)
        exc = httpx.HTTPStatusError("Too Many Requests", request=req, response=resp)

        is_retryable, retry_after = is_transient_error(exc)
        self.assertTrue(is_retryable)
        self.assertEqual(retry_after, 45.0)

        delay = calculate_retry_delay(1, retry_after=retry_after)
        self.assertEqual(delay, 45.0)  # max(30.0, 45.0)

    # -------------------------------------------------------------------------
    # Requirement 7: Permanent failures do not trigger endless retries
    # -------------------------------------------------------------------------
    def test_07_permanent_failures_do_not_retry(self):
        prod_id = self.db.add_product("Corrupted Data Item")
        job_id = self.db.create_image_job(prod_id, "Corrupted Data Item")

        mock_resolver = MagicMock(spec=ProductImageResolver)
        # Permanent format / argument error
        mock_resolver.resolve_product_image.side_effect = ValueError("Malformed catalog response")

        process_image_discovery_job(job_id, self.db, resolver=mock_resolver)
        job = self.db.get_image_job(job_id)
        self.assertEqual(job.status, "failed")

        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_status, "failed")

    # -------------------------------------------------------------------------
    # Requirement 8: Exhausted retries leave the product intact
    # -------------------------------------------------------------------------
    def test_08_exhausted_retries_leave_product_intact(self):
        prod_id = self.db.add_product(
            product_name="Mango Drink",
            brand="Frooti",
            food_category="Beverages",
            normalized_date="2027-05-10",
            notes="Stored in pantry",
        )
        job_id = self.db.create_image_job(prod_id, "Frooti Mango Drink", max_attempts=2)

        mock_resolver = MagicMock(spec=ProductImageResolver)
        mock_resolver.resolve_product_image.side_effect = httpx.NetworkError("Network down")

        # Attempt 1
        process_image_discovery_job(job_id, self.db, resolver=mock_resolver)
        job = self.db.get_image_job(job_id)
        self.assertEqual(job.status, "retry_scheduled")

        # Fast-forward next_eligible_at to simulate time passing
        with self.db._get_connection() as conn:
            conn.execute("UPDATE image_discovery_jobs SET next_eligible_at = '2020-01-01T00:00:00' WHERE id = ?", (job_id,))

        # Attempt 2 (exhausts max_attempts=2)
        process_image_discovery_job(job_id, self.db, resolver=mock_resolver)
        job = self.db.get_image_job(job_id)
        self.assertEqual(job.status, "failed")

        # Product remains intact with all dates and notes preserved!
        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.product_name, "Mango Drink")
        self.assertEqual(prod.brand, "Frooti")
        self.assertEqual(prod.normalized_date, "2027-05-10")
        self.assertEqual(prod.notes, "Stored in pantry")
        self.assertEqual(prod.image_status, "failed")

    # -------------------------------------------------------------------------
    # Requirement 9: No-match results do not cause endless searches
    # -------------------------------------------------------------------------
    def test_09_no_match_results_do_not_cause_endless_searches(self):
        prod_id = self.db.add_product("Obscure Local Biscuit")
        job_id = self.db.create_image_job(prod_id, "Obscure Local Biscuit")

        mock_resolver = MagicMock(spec=ProductImageResolver)
        # Discovery completes successfully but finds no acceptable image candidate
        mock_resolver.resolve_product_image.return_value = ImageMetadata(
            source="category_fallback",
            original_url=None,
            cached_path=None,
            status=ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH,
            barcode=None,
            product_identity="Obscure Local Biscuit",
        )

        success = process_image_discovery_job(job_id, self.db, resolver=mock_resolver)
        self.assertTrue(success)

        job = self.db.get_image_job(job_id)
        self.assertEqual(job.status, "no_match")
        self.assertIsNotNone(job.completed_at)

        # Due jobs query must NOT return no_match jobs for further retries
        due = self.db.get_due_image_jobs()
        self.assertEqual(len(due), 0)

        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_status, "no_match")

    # -------------------------------------------------------------------------
    # Requirement 10: Duplicate jobs are handled idempotently
    # -------------------------------------------------------------------------
    def test_10_duplicate_jobs_handled_idempotently(self):
        prod_id = self.db.add_product("Chili Flakes", brand="Keya")
        job_id_1 = self.db.create_image_job(prod_id, "Keya Chili Flakes")
        job_id_2 = self.db.create_image_job(prod_id, "Keya Chili Flakes")
        self.assertEqual(job_id_1, job_id_2)

    # -------------------------------------------------------------------------
    # Requirement 11: Concurrent workers cannot corrupt the same product's image state
    # -------------------------------------------------------------------------
    def test_11_concurrent_workers_atomic_claim(self):
        prod_id = self.db.add_product("Basmati Rice 5kg", brand="India Gate")
        job_id = self.db.create_image_job(prod_id, "India Gate Basmati Rice 5kg")

        claimed_results = []

        def worker_claim():
            return self.db.claim_image_job(job_id)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker_claim) for _ in range(5)]
            for f in concurrent.futures.as_completed(futures):
                claimed_results.append(f.result())

        # Exactly ONE thread can succeed in claiming the job
        self.assertEqual(claimed_results.count(True), 1)
        self.assertEqual(claimed_results.count(False), 4)

    # -------------------------------------------------------------------------
    # Requirement 12: Deleted products are not recreated by old jobs
    # -------------------------------------------------------------------------
    def test_12_deleted_products_not_recreated(self):
        prod_id = self.db.add_product("Disposable Beverage", brand="TestBrand")
        job_id = self.db.create_image_job(prod_id, "TestBrand Disposable Beverage")

        # Delete product
        self.db.delete_product(prod_id)
        self.assertIsNone(self.db.get_product(prod_id))

        # Attempt to apply image resolution
        res = self.db.apply_resolved_product_image(
            product_id=prod_id,
            job_id=job_id,
            image_path="https://example.com/item.jpg",
        )
        self.assertFalse(res)
        self.assertIsNone(self.db.get_product(prod_id))

    # -------------------------------------------------------------------------
    # Requirement 13: Stale jobs cannot overwrite newer identity information
    # -------------------------------------------------------------------------
    def test_13_stale_jobs_cannot_overwrite_modified_identity(self):
        prod_id = self.db.add_product("Original Bread", brand="BrandA")
        job_id = self.db.create_image_job(prod_id, "BrandA Original Bread")

        # User updates product name to Butter
        self.db.update_product(prod_id, product_name="Salted Butter", brand="BrandB")

        # Background worker attempts to apply result for old identity
        res = self.db.apply_resolved_product_image(
            product_id=prod_id,
            job_id=job_id,
            image_path="https://example.com/bread.jpg",
        )
        self.assertFalse(res)

        # Product image remains untouched
        prod = self.db.get_product(prod_id)
        self.assertNotEqual(prod.image_path, "https://example.com/bread.jpg")

    # -------------------------------------------------------------------------
    # Requirement 14: Manual image selections are never overwritten
    # -------------------------------------------------------------------------
    def test_14_manual_image_selections_never_overwritten(self):
        prod_id = self.db.add_product("Custom Pasta", brand="Barilla")
        job_id = self.db.create_image_job(prod_id, "Barilla Custom Pasta")

        # User manually uploads or selects their own image
        self.db.update_product(
            prod_id,
            image_path="/user_uploads/my_custom_pasta.png",
            image_source_type="manual",
            image_status="resolved",
        )

        mock_resolver = MagicMock(spec=ProductImageResolver)
        mock_resolver.resolve_product_image.return_value = ImageMetadata(
            source="open_food_facts",
            original_url="https://images.openfoodfacts.org/barilla.jpg",
            cached_path=None,
            status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
            barcode=None,
            product_identity="Barilla Custom Pasta",
        )

        # Discovery worker runs
        process_image_discovery_job(job_id, self.db, resolver=mock_resolver)

        # Manual image is preserved!
        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_path, "/user_uploads/my_custom_pasta.png")
        self.assertEqual(prod.image_source_type, "manual")

    # -------------------------------------------------------------------------
    # Requirement 15: Existing valid images survive failed discovery
    # -------------------------------------------------------------------------
    def test_15_existing_valid_images_survive_failed_discovery(self):
        prod_id = self.db.add_product(
            "Orange Juice",
            brand="Tropicana",
            image_path="https://existing.cdn/orange.jpg",
            image_status="resolved",
        )
        job_id = self.db.create_image_job(prod_id, "Tropicana Orange Juice")

        # Discovery completes with no match
        self.db.apply_no_match_product_image(prod_id, job_id)

        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_path, "https://existing.cdn/orange.jpg")

    # -------------------------------------------------------------------------
    # Requirement 16: Unrelated product fields remain unchanged
    # -------------------------------------------------------------------------
    def test_16_unrelated_product_fields_remain_unchanged(self):
        prod_id = self.db.add_product(
            product_name="Almond Milk",
            brand="Silk",
            food_category="Dairy & Eggs",
            date_type="best_before",
            date_text="BEST BEFORE 12/26",
            normalized_date="2026-12-01",
            date_status="confirmed",
            date_source="user_confirmed",
            notes="Stored on top fridge shelf | Quantity: 1L",
        )
        job_id = self.db.create_image_job(prod_id, "Silk Almond Milk")

        self.db.apply_resolved_product_image(
            product_id=prod_id,
            job_id=job_id,
            image_path="https://example.com/silk.jpg",
            image_source_type="catalog",
        )

        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.product_name, "Almond Milk")
        self.assertEqual(prod.brand, "Silk")
        self.assertEqual(prod.food_category, "Dairy & Eggs")
        self.assertEqual(prod.date_type, "best_before")
        self.assertEqual(prod.date_text, "BEST BEFORE 12/26")
        self.assertEqual(prod.normalized_date, "2026-12-01")
        self.assertEqual(prod.date_status, "confirmed")
        self.assertEqual(prod.date_source, "user_confirmed")
        self.assertEqual(prod.notes, "Stored on top fridge shelf | Quantity: 1L")
        self.assertEqual(prod.image_path, "https://example.com/silk.jpg")

    # -------------------------------------------------------------------------
    # Requirement 17: Job recovery works after an interrupted/stalled attempt
    # -------------------------------------------------------------------------
    def test_17_stalled_job_recovery(self):
        prod_id = self.db.add_product("Stalled Item", brand="BrandX")
        job_id = self.db.create_image_job(prod_id, "BrandX Stalled Item", max_attempts=4)

        # Put job in searching state with an old last_attempt_at (e.g. 10 minutes ago)
        old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)).isoformat()
        with self.db._get_connection() as conn:
            conn.execute(
                """
                UPDATE image_discovery_jobs
                SET status = 'searching', last_attempt_at = ?, attempt_count = 1
                WHERE id = ?
                """,
                (old_time, job_id),
            )

        # Run recovery
        recovered = self.db.recover_stalled_jobs(stalled_seconds=300)
        self.assertEqual(recovered, 1)

        job = self.db.get_image_job(job_id)
        self.assertEqual(job.status, "retry_scheduled")

    # -------------------------------------------------------------------------
    # Requirement 18: Existing image-fetching security tests still pass
    # -------------------------------------------------------------------------
    def test_18_security_private_network_rejection(self):
        from product_image_resolver import is_safe_public_url, is_ip_disallowed

        # RFC 1918 private IPs
        self.assertTrue(is_ip_disallowed("127.0.0.1"))
        self.assertTrue(is_ip_disallowed("10.0.0.1"))
        self.assertTrue(is_ip_disallowed("192.168.1.1"))
        self.assertTrue(is_ip_disallowed("169.254.169.254"))
        self.assertTrue(is_ip_disallowed("100.64.0.1"))

        # Non-HTTPS URL
        is_safe, err = is_safe_public_url("http://insecure.example.com/test.jpg")
        self.assertFalse(is_safe)
        self.assertIn("HTTPS", err)

    # -------------------------------------------------------------------------
    # Requirement 19: Unsafe URLs, redirects, oversized downloads remain rejected
    # -------------------------------------------------------------------------
    def test_19_oversized_download_rejected(self):
        from product_image_resolver import download_and_validate_web_image

        mock_client = MagicMock(spec=httpx.Client)
        # Mock oversized streaming response (6 MB > 5 MB limit)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/jpeg", "Content-Length": str(6 * 1024 * 1024)}
        mock_resp.iter_bytes.return_value = [b"X" * (1024 * 1024) for _ in range(6)]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        mock_client.stream.return_value = mock_resp

        success, path, meta, err = download_and_validate_web_image(
            "https://example.com/huge.jpg",
            target_dir=self.cache_dir,
            client=mock_client,
        )
        self.assertFalse(success)
        self.assertIn("exceeds limit", err.lower())

    # -------------------------------------------------------------------------
    # Requirement 20: Existing barcode and catalog matching behavior preserved
    # -------------------------------------------------------------------------
    def test_20_exact_barcode_matching_preserved(self):
        from barcode_detector import is_valid_gtin_checksum

        # Valid GTIN
        self.assertTrue(is_valid_gtin_checksum("5901234123457"))
        # Invalid checksum
        self.assertFalse(is_valid_gtin_checksum("012345678909"))

        # Candidate scoring prioritizes exact brand + name match
        score_exact = score_candidate("Amul", "Taaza Fresh Toned Milk", "Amul", "Taaza Fresh Toned Milk", has_front_img=True)
        score_diff = score_candidate("Mother Dairy", "Cow Milk", "Amul", "Taaza Fresh Toned Milk", has_front_img=False)
        self.assertGreater(score_exact, score_diff)
        self.assertGreater(score_exact, 80.0)


if __name__ == "__main__":
    unittest.main()
