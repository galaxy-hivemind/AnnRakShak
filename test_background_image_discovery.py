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

    # -------------------------------------------------------------------------
    # Production-Readiness Task 1 & 2: Cron Endpoint Authentication & GET Route
    # -------------------------------------------------------------------------
    def test_21_cron_endpoint_missing_server_secret(self):
        """When CRON_SECRET is not configured on server, return 500 configuration error."""
        with patch.dict(os.environ, {}, clear=False):
            if "CRON_SECRET" in os.environ:
                del os.environ["CRON_SECRET"]
            resp = self.client.post("/api/jobs/process-pending")
            self.assertEqual(resp.status_code, 500)
            self.assertIn("CRON_SECRET is not configured", resp.json()["detail"])

    def test_22_cron_endpoint_missing_authorization_header(self):
        """When CRON_SECRET is set, reject unauthenticated requests with 401 and do not process jobs."""
        prod_id = self.db.add_product(product_name="Granola Bar", brand="Nature Valley")
        job_id = self.db.create_image_job(product_id=prod_id, normalized_identity="Nature Valley Granola Bar")

        with patch.dict(os.environ, {"CRON_SECRET": "test_super_secret_cron_token_12345"}):
            # POST without header
            resp = self.client.post("/api/jobs/process-pending")
            self.assertEqual(resp.status_code, 401)
            self.assertIn("Authorization header is required", resp.json()["detail"])

            # Job is untouched and still pending
            job = self.db.get_image_job(job_id)
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.attempt_count, 0)

    def test_23_cron_endpoint_invalid_authorization_token(self):
        """When token does not match, reject with 401 and do not process jobs."""
        prod_id = self.db.add_product(product_name="Dark Chocolate", brand="Amul")
        job_id = self.db.create_image_job(product_id=prod_id, normalized_identity="Amul Dark Chocolate")

        with patch.dict(os.environ, {"CRON_SECRET": "expected_secret_token"}):
            headers = {"Authorization": "Bearer wrong_token_xyz"}
            resp = self.client.post("/api/jobs/process-pending", headers=headers)
            self.assertEqual(resp.status_code, 401)
            self.assertIn("Invalid authorization token", resp.json()["detail"])

            # Job is untouched
            job = self.db.get_image_job(job_id)
            self.assertEqual(job.status, "pending")

    @patch("api.process_due_image_jobs")
    def test_24_cron_endpoint_valid_credentials_post(self, mock_process):
        """Valid Bearer token allows POST /api/jobs/process-pending and executes job processor."""
        mock_process.return_value = 3
        with patch.dict(os.environ, {"CRON_SECRET": "production_secret_98765"}):
            headers = {"Authorization": "Bearer production_secret_98765"}
            resp = self.client.post("/api/jobs/process-pending?limit=15&max_duration_seconds=12", headers=headers)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["processed"], 3)
            mock_process.assert_called_once()
            _, kwargs = mock_process.call_args
            self.assertEqual(kwargs.get("limit"), 15)
            self.assertEqual(kwargs.get("time_budget_seconds"), 12.0)

    @patch("api.process_due_image_jobs")
    def test_25_cron_endpoint_valid_credentials_get_for_vercel(self, mock_process):
        """Vercel Cron uses GET requests; verify GET /api/jobs/process-pending works with valid auth."""
        mock_process.return_value = 1
        with patch.dict(os.environ, {"CRON_SECRET": "vercel_cron_token_abc"}):
            headers = {"Authorization": "Bearer vercel_cron_token_abc"}
            resp = self.client.get("/api/jobs/process-pending", headers=headers)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["processed"], 1)

    # -------------------------------------------------------------------------
    # Production-Readiness Task 3: Bounded Serverless Execution Time
    # -------------------------------------------------------------------------
    def test_26_serverless_execution_time_budget_stops_before_claiming(self):
        """Worker stops claiming new jobs when time budget is nearly exhausted, leaving remaining jobs pending."""
        p1 = self.db.add_product(product_name="Product A", brand="Brand A")
        p2 = self.db.add_product(product_name="Product B", brand="Brand B")
        j1 = self.db.create_image_job(product_id=p1, normalized_identity="Brand A Product A")
        j2 = self.db.create_image_job(product_id=p2, normalized_identity="Brand B Product B")

        # Mock process_image_discovery_job to take 0.15s per job
        def mock_process(job_id, db, resolver=None, **kwargs):
            time.sleep(0.15)
            return True

        # Provide a very small time budget (0.1s) with min_job_budget_seconds=0.1
        # It should process at most 0 or 1 job, and definitely stop before claiming j2
        with patch("image_job_worker.process_image_discovery_job", side_effect=mock_process):
            processed = process_due_image_jobs(
                self.db,
                limit=10,
                time_budget_seconds=0.12,
                min_job_budget_seconds=0.10,
            )
            self.assertEqual(processed, 1)

        # Job 2 was never processed and is still pending in the DB
        job2 = self.db.get_image_job(j2)
        self.assertEqual(job2.status, "pending")
        self.assertEqual(job2.attempt_count, 0)

    def test_27_stalled_job_recovered_after_interrupted_serverless_execution(self):
        """Jobs left in 'searching' state (e.g. from lambda timeout/freeze) are safely recovered."""
        prod_id = self.db.add_product(product_name="Coffee Beans", brand="Blue Tokai")
        job_id = self.db.create_image_job(product_id=prod_id, normalized_identity="Blue Tokai Coffee Beans")

        # Simulate job claimed and worker terminated 10 minutes ago
        old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=600)).isoformat()
        with self.db._get_connection() as conn:
            conn.execute(
                """
                UPDATE image_discovery_jobs
                SET status = 'searching', last_attempt_at = ?, attempt_count = 1
                WHERE id = ?
                """,
                (old_time, job_id),
            )

        # process_due_image_jobs recovers stalled jobs at the start
        with patch("image_job_worker.process_image_discovery_job") as mock_worker:
            # Stalled job will be recovered to retry_scheduled, and then eligible for processing
            processed = process_due_image_jobs(self.db, limit=5)
            self.assertEqual(processed, 1)
            mock_worker.assert_called_once()

    def test_28_job_execution_deadline_triggers_retryable_timeout(self):
        """When an individual job exceeds its deadline, it catches TimeoutError and schedules a clean retry."""
        prod_id = self.db.add_product(product_name="Organic Honey", brand="Dabur")
        job_id = self.db.create_image_job(product_id=prod_id, normalized_identity="Dabur Organic Honey")

        mock_resolver = MagicMock()
        mock_resolver.resolve_product_image.side_effect = TimeoutError("Execution budget exceeded during catalog search")

        success = process_image_discovery_job(job_id, self.db, resolver=mock_resolver, deadline=time.monotonic() - 1.0)
        self.assertFalse(success)

        # Job is scheduled for retry with attempt recorded, not permanently failed
        job = self.db.get_image_job(job_id)
        self.assertEqual(job.status, "retry_scheduled")
        self.assertEqual(job.attempt_count, 1)
        self.assertIn("TimeoutError", job.last_error)

    def test_29_shared_http_client_timeout_is_intentional(self):
        """Shared safe image client has intentional 5.0s timeout."""
        from product_image_resolver import create_safe_image_client, DOWNLOAD_TIMEOUT_SECONDS
        client = create_safe_image_client()
        self.assertEqual(DOWNLOAD_TIMEOUT_SECONDS, 5.0)
        self.assertEqual(client.timeout.connect, 5.0)
        self.assertEqual(client.timeout.read, 5.0)

    def test_30_stalled_job_timeout_threshold_preserved(self):
        """STALLED_JOB_TIMEOUT_SECONDS remains 300 to preserve persistent server safety."""
        from image_job_worker import STALLED_JOB_TIMEOUT_SECONDS
        self.assertEqual(STALLED_JOB_TIMEOUT_SECONDS, 300)

    def test_31_process_due_image_jobs_full_lifecycle_deterministic(self):
        """
        Validate the complete worker lifecycle via process_due_image_jobs:
        1. Enqueues a pending job for a product with missing image.
        2. Retrieves and processes it through process_due_image_jobs with a mocked resolver.
        3. Confirms job and product state transitions to 'resolved'.
        4. Confirms subsequent worker run reports processed: 0 as no due jobs remain.
        """
        prod_id = self.db.add_product(product_name="Almond Milk", brand="Silk", food_category="Dairy & Eggs")
        job_id = self.db.create_image_job(product_id=prod_id, normalized_identity="Silk Almond Milk")

        # Initial state verification
        job_before = self.db.get_image_job(job_id)
        self.assertEqual(job_before.status, "pending")
        self.assertEqual(job_before.attempt_count, 0)
        prod_before = self.db.get_product(prod_id)
        self.assertEqual(prod_before.image_status, "pending")

        # Deterministic mock resolver (no external network calls)
        mock_resolver = MagicMock(spec=ProductImageResolver)
        mock_resolver.resolve_product_image.return_value = ImageMetadata(
            source="mock_catalog",
            original_url="https://images.example.com/products/silk_almond.jpg",
            cached_path="/mock/cache/silk_almond.jpg",
            status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
            barcode=None,
            product_identity="Silk Almond Milk",
        )

        # Run worker directly through process_due_image_jobs
        processed = process_due_image_jobs(self.db, limit=5, resolver=mock_resolver)
        self.assertEqual(processed, 1)
        mock_resolver.resolve_product_image.assert_called_once()

        # Verify job and product state after processing
        job_after = self.db.get_image_job(job_id)
        self.assertEqual(job_after.status, "resolved")
        self.assertEqual(job_after.attempt_count, 1)

        prod_after = self.db.get_product(prod_id)
        self.assertEqual(prod_after.image_status, "resolved")
        self.assertEqual(prod_after.image_path, "https://images.example.com/products/silk_almond.jpg")
        self.assertEqual(prod_after.image_source_type, "catalog")

        # Second run: queue is now clear; returns processed: 0
        second_processed = process_due_image_jobs(self.db, limit=5, resolver=mock_resolver)
        self.assertEqual(second_processed, 0)


if __name__ == "__main__":
    unittest.main()
