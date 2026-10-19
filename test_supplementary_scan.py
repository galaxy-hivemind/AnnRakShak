"""
AnnaRakshak — Comprehensive Supplementary Scan & Evidence Merging Tests
========================================================================
Validates multi-image supplementary scanning, evidence merging, conflict detection,
confidence assessment, auto-save / manual review workflows, and stable scan ID integrity.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from api import app, get_analyzer, get_db
from evidence_merger import merge_scan_results
from gemini_analyzer import DateCandidate, FoodAnalysisResult, GeminiAnalyzer
from inventory_db import InventoryDatabase


class TestEvidenceMerger(unittest.TestCase):
    """Test deterministic evidence merging logic."""

    def test_missing_expiry_filled_by_second_image(self):
        """A second image can fill a missing expiry date while retaining original identity."""
        orig = FoodAnalysisResult(
            product_name="Bisleri Mineral Water",
            brand="Bisleri",
            food_category="Beverage",
            quantity="1 L",
            date_candidates=[],
            selected_expiry_date=None,
            analysis_status="needs_review",
            needs_review=True,
            review_reason="Expiry date missing",
        )
        supp = FoodAnalysisResult(
            product_name=None,
            brand=None,
            food_category=None,
            quantity=None,
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2027-05-20",
                    date_type="expiry",
                    normalized_date="2027-05-20",
                    confidence=0.95,
                    evidence="Printed on bottle neck",
                )
            ],
            selected_expiry_date="2027-05-20",
            analysis_status="success",
            needs_review=False,
        )

        outcome = merge_scan_results(orig, supp)
        res = outcome.merged_result

        self.assertEqual(res.product_name, "Bisleri Mineral Water")
        self.assertEqual(res.brand, "Bisleri")
        self.assertEqual(res.food_category, "Beverage")
        self.assertEqual(res.quantity, "1 L")
        self.assertEqual(res.selected_expiry_date, "2027-05-20")
        self.assertFalse(outcome.has_conflicts)
        self.assertIn("selected_expiry_date", outcome.fields_updated)
        self.assertEqual(len(res.date_candidates), 1)
        self.assertIn("[Supplementary capture]", res.date_candidates[0].evidence)

    def test_missing_mfg_filled_by_second_image(self):
        """A second image can add a missing manufacturing date without treating it as expiry."""
        orig = FoodAnalysisResult(
            product_name="Amul Butter",
            brand="Amul",
            food_category="Dairy",
            quantity="500 g",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2027-03-01",
                    date_type="expiry",
                    normalized_date="2027-03-01",
                    confidence=0.92,
                    evidence="Printed on side panel",
                )
            ],
            selected_expiry_date="2027-03-01",
            analysis_status="success",
            needs_review=False,
        )
        supp = FoodAnalysisResult(
            product_name=None,
            brand=None,
            food_category=None,
            quantity=None,
            date_candidates=[
                DateCandidate(
                    raw_text="MFD 2026-10-15",
                    date_type="manufacturing",
                    normalized_date="2026-10-15",
                    confidence=0.90,
                    evidence="Stamped on bottom flap",
                )
            ],
            selected_expiry_date=None,
            analysis_status="success",
            needs_review=False,
        )

        outcome = merge_scan_results(orig, supp)
        res = outcome.merged_result

        self.assertEqual(res.selected_expiry_date, "2027-03-01")
        self.assertEqual(len(res.date_candidates), 2)
        # Verify manufacturing date is not selected as expiry date
        types = {c.date_type: c.normalized_date for c in res.date_candidates}
        self.assertEqual(types.get("manufacturing"), "2026-10-15")
        self.assertEqual(types.get("expiry"), "2027-03-01")
        self.assertFalse(outcome.has_conflicts)

    def test_second_image_adds_missing_product_info(self):
        """A second image can add previously missing brand and quantity."""
        orig = FoodAnalysisResult(
            product_name="Corn Flakes",
            brand=None,
            food_category="Grains",
            quantity=None,
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2027-06-30",
                    date_type="expiry",
                    normalized_date="2027-06-30",
                    confidence=0.95,
                    evidence="Top flap",
                )
            ],
            selected_expiry_date="2027-06-30",
            analysis_status="success",
            needs_review=False,
        )
        supp = FoodAnalysisResult(
            product_name="Corn Flakes",
            brand="Kellogg's",
            food_category="Grains",
            quantity="475 g",
            date_candidates=[],
            selected_expiry_date=None,
            analysis_status="success",
            needs_review=False,
        )

        outcome = merge_scan_results(orig, supp)
        res = outcome.merged_result

        self.assertEqual(res.product_name, "Corn Flakes")
        self.assertEqual(res.brand, "Kellogg's")
        self.assertEqual(res.quantity, "475 g")
        self.assertEqual(res.selected_expiry_date, "2027-06-30")
        self.assertIn("brand", outcome.fields_updated)
        self.assertIn("quantity", outcome.fields_updated)

    def test_strong_original_evidence_not_overwritten_by_weaker_new_evidence(self):
        """A confident original product name is not overwritten by an unreadable second image."""
        orig = FoodAnalysisResult(
            product_name="Dettol Antiseptic Liquid",
            brand="Dettol",
            food_category="Medicine",
            quantity="250 ml",
            date_candidates=[],
            selected_expiry_date=None,
            analysis_status="needs_review",
            needs_review=True,
        )
        supp = FoodAnalysisResult(
            product_name="Unknown Item",
            brand=None,
            food_category=None,
            quantity=None,
            date_candidates=[],
            selected_expiry_date=None,
            analysis_status="needs_review",
            needs_review=True,
        )

        outcome = merge_scan_results(orig, supp)
        res = outcome.merged_result

        self.assertEqual(res.product_name, "Dettol Antiseptic Liquid")
        self.assertEqual(res.brand, "Dettol")
        self.assertEqual(res.food_category, "Medicine")

    def test_conflicting_dates_trigger_manual_review(self):
        """Conflicting expiry dates across captures flag conflict and force manual review."""
        orig = FoodAnalysisResult(
            product_name="Organic Milk",
            brand="Organic Valley",
            food_category="Dairy",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-11-01",
                    date_type="expiry",
                    normalized_date="2026-11-01",
                    confidence=0.90,
                    evidence="Cap stamp",
                )
            ],
            selected_expiry_date="2026-11-01",
            analysis_status="success",
            needs_review=False,
        )
        supp = FoodAnalysisResult(
            product_name="Organic Milk",
            brand="Organic Valley",
            food_category="Dairy",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-11-20",
                    date_type="expiry",
                    normalized_date="2026-11-20",
                    confidence=0.88,
                    evidence="Side printed code",
                )
            ],
            selected_expiry_date="2026-11-20",
            analysis_status="success",
            needs_review=False,
        )

        outcome = merge_scan_results(orig, supp)
        res = outcome.merged_result

        self.assertTrue(outcome.has_conflicts)
        self.assertTrue(res.needs_review)
        self.assertIn("Conflicting expiry dates", res.review_reason)

    def test_user_edited_fields_preserved(self):
        """User explicit edits take precedence over model output from both captures."""
        orig = FoodAnalysisResult(
            product_name="Plain Salt",
            brand="Generic",
            food_category="Pantry",
            date_candidates=[],
            analysis_status="needs_review",
            needs_review=True,
        )
        supp = FoodAnalysisResult(
            product_name="Iodized Table Salt",
            brand="Tata",
            food_category="Pantry",
            date_candidates=[],
            analysis_status="needs_review",
            needs_review=True,
        )
        overrides = {
            "name": "My Custom Salt",
            "brand": "Special Brand",
            "quantity": "1 kg",
        }

        outcome = merge_scan_results(orig, supp, user_overrides=overrides)
        res = outcome.merged_result

        self.assertEqual(res.product_name, "My Custom Salt")
        self.assertEqual(res.brand, "Special Brand")
        self.assertEqual(res.quantity, "1 kg")

    def test_expiry_earlier_than_mfg_flags_conflict(self):
        """Expiry date earlier than manufacturing date flags a conflict."""
        orig = FoodAnalysisResult(
            product_name="Fruit Juice",
            brand="Tropicana",
            food_category="Beverage",
            date_candidates=[
                DateCandidate(
                    raw_text="MFD 2027-01-01",
                    date_type="manufacturing",
                    normalized_date="2027-01-01",
                    confidence=0.95,
                    evidence="Top cap",
                )
            ],
            selected_expiry_date=None,
            analysis_status="needs_review",
            needs_review=True,
        )
        supp = FoodAnalysisResult(
            product_name=None,
            brand=None,
            food_category=None,
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-05-01",
                    date_type="expiry",
                    normalized_date="2026-05-01",
                    confidence=0.90,
                    evidence="Side label",
                )
            ],
            selected_expiry_date="2026-05-01",
            analysis_status="success",
            needs_review=False,
        )

        outcome = merge_scan_results(orig, supp)
        self.assertTrue(outcome.has_conflicts)
        self.assertTrue(outcome.merged_result.needs_review)
        self.assertIn("earlier than manufacturing date", outcome.merged_result.review_reason)


class TestSupplementaryScanAPI(unittest.TestCase):
    """End-to-end tests for supplementary scan API and database persistence."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_supp.db"
        self.db = InventoryDatabase(db_path=self.db_path)
        self.mock_analyzer = MagicMock(spec=GeminiAnalyzer)

        app.state.db = self.db
        app.state.analyzer = self.mock_analyzer
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_analyzer] = lambda: self.mock_analyzer

        self.client = TestClient(app)

        # Create sample JPEG bytes
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        _, encoded = cv2.imencode(".jpg", img)
        self.sample_jpeg = encoded.tobytes()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        self.temp_dir.cleanup()

    def _create_initial_scan(self, auto_save: bool = False) -> int:
        """Helper to create an initial scan in the database."""
        result = FoodAnalysisResult(
            product_name="Kinley Club Soda",
            brand="Kinley",
            food_category="Beverage",
            quantity=None,
            date_candidates=[] if not auto_save else [
                DateCandidate(
                    raw_text="EXP 2027-08-10",
                    date_type="expiry",
                    normalized_date="2027-08-10",
                    confidence=0.95,
                    evidence="Cap",
                )
            ],
            selected_expiry_date="2027-08-10" if auto_save else None,
            analysis_status="success",
            needs_review=not auto_save,
            review_reason=None if auto_save else "Expiry date missing",
        )
        scan_id = self.db.record_scan("captures/init_scan.jpg", result=result)
        if auto_save:
            self.db.add_product(
                product_name=result.product_name,
                brand=result.brand,
                food_category=result.food_category,
                date_type="expiry",
                date_text=None,
                normalized_date=result.selected_expiry_date,
                date_status="confirmed",
                date_source="printed",
                analysis_status="success",
                image_path="captures/init_scan.jpg",
                scan_id=scan_id,
            )
        return scan_id

    @patch("api.run_local_ocr")
    def test_supplementary_capture_uses_same_scan_id(self, mock_ocr):
        """Supplementary capture uses the same scan ID across the sequence."""
        mock_ocr.return_value = None
        scan_id = self._create_initial_scan(auto_save=False)

        mock_supp_result = FoodAnalysisResult(
            product_name=None,
            brand=None,
            food_category=None,
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2027-09-15",
                    date_type="expiry",
                    normalized_date="2027-09-15",
                    confidence=0.95,
                    evidence="Side panel",
                )
            ],
            selected_expiry_date="2027-09-15",
            analysis_status="success",
            needs_review=False,
        )
        self.mock_analyzer.analyze_image.return_value = mock_supp_result

        resp = self.client.post(
            f"/api/scans/{scan_id}/supplementary",
            files={"image": ("supp.jpg", self.sample_jpeg, "image/jpeg")},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], scan_id)
        self.assertEqual(data["product_name"], "Kinley Club Soda")
        self.assertEqual(data["selected_expiry_date"], "2027-09-15")
        self.assertTrue(len(data["supplementary_images"]) >= 1)

    @patch("api.run_local_ocr")
    def test_high_confidence_consolidated_result_auto_saves(self, mock_ocr):
        """Consolidated result that fulfills auto-save criteria automatically saves to inventory."""
        mock_ocr.return_value = None
        scan_id = self._create_initial_scan(auto_save=False)
        self.assertEqual(len(self.db.list_products()), 0)

        mock_supp_result = FoodAnalysisResult(
            product_name="Kinley Club Soda",
            brand="Kinley",
            food_category="Beverage",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2027-12-01",
                    date_type="expiry",
                    normalized_date="2027-12-01",
                    confidence=0.95,
                    evidence="Printed date code",
                )
            ],
            selected_expiry_date="2027-12-01",
            analysis_status="success",
            needs_review=False,
        )
        self.mock_analyzer.analyze_image.return_value = mock_supp_result

        resp = self.client.post(
            f"/api/scans/{scan_id}/supplementary",
            files={"image": ("supp.jpg", self.sample_jpeg, "image/jpeg")},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["auto_saved"])
        self.assertIsNotNone(data["product_id"])

        # Check inventory product created
        products = self.db.list_products()
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].product_name, "Kinley Club Soda")
        self.assertEqual(products[0].normalized_date, "2027-12-01")
        self.assertEqual(products[0].scan_id, scan_id)

    @patch("api.run_local_ocr")
    def test_supplementary_updates_existing_auto_saved_product(self, mock_ocr):
        """Supplementary capture updates an already auto-saved product rather than creating a duplicate."""
        mock_ocr.return_value = None
        scan_id = self._create_initial_scan(auto_save=True)
        products_before = self.db.list_products()
        self.assertEqual(len(products_before), 1)
        initial_prod_id = products_before[0].id

        mock_supp_result = FoodAnalysisResult(
            product_name="Kinley Club Soda",
            brand="Kinley",
            food_category="Beverage",
            quantity="1.25 L",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2027-08-10",
                    date_type="expiry",
                    normalized_date="2027-08-10",
                    confidence=0.95,
                    evidence="Cap",
                )
            ],
            selected_expiry_date="2027-08-10",
            analysis_status="success",
            needs_review=False,
        )
        self.mock_analyzer.analyze_image.return_value = mock_supp_result

        resp = self.client.post(
            f"/api/scans/{scan_id}/supplementary",
            files={"image": ("supp.jpg", self.sample_jpeg, "image/jpeg")},
        )

        self.assertEqual(resp.status_code, 200)
        products_after = self.db.list_products()
        self.assertEqual(len(products_after), 1)  # No duplicate product!
        self.assertEqual(products_after[0].id, initial_prod_id)
        self.assertIn("1.25 L", products_after[0].notes or "")

    @patch("api.run_local_ocr")
    def test_low_confidence_consolidated_result_remains_in_review(self, mock_ocr):
        """If consolidated result remains uncertain, product remains out of inventory."""
        mock_ocr.return_value = None
        scan_id = self._create_initial_scan(auto_save=False)

        mock_supp_result = FoodAnalysisResult(
            product_name=None,
            brand=None,
            food_category=None,
            date_candidates=[
                DateCandidate(
                    raw_text="OCT 2027",
                    date_type="expiry",
                    normalized_date=None,  # Month-only, uncertain day
                    confidence=0.60,
                    evidence="Faint ink stamp",
                )
            ],
            selected_expiry_date=None,
            analysis_status="needs_review",
            needs_review=True,
            review_reason="Month-only date, exact day unknown",
        )
        self.mock_analyzer.analyze_image.return_value = mock_supp_result

        resp = self.client.post(
            f"/api/scans/{scan_id}/supplementary",
            files={"image": ("supp.jpg", self.sample_jpeg, "image/jpeg")},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["auto_saved"])
        self.assertTrue(data["needs_review"])
        self.assertIsNone(data["product_id"])
        self.assertEqual(len(self.db.list_products()), 0)

    @patch("api.run_local_ocr")
    def test_failed_supplementary_analysis_preserves_original_scan(self, mock_ocr):
        """Failed supplementary analysis preserves original scan and returns error."""
        mock_ocr.return_value = None
        scan_id = self._create_initial_scan(auto_save=False)
        orig_scan = self.db.get_scan(scan_id)

        self.mock_analyzer.analyze_image.side_effect = RuntimeError("AI Timeout")

        resp = self.client.post(
            f"/api/scans/{scan_id}/supplementary",
            files={"image": ("supp.jpg", self.sample_jpeg, "image/jpeg")},
        )

        self.assertEqual(resp.status_code, 500)
        # Verify original scan is intact
        scan_after = self.db.get_scan(scan_id)
        self.assertEqual(scan_after.product_name, orig_scan.product_name)
        self.assertEqual(scan_after.needs_review, orig_scan.needs_review)
        self.assertEqual(scan_after.product_name, orig_scan.product_name)
        self.assertEqual(scan_after.needs_review, orig_scan.needs_review)

    @patch("api.run_local_ocr")
    def test_delete_scan_cleans_up_all_captures(self, mock_ocr):
        """Deleting a scan removes both primary and supplementary capture files."""
        mock_ocr.return_value = None
        # Create temp files on disk to test cleanup
        temp_dir = Path("captures")
        temp_dir.mkdir(exist_ok=True)
        prim_file = temp_dir / "test_prim.jpg"
        supp_file = temp_dir / "test_supp.jpg"
        prim_file.write_bytes(self.sample_jpeg)
        supp_file.write_bytes(self.sample_jpeg)

        try:
            result = FoodAnalysisResult(
                product_name="Test Item",
                brand="Brand",
                food_category="Snacks",
                date_candidates=[],
                analysis_status="success",
                needs_review=False,
            )
            scan_id = self.db.record_scan(str(prim_file), result=result)
            self.db.update_scan(scan_id, result=result, supplementary_image_path=str(supp_file))

            # Delete the scan
            success, _ = self.db.delete_scan(scan_id)
            self.assertTrue(success)

            # Check both files removed
            self.assertFalse(prim_file.exists())
            self.assertFalse(supp_file.exists())
        finally:
            if prim_file.exists():
                prim_file.unlink()
            if supp_file.exists():
                supp_file.unlink()


if __name__ == "__main__":
    unittest.main()
