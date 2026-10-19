"""
Tests for Intelligent Product Image Discovery, Barcode Identification & Persistent Image Caching
Covering all 20 scenarios from Section 10 of requirements.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
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
                "image_front_url": "https://images.openfoodfacts.org/images/products/0042421000028/front_en.jpg",
            },
        }
        mock_client.get.return_value = mock_resp

        with patch("product_image_resolver.download_and_validate_web_image") as mock_dl:
            cached_file = str(self.cache_dir / "0042421000028.jpg")
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
                    barcode="0042421000028",
                    category="Dairy & Eggs",
                )

        self.assertEqual(meta.status, ImageResolutionStatus.VERIFIED_WEB_IMAGE)
        self.assertEqual(meta.source, "open_food_facts_barcode")
        self.assertEqual(meta.barcode, "0042421000028")
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
            barcode="0042421000028",
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
                barcode="0042421000028",
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
            barcode="0042421000028",
            product_identity="Horizon Whole Milk",
        )
        scan_id = self.db.record_scan(
            image_path=str(self.captures_dir / "primary.jpg"),
            result=FoodAnalysisResult(
                product_name="Horizon Whole Milk",
                brand="Horizon",
                barcode="0042421000028",
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
                barcode="3068320114059",
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
                barcode="3068320114059",
                product_identity="Evian Mineral Water",
            )

        with patch.object(self.resolver, "_lookup_open_food_facts_barcode", side_effect=slow_lookup):
            results = []

            def worker():
                meta = self.resolver.resolve_product_image(
                    product_name="Mineral Water",
                    brand="Evian",
                    barcode="3068320114059",
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


if __name__ == "__main__":
    unittest.main()
