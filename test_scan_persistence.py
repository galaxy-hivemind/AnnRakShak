"""
AnnaRakshak — Scan Persistence & Completion Workflow Test Suite
===============================================================
Automated testing for scan persistence, product creation, idempotency,
deletion cascading, and SQLite/PostgreSQL compatibility.
"""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api import app, get_analyzer, get_db
from gemini_analyzer import DateCandidate, FoodAnalysisResult, GeminiAnalyzer
from inventory_db import InventoryDatabase, DuplicateProductError


class TestScanPersistenceAndCompletion(unittest.TestCase):
    """Test suite for completed-scan persistence and inventory lifecycle."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_persistence.db"
        self.db = InventoryDatabase(db_path=self.db_path)

        self.mock_analyzer = MagicMock(spec=GeminiAnalyzer)

        app.state.db = self.db
        app.state.analyzer = self.mock_analyzer
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_analyzer] = lambda: self.mock_analyzer

        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.temp_dir.cleanup()

    def test_1_completing_scan_creates_persistent_scan_and_inventory_product(self):
        """Scenario 1: Completing a scan creates both persistent scan record and inventory product."""
        # 1. Record an initial scan that needs review
        result = FoodAnalysisResult(
            product_name="Organic Oat Milk",
            brand="Oatly",
            food_category="Dairy",
            needs_review=True,
            review_reason="Check printed expiry",
            analysis_status="success",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-11-15",
                    date_type="expiry",
                    normalized_date="2026-11-15",
                    confidence=0.95,
                    evidence="Visible expiry date",
                ),
            ],
        )
        scan_id = self.db.record_scan(image_path="/tmp/fake_oat.jpg", result=result)

        # Before confirmation: scan exists with needs_review=True, no product
        scan = self.db.get_scan(scan_id)
        self.assertIsNotNone(scan)
        self.assertTrue(scan.needs_review)
        self.assertIsNone(scan.product_id)

        # 2. Confirm scan via /api/products with scan_id
        payload = {
            "product_name": "Organic Oat Milk (Confirmed)",
            "brand": "Oatly",
            "food_category": "Dairy",
            "date_type": "expiry",
            "normalized_date": "2026-11-15",
            "date_status": "confirmed",
            "date_source": "user_confirmed",
            "notes": "Quantity: 1 Liter | EXP: 2026-11-15",
            "scan_id": scan_id,
            "force": True,
        }
        res = self.client.post("/api/products", json=payload)
        self.assertEqual(res.status_code, 201)
        prod_data = res.json()
        self.assertEqual(prod_data["scan_id"], scan_id)
        self.assertEqual(prod_data["product_name"], "Organic Oat Milk (Confirmed)")

        # Verify scan history is now confirmed and linked to product
        updated_scan = self.db.get_scan(scan_id)
        self.assertIsNotNone(updated_scan)
        self.assertFalse(updated_scan.needs_review)
        self.assertEqual(updated_scan.product_id, prod_data["id"])
        self.assertEqual(updated_scan.selected_expiry_date, "2026-11-15")

    def test_2_new_product_appears_in_inventory_api_response(self):
        """Scenario 2: The new product appears in the Inventory API response with scan_id."""
        result = FoodAnalysisResult(
            product_name="Greek Yogurt",
            brand="Chobani",
            food_category="Dairy",
            needs_review=True,
            analysis_status="success",
        )
        scan_id = self.db.record_scan(image_path="/tmp/yogurt.jpg", result=result)

        # Confirm
        payload = {
            "product_name": "Greek Yogurt",
            "brand": "Chobani",
            "food_category": "Dairy",
            "date_type": "use_by",
            "normalized_date": "2026-10-30",
            "date_status": "confirmed",
            "scan_id": scan_id,
            "force": True,
        }
        create_res = self.client.post("/api/products", json=payload)
        self.assertEqual(create_res.status_code, 201)

        # GET /api/products
        get_res = self.client.get("/api/products")
        self.assertEqual(get_res.status_code, 200)
        items = get_res.json()
        matching = [p for p in items if p["scan_id"] == scan_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["product_name"], "Greek Yogurt")
        self.assertEqual(matching[0]["date_status"], "confirmed")

    def test_3_reloading_database_preserves_saved_product_and_scan_link(self):
        """Scenario 3: Reloading the database (simulating page reload or app restart) does not lose data."""
        scan_id = self.db.record_scan(image_path="/tmp/bread.jpg", error_message=None)
        prod_id = self.db.add_product(
            product_name="Sourdough Bread",
            brand="Artisan Bakery",
            food_category="Bakery",
            date_type="best_before",
            normalized_date="2026-10-25",
            date_status="confirmed",
            scan_id=scan_id,
            force=True,
        )

        # Close existing DB connection and instantiate a new one pointing to same file
        self.db.close()
        reloaded_db = InventoryDatabase(db_path=self.db_path)

        p = reloaded_db.get_product(prod_id)
        self.assertIsNotNone(p)
        self.assertEqual(p.product_name, "Sourdough Bread")
        self.assertEqual(p.scan_id, scan_id)

        s = reloaded_db.get_scan(scan_id)
        self.assertIsNotNone(s)
        self.assertEqual(s.product_id, prod_id)
        self.assertFalse(s.needs_review)

    def test_4_corrected_metadata_dates_brand_category_and_quantity_are_persisted(self):
        """Scenario 4: Corrected dates, brand, category, and quantity are persisted."""
        result = FoodAnalysisResult(
            product_name="Unknown Cereal",
            brand="OldBrand",
            food_category="Snacks",
            analysis_status="needs_review",
            needs_review=True,
            date_candidates=[
                DateCandidate(
                    raw_text="MFG 2026-01-01",
                    date_type="manufacturing",
                    normalized_date="2026-01-01",
                    confidence=0.9,
                    evidence="Visible MFG label",
                ),
                DateCandidate(
                    raw_text="BB 2026-12-31",
                    date_type="best_before",
                    normalized_date="2026-12-31",
                    confidence=0.9,
                    evidence="Visible BB label",
                ),
            ],
        )
        scan_id = self.db.record_scan(image_path="/tmp/cereal.jpg", result=result)

        # User corrects name, brand, category, quantity, and date
        payload = {
            "product_name": "Crunchy Honey Oats",
            "brand": "Kellogg's",
            "food_category": "Grains & Cereals",
            "quantity": "750g Box",
            "date_type": "best_before",
            "normalized_date": "2026-12-31",
            "notes": "Quantity: 750g Box | MFG: 2026-01-01 | BB: 2026-12-31 [Verified]",
            "date_status": "confirmed",
            "date_source": "user_confirmed",
            "scan_id": scan_id,
            "force": True,
        }
        res = self.client.post("/api/products", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["product_name"], "Crunchy Honey Oats")
        self.assertEqual(data["brand"], "Kellogg's")
        self.assertEqual(data["food_category"], "Grains & Cereals")
        self.assertEqual(data["quantity"], "750g Box")
        self.assertEqual(data["normalized_date"], "2026-12-31")

        # Scan history also carries corrected name, brand, category
        s = self.db.get_scan(scan_id)
        self.assertEqual(s.product_name, "Crunchy Honey Oats")
        self.assertEqual(s.brand, "Kellogg's")
        self.assertEqual(s.food_category, "Grains & Cereals")

    def test_5_repeated_confirmation_does_not_create_duplicate_products(self):
        """Scenario 5: Repeated confirmation does not create duplicate products (idempotent)."""
        scan_id = self.db.record_scan(image_path="/tmp/butter.jpg")

        payload = {
            "product_name": "Salted Butter",
            "brand": "Amul",
            "food_category": "Dairy",
            "date_type": "best_before",
            "normalized_date": "2026-12-15",
            "date_status": "confirmed",
            "scan_id": scan_id,
            "force": True,
        }

        # First confirmation
        res1 = self.client.post("/api/products", json=payload)
        self.assertEqual(res1.status_code, 201)
        id1 = res1.json()["id"]

        # Repeated confirmation (e.g. double click or retry)
        payload["product_name"] = "Salted Butter (Updated)"
        res2 = self.client.post("/api/products", json=payload)
        self.assertEqual(res2.status_code, 201)
        id2 = res2.json()["id"]

        # Same product ID returned - NO duplicate!
        self.assertEqual(id1, id2)

        # Check total products in inventory
        products = self.db.list_products()
        matching = [p for p in products if p.scan_id == scan_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].product_name, "Salted Butter (Updated)")

    def test_6_backend_save_failure_does_not_show_false_completed_state(self):
        """Scenario 6: Backend validation or database error does not mark scan confirmed."""
        scan_id = self.db.record_scan(image_path="/tmp/apple.jpg")

        # Invalid date format should trigger 422
        bad_payload = {
            "product_name": "Fuji Apple",
            "date_type": "expiry",
            "normalized_date": "not-a-date",
            "scan_id": scan_id,
        }
        res = self.client.post("/api/products", json=bad_payload)
        self.assertEqual(res.status_code, 422)

        # Scan record must remain unconfirmed
        s = self.db.get_scan(scan_id)
        self.assertTrue(s.needs_review)
        self.assertIsNone(s.product_id)

    def test_7_delete_scan_removes_scan_and_associated_product_only(self):
        """Scenario 7: Delete Scan removes only the intended scan and its product, leaving others intact."""
        # Create an unrelated product
        unrelated_prod_id = self.db.add_product(
            product_name="Unrelated Salt",
            date_type="unknown",
            force=True,
        )

        # Create scan and confirm into product
        scan_id = self.db.record_scan(image_path="/tmp/temp_scan.jpg")
        confirmed_prod_id = self.db.add_product(
            product_name="Target Milk to Delete",
            date_type="expiry",
            normalized_date="2026-10-25",
            date_status="confirmed",
            scan_id=scan_id,
            force=True,
        )

        # Call DELETE /api/scans/{scan_id}
        del_res = self.client.delete(f"/api/scans/{scan_id}?delete_product=true")
        self.assertEqual(del_res.status_code, 200)
        del_data = del_res.json()
        self.assertTrue(del_data["success"])

        # Target scan and target product are gone
        self.assertIsNone(self.db.get_scan(scan_id))
        self.assertIsNone(self.db.get_product(confirmed_prod_id))

        # Unrelated product is strictly preserved!
        unrelated = self.db.get_product(unrelated_prod_id)
        self.assertIsNotNone(unrelated)
        self.assertEqual(unrelated.product_name, "Unrelated Salt")

        # Calling delete on already-deleted scan is safe
        safe_res = self.client.delete(f"/api/scans/{scan_id}?delete_product=true")
        self.assertEqual(safe_res.status_code, 200)
        self.assertTrue(safe_res.json()["success"])

    def test_8_new_scan_preserves_previous_saved_scan_and_product(self):
        """Scenario 8: New Scan preserves the previous saved scan and product."""
        scan1_id = self.db.record_scan(image_path="/tmp/scan1.jpg")
        prod1_id = self.db.add_product(
            product_name="Scan 1 Product",
            date_type="expiry",
            normalized_date="2026-11-01",
            date_status="confirmed",
            scan_id=scan1_id,
            force=True,
        )

        # Start a fresh scan (new scan ID)
        scan2_id = self.db.record_scan(image_path="/tmp/scan2.jpg")
        self.assertNotEqual(scan1_id, scan2_id)

        # Scan 1 and Product 1 are completely intact
        s1 = self.db.get_scan(scan1_id)
        self.assertIsNotNone(s1)
        self.assertEqual(s1.product_id, prod1_id)

        p1 = self.db.get_product(prod1_id)
        self.assertIsNotNone(p1)
        self.assertEqual(p1.product_name, "Scan 1 Product")

    def test_9_sqlite_and_postgres_schema_consistency(self):
        """Scenario 9: SQLite and PostgreSQL schemas both have scan_id on products and product_id on scan_history."""
        from inventory_db import SQLITE_SCHEMA, POSTGRES_SCHEMA

        self.assertIn("scan_id INTEGER", SQLITE_SCHEMA)
        self.assertIn("product_id INTEGER", SQLITE_SCHEMA)
        self.assertIn("scan_id INTEGER", POSTGRES_SCHEMA)
        self.assertIn("product_id INTEGER", POSTGRES_SCHEMA)


if __name__ == "__main__":
    unittest.main()
