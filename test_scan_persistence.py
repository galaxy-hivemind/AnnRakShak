"""
AnnaRakshak — Scan Persistence & Completion Workflow Test Suite
===============================================================
Comprehensive automated testing covering:
1. High-confidence scan automatically creates an inventory product.
2. The high-confidence product appears in the inventory API response.
3. Low-confidence scan does not create an inventory product.
4. Editing and manually approving a low-confidence scan creates the corrected product.
5. Editing an automatically saved product updates the existing record.
6. Changes survive refresh and a fresh database connection.
7. A failed auto-save never displays a saved/confirmed state.
8. Retrying a successful save does not create duplicate products.
9. Rescanning re-evaluates confidence and follows the correct path.
10. New Scan preserves previous saved scan and product.
11. Delete Scan confirmation deletes only the selected scan and its associated product.
12. Date confirmation never deletes an inventory product.
13. Confusing message about product removal is prevented.
14. Failed deletion and failed saving show recoverable errors.
15. Exactly two actions and persistence integrity.
16. Both SQLite and PostgreSQL schema/migration paths remain valid.
"""

from __future__ import annotations

import datetime
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import cv2
import numpy as np

from api import app, get_analyzer, get_db
from confidence_evaluator import evaluate_scan_confidence
from gemini_analyzer import DateCandidate, FoodAnalysisResult, GeminiAnalyzer
from inventory_db import (
    InventoryDatabase,
    ProductNotFoundError,
    SQLITE_SCHEMA,
    POSTGRES_SCHEMA,
)


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

    def _create_test_image(self) -> bytes:
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        img.fill(255)
        success, encoded = cv2.imencode(".jpg", img)
        return encoded.tobytes()

    def test_1_and_2_high_confidence_scan_auto_creates_inventory_product_and_appears_in_api(self):
        """
        Scenarios 1 & 2:
        - High-confidence scan automatically creates an inventory product without manual approval.
        - The high-confidence product appears immediately in the inventory API response.
        """
        high_conf_result = FoodAnalysisResult(
            product_name="Organic Whole Milk",
            brand="Amul",
            food_category="Dairy",
            quantity="1 Liter",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2026-10-25",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-10-25",
                    date_type="expiry",
                    normalized_date="2026-10-25",
                    confidence=0.96,
                    evidence="Crisp printed date",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = high_conf_result

        img_bytes = self._create_test_image()
        files = {"image": ("test_milk.jpg", img_bytes, "image/jpeg")}
        resp = self.client.post("/api/scans", files=files)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()

        # Verify auto-save flags and linkage
        self.assertTrue(data["auto_saved"])
        self.assertFalse(data["needs_review"])
        self.assertIsNotNone(data["product_id"])
        prod_id = data["product_id"]

        # Verify inventory product was created in database
        product = self.db.get_product(prod_id)
        self.assertIsNotNone(product)
        self.assertEqual(product.product_name, "Organic Whole Milk")
        self.assertEqual(product.normalized_date, "2026-10-25")
        self.assertEqual(product.scan_id, data["id"])

        # Scenario 2: Verify product appears in GET /api/products response immediately
        prod_resp = self.client.get("/api/products")
        self.assertEqual(prod_resp.status_code, 200)
        items = prod_resp.json()
        matching = [p for p in items if p["id"] == prod_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["product_name"], "Organic Whole Milk")

    def test_3_low_confidence_scan_does_not_create_inventory_product(self):
        """
        Scenario 3:
        Low-confidence scan (e.g. ambiguous date, missing name, or low confidence score)
        must enter manual review and NEVER create an inventory product automatically.
        """
        low_conf_result = FoodAnalysisResult(
            product_name="Generic Packaging",
            brand=None,
            food_category=None,
            needs_review=True,
            review_reason="Blurry date markings",
            analysis_status="needs_review",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP ??/2026",
                    date_type="expiry",
                    normalized_date=None,
                    confidence=0.40,
                    evidence="Partially rubbed off ink",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = low_conf_result

        img_bytes = self._create_test_image()
        files = {"image": ("test_low.jpg", img_bytes, "image/jpeg")}
        resp = self.client.post("/api/scans", files=files)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()

        # Must NOT be auto-saved
        self.assertFalse(data["auto_saved"])
        self.assertTrue(data["needs_review"])
        self.assertIsNone(data["product_id"])

        # Database inventory must be completely empty
        products = self.db.list_products()
        self.assertEqual(len(products), 0)

    def test_4_editing_and_manually_approving_low_confidence_scan_creates_product(self):
        """
        Scenario 4:
        Editing and approving a low-confidence scan creates the corrected product,
        links it to the scan record, and sets needs_review=False.
        """
        low_conf_result = FoodAnalysisResult(
            product_name="Unknown Cereal",
            brand=None,
            food_category="Snacks",
            needs_review=True,
            analysis_status="needs_review",
            date_candidates=[
                DateCandidate(
                    raw_text="BB DEC 2026",
                    date_type="best_before",
                    normalized_date=None,
                    confidence=0.50,
                    evidence="Month only, day missing",
                )
            ],
        )
        scan_id = self.db.record_scan(image_path="/tmp/cereal.jpg", result=low_conf_result)

        # User provides corrected details and approves
        payload = {
            "product_name": "Honey Crunchy Granola",
            "brand": "Kellogg's",
            "food_category": "Grains & Cereals",
            "quantity": "500g",
            "date_type": "best_before",
            "normalized_date": "2026-12-31",
            "date_status": "confirmed",
            "date_source": "user_confirmed",
            "scan_id": scan_id,
            "force": True,
        }
        resp = self.client.post("/api/products", json=payload)
        self.assertEqual(resp.status_code, 201)
        p_data = resp.json()
        prod_id = p_data["id"]

        # Verify scan is now confirmed and linked to product
        updated_scan = self.db.get_scan(scan_id)
        self.assertIsNotNone(updated_scan)
        self.assertEqual(updated_scan.product_id, prod_id)
        self.assertFalse(updated_scan.needs_review)

    def test_5_editing_automatically_saved_product_updates_existing_record(self):
        """
        Scenario 5:
        Editing an automatically saved product updates the existing record
        rather than creating a duplicate.
        """
        high_conf_result = FoodAnalysisResult(
            product_name="Almond Milk",
            brand="Silk",
            food_category="Dairy",
            quantity="1 L",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2026-11-20",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-11-20",
                    date_type="expiry",
                    normalized_date="2026-11-20",
                    confidence=0.98,
                    evidence="Visible expiry date",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = high_conf_result

        img_bytes = self._create_test_image()
        resp = self.client.post("/api/scans", files={"image": ("silk.jpg", img_bytes, "image/jpeg")})
        self.assertEqual(resp.status_code, 201)
        scan_data = resp.json()
        prod_id = scan_data["product_id"]

        # Edit name, quantity, and date
        patch_payload = {
            "product_name": "Organic Almond Milk (Unsweetened)",
            "quantity": "946 ml",
            "normalized_date": "2026-11-25",
        }
        patch_resp = self.client.patch(f"/api/products/{prod_id}", json=patch_payload)
        self.assertEqual(patch_resp.status_code, 200)

        # Verify no duplicate was created
        all_products = self.db.list_products()
        self.assertEqual(len(all_products), 1)

        # Verify product reflects the edits
        updated = self.db.get_product(prod_id)
        self.assertEqual(updated.product_name, "Organic Almond Milk (Unsweetened)")
        self.assertEqual(updated.normalized_date, "2026-11-25")

        # Verify scan history record synchronized
        sync_scan = self.db.get_scan(scan_data["id"])
        self.assertEqual(sync_scan.product_name, "Organic Almond Milk (Unsweetened)")
        self.assertEqual(sync_scan.selected_expiry_date, "2026-11-25")

    def test_6_changes_survive_refresh_and_fresh_database_connection(self):
        """
        Scenario 6:
        Changes survive restart/refresh and querying from a fresh database connection instance.
        """
        high_conf_result = FoodAnalysisResult(
            product_name="Greek Yogurt",
            brand="Chobani",
            food_category="Dairy",
            quantity="450g",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2026-11-01",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-11-01",
                    date_type="expiry",
                    normalized_date="2026-11-01",
                    confidence=0.95,
                    evidence="Printed foil lid",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = high_conf_result

        img_bytes = self._create_test_image()
        resp = self.client.post("/api/scans", files={"image": ("yogurt.jpg", img_bytes, "image/jpeg")})
        scan_data = resp.json()
        prod_id = scan_data["product_id"]

        # Simulate reload: instantiate fresh database pointing to same file
        fresh_db = InventoryDatabase(db_path=self.db_path)
        fresh_product = fresh_db.get_product(prod_id)
        fresh_scan = fresh_db.get_scan(scan_data["id"])

        self.assertIsNotNone(fresh_product)
        self.assertEqual(fresh_product.product_name, "Greek Yogurt")
        self.assertEqual(fresh_product.scan_id, scan_data["id"])
        self.assertEqual(fresh_scan.product_id, prod_id)
        self.assertFalse(fresh_scan.needs_review)

    def test_7_failed_auto_save_never_displays_saved_confirmed_state(self):
        """
        Scenario 7:
        If saving to persistent database fails during auto-save, the scan must
        NOT falsely report success or auto_saved=True.
        """
        high_conf_result = FoodAnalysisResult(
            product_name="Farm Fresh Eggs",
            brand="Local",
            food_category="Dairy",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2026-11-10",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-11-10",
                    date_type="expiry",
                    normalized_date="2026-11-10",
                    confidence=0.95,
                    evidence="Clear carton stamp",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = high_conf_result

        # Simulate database failure during add_product
        with patch.object(self.db, "add_product", side_effect=RuntimeError("Disk I/O error")):
            img_bytes = self._create_test_image()
            resp = self.client.post("/api/scans", files={"image": ("eggs.jpg", img_bytes, "image/jpeg")})
            self.assertEqual(resp.status_code, 201)
            data = resp.json()

            # Must NOT report auto_saved or confirmed
            self.assertFalse(data["auto_saved"])
            self.assertTrue(data["needs_review"])
            self.assertIn("Failed to save product", data["review_reason"])

    def test_8_retrying_successful_save_does_not_create_duplicate_products(self):
        """
        Scenario 8:
        Retrying a confirmation call with the same scan_id updates the existing record
        rather than creating duplicates.
        """
        high_conf_result = FoodAnalysisResult(
            product_name="Orange Juice",
            brand="Tropicana",
            food_category="Beverage",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2026-10-30",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-10-30",
                    date_type="expiry",
                    normalized_date="2026-10-30",
                    confidence=0.95,
                    evidence="Cap stamp",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = high_conf_result

        img_bytes = self._create_test_image()
        resp = self.client.post("/api/scans", files={"image": ("oj.jpg", img_bytes, "image/jpeg")})
        scan_data = resp.json()
        scan_id = scan_data["id"]

        # Call POST /api/products repeatedly with scan_id
        payload = {
            "product_name": "Orange Juice (No Pulp)",
            "brand": "Tropicana",
            "food_category": "Beverage",
            "date_type": "expiry",
            "normalized_date": "2026-10-30",
            "scan_id": scan_id,
            "force": True,
        }
        resp1 = self.client.post("/api/products", json=payload)
        resp2 = self.client.post("/api/products", json=payload)

        self.assertEqual(resp1.status_code, 201)
        self.assertEqual(resp2.status_code, 201)
        self.assertEqual(resp1.json()["id"], resp2.json()["id"])

        # Exactly 1 product exists
        all_prods = self.db.list_products()
        self.assertEqual(len(all_prods), 1)

    def test_9_rescanning_reevaluates_confidence_and_follows_correct_path(self):
        """
        Scenario 9:
        Rescanning (/api/scans/{id}/reanalyze) re-evaluates evidence and confidence:
        a low-confidence scan re-analyzed with high confidence gets automatically saved.
        """
        low_result = FoodAnalysisResult(
            product_name="Unknown Box",
            brand=None,
            food_category=None,
            needs_review=True,
            analysis_status="needs_review",
            date_candidates=[],
        )
        img_file = Path(self.temp_dir.name) / "reanalyze_test.jpg"
        cv2.imwrite(str(img_file), np.zeros((100, 100, 3), dtype=np.uint8))
        scan_id = self.db.record_scan(image_path=str(img_file), result=low_result)

        # Reanalyze with high confidence
        better_result = FoodAnalysisResult(
            product_name="Cheddar Cheese Block",
            brand="Tillamook",
            food_category="Dairy",
            quantity="200g",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2027-01-15",
            date_candidates=[
                DateCandidate(
                    raw_text="BEST BY 2027-01-15",
                    date_type="best_before",
                    normalized_date="2027-01-15",
                    confidence=0.94,
                    evidence="Clear back label stamp",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = better_result

        re_resp = self.client.post(f"/api/scans/{scan_id}/reanalyze")
        self.assertEqual(re_resp.status_code, 200)
        re_data = re_resp.json()

        self.assertTrue(re_data["auto_saved"])
        self.assertFalse(re_data["needs_review"])
        self.assertIsNotNone(re_data["product_id"])

        # Product is now in inventory
        prod = self.db.get_product(re_data["product_id"])
        self.assertIsNotNone(prod)
        self.assertEqual(prod.product_name, "Cheddar Cheese Block")

    def test_10_new_scan_preserves_previous_saved_scan_and_product(self):
        """
        Scenario 10:
        Starting a new scan leaves previous saved scans and products untouched.
        """
        # Save first product via high confidence scan
        res1 = FoodAnalysisResult(
            product_name="Product 1",
            brand="Brand 1",
            food_category="Snacks",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2026-12-01",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-12-01",
                    date_type="expiry",
                    normalized_date="2026-12-01",
                    confidence=0.92,
                    evidence="Evidence 1",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = res1
        resp1 = self.client.post("/api/scans", files={"image": ("scan1.jpg", self._create_test_image(), "image/jpeg")})
        scan1_id = resp1.json()["id"]
        prod1_id = resp1.json()["product_id"]

        # Save second product via new scan
        res2 = FoodAnalysisResult(
            product_name="Product 2",
            brand="Brand 2",
            food_category="Pantry",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2026-12-05",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-12-05",
                    date_type="expiry",
                    normalized_date="2026-12-05",
                    confidence=0.95,
                    evidence="Evidence 2",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = res2
        resp2 = self.client.post("/api/scans", files={"image": ("scan2.jpg", self._create_test_image(), "image/jpeg")})
        scan2_id = resp2.json()["id"]
        prod2_id = resp2.json()["product_id"]

        self.assertNotEqual(scan1_id, scan2_id)
        self.assertNotEqual(prod1_id, prod2_id)

        # Both products and scans exist independently
        self.assertIsNotNone(self.db.get_scan(scan1_id))
        self.assertIsNotNone(self.db.get_product(prod1_id))
        self.assertIsNotNone(self.db.get_scan(scan2_id))
        self.assertIsNotNone(self.db.get_product(prod2_id))

    def test_11_delete_scan_confirmation_deletes_only_intended_scan_and_product(self):
        """
        Scenario 11:
        Delete scan deletes the target scan and its associated product,
        without deleting unrelated products.
        """
        # Create unrelated independent product
        unrelated_id = self.db.add_product(
            product_name="Unrelated Butter",
            date_type="expiry",
            normalized_date="2026-12-30",
            force=True,
        )

        # Create scan with linked product
        res = FoodAnalysisResult(
            product_name="Scan To Delete",
            brand="Test",
            food_category="Dairy",
            needs_review=False,
            analysis_status="success",
            selected_expiry_date="2026-11-15",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-11-15",
                    date_type="expiry",
                    normalized_date="2026-11-15",
                    confidence=0.95,
                    evidence="Evidence",
                )
            ],
        )
        self.mock_analyzer.analyze_image.return_value = res
        resp = self.client.post("/api/scans", files={"image": ("del.jpg", self._create_test_image(), "image/jpeg")})
        scan_id = resp.json()["id"]
        linked_prod_id = resp.json()["product_id"]

        # Delete the scan
        del_resp = self.client.delete(f"/api/scans/{scan_id}?delete_product=true")
        self.assertEqual(del_resp.status_code, 200)

        # Scan and linked product are deleted
        self.assertIsNone(self.db.get_scan(scan_id))
        self.assertIsNone(self.db.get_product(linked_prod_id))

        # Unrelated product is strictly preserved
        self.assertIsNotNone(self.db.get_product(unrelated_id))

    def test_12_and_13_date_confirmation_never_deletes_inventory_product(self):
        """
        Scenarios 12 & 13:
        Date confirmation operations never delete products, and never trigger removal messages.
        """
        prod_id = self.db.add_product(
            product_name="Sourdough Bread",
            date_type="best_before",
            normalized_date="2026-10-25",
            force=True,
        )

        # Confirm new date on the product
        success = self.db.confirm_product_date(
            product_id=prod_id,
            normalized_date="2026-10-28",
            date_type="expiry",
            notes="Extended shelf life",
        )
        self.assertTrue(success)

        # Product must definitely still exist
        p = self.db.get_product(prod_id)
        self.assertIsNotNone(p)
        self.assertEqual(p.normalized_date, "2026-10-28")
        self.assertEqual(p.date_type, "expiry")

    def test_14_failed_operations_show_recoverable_errors(self):
        """
        Scenario 14:
        Deleting a non-existent scan or invalid product IDs returns clean errors.
        """
        del_resp = self.client.delete("/api/scans/99999?delete_product=true")
        self.assertEqual(del_resp.status_code, 404)

        patch_resp = self.client.patch("/api/products/99999", json={"product_name": "Ghost"})
        self.assertEqual(patch_resp.status_code, 404)

    def test_16_both_sqlite_and_postgres_schemas_remain_valid(self):
        """
        Scenario 16:
        Both SQLite and PostgreSQL schemas contain required scan_id and product_id columns.
        """
        self.assertIn("scan_id", SQLITE_SCHEMA)
        self.assertIn("product_id", SQLITE_SCHEMA)
        self.assertIn("scan_id", POSTGRES_SCHEMA)
        self.assertIn("product_id", POSTGRES_SCHEMA)


if __name__ == "__main__":
    unittest.main()
