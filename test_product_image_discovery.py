"""
Tests for Intelligent Product Image Discovery, Barcode Identification & Persistent Image Caching
Covering all 20 scenarios from Section 10 of requirements.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import httpx
import numpy as np
from fastapi.testclient import TestClient

from api import app, get_db, get_analyzer
from barcode_detector import (
    is_valid_gtin_checksum,
    extract_barcode_from_ocr,
    detect_barcode_from_cv_image,
    resolve_scanned_barcode,
)
from gemini_analyzer import FoodAnalysisResult, DateCandidate
from inventory_db import InventoryDatabase
from product_image_resolver import (
    ProductImageResolver,
    ImageMetadata,
    ImageResolutionStatus,
    is_safe_public_url,
    validate_and_decode_image_bytes,
    download_and_validate_web_image,
    SafeSSRFTransport,
    PinnedSyncBackend,
    create_safe_image_client,
)


def create_dummy_jpeg(width: int = 200, height: int = 200, color: tuple[int, int, int] = (100, 150, 200)) -> bytes:
    img = np.full((height, width, 3), color, dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", img)
    assert success
    return encoded.tobytes()


class TestProductImageDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_inventory.db"
        self.captures_dir = Path(self.temp_dir) / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(self.temp_dir) / "image_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        os.environ["ANNARAKSHAK_CAPTURES_DIR"] = str(self.captures_dir)

        self.db = InventoryDatabase(db_path=self.db_path)
        self.db.init_db()

        self.resolver = ProductImageResolver(cache_dir=self.cache_dir)

        self.client = TestClient(app)
        app.dependency_overrides[get_db] = lambda: self.db

        self.dummy_jpeg = create_dummy_jpeg(300, 300)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Scenario 1: Exact barcode match retrieves the correct product image
    # -------------------------------------------------------------------------
    def test_exact_barcode_match_retrieves_image(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 1,
            "product": {
                "product_name": "Organic Whole Milk",
                "brands": "Horizon Organic",
                "image_front_url": "https://images.openfoodfacts.org/images/products/5901234123457/front_en.jpg",
            },
        }
        mock_client.get.return_value = mock_resp

        with patch("product_image_resolver.download_and_validate_web_image") as mock_dl:
            cached_file = str(self.cache_dir / "5901234123457.jpg")
            mock_dl.return_value = (
                True,
                self.dummy_jpeg,
                {"cached_path": cached_file, "content_type": "image/jpeg", "width": 300, "height": 300},
                "",
            )
            with patch.object(self.resolver, "_get_client", return_value=mock_client):
                meta = self.resolver.resolve_product_image(
                    product_name="Organic Whole Milk",
                    brand="Horizon Organic",
                    barcode="5901234123457",
                    category="Dairy & Eggs",
                )

        self.assertEqual(meta.status, ImageResolutionStatus.VERIFIED_WEB_IMAGE)
        self.assertEqual(meta.source, "open_food_facts_barcode")
        self.assertEqual(meta.barcode, "5901234123457")
        self.assertIn("openfoodfacts.org", meta.original_url or "")

    # -------------------------------------------------------------------------
    # Scenario 2: Barcode unavailable; exact product-name and brand match retrieves valid image
    # -------------------------------------------------------------------------
    def test_name_and_brand_match_retrieves_image(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "count": 1,
            "products": [
                {
                    "code": "8901030000000",
                    "product_name": "Choco Chip Cookies",
                    "brands": "Britannia",
                    "image_url": "https://images.openfoodfacts.org/images/products/8901030000000/front.jpg",
                }
            ],
        }
        mock_client.get.return_value = mock_resp

        with patch("product_image_resolver.download_and_validate_web_image") as mock_dl:
            cached_file = str(self.cache_dir / "britannia_choco.jpg")
            mock_dl.return_value = (
                True,
                self.dummy_jpeg,
                {"cached_path": cached_file, "content_type": "image/jpeg", "width": 300, "height": 300},
                "",
            )
            with patch.object(self.resolver, "_get_client", return_value=mock_client):
                meta = self.resolver.resolve_product_image(
                    product_name="Choco Chip Cookies",
                    brand="Britannia",
                    barcode=None,
                    category="Snacks",
                )

        self.assertEqual(meta.status, ImageResolutionStatus.VERIFIED_WEB_IMAGE)
        self.assertEqual(meta.source, "open_food_facts_search")

    # -------------------------------------------------------------------------
    # Scenario 3: Product identity is too uncertain; no misleading image is selected
    # -------------------------------------------------------------------------
    def test_uncertain_product_identity_no_misleading_image(self):
        meta = self.resolver.resolve_product_image(
            product_name="Item",
            brand="",
            barcode=None,
            category="Pantry Staples",
        )
        self.assertEqual(meta.status, ImageResolutionStatus.CATEGORY_FALLBACK)
        self.assertIsNone(meta.original_url)

    # -------------------------------------------------------------------------
    # Scenario 4: External image URL returns an error; category fallback is used
    # -------------------------------------------------------------------------
    def test_external_image_url_error_falls_back(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 1,
            "product": {
                "product_name": "Some Tea",
                "image_front_url": "https://example.com/notfound.jpg",
            },
        }
        mock_client.get.return_value = mock_resp

        with patch("product_image_resolver.download_and_validate_web_image") as mock_dl:
            mock_dl.return_value = (False, None, {}, "HTTP 404 Not Found")
            with patch.object(self.resolver, "_get_client", return_value=mock_client):
                meta = self.resolver.resolve_product_image(
                    product_name="Some Tea",
                    brand="Brand X",
                    barcode="012345678905",
                )

        self.assertIn(meta.status, (ImageResolutionStatus.CATEGORY_FALLBACK, ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH))
        self.assertIsNone(meta.original_url)

    # -------------------------------------------------------------------------
    # Scenario 5: External URL returns HTML instead of image data; candidate is rejected
    # -------------------------------------------------------------------------
    def test_external_url_returns_html_rejected(self):
        html_content = b"<!DOCTYPE html><html><body>Error 403 Forbidden</body></html>"
        is_valid, width, height, err = validate_and_decode_image_bytes(html_content, "https://example.com/blocked.jpg")
        self.assertFalse(is_valid)
        self.assertEqual(width, 0)
        self.assertIn("HTML", err)

    # -------------------------------------------------------------------------
    # Scenario 6: Image is corrupted, oversized, or below minimum dimensions; rejected
    # -------------------------------------------------------------------------
    def test_corrupted_oversized_underdimensioned_rejected(self):
        # 1. Corrupted bytes
        corrupted = b"\xff\xd8\xff\xe0garbage12345"
        is_valid, _, _, err = validate_and_decode_image_bytes(corrupted, "https://example.com/corrupt.jpg")
        self.assertFalse(is_valid)

        # 2. Oversized bytes (> 5 MB)
        oversized = b"0" * (6 * 1024 * 1024)
        is_valid, _, _, err = validate_and_decode_image_bytes(oversized, "https://example.com/large.jpg")
        self.assertFalse(is_valid)
        self.assertIn("exceeds limit", err)

        # 3. Under-dimensioned image (e.g. 50x50 icon)
        tiny_jpeg = create_dummy_jpeg(50, 50)
        is_valid, _, _, err = validate_and_decode_image_bytes(tiny_jpeg, "https://example.com/tiny.jpg")
        self.assertFalse(is_valid)
        self.assertIn("below minimum", err)

    # -------------------------------------------------------------------------
    # Scenario 7: Unsafe URL, private IP, or malicious redirect is rejected (SSRF protection)
    # -------------------------------------------------------------------------
    def test_unsafe_url_private_ip_ssrf_rejected(self):
        unsafe_urls = [
            "http://example.com/image.jpg",                # HTTP not HTTPS
            "https://127.0.0.1/secret.jpg",                # Loopback IPv4
            "https://localhost/image.png",                 # Localhost
            "https://10.0.0.1/admin.png",                  # RFC1918 Private class A
            "https://192.168.1.1/router.jpg",              # RFC1918 Private class C
            "https://172.16.0.1/server.jpg",               # RFC1918 Private class B
            "https://169.254.169.254/latest/meta-data/",   # AWS / Cloud link-local metadata
            "ftp://files.example.com/img.jpg",             # Non-HTTP protocol
            "javascript:alert(1)",                         # XSS scheme
        ]
        for url in unsafe_urls:
            is_safe, reason = is_safe_public_url(url)
            self.assertFalse(is_safe, f"URL '{url}' should be rejected for SSRF: {reason}")

    # -------------------------------------------------------------------------
    # Scenario 8: Gemini fails; image retrieval failure does not break the scan
    # -------------------------------------------------------------------------
    def test_gemini_failure_scan_isolation(self):
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            analysis_status="error",
            needs_review=True,
            review_reason="Gemini 503 unavailable",
        )

        app.dependency_overrides[get_analyzer] = lambda: mock_analyzer
        try:
            resp = self.client.post(
                "/api/scans",
                files={"image": ("test.jpg", self.dummy_jpeg, "image/jpeg")},
            )
            # Scan returns 201 with analysis_status=error or needs_review=True without breaking
            self.assertIn(resp.status_code, (200, 201))
            data = resp.json()
            self.assertTrue(data["needs_review"])
            self.assertEqual(data["analysis_status"], "error")
        finally:
            if get_analyzer in app.dependency_overrides:
                del app.dependency_overrides[get_analyzer]

    # -------------------------------------------------------------------------
    # Scenario 9: Existing captured evidence remains available after web image selected
    # -------------------------------------------------------------------------
    def test_existing_captured_evidence_remains_available(self):
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Organic Whole Milk",
            brand="Horizon",
            food_category="Dairy & Eggs",
            barcode="5901234123457",
            date_candidates=[
                DateCandidate(
                    raw_text="2026-11-20",
                    date_type="expiry",
                    normalized_date="2026-11-20",
                    confidence=0.98,
                    evidence="EXP 2026-11-20",
                )
            ],
            selected_expiry_date="2026-11-20",
            analysis_status="success",
            needs_review=False,
        )
        app.dependency_overrides[get_analyzer] = lambda: mock_analyzer

        # Mock image discovery to return a verified web image
        with patch("api.get_image_resolver") as mock_get_res:
            res_mock = MagicMock()
            res_mock.resolve_product_image.return_value = ImageMetadata(
                source="open_food_facts_barcode",
                original_url="https://images.openfoodfacts.org/front.jpg",
                cached_path=None,
                status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                barcode="5901234123457",
                product_identity="Organic Whole Milk",
            )
            mock_get_res.return_value = res_mock

            resp = self.client.post(
                "/api/scans",
                files={"image": ("scan_evidence.jpg", self.dummy_jpeg, "image/jpeg")},
            )
            self.assertEqual(resp.status_code, 201)
            scan_data = resp.json()
            scan_id = scan_data["id"]

            # 1. Product got verified image URL
            prod_id = scan_data["product_id"]
            self.assertIsNotNone(prod_id)
            prod = self.db.get_product(prod_id)
            self.assertEqual(prod.image_path, "https://images.openfoodfacts.org/front.jpg")

            # 2. Original captured photo remains accessible via /api/scans/{id}/image
            img_resp = self.client.get(f"/api/scans/{scan_id}/image")
            self.assertEqual(img_resp.status_code, 200)
            self.assertEqual(img_resp.headers["content-type"], "image/jpeg")

    # -------------------------------------------------------------------------
    # Scenario 10: A previously verified image is preserved during later edits and confirmations
    # -------------------------------------------------------------------------
    def test_verified_image_preserved_during_edits_confirmations(self):
        prod_id = self.db.add_product(
            product_name="Cough Syrup",
            brand="Benadryl",
            food_category="Medicine",
            date_type="expiry",
            normalized_date="2027-01-01",
            date_status="confirmed",
            image_path="https://example.com/verified_bottle.jpg",
        )
        p = self.db.get_product(prod_id)
        self.assertEqual(p.image_path, "https://example.com/verified_bottle.jpg")

        # Edit date and name without providing image_path
        patch_resp = self.client.patch(
            f"/api/products/{prod_id}",
            json={"product_name": "Benadryl Cough Formula", "normalized_date": "2027-02-01"},
        )
        self.assertEqual(patch_resp.status_code, 200)
        updated = self.db.get_product(prod_id)
        self.assertEqual(updated.image_path, "https://example.com/verified_bottle.jpg")

    # -------------------------------------------------------------------------
    # Scenario 11: First scan finds verified web image; supplementary scans perform NO new search
    # -------------------------------------------------------------------------
    def test_first_scan_finds_image_supplementary_no_new_search(self):
        # 1. First scan
        verified_meta = ImageMetadata(
            source="open_food_facts_barcode",
            original_url="https://images.openfoodfacts.org/milk.jpg",
            cached_path=None,
            status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
            barcode="5901234123457",
            product_identity="Horizon Whole Milk",
        )
        scan_id = self.db.record_scan(
            image_path=str(self.captures_dir / "primary.jpg"),
            result=FoodAnalysisResult(
                product_name="Horizon Whole Milk",
                brand="Horizon",
                barcode="5901234123457",
                food_category="Dairy & Eggs",
                analysis_status="success",
                needs_review=False,
            ),
            image_metadata=verified_meta.to_dict(),
        )

        # 2. Supplementary scan with mock resolver
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Horizon Whole Milk",
            date_candidates=[
                DateCandidate(
                    raw_text="2026-12-15",
                    date_type="expiry",
                    normalized_date="2026-12-15",
                    confidence=0.99,
                    evidence="EXP 2026-12-15",
                )
            ],
            selected_expiry_date="2026-12-15",
            analysis_status="success",
            needs_review=False,
        )
        app.dependency_overrides[get_analyzer] = lambda: mock_analyzer

        with patch.object(ProductImageResolver, "_lookup_open_food_facts_barcode") as mock_off_bar, \
             patch.object(ProductImageResolver, "_lookup_open_food_facts_search") as mock_off_search:
            resp = self.client.post(
                f"/api/scans/{scan_id}/supplementary",
                files={"image": ("supp.jpg", self.dummy_jpeg, "image/jpeg")},
            )
            self.assertEqual(resp.status_code, 200)
            # Verify no network lookup functions were invoked
            mock_off_bar.assert_not_called()
            mock_off_search.assert_not_called()

        updated_scan = self.db.get_scan(scan_id)
        self.assertEqual(updated_scan.image_metadata["status"], "verified_web_image")

    # -------------------------------------------------------------------------
    # Scenario 12: First scan finds no image; subsequent supplementary scans do not repeatedly search
    # -------------------------------------------------------------------------
    def test_first_scan_no_image_supplementary_no_repeated_search(self):
        no_match_meta = ImageMetadata(
            source="category_fallback",
            original_url=None,
            cached_path=None,
            status=ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH,
            barcode=None,
            product_identity="Generic Biscuits",
        )
        scan_id = self.db.record_scan(
            image_path=str(self.captures_dir / "primary2.jpg"),
            result=FoodAnalysisResult(
                product_name="Generic Biscuits",
                food_category="Snacks",
                analysis_status="needs_review",
                needs_review=True,
            ),
            image_metadata=no_match_meta.to_dict(),
        )

        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Generic Biscuits",
            date_candidates=[],
            analysis_status="needs_review",
            needs_review=True,
        )
        app.dependency_overrides[get_analyzer] = lambda: mock_analyzer

        with patch.object(ProductImageResolver, "_lookup_open_food_facts_search") as mock_off_search:
            resp = self.client.post(
                f"/api/scans/{scan_id}/supplementary",
                files={"image": ("supp2.jpg", self.dummy_jpeg, "image/jpeg")},
            )
            self.assertEqual(resp.status_code, 200)
            # Search was not repeated on supplementary capture because identity did not change and no barcode was found
            mock_off_search.assert_not_called()

    # -------------------------------------------------------------------------
    # Scenario 13: A newly resolved barcode allows one justified new lookup
    # -------------------------------------------------------------------------
    def test_newly_resolved_barcode_allows_one_lookup(self):
        # 1. Primary scan had no barcode and no match
        no_match_meta = ImageMetadata(
            source="category_fallback",
            original_url=None,
            cached_path=None,
            status=ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH,
            barcode=None,
            product_identity="Tomato Soup",
        )
        scan_id = self.db.record_scan(
            image_path=str(self.captures_dir / "soup_front.jpg"),
            result=FoodAnalysisResult(
                product_name="Tomato Soup",
                brand="Campbell",
                food_category="Pantry Staples",
                barcode=None,
                analysis_status="needs_review",
                needs_review=True,
            ),
            image_metadata=no_match_meta.to_dict(),
        )

        # 2. Supplementary scan captures barcode back side
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Tomato Soup",
            brand="Campbell",
            barcode="005100000011",
            analysis_status="success",
            needs_review=False,
        )
        app.dependency_overrides[get_analyzer] = lambda: mock_analyzer

        with patch("product_image_resolver.ProductImageResolver._lookup_open_food_facts_barcode") as mock_lookup:
            mock_lookup.return_value = ImageMetadata(
                source="open_food_facts_barcode",
                original_url="https://images.openfoodfacts.org/campbell_soup.jpg",
                cached_path=None,
                status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                barcode="005100000011",
                product_identity="Campbell Tomato Soup",
            )
            resp = self.client.post(
                f"/api/scans/{scan_id}/supplementary",
                files={"image": ("soup_back.jpg", self.dummy_jpeg, "image/jpeg")},
            )
            self.assertEqual(resp.status_code, 200)
            mock_lookup.assert_called_once_with("005100000011", "Campbell Tomato Soup", unittest.mock.ANY)

        updated_scan = self.db.get_scan(scan_id)
        self.assertEqual(updated_scan.image_metadata["status"], "verified_web_image")

    # -------------------------------------------------------------------------
    # Scenario 14: Failed supplementary analysis does not erase the current image
    # -------------------------------------------------------------------------
    def test_failed_supplementary_analysis_does_not_erase_image(self):
        verified_meta = ImageMetadata(
            source="open_food_facts_barcode",
            original_url="https://images.openfoodfacts.org/apple_juice.jpg",
            cached_path=None,
            status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
            barcode="012345678905",
            product_identity="Apple Juice",
        )
        scan_id = self.db.record_scan(
            image_path=str(self.captures_dir / "juice.jpg"),
            result=FoodAnalysisResult(
                product_name="Apple Juice",
                food_category="Beverages",
                analysis_status="success",
                needs_review=False,
            ),
            image_metadata=verified_meta.to_dict(),
        )

        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Unknown",
            analysis_status="error",
            needs_review=True,
            review_reason="Blurry image",
        )
        app.dependency_overrides[get_analyzer] = lambda: mock_analyzer

        resp = self.client.post(
            f"/api/scans/{scan_id}/supplementary",
            files={"image": ("blurry.jpg", self.dummy_jpeg, "image/jpeg")},
        )
        self.assertEqual(resp.status_code, 200)
        updated = self.db.get_scan(scan_id)
        self.assertEqual(updated.image_metadata["status"], "verified_web_image")
        self.assertEqual(updated.image_metadata["original_url"], "https://images.openfoodfacts.org/apple_juice.jpg")

    # -------------------------------------------------------------------------
    # Scenario 15: Concurrent supplementary requests do not create duplicate searches
    # -------------------------------------------------------------------------
    def test_concurrent_supplementary_requests_safe(self):
        scan_id = self.db.record_scan(
            image_path=str(self.captures_dir / "concurrent_scan.jpg"),
            result=FoodAnalysisResult(
                product_name="Mineral Water",
                brand="Evian",
                barcode="3068320114057",
                food_category="Beverages",
                analysis_status="success",
                needs_review=False,
            ),
        )

        call_count = 0
        call_lock = threading.Lock()

        def slow_lookup(*args, **kwargs):
            nonlocal call_count
            with call_lock:
                call_count += 1
            import time
            time.sleep(0.05)
            return ImageMetadata(
                source="open_food_facts_barcode",
                original_url="https://images.openfoodfacts.org/evian.jpg",
                cached_path=None,
                status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                barcode="3068320114057",
                product_identity="Evian Mineral Water",
            )

        with patch.object(self.resolver, "_lookup_open_food_facts_barcode", side_effect=slow_lookup):
            results = []

            def worker():
                meta = self.resolver.resolve_product_image(
                    product_name="Mineral Water",
                    brand="Evian",
                    barcode="3068320114057",
                    category="Beverages",
                )
                results.append(meta)

            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Concurrency deduplication ensures only 1 external call was made
            self.assertEqual(call_count, 1)
            for res in results:
                self.assertEqual(res.status, ImageResolutionStatus.VERIFIED_WEB_IMAGE)

    # -------------------------------------------------------------------------
    # Scenario 16: Image-search failure does not break evidence merging and expiry rules
    # -------------------------------------------------------------------------
    def test_image_search_failure_preserves_evidence_merging(self):
        scan_id = self.db.record_scan(
            image_path=str(self.captures_dir / "dairy.jpg"),
            result=FoodAnalysisResult(
                product_name="Cheddar Cheese",
                food_category="Dairy & Eggs",
                analysis_status="needs_review",
                needs_review=True,
            ),
        )

        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Cheddar Cheese",
            date_candidates=[
                DateCandidate(
                    raw_text="2027-05-10",
                    date_type="expiry",
                    normalized_date="2027-05-10",
                    confidence=0.97,
                    evidence="EXP: 10/05/2027",
                )
            ],
            selected_expiry_date="2027-05-10",
            analysis_status="success",
            needs_review=False,
        )
        app.dependency_overrides[get_analyzer] = lambda: mock_analyzer

        # Force image resolver to fail
        with patch("api.get_image_resolver") as mock_res:
            res_mock = MagicMock()
            res_mock.resolve_product_image.side_effect = Exception("Catalog network timeout")
            mock_res.return_value = res_mock

            resp = self.client.post(
                f"/api/scans/{scan_id}/supplementary",
                files={"image": ("supp_date.jpg", self.dummy_jpeg, "image/jpeg")},
            )
            # Scan should succeed and merge evidence regardless of image search failure
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["auto_saved"])
            self.assertEqual(data["selected_expiry_date"], "2027-05-10")

    # -------------------------------------------------------------------------
    # Scenario 17: Fallback image is correctly chosen for product category
    # -------------------------------------------------------------------------
    def test_fallback_image_correctly_chosen_for_category(self):
        with patch.object(self.resolver, "_lookup_open_food_facts_search", return_value=None):
            meta = self.resolver.resolve_product_image(
                product_name="White Flour",
                brand="",
                barcode=None,
                category="Grains & Cereals",
            )
        self.assertIn(meta.status, (ImageResolutionStatus.CATEGORY_FALLBACK, ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH))

    # -------------------------------------------------------------------------
    # Scenario 18: Manually selected image is preserved
    # -------------------------------------------------------------------------
    def test_manually_selected_image_preserved(self):
        prod_id = self.db.add_product(
            product_name="Custom Blend Coffee",
            date_type="best_before",
            normalized_date="2026-12-31",
            image_path="captures/user_chosen_photo.jpg",
        )
        p = self.db.get_product(prod_id)
        self.assertEqual(p.image_path, "captures/user_chosen_photo.jpg")

    # -------------------------------------------------------------------------
    # Scenario 19: Existing SQLite records and Postgres-compatible serialization work
    # -------------------------------------------------------------------------
    def test_sqlite_records_and_postgres_compatibility(self):
        scan_id = self.db.record_scan(
            image_path=str(self.captures_dir / "compat.jpg"),
            result=FoodAnalysisResult(
                product_name="Almond Milk",
                brand="Silk",
                barcode="025293000987",
                food_category="Dairy & Eggs",
                analysis_status="success",
                needs_review=False,
            ),
            image_metadata={
                "source": "open_food_facts_barcode",
                "image_status": "verified_web_image",
                "image_url": "https://images.openfoodfacts.org/silk.jpg",
                "barcode": "025293000987",
            },
        )
        rec = self.db.get_scan(scan_id)
        self.assertIsNotNone(rec)
        d = rec.to_dict()
        self.assertIn("image_metadata", d)
        self.assertEqual(d["image_metadata"]["image_status"], "verified_web_image")

    # -------------------------------------------------------------------------
    # Scenario 20: GET /api/products/{id}/image backward-compatible redirect and serving
    # -------------------------------------------------------------------------
    def test_inventory_cards_and_image_endpoints_backward_compatible(self):
        # 1. Product with remote HTTPS URL redirects via 307
        prod_id_remote = self.db.add_product(
            product_name="Orange Juice",
            date_type="expiry",
            normalized_date="2026-12-01",
            image_path="https://images.openfoodfacts.org/juice.jpg",
        )
        res_remote = self.client.get(f"/api/products/{prod_id_remote}/image", follow_redirects=False)
        self.assertEqual(res_remote.status_code, 307)
        self.assertEqual(res_remote.headers["location"], "https://images.openfoodfacts.org/juice.jpg")

        # 2. Product with local file path serves the image
        local_img = self.captures_dir / "product_photo.jpg"
        local_img.write_bytes(self.dummy_jpeg)
        prod_id_local = self.db.add_product(
            product_name="Fresh Carrots",
            date_type="best_before",
            normalized_date="2026-11-01",
            image_path=str(local_img),
        )
        res_local = self.client.get(f"/api/products/{prod_id_local}/image")
        self.assertEqual(res_local.status_code, 200)
        self.assertEqual(res_local.headers["content-type"], "image/jpeg")

        # 3. Product with no image returns 404 prompting client fallback
        prod_id_none = self.db.add_product(
            product_name="Brown Rice",
            date_type="best_before",
            normalized_date="2028-01-01",
            image_path=None,
        )
        res_none = self.client.get(f"/api/products/{prod_id_none}/image")
        self.assertEqual(res_none.status_code, 404)

    # -------------------------------------------------------------------------
    # Scenario 21: Valid GTIN invokes exact-barcode lookup
    # -------------------------------------------------------------------------
    def test_valid_gtin_invokes_exact_barcode_lookup(self):
        with patch.object(self.resolver, "_lookup_open_food_facts_barcode") as mock_off_bar:
            mock_off_bar.return_value = ImageMetadata(
                source="open_food_facts_barcode",
                original_url="https://images.openfoodfacts.org/valid.jpg",
                cached_path=None,
                status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                barcode="5901234123457",
                product_identity="Test Product",
            )
            meta = self.resolver.resolve_product_image(
                product_name="Test Product",
                brand="Test Brand",
                barcode="5901234123457",
                category="Snacks",
            )
            mock_off_bar.assert_called_once_with("5901234123457", "Test Brand Test Product", unittest.mock.ANY)
            self.assertEqual(meta.status, ImageResolutionStatus.VERIFIED_WEB_IMAGE)

    # -------------------------------------------------------------------------
    # Scenario 22: Invalid GTIN skips exact-barcode lookup and falls back to Stage 2
    # -------------------------------------------------------------------------
    def test_invalid_gtin_skips_barcode_lookup_and_falls_back(self):
        with patch.object(self.resolver, "_lookup_open_food_facts_barcode") as mock_off_bar, \
             patch.object(self.resolver, "_lookup_open_food_facts_search") as mock_off_search:
            mock_off_search.return_value = ImageMetadata(
                source="open_food_facts_search",
                original_url="https://images.openfoodfacts.org/found_by_name.jpg",
                cached_path=None,
                status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                barcode=None,
                product_identity="Test Brand Test Product",
            )
            # 0042421000028 has an invalid check digit
            meta = self.resolver.resolve_product_image(
                product_name="Test Product",
                brand="Test Brand",
                barcode="0042421000028",
                category="Snacks",
            )
            # Stage 1 barcode lookup must NOT be called for invalid GTIN
            mock_off_bar.assert_not_called()
            # Stage 2 search lookup should be called instead
            mock_off_search.assert_called_once()
            self.assertEqual(meta.status, ImageResolutionStatus.VERIFIED_WEB_IMAGE)

    # -------------------------------------------------------------------------
    # Scenario 23: Product without barcode uses name-and-brand search
    # -------------------------------------------------------------------------
    def test_product_without_barcode_uses_name_brand_lookup(self):
        with patch.object(self.resolver, "_lookup_open_food_facts_barcode") as mock_off_bar, \
             patch.object(self.resolver, "_lookup_open_food_facts_search") as mock_off_search:
            mock_off_search.return_value = ImageMetadata(
                source="open_food_facts_search",
                original_url="https://images.openfoodfacts.org/name_only.jpg",
                cached_path=None,
                status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                barcode=None,
                product_identity="Artisan Bread",
            )
            meta = self.resolver.resolve_product_image(
                product_name="Artisan Bread",
                brand="",
                barcode=None,
                category="Bakery",
            )
            mock_off_bar.assert_not_called()
            mock_off_search.assert_called_once()
            self.assertEqual(meta.status, ImageResolutionStatus.VERIFIED_WEB_IMAGE)


class TestBarcodeDetector(unittest.TestCase):
    def test_gtin_checksum(self):
        self.assertTrue(is_valid_gtin_checksum("012345678905"))
        self.assertTrue(is_valid_gtin_checksum("5901234123457"))
        self.assertFalse(is_valid_gtin_checksum("012345678909"))  # Bad checksum digit
        self.assertFalse(is_valid_gtin_checksum("12345"))          # Too short

    def test_extract_barcode_from_ocr(self):
        ocr = "Net Wt 500g \n 012345678905 \n MFD 2026-01-01"
        found = extract_barcode_from_ocr(ocr)
        self.assertEqual(found, "012345678905")

        # Invalid checksum in OCR should be rejected
        bad_ocr = "Batch 1234567890129"
        self.assertIsNone(extract_barcode_from_ocr(bad_ocr))

    def test_optical_priority_over_conflicting_valid_ai(self):
        """Optical OpenCV detection must take precedence over valid OCR and AI candidates."""
        with patch("barcode_detector.detect_barcode_from_file", return_value="5901234123457"):
            resolved = resolve_scanned_barcode(
                image_path="test_frame.jpg",
                ocr_text="Found barcode 012345678905 on box",
                ai_barcode="3068320114057",
            )
            self.assertEqual(resolved, "5901234123457")

    def test_ocr_priority_when_optical_none(self):
        """When optical detection yields nothing, valid OCR candidate takes precedence over AI."""
        with patch("barcode_detector.detect_barcode_from_file", return_value=None):
            resolved = resolve_scanned_barcode(
                image_path="test_frame.jpg",
                ocr_text="Found barcode 012345678905 on box",
                ai_barcode="3068320114057",
            )
            self.assertEqual(resolved, "012345678905")

    def test_ai_used_when_optical_and_ocr_none(self):
        """When optical and OCR detection yield nothing, valid AI candidate is used."""
        with patch("barcode_detector.detect_barcode_from_file", return_value=None):
            resolved = resolve_scanned_barcode(
                image_path="test_frame.jpg",
                ocr_text="Pure descriptive text without numbers",
                ai_barcode="3068320114057",
            )
            self.assertEqual(resolved, "3068320114057")

    def test_invalid_checksums_rejected_across_all_sources(self):
        """Candidates from any source with invalid GTIN checksums must be rejected."""
        with patch("barcode_detector.detect_barcode_from_file", return_value=None):
            resolved = resolve_scanned_barcode(
                image_path="test_frame.jpg",
                ocr_text="Batch 1234567890129",
                ai_barcode="0042421000028",  # Invalid checksum
            )
            self.assertIsNone(resolved)

    def test_failed_optical_detection_handled_gracefully(self):
        """Optical detection failure or exception must not raise an error or crash scanning."""
        with patch("barcode_detector.detect_barcode_from_file", side_effect=Exception("OpenCV decode error")):
            # Should not crash; gracefully falls back to OCR / AI
            resolved = resolve_scanned_barcode(
                image_path="corrupt.jpg",
                ocr_text="Barcode: 012345678905",
                ai_barcode=None,
            )
            self.assertEqual(resolved, "012345678905")


class TestRedirectSSRFAndStreaming(unittest.TestCase):
    """Targeted regression tests for SSRF redirect handling, streaming byte limits, and DNS rebinding."""

    def setUp(self):
        self.dummy_jpeg = create_dummy_jpeg(200, 200)
        self.dns_patcher = patch("socket.getaddrinfo", side_effect=self._mock_getaddrinfo)
        self.dns_patcher.start()

    def tearDown(self):
        self.dns_patcher.stop()

    def _mock_getaddrinfo(self, host, port, *args, **kwargs):
        # Resolve public test hostnames to public IP 93.184.216.34 (example.com)
        if host in ("public.example.com", "cdn1.example.com", "cdn2.example.com"):
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port or 443))]
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port or 443))]

    def test_redirect_to_loopback_rejected(self):
        """Redirect to 127.0.0.1 must be rejected without making internal request."""
        def handler(request: httpx.Request):
            if request.url == "https://public.example.com/product.jpg":
                return httpx.Response(302, headers={"Location": "https://127.0.0.1/admin.jpg"})
            self.fail("Request should never reach the redirected destination")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, _, _, err = download_and_validate_web_image("https://public.example.com/product.jpg", client=client)
        self.assertFalse(success)
        self.assertIn("SSRF", err)

    def test_redirect_to_metadata_ip_rejected(self):
        """Redirect to AWS/GCP cloud metadata IP 169.254.169.254 must be blocked."""
        def handler(request: httpx.Request):
            if request.url == "https://public.example.com/item.jpg":
                return httpx.Response(302, headers={"Location": "https://169.254.169.254/latest/meta-data"})
            self.fail("Request should never reach the cloud metadata IP")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, _, _, err = download_and_validate_web_image("https://public.example.com/item.jpg", client=client)
        self.assertFalse(success)
        self.assertIn("SSRF", err)

    def test_redirect_to_non_https_rejected(self):
        """Redirects to non-HTTPS destinations (e.g. http://) must be rejected."""
        def handler(request: httpx.Request):
            if request.url == "https://public.example.com/start":
                return httpx.Response(302, headers={"Location": "http://public.example.com/insecure.jpg"})
            self.fail("Insecure HTTP destination should not be requested")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, _, _, err = download_and_validate_web_image("https://public.example.com/start", client=client)
        self.assertFalse(success)
        self.assertIn("HTTPS", err)

    def test_redirect_loop_detected_and_rejected(self):
        """Redirect loops (A -> B -> A) must be detected and aborted without recursion or infinite loop."""
        def handler(request: httpx.Request):
            if request.url == "https://public.example.com/hopA":
                return httpx.Response(302, headers={"Location": "https://public.example.com/hopB"})
            elif request.url == "https://public.example.com/hopB":
                return httpx.Response(302, headers={"Location": "https://public.example.com/hopA"})
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, _, _, err = download_and_validate_web_image("https://public.example.com/hopA", client=client)
        self.assertFalse(success)
        self.assertIn("redirect loop", err)

    def test_too_many_redirects_rejected(self):
        """Redirect chains exceeding MAX_REDIRECTS (3) must be stopped."""
        def handler(request: httpx.Request):
            url_str = str(request.url)
            if "hop1" in url_str:
                return httpx.Response(302, headers={"Location": "https://public.example.com/hop2"})
            elif "hop2" in url_str:
                return httpx.Response(302, headers={"Location": "https://public.example.com/hop3"})
            elif "hop3" in url_str:
                return httpx.Response(302, headers={"Location": "https://public.example.com/hop4"})
            elif "hop4" in url_str:
                return httpx.Response(302, headers={"Location": "https://public.example.com/hop5"})
            return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=self.dummy_jpeg)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, _, _, err = download_and_validate_web_image("https://public.example.com/hop1", client=client)
        self.assertFalse(success)
        self.assertIn("Too many redirects", err)

    def test_relative_redirect_resolved_and_succeeds(self):
        """Relative Location headers must be properly resolved against the current URL."""
        def handler(request: httpx.Request):
            if request.url == "https://public.example.com/products/item1":
                return httpx.Response(302, headers={"Location": "/static/images/final.jpg"})
            elif request.url == "https://public.example.com/static/images/final.jpg":
                return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=self.dummy_jpeg)
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, data, meta, err = download_and_validate_web_image("https://public.example.com/products/item1", client=client)
        self.assertTrue(success, f"Failed with: {err}")
        self.assertIsNotNone(data)
        self.assertEqual(meta["width"], 200)
        self.assertEqual(meta["height"], 200)

    def test_valid_redirect_between_public_https_urls_succeeds(self):
        """Permitted redirect from one valid public HTTPS host to another must succeed."""
        def handler(request: httpx.Request):
            if request.url == "https://cdn1.example.com/shortlink":
                return httpx.Response(301, headers={"Location": "https://cdn2.example.com/full_photo.jpg"})
            elif request.url == "https://cdn2.example.com/full_photo.jpg":
                return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=self.dummy_jpeg)
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, data, meta, err = download_and_validate_web_image("https://cdn1.example.com/shortlink", client=client)
        self.assertTrue(success, f"Failed with: {err}")
        self.assertIsNotNone(data)

    def test_url_with_credentials_rejected(self):
        """URLs containing credentials (user:pass) must be rejected immediately."""
        success, _, _, err = download_and_validate_web_image("https://admin:secret@public.example.com/pic.jpg")
        self.assertFalse(success)
        self.assertIn("credentials", err.lower())

    def test_dns_rebinding_socket_check(self):
        """Connected socket returning a disallowed private IP is rejected post-connect."""
        class MockNetworkStream:
            def get_extra_info(self, name):
                if name == "server_addr":
                    return ("10.0.0.1", 443)  # Private RFC 1918 address
                return None

        def handler(request: httpx.Request):
            resp = httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=self.dummy_jpeg)
            resp.extensions["network_stream"] = MockNetworkStream()
            return resp

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, _, _, err = download_and_validate_web_image("https://public.example.com/photo.jpg", client=client)
        self.assertFalse(success)
        self.assertIn("DNS rebinding", err)

    def test_oversized_declared_content_length_rejected_upfront(self):
        """Declared Content-Length > 5MB must be rejected without streaming or reading body."""
        read_attempted = False

        class TrackedStream(httpx.SyncByteStream):
            def __iter__(self):
                nonlocal read_attempted
                read_attempted = True
                yield b"X" * 1024

        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                headers={"Content-Type": "image/jpeg", "Content-Length": "10485760"},  # 10 MB
                stream=TrackedStream(),
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, _, _, err = download_and_validate_web_image("https://public.example.com/huge.jpg", client=client)
        self.assertFalse(success)
        self.assertIn("exceeds limit", err)
        self.assertFalse(read_attempted, "Stream content should not be read when declared length is oversized")

    def test_oversized_stream_without_content_length_aborted_immediately(self):
        """Chunked response without Content-Length must abort mid-stream immediately upon exceeding 5MB."""
        chunks_yielded = 0

        class InfiniteChunkStream(httpx.SyncByteStream):
            def __iter__(self):
                nonlocal chunks_yielded
                for _ in range(1000):  # 1000 * 16384 = 16.38 MB
                    chunks_yielded += 1
                    yield b"X" * 16384

        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                headers={"Content-Type": "image/jpeg"},  # No Content-Length
                stream=InfiniteChunkStream(),
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, _, _, err = download_and_validate_web_image("https://public.example.com/stream.jpg", client=client)
        self.assertFalse(success)
        self.assertIn("exceeds limit", err)
        # Should stop after reaching ~5MB (321 chunks), not 1000 chunks
        self.assertLess(chunks_yielded, 400)

    def test_valid_image_streamed_and_decoded(self):
        """Valid JPEG within size limit is streamed, parsed, and validated."""
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                headers={"Content-Type": "image/jpeg", "Content-Length": str(len(self.dummy_jpeg))},
                content=self.dummy_jpeg,
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        success, data, meta, err = download_and_validate_web_image("https://public.example.com/good.jpg", client=client)
        self.assertTrue(success, f"Failed with: {err}")
        self.assertEqual(len(data), len(self.dummy_jpeg))
        self.assertEqual(meta["width"], 200)
        self.assertEqual(meta["height"], 200)

    def test_dns_rebinding_blocked_before_socket_connection(self):
        """
        DNS Rebinding attack: Hostname resolves to public IP during pre-validation,
        but rebinds to loopback 127.0.0.1 at connection time.
        Must be blocked BEFORE any socket connection to 127.0.0.1 is made.
        """
        dns_call_counts = {}

        def mock_rebind_dns(host, port, *args, **kwargs):
            count = dns_call_counts.get(host, 0) + 1
            dns_call_counts[host] = count
            if host == "rebind.example.com":
                if count == 1:
                    # Initial validation: returns public IP
                    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port or 443))]
                else:
                    # Connection time: rebinds to 127.0.0.1
                    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", port or 443))]
            return self._mock_getaddrinfo(host, port, *args, **kwargs)

        socket_connect_destinations = []

        def mock_create_connection(address, *args, **kwargs):
            socket_connect_destinations.append(address[0])
            raise ConnectionRefusedError("Simulated refusal")

        with patch("socket.getaddrinfo", side_effect=mock_rebind_dns):
            with patch("socket.create_connection", side_effect=mock_create_connection):
                success, data, meta, err = download_and_validate_web_image("https://rebind.example.com/malicious.jpg")
                self.assertFalse(success)
                self.assertIn("SSRF", err)
                # CRITICAL: Socket must NEVER have been connected to 127.0.0.1
                self.assertNotIn("127.0.0.1", socket_connect_destinations)
                self.assertEqual(socket_connect_destinations, [])

    def test_dns_rebinding_to_cloud_metadata_blocked_before_connection(self):
        """
        DNS Rebinding attack: Hostname resolves to public IP during pre-validation,
        but rebinds to cloud metadata IP 169.254.169.254 at connection time.
        Must be blocked BEFORE socket connection to cloud metadata is established.
        """
        dns_call_counts = {}

        def mock_metadata_rebind_dns(host, port, *args, **kwargs):
            count = dns_call_counts.get(host, 0) + 1
            dns_call_counts[host] = count
            if host == "metadata.rebind.example.com":
                if count == 1:
                    # Initial validation: returns public IP
                    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port or 443))]
                else:
                    # Connection time: rebinds to 169.254.169.254
                    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("169.254.169.254", port or 443))]
            return self._mock_getaddrinfo(host, port, *args, **kwargs)

        socket_connect_destinations = []

        def mock_create_connection(address, *args, **kwargs):
            socket_connect_destinations.append(address[0])
            raise ConnectionRefusedError("Simulated refusal")

        with patch("socket.getaddrinfo", side_effect=mock_metadata_rebind_dns):
            with patch("socket.create_connection", side_effect=mock_create_connection):
                success, data, meta, err = download_and_validate_web_image("https://metadata.rebind.example.com/pic.jpg")
                self.assertFalse(success)
                self.assertIn("SSRF", err)
                # CRITICAL: Socket must NEVER have been connected to 169.254.169.254
                self.assertNotIn("169.254.169.254", socket_connect_destinations)
                self.assertEqual(socket_connect_destinations, [])

    def test_safe_ssrf_transport_blocks_private_and_metadata_directly(self):
        """SafeSSRFTransport directly blocks connection to private and metadata IPs at connection time."""
        transport = SafeSSRFTransport()
        disallowed_hosts = ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1"]

        for bad_host in disallowed_hosts:
            with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (bad_host, 443))]):
                client = httpx.Client(transport=transport)
                with self.assertRaises(httpx.ConnectError) as ctx:
                    client.get(f"https://{bad_host}/secret.jpg")
                self.assertIn("SSRF", str(ctx.exception))

    def test_redirect_to_rebinding_destination_blocked_before_transmission(self):
        """
        A public HTTPS URL redirects to a host that rebinds to a private RFC 1918 IP at connection time.
        Must be blocked before any connection is made or request bytes sent to the private address.
        """
        dns_call_counts = {}

        def mock_redirect_rebind_dns(host, port, *args, **kwargs):
            count = dns_call_counts.get(host, 0) + 1
            dns_call_counts[host] = count
            if host == "rebind.attacker.com":
                if count == 1:
                    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port or 443))]
                else:
                    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.1", port or 443))]
            return self._mock_getaddrinfo(host, port, *args, **kwargs)

        socket_connect_destinations = []

        def mock_create_connection(address, *args, **kwargs):
            socket_connect_destinations.append(address[0])
            raise ConnectionRefusedError("Simulated refusal")

        # Simulate hop 1 returning redirect to rebind.attacker.com
        # Hop 2 attempts connection via SafeSSRFTransport
        with patch("socket.getaddrinfo", side_effect=mock_redirect_rebind_dns):
            with patch("socket.create_connection", side_effect=mock_create_connection):
                success, data, meta, err = download_and_validate_web_image("https://rebind.attacker.com/final.jpg")
                self.assertFalse(success)
                self.assertIn("SSRF", err)
                self.assertNotIn("10.0.0.1", socket_connect_destinations)
                self.assertEqual(socket_connect_destinations, [])

    def test_mixed_dns_answers_rejected_before_connection(self):
        """
        Mixed DNS answers returning both public and prohibited IP addresses must be rejected,
        and socket connection must never be attempted to either address.
        """
        socket_connect_destinations = []

        def mock_create_connection(address, *args, **kwargs):
            socket_connect_destinations.append(address[0])
            raise ConnectionRefusedError("Simulated refusal")

        mixed_answers = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
        ]

        with patch("socket.getaddrinfo", return_value=mixed_answers):
            with patch("socket.create_connection", side_effect=mock_create_connection):
                success, data, meta, err = download_and_validate_web_image("https://mixed.example.com/item.jpg")
                self.assertFalse(success)
                self.assertIn("SSRF", err)
                # Socket connection must NEVER have been attempted
                self.assertEqual(socket_connect_destinations, [])

    def test_empty_dns_result_rejected_before_connection(self):
        """
        Empty DNS resolution result must fail safely and never attempt socket connection.
        """
        socket_connect_destinations = []

        def mock_create_connection(address, *args, **kwargs):
            socket_connect_destinations.append(address[0])
            raise ConnectionRefusedError("Simulated refusal")

        with patch("socket.getaddrinfo", return_value=[]):
            with patch("socket.create_connection", side_effect=mock_create_connection):
                success, data, meta, err = download_and_validate_web_image("https://empty.example.com/item.jpg")
                self.assertFalse(success)
                self.assertIn("no addresses", err.lower())
                self.assertEqual(socket_connect_destinations, [])

    def test_ipv4_mapped_ipv6_loopback_and_metadata_blocked_before_connection(self):
        """
        IPv4-mapped IPv6 addresses embedding loopback or metadata destinations must be blocked
        before any connection attempt.
        """
        socket_connect_destinations = []

        def mock_create_connection(address, *args, **kwargs):
            socket_connect_destinations.append(address[0])
            raise ConnectionRefusedError("Simulated refusal")

        for mapped_ip in ("::ffff:127.0.0.1", "::ffff:169.254.169.254"):
            socket_connect_destinations.clear()
            mapped_answer = [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (mapped_ip, 443))]
            with patch("socket.getaddrinfo", return_value=mapped_answer):
                with patch("socket.create_connection", side_effect=mock_create_connection):
                    success, data, meta, err = download_and_validate_web_image(f"https://mapped.example.com/pic.jpg")
                    self.assertFalse(success)
                    self.assertIn("SSRF", err)
                    self.assertEqual(socket_connect_destinations, [])

    def test_nat64_embedded_prohibited_ipv4_blocked_before_connection(self):
        """
        Verify that:
        1. RFC 8215 local-use NAT64 addresses (64:ff9b:1::/48) embedding loopback, private, or
           cloud metadata (even with a non-zero public-looking suffix like 64:ff9b:1:a9fe:a9:fe00:808:808)
           are rejected outright.
        2. RFC 6052 Well-Known Prefix (64:ff9b::/96) addresses embedding prohibited IPv4 destinations
           are blocked.
        3. All prohibited addresses are blocked before any socket connection is attempted.
        """
        socket_connect_destinations = []

        def mock_create_connection(address, *args, **kwargs):
            socket_connect_destinations.append(address[0])
            raise ConnectionRefusedError("Simulated refusal")

        prohibited_nat64_ips = [
            # RFC 8215 /48 embedding loopback
            "64:ff9b:1::127.0.0.1",
            "64:ff9b:1:7f00:0:100:0:0",
            # RFC 8215 /48 embedding metadata 169.254.169.254 with non-zero public-looking suffix
            "64:ff9b:1:a9fe:a9:fe00:808:808",
            # RFC 8215 /48 embedding private destinations
            "64:ff9b:1::10.0.0.1",
            "64:ff9b:1::192.168.1.1",
            # RFC 6052 /96 embedding prohibited destinations
            "64:ff9b::127.0.0.1",
            "64:ff9b::169.254.169.254",
            "64:ff9b::10.0.0.1",
        ]

        for nat64_ip in prohibited_nat64_ips:
            socket_connect_destinations.clear()
            nat64_answer = [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (nat64_ip, 443))]
            with patch("socket.getaddrinfo", return_value=nat64_answer):
                with patch("socket.create_connection", side_effect=mock_create_connection):
                    success, data, meta, err = download_and_validate_web_image("https://nat64.example.com/pic.jpg")
                    self.assertFalse(success)
                    self.assertIn("SSRF", err)
                    self.assertEqual(socket_connect_destinations, [])

    def test_nat64_wkp_public_ipv4_allowed_before_connection(self):
        """
        Existing RFC 6052 64:ff9b::/96 behavior remains correct: embedded public IPv4
        addresses are NOT rejected solely because of the NAT64 wrapper, and proceed to socket connection.
        """
        socket_connect_destinations = []

        def mock_create_connection(address, *args, **kwargs):
            socket_connect_destinations.append(address[0])
            raise ConnectionRefusedError("Simulated refusal")

        # 93.184.216.34 is public (example.com)
        public_wkp_ip = "64:ff9b::93.184.216.34"
        nat64_answer = [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (public_wkp_ip, 443))]

        with patch("socket.getaddrinfo", return_value=nat64_answer):
            with patch("socket.create_connection", side_effect=mock_create_connection):
                success, data, meta, err = download_and_validate_web_image("https://nat64pub.example.com/pic.jpg")
                self.assertFalse(success)
                # Must not be rejected by SSRF filter
                self.assertNotIn("SSRF", err)
                # Socket connection must have been attempted to the public NAT64 destination
                self.assertEqual(socket_connect_destinations, [public_wkp_ip])


class TestReliableWebImageDiscoveryAndFraming(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_inventory.db"
        self.captures_dir = Path(self.temp_dir) / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(self.temp_dir) / "image_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        os.environ["ANNARAKSHAK_CAPTURES_DIR"] = str(self.captures_dir)
        self.db = InventoryDatabase(db_path=self.db_path)
        self.db.init_db()
        self.resolver = ProductImageResolver(cache_dir=self.cache_dir)
        self.client = TestClient(app)
        app.dependency_overrides[get_db] = lambda: self.db

        self.dummy_bottle = create_dummy_jpeg(200, 800)  # Portrait bottle
        self.dummy_packet = create_dummy_jpeg(800, 300)  # Wide packet
        self.dummy_bar = create_dummy_jpeg(600, 200)     # Chocolate bar

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_exact_query_empty_broader_query_finds_image(self):
        """When an exact 5-word query returns no results, progressive broadening finds product packaging image."""
        mock_client = MagicMock()

        def mock_get(url, params=None):
            resp = MagicMock()
            resp.status_code = 200
            search_terms = (params or {}).get("search_terms", "")
            if search_terms == "Paper Boat Swing Lively Orange":
                resp.json.return_value = {"products": []}
            elif "Orange" in search_terms or "Swing" in search_terms:
                resp.json.return_value = {
                    "products": [
                        {
                            "product_name": "Swing Lively Orange",
                            "brands": "Paper Boat",
                            "image_front_url": "https://images.openfoodfacts.org/paper_boat_orange.jpg",
                        }
                    ]
                }
            else:
                resp.json.return_value = {"products": []}
            return resp

        mock_client.get.side_effect = mock_get

        with patch("product_image_resolver.download_and_validate_web_image") as mock_dl:
            mock_dl.return_value = (
                True,
                self.dummy_bottle,
                {"cached_path": str(self.cache_dir / "pb_orange.jpg"), "content_type": "image/jpeg", "width": 200, "height": 800},
                "",
            )
            with patch.object(self.resolver, "_get_client", return_value=mock_client):
                meta = self.resolver.resolve_product_image(
                    product_name="Swing Lively Orange",
                    brand="Paper Boat",
                    barcode=None,
                    category="Beverages",
                )
                self.assertIsNotNone(meta)
                self.assertTrue(meta.is_verified)
                self.assertEqual(meta.original_url, "https://images.openfoodfacts.org/paper_boat_orange.jpg")

    def test_first_candidate_irrelevant_later_candidate_matched(self):
        """When first candidate is a brand mismatch (e.g. Silk Soymilk), candidate ranking selects matching brand."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "products": [
                {
                    "product_name": "Silk Pure Almond Vanilla",
                    "brands": "Silk",
                    "image_front_url": "https://images.openfoodfacts.org/silk_almond.jpg",
                },
                {
                    "product_name": "Silk Deserts Brownie",
                    "brands": "Cadbury, Cadbury Dairy Milk",
                    "image_front_url": "https://images.openfoodfacts.org/cadbury_silk_brownie.jpg",
                },
            ]
        }
        mock_client.get.return_value = mock_resp

        with patch("product_image_resolver.download_and_validate_web_image") as mock_dl:
            mock_dl.return_value = (
                True,
                self.dummy_bar,
                {"cached_path": str(self.cache_dir / "cadbury_brownie.jpg"), "content_type": "image/jpeg", "width": 600, "height": 200},
                "",
            )
            with patch.object(self.resolver, "_get_client", return_value=mock_client):
                meta = self.resolver.resolve_product_image(
                    product_name="Dairy Milk Silk Brownie",
                    brand="Cadbury",
                    barcode=None,
                    category="Snacks",
                )
                self.assertIsNotNone(meta)
                self.assertTrue(meta.is_verified)
                self.assertEqual(meta.original_url, "https://images.openfoodfacts.org/cadbury_silk_brownie.jpg")

    def test_failed_image_url_skips_to_next_candidate(self):
        """When first ranked candidate has an inaccessible/404 image, next candidate is attempted and succeeds."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "products": [
                {
                    "product_name": "Cool Mint Antiseptic",
                    "brands": "Listerine",
                    "image_front_url": "https://images.openbeautyfacts.org/broken_listerine.jpg",
                },
                {
                    "product_name": "Cool Mint Mouthwash",
                    "brands": "Listerine",
                    "image_front_url": "https://images.openbeautyfacts.org/good_listerine.jpg",
                },
            ]
        }
        mock_client.get.return_value = mock_resp

        def mock_dl(url, **kwargs):
            if "broken" in url:
                return False, None, {}, "HTTP 404 Not Found"
            return (
                True,
                self.dummy_bottle,
                {"cached_path": str(self.cache_dir / "good_listerine.jpg"), "content_type": "image/jpeg", "width": 200, "height": 800},
                "",
            )

        with patch("product_image_resolver.download_and_validate_web_image", side_effect=mock_dl):
            with patch.object(self.resolver, "_get_client", return_value=mock_client):
                meta = self.resolver.resolve_product_image(
                    product_name="Cool Mint Mouthwash",
                    brand="Listerine",
                    barcode=None,
                    category="Pantry Staples",
                )
                self.assertIsNotNone(meta)
                self.assertTrue(meta.is_verified)
                self.assertEqual(meta.original_url, "https://images.openbeautyfacts.org/good_listerine.jpg")

    def test_search_provider_transient_503_retried_successfully(self):
        """Transient HTTP 503 Service Unavailable does not immediately trigger AI fallback; retry succeeds."""
        mock_client = MagicMock()
        call_count = 0

        def mock_get(url, params=None):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count == 1:
                resp.status_code = 503
                resp.content = b"Service Unavailable"
            else:
                resp.status_code = 200
                resp.json.return_value = {
                    "products": [
                        {
                            "product_name": "Bhajani Chakli",
                            "brands": "",
                            "image_front_url": "https://images.openfoodfacts.org/chakli.jpg",
                        }
                    ]
                }
            return resp

        mock_client.get.side_effect = mock_get

        with patch("product_image_resolver.download_and_validate_web_image") as mock_dl:
            mock_dl.return_value = (
                True,
                self.dummy_packet,
                {"cached_path": str(self.cache_dir / "chakli.jpg"), "content_type": "image/jpeg", "width": 800, "height": 300},
                "",
            )
            with patch.object(self.resolver, "_get_client", return_value=mock_client):
                meta = self.resolver.resolve_product_image(
                    product_name="Bhajani Chakli",
                    brand=None,
                    barcode=None,
                    category="Snacks",
                )
                self.assertIsNotNone(meta)
                self.assertTrue(meta.is_verified)
                self.assertGreaterEqual(call_count, 2)

    def test_bounded_search_exhaustion_records_web_unavailable(self):
        """When bounded search genuinely exhausts all queries and catalogs with no results, records web_unavailable."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"products": [], "query": {"pages": {}}}
        mock_client.get.return_value = mock_resp

        with patch.object(self.resolver, "_get_client", return_value=mock_client):
            meta = self.resolver.resolve_product_image(
                product_name="ChanduRam Chocolate Cookies",
                brand="ChanduRam",
                barcode=None,
                category="Snacks",
            )
            self.assertIsNotNone(meta)
            self.assertFalse(meta.is_verified)
            self.assertIn(meta.status, (ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH, ImageResolutionStatus.WEB_UNAVAILABLE))

    def test_saved_valid_web_image_retained_on_later_failed_search(self):
        """A previously validated web image is retained during supplementary scans or edits when later search fails."""
        existing_meta = {
            "source": "open_food_facts_search",
            "original_url": "https://images.openfoodfacts.org/saved_image.jpg",
            "cached_path": str(self.cache_dir / "saved.jpg"),
            "status": "verified_web_image",
            "barcode": None,
            "product_identity": "Haldiram Mixture",
        }
        meta = self.resolver.resolve_product_image(
            product_name="Mixture",
            brand="Haldiram",
            barcode=None,
            category="Snacks",
            existing_metadata=existing_meta,
            is_supplementary=False,
        )
        self.assertTrue(meta.is_verified)
        self.assertEqual(meta.original_url, "https://images.openfoodfacts.org/saved_image.jpg")

    def test_framing_preserves_full_product_aspect_ratio_no_crop(self):
        """Verify that downloaded images (portrait bottles, wide packets, bars) preserve raw bytes with zero crop."""
        tall_bottle_bytes = create_dummy_jpeg(250, 900)
        ok, w, h, msg = validate_and_decode_image_bytes(tall_bottle_bytes)
        self.assertTrue(ok)
        self.assertEqual(w, 250)
        self.assertEqual(h, 900)

        wide_packet_bytes = create_dummy_jpeg(1200, 450)
        ok, w, h, msg = validate_and_decode_image_bytes(wide_packet_bytes)
        self.assertTrue(ok)
        self.assertEqual(w, 1200)
        self.assertEqual(h, 450)

    def test_inventory_serves_verified_image_without_revert_to_ai(self):
        """Inventory endpoint correctly serves or redirects to verified product image without falling back."""
        test_file = self.cache_dir / "verified_prod.jpg"
        test_file.write_bytes(self.dummy_bottle)

        prod_id = self.db.add_product(
            product_name="Listerine Cool Mint Mouthwash",
            brand="Listerine",
            food_category="Pantry Staples",
            image_path=str(test_file),
            force=True,
        )

        resp = self.client.get(f"/api/products/{prod_id}/image")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "image/jpeg")
        self.assertEqual(len(resp.content), len(self.dummy_bottle))


if __name__ == "__main__":
    unittest.main()
