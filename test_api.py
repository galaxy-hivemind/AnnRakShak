"""
AnnaRakshak — API Test Suite
============================
Automated testing for the AnnaRakshak FastAPI backend (`api.py`).
Tests all 12 REST endpoints, validation rules, CORS, error handling,
and data persistence using isolated temporary SQLite databases.

Never touches or modifies the production `annarakshak.db`.
Does not call real external APIs or access physical cameras.
Uses standard Python unittest for zero additional testing dependencies.
"""

from __future__ import annotations

import base64
import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cv2
from fastapi.testclient import TestClient
import numpy as np

from api import app, get_analyzer, get_db
from gemini_analyzer import DateCandidate, FoodAnalysisResult, GeminiAnalyzer
from inventory_db import InventoryDatabase


class TestApiEndpoints(unittest.TestCase):
    """Comprehensive test suite for AnnaRakshak HTTP API."""

    def setUp(self) -> None:
        """Create a fresh temporary SQLite database and mock analyzer for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_annarakshak.db"
        self.db = InventoryDatabase(db_path=self.db_path)

        # Mock analyzer
        self.mock_analyzer = MagicMock(spec=GeminiAnalyzer)

        # Override dependencies
        app.state.db = self.db
        app.state.analyzer = self.mock_analyzer
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_analyzer] = lambda: self.mock_analyzer

        self.client = TestClient(app)

    def tearDown(self) -> None:
        """Clean up temporary directory and dependency overrides."""
        app.dependency_overrides.clear()
        self.temp_dir.cleanup()

    # -----------------------------------------------------------------------
    # 1. Health Endpoint
    # -----------------------------------------------------------------------

    def test_health_check_empty_db(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "connected")
        self.assertEqual(data["total_products"], 0)
        self.assertIn("version", data)

    def test_health_check_with_products(self):
        self.db.add_product(product_name="Sample Milk")
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_products"], 1)

    # -----------------------------------------------------------------------
    # 2. Products Endpoints (CRUD)
    # -----------------------------------------------------------------------

    def test_create_product_success(self):
        payload = {
            "product_name": "Amul Taaza Milk",
            "brand": "Amul",
            "food_category": "Dairy",
            "date_type": "expiry",
            "normalized_date": "2026-10-20",
            "notes": "Stored in fridge",
        }
        response = self.client.post("/api/products", json=payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertGreater(data["id"], 0)
        self.assertEqual(data["product_name"], "Amul Taaza Milk")
        self.assertEqual(data["brand"], "Amul")
        self.assertEqual(data["food_category"], "Dairy")
        self.assertEqual(data["normalized_date"], "2026-10-20")
        self.assertEqual(data["date_status"], "confirmed")

    def test_create_product_blank_name_rejected(self):
        payload = {"product_name": "   "}
        response = self.client.post("/api/products", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_create_product_invalid_date_format_rejected(self):
        payload = {
            "product_name": "Bread",
            "normalized_date": "20-10-2026",  # Not ISO YYYY-MM-DD
        }
        response = self.client.post("/api/products", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertIn("Invalid date format", response.text)

    def test_create_product_invalid_date_type_rejected(self):
        payload = {
            "product_name": "Bread",
            "date_type": "fabricated_type",
        }
        response = self.client.post("/api/products", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_create_duplicate_product_conflict(self):
        payload = {
            "product_name": "Modern Bread",
            "brand": "Modern",
            "normalized_date": "2026-10-18",
        }
        res1 = self.client.post("/api/products", json=payload)
        self.assertEqual(res1.status_code, 201)
        first_id = res1.json()["id"]

        # Duplicate attempt without force
        res2 = self.client.post("/api/products", json=payload)
        self.assertEqual(res2.status_code, 409)
        data2 = res2.json()
        self.assertIn("existing_id", data2)
        self.assertEqual(data2["existing_id"], first_id)

        # Duplicate attempt with force=True
        payload["force"] = True
        res3 = self.client.post("/api/products", json=payload)
        self.assertEqual(res3.status_code, 201)
        self.assertNotEqual(res3.json()["id"], first_id)

    def test_get_product_by_id_success(self):
        p_id = self.db.add_product(
            product_name="Kissan Jam",
            brand="Kissan",
            food_category="Condiments",
            normalized_date="2027-01-01",
        )
        response = self.client.get(f"/api/products/{p_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], p_id)
        self.assertEqual(data["product_name"], "Kissan Jam")
        self.assertEqual(data["food_category"], "Condiments")

    def test_get_product_not_found(self):
        response = self.client.get("/api/products/99999")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())

    def test_list_products_and_filters(self):
        self.db.add_product(product_name="Amul Butter", food_category="Dairy", normalized_date="2026-12-01")
        self.db.add_product(product_name="Tata Salt", food_category="Grains", normalized_date="2028-01-01")
        self.db.add_product(product_name="Britannia Rusk", food_category="Bakery", normalized_date="2026-11-15")

        # List all
        res_all = self.client.get("/api/products")
        self.assertEqual(res_all.status_code, 200)
        self.assertEqual(len(res_all.json()), 3)

        # Filter by category
        res_cat = self.client.get("/api/products?category=Dairy")
        self.assertEqual(res_cat.status_code, 200)
        self.assertEqual(len(res_cat.json()), 1)
        self.assertEqual(res_cat.json()[0]["product_name"], "Amul Butter")

        # Search
        res_search = self.client.get("/api/products?search=salt")
        self.assertEqual(res_search.status_code, 200)
        self.assertEqual(len(res_search.json()), 1)
        self.assertEqual(res_search.json()[0]["product_name"], "Tata Salt")

        # Sort by name
        res_sort = self.client.get("/api/products?sort_by=name")
        self.assertEqual(res_sort.status_code, 200)
        names = [p["product_name"] for p in res_sort.json()]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_patch_product_metadata_and_date(self):
        p_id = self.db.add_product(
            product_name="Brown Bread",
            brand="Local Baker",
            food_category="Bakery",
            date_status="unverified",
        )

        patch_payload = {
            "product_name": "Whole Wheat Brown Bread",
            "brand": "Healthy Bakes",
            "normalized_date": "2026-10-25",
            "date_type": "use_by",
            "notes": "Verified by user",
        }
        res = self.client.patch(f"/api/products/{p_id}", json=patch_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["product_name"], "Whole Wheat Brown Bread")
        self.assertEqual(data["brand"], "Healthy Bakes")
        self.assertEqual(data["normalized_date"], "2026-10-25")
        self.assertEqual(data["date_type"], "use_by")
        self.assertEqual(data["date_status"], "confirmed")

    def test_patch_product_not_found(self):
        res = self.client.patch("/api/products/9999", json={"product_name": "New Name"})
        self.assertEqual(res.status_code, 404)

    def test_patch_product_invalid_date(self):
        p_id = self.db.add_product(product_name="Juice")
        res = self.client.patch(f"/api/products/{p_id}", json={"normalized_date": "invalid-date"})
        self.assertEqual(res.status_code, 422)

    def test_delete_product_success(self):
        p_id = self.db.add_product(product_name="Expiring Yogurt")
        res = self.client.delete(f"/api/products/{p_id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_id"], p_id)

        # Verify it is gone
        self.assertIsNone(self.db.get_product(p_id))

    def test_delete_product_not_found(self):
        res = self.client.delete("/api/products/99999")
        self.assertEqual(res.status_code, 404)

    def test_delete_product_preserves_scan_history(self):
        # Record a scan
        scan_id = self.db.record_scan(
            image_path="captures/scan_test.jpg",
            result=FoodAnalysisResult(
                product_name="Canned Beans",
                brand="Heinz",
                food_category="Canned Goods",
                analysis_status="success",
                needs_review=False,
                review_reason=None,
                selected_expiry_date="2027-05-01",
                date_candidates=[],
            ),
        )
        # Add a product
        p_id = self.db.add_product(product_name="Canned Beans")

        # Delete product
        del_res = self.client.delete(f"/api/products/{p_id}")
        self.assertEqual(del_res.status_code, 200)

        # Scan history must still be fully intact!
        scan = self.db.get_scan(scan_id)
        self.assertIsNotNone(scan)
        self.assertEqual(scan.product_name, "Canned Beans")

    # -----------------------------------------------------------------------
    # 3. Scans & Candidates Endpoints
    # -----------------------------------------------------------------------

    def test_list_scans_and_get_scan(self):
        result = FoodAnalysisResult(
            product_name="Digestive Biscuits",
            brand="Britannia",
            food_category="Snacks",
            analysis_status="success",
            needs_review=False,
            review_reason=None,
            selected_expiry_date="2026-12-31",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP: 31/12/2026",
                    date_type="expiry",
                    normalized_date="2026-12-31",
                    confidence=0.98,
                    evidence="Visible on back panel",
                )
            ],
        )
        scan_id = self.db.record_scan(image_path="captures/biscuit.jpg", result=result)

        # List scans
        res_list = self.client.get("/api/scans?limit=10")
        self.assertEqual(res_list.status_code, 200)
        scans = res_list.json()
        self.assertEqual(len(scans), 1)
        self.assertEqual(scans[0]["id"], scan_id)
        self.assertEqual(scans[0]["product_name"], "Digestive Biscuits")

        # Get scan by id
        res_get = self.client.get(f"/api/scans/{scan_id}")
        self.assertEqual(res_get.status_code, 200)
        scan_data = res_get.json()
        self.assertEqual(scan_data["id"], scan_id)
        self.assertEqual(len(scan_data["date_candidates"]), 1)
        self.assertEqual(scan_data["date_candidates"][0]["raw_text"], "EXP: 31/12/2026")

    def test_get_scan_not_found(self):
        res = self.client.get("/api/scans/99999")
        self.assertEqual(res.status_code, 404)

    def test_get_scan_date_candidates(self):
        result = FoodAnalysisResult(
            product_name="Butter Cookies",
            brand="Danish",
            food_category="Snacks",
            analysis_status="success",
            needs_review=False,
            review_reason=None,
            selected_expiry_date=None,
            date_candidates=[
                DateCandidate(
                    raw_text="MFD 01/2026",
                    date_type="manufacturing",
                    normalized_date=None,
                    confidence=0.9,
                    evidence="Front panel",
                ),
                DateCandidate(
                    raw_text="BB 01/2027",
                    date_type="best_before",
                    normalized_date=None,
                    confidence=0.88,
                    evidence="Back panel",
                ),
            ],
        )
        scan_id = self.db.record_scan(image_path="captures/cookies.jpg", result=result)

        res = self.client.get(f"/api/scans/{scan_id}/date-candidates")
        self.assertEqual(res.status_code, 200)
        candidates = res.json()
        self.assertEqual(len(candidates), 2)
        types = {c["date_type"] for c in candidates}
        self.assertIn("manufacturing", types)
        self.assertIn("best_before", types)

    def test_get_scan_date_candidates_not_found(self):
        res = self.client.get("/api/scans/99999/date-candidates")
        self.assertEqual(res.status_code, 404)

    def test_reanalyze_scan_success(self):
        # Create a real test image file
        test_img_path = Path(self.temp_dir.name) / "test_scan.jpg"
        test_img_path.write_bytes(b"dummy image bytes")

        # Initial scan with error or unverified
        scan_id = self.db.record_scan(
            image_path=str(test_img_path),
            result=None,
            error_message="Initial network failure",
        )

        # Mock analyzer response
        self.mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Pringles Sour Cream",
            brand="Pringles",
            food_category="Snacks",
            analysis_status="success",
            needs_review=False,
            selected_expiry_date="2027-04-15",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 15/04/2027",
                    date_type="expiry",
                    normalized_date="2027-04-15",
                    confidence=0.97,
                    evidence="Base of the can",
                )
            ],
        )

        res = self.client.post(f"/api/scans/{scan_id}/reanalyze")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["id"], scan_id)
        self.assertEqual(data["product_name"], "Pringles Sour Cream")
        self.assertEqual(data["selected_expiry_date"], "2027-04-15")
        self.assertEqual(len(data["date_candidates"]), 1)

        # Check analyzer was called with image path
        self.mock_analyzer.analyze_image.assert_called_once_with(str(test_img_path))

    def test_reanalyze_scan_missing_image_file(self):
        scan_id = self.db.record_scan(
            image_path="/nonexistent/path/image.jpg",
            result=None,
        )
        res = self.client.post(f"/api/scans/{scan_id}/reanalyze")
        self.assertEqual(res.status_code, 400)
        self.assertIn("does not exist or is inaccessible", res.json()["detail"])

    def test_reanalyze_scan_not_found(self):
        res = self.client.post("/api/scans/99999/reanalyze")
        self.assertEqual(res.status_code, 404)

    # -----------------------------------------------------------------------
    # 4. Dashboard & Alerts with Mixed Date Statuses
    # -----------------------------------------------------------------------

    def test_dashboard_and_alerts_mixed_statuses(self):
        today = datetime.date.today()
        past_date = (today - datetime.timedelta(days=10)).isoformat()
        soon_date = (today + datetime.timedelta(days=3)).isoformat()
        future_date = (today + datetime.timedelta(days=60)).isoformat()
        bb_past = (today - datetime.timedelta(days=5)).isoformat()
        bb_soon = (today + datetime.timedelta(days=4)).isoformat()

        # 1. Expired product
        self.db.add_product(
            product_name="Expired Milk",
            date_type="expiry",
            normalized_date=past_date,
        )

        # 2. Expiring soon product
        self.db.add_product(
            product_name="Yogurt Expiring Soon",
            date_type="expiry",
            normalized_date=soon_date,
        )

        # 3. Safe product
        self.db.add_product(
            product_name="Safe Rice",
            date_type="expiry",
            normalized_date=future_date,
        )

        # 4. Best before passed
        self.db.add_product(
            product_name="Old Crackers",
            date_type="best_before",
            normalized_date=bb_past,
        )

        # 5. Best before soon
        self.db.add_product(
            product_name="Cereal BB Soon",
            date_type="best_before",
            normalized_date=bb_soon,
        )

        # 6. Manufacturing date (never classified as expiry!)
        self.db.add_product(
            product_name="Olive Oil",
            date_type="manufacturing",
            normalized_date=past_date,
        )

        # 7. Unverified item
        self.db.add_product(
            product_name="Unknown Spice Bottle",
            date_type="unknown",
            normalized_date=None,
            date_status="unverified",
        )

        # Check Dashboard metrics
        dash_res = self.client.get("/api/dashboard")
        self.assertEqual(dash_res.status_code, 200)
        dash = dash_res.json()

        self.assertEqual(dash["total_products"], 7)
        self.assertEqual(dash["expired_count"], 1)
        self.assertEqual(dash["expiring_soon_count"], 1)
        self.assertEqual(dash["best_before_passed_count"], 1)
        self.assertEqual(dash["best_before_soon_count"], 1)
        self.assertEqual(dash["safe_count"], 1)  # Safe Rice
        # Needs review: Unknown Spice Bottle + Olive Oil (manufacturing, normalized_date not expiry)
        self.assertGreaterEqual(dash["needs_review_count"], 1)

        # Check Alerts list
        alerts_res = self.client.get("/api/alerts")
        self.assertEqual(alerts_res.status_code, 200)
        alerts = alerts_res.json()

        # Critical alerts must come first (Expired Milk, Old Crackers)
        urgencies = [a["urgency"] for a in alerts]
        self.assertEqual(urgencies[0], "critical")

        # Verify manufacturing date is not an expiry alert
        mfg_alerts = [a for a in alerts if a["product_name"] == "Olive Oil" and a["urgency"] == "critical"]
        self.assertEqual(len(mfg_alerts), 0)

        # Verify distinct message for best before vs expiry
        bb_alert = [a for a in alerts if a["product_name"] == "Old Crackers"][0]
        self.assertIn("best-before", bb_alert["message"].lower())

        exp_alert = [a for a in alerts if a["product_name"] == "Expired Milk"][0]
        self.assertIn("expired", exp_alert["message"].lower())

    # -----------------------------------------------------------------------
    # 5. CORS & Security
    # -----------------------------------------------------------------------

    def test_cors_preflight_and_headers(self):
        endpoints = [
            "/api/dashboard",
            "/api/dashboard?warning_days=7",
            "/api/products",
            "/api/alerts",
            "/api/alerts?warning_days=7",
            "/api/scans",
            "/api/scans?limit=50",
        ]
        origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://localhost:8081",
            "http://127.0.0.1:8081",
            "http://localhost:3000",
        ]
        methods = ["GET", "POST", "PATCH", "DELETE"]

        for path in endpoints:
            for origin in origins:
                for method in methods:
                    response = self.client.options(
                        path,
                        headers={
                            "Origin": origin,
                            "Access-Control-Request-Method": method,
                            "Access-Control-Request-Headers": "content-type, authorization",
                        },
                    )
                    self.assertEqual(
                        response.status_code,
                        200,
                        f"OPTIONS preflight failed with {response.status_code} on {path} from {origin}",
                    )
                    self.assertEqual(
                        response.headers.get("access-control-allow-origin"),
                        origin,
                        f"Incorrect Access-Control-Allow-Origin on {path} from {origin}",
                    )
                    self.assertIn(
                        "content-type",
                        response.headers.get("access-control-allow-headers", "").lower(),
                    )

    def test_cors_rejects_malicious_origin(self):
        response = self.client.options(
            "/api/products",
            headers={
                "Origin": "http://malicious-external-origin.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_api_keys_never_leaked(self):
        res = self.client.get("/api/health")
        self.assertNotIn("AQ.", res.text)
        self.assertNotIn("GEMINI_API_KEY", res.text)

    def test_error_response_no_stack_traces(self):
        res = self.client.post("/api/products", content=b"invalid json")
        self.assertIn(res.status_code, [400, 422])
        self.assertNotIn("Traceback (most recent call last)", res.text)

    def test_post_scan_multipart_success(self):
        # Create a valid test image encoded as JPEG
        dummy_img = np.zeros((120, 120, 3), dtype=np.uint8)
        _, img_bytes = cv2.imencode(".jpg", dummy_img)
        jpeg_data = img_bytes.tobytes()

        self.mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Organic Rolled Oats",
            brand="True Elements",
            food_category="Grains",
            analysis_status="success",
            needs_review=False,
            selected_expiry_date="2027-08-20",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 20/08/2027",
                    date_type="expiry",
                    normalized_date="2027-08-20",
                    confidence=0.98,
                    evidence="Bottom flap",
                )
            ],
        )

        res = self.client.post(
            "/api/scans",
            files={"image": ("oats.jpg", jpeg_data, "image/jpeg")},
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["product_name"], "Organic Rolled Oats")
        self.assertEqual(data["brand"], "True Elements")
        self.assertEqual(data["food_category"], "Grains")
        self.assertEqual(data["analysis_status"], "success")
        self.assertFalse(data["needs_review"])
        self.assertEqual(data["selected_expiry_date"], "2027-08-20")
        self.assertEqual(len(data["date_candidates"]), 1)
        self.assertEqual(data["date_candidates"][0]["raw_text"], "EXP 20/08/2027")

        # Verify image was stored on disk and can be retrieved
        scan_id = data["id"]
        img_res = self.client.get(f"/api/scans/{scan_id}/image")
        self.assertEqual(img_res.status_code, 200)
        self.assertEqual(img_res.headers["content-type"], "image/jpeg")

    def test_post_scan_json_base64_success(self):
        dummy_img = np.zeros((80, 80, 3), dtype=np.uint8)
        _, img_bytes = cv2.imencode(".png", dummy_img)
        png_data = img_bytes.tobytes()
        b64_str = base64.b64encode(png_data).decode("ascii")

        self.mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Almond Milk",
            brand="Silk",
            food_category="Dairy",
            analysis_status="success",
            needs_review=True,
            review_reason="Check cap for day",
            selected_expiry_date=None,
            date_candidates=[],
        )

        res = self.client.post(
            "/api/scans",
            json={"image": f"data:image/png;base64,{b64_str}"},
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["product_name"], "Almond Milk")
        self.assertTrue(data["needs_review"])

    def test_post_scan_empty_image_rejected(self):
        res = self.client.post(
            "/api/scans",
            files={"image": ("empty.jpg", b"", "image/jpeg")},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("empty", res.json()["detail"].lower())

    def test_post_scan_corrupted_image_rejected(self):
        res = self.client.post(
            "/api/scans",
            files={"image": ("corrupted.jpg", b"not-a-valid-image-content", "image/jpeg")},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid image data", res.json()["detail"].lower())

    def test_get_scan_image_not_found(self):
        res = self.client.get("/api/scans/99999/image")
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
