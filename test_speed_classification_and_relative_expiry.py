"""
AnnaRakshak — Speed, Product Classification & Relative Expiry Tests
==================================================================
Comprehensive test suite verifying:
  1. Phase 1: Structured latency timing measurements & metadata exposure.
  2. Phase 2: Reliable product classification with deterministic rules:
     - Cough syrup -> Medicine
     - Tablets & capsules -> Medicine
     - Fruit juice -> Beverage
     - Packaged milk -> Dairy
     - Genuinely ambiguous product -> Uncertain / Needs Review
     - Medicine is NEVER classified as Beverage due to liquid/syrup.
  3. Phase 3: Relative shelf-life & expiry date interpretation:
     - "Best before 4 months from date of manufacture" calculated from verified MFG
     - "Best before 6 months from MFG"
     - "Shelf life: 12 months from manufacturing"
     - Calendar arithmetic with month-end clamping (Aug 31 -> Sep 30, Jan 31 -> Feb 28)
     - Leap year arithmetic (Jan 31, 2024 -> Feb 29, 2024)
     - "Use within 30 days of opening" -> after-opening instruction without invented date
     - Missing reference date ("Best before 4 months" alone) -> no invented date, review flagged
     - Zero silent conversions: MFG is never converted to EXP.
"""

from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
from fastapi.testclient import TestClient

from api import app, get_analyzer, get_db, serialize_scan
from gemini_analyzer import DateCandidate, FoodAnalysisResult, GeminiAnalyzer
from inventory_db import InventoryDatabase
from product_classifier import (
    CATEGORY_BEVERAGE,
    CATEGORY_DAIRY,
    CATEGORY_GRAINS,
    CATEGORY_MEDICINE,
    CATEGORY_PANTRY,
    CATEGORY_SNACKS,
    ProductClassifier,
)
from relative_expiry import (
    RelativeExpiryResolver,
    add_calendar_months,
)


class TestProductClassification(unittest.TestCase):
    """Phase 2: Tests for high-confidence deterministic product categorization."""

    def test_cough_syrup_classified_as_medicine(self):
        """Cough syrup must be classified as Medicine, never Beverage."""
        res = ProductClassifier.classify(
            product_name="Benadryl Cough Syrup",
            brand="Benadryl",
            label_text="Oral cough and cold syrup 100ml. Relieves chest congestion.",
            product_form="syrup",
        )
        self.assertEqual(res.category, CATEGORY_MEDICINE)
        self.assertNotEqual(res.category, CATEGORY_BEVERAGE)
        self.assertEqual(res.source, "rule_deterministic")
        self.assertFalse(res.needs_review)

    def test_tablets_and_capsules_classified_as_medicine(self):
        """Tablets and capsules must be classified as Medicine."""
        # Tablets
        res_tab = ProductClassifier.classify(
            product_name="Dolo 650 Tablets",
            brand="Micro Labs",
            label_text="Paracetamol Tablets IP 650 mg. Dosage: As directed by physician.",
            product_form="tablets",
        )
        self.assertEqual(res_tab.category, CATEGORY_MEDICINE)
        self.assertEqual(res_tab.source, "rule_deterministic")

        # Capsules
        res_cap = ProductClassifier.classify(
            product_name="Amoxicillin Capsules",
            brand="Novartis",
            label_text="500 mg capsules USP. Prescription only. Schedule H drug.",
            product_form="capsules",
        )
        self.assertEqual(res_cap.category, CATEGORY_MEDICINE)
        self.assertEqual(res_cap.source, "rule_deterministic")

    def test_fruit_juice_classified_as_beverage(self):
        """Fruit juice must be classified as Beverage."""
        res = ProductClassifier.classify(
            product_name="Real Fruit Juice Mixed Fruit",
            brand="Real",
            label_text="100% natural mixed fruit juice drink. Refreshing beverage.",
            product_form="liquid",
        )
        self.assertEqual(res.category, CATEGORY_BEVERAGE)
        self.assertEqual(res.source, "rule_deterministic")
        self.assertFalse(res.needs_review)

    def test_packaged_milk_classified_as_dairy(self):
        """Packaged milk must be classified as Dairy."""
        res = ProductClassifier.classify(
            product_name="Amul Taaza Toned Milk",
            brand="Amul",
            label_text="Pasteurized homogenized toned milk. Per 100ml.",
            product_form="liquid",
        )
        self.assertEqual(res.category, CATEGORY_DAIRY)
        self.assertEqual(res.source, "rule_deterministic")
        self.assertFalse(res.needs_review)

    def test_ambiguous_product_yields_uncertain_and_needs_review(self):
        """Genuinely ambiguous product must return uncertain state and flag review."""
        res = ProductClassifier.classify(
            product_name="Generic Batch Item",
            brand="Vendor 42",
            label_text="Batch code 847291 Net Wt 500g",
            product_form=None,
        )
        self.assertIsNone(res.category)
        self.assertEqual(res.source, "uncertain")
        self.assertTrue(res.needs_review)
        self.assertIn("ambiguous", (res.review_reason or "").lower())

    def test_medicine_never_classified_as_beverage_even_if_liquid_syrup(self):
        """Even if text calls it a soothing syrup or liquid, medicine is never beverage."""
        res = ProductClassifier.classify(
            product_name="Honey Menthol Cough Syrup",
            brand="Vicks",
            label_text="Liquid syrup for soothing dry cough and throat irritation. 5ml dose.",
            product_form="liquid syrup",
        )
        self.assertEqual(res.category, CATEGORY_MEDICINE)
        self.assertNotEqual(res.category, CATEGORY_BEVERAGE)

    def test_post_validate_overrides_accidental_beverage_to_medicine(self):
        """FoodAnalysisResult.post_validate must override accidental AI Beverage category to Medicine."""
        initial = FoodAnalysisResult(
            product_name="Corex Cough Syrup",
            brand="Pfizer",
            food_category="Beverage",  # Accidental misclassification
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 04/2027",
                    date_type="expiry",
                    normalized_date=None,
                    confidence=0.9,
                    evidence="100ml cough syrup",
                )
            ],
            analysis_status="success",
            needs_review=False,
        )
        validated = FoodAnalysisResult.post_validate(initial)
        self.assertEqual(validated.food_category, CATEGORY_MEDICINE)


class TestRelativeExpiryAndCalendarArithmetic(unittest.TestCase):
    """Phase 3: Tests for relative shelf-life calculations and calendar arithmetic."""

    def test_calendar_arithmetic_month_end_clamping(self):
        """Jan 31 + 1 month in non-leap year must clamp to Feb 28."""
        d = datetime.date(2026, 1, 31)
        res = add_calendar_months(d, 1)
        self.assertEqual(res, datetime.date(2026, 2, 28))

    def test_calendar_arithmetic_leap_year(self):
        """Jan 31 + 1 month in leap year (2024) must clamp to Feb 29."""
        d = datetime.date(2024, 1, 31)
        res = add_calendar_months(d, 1)
        self.assertEqual(res, datetime.date(2024, 2, 29))

    def test_calendar_arithmetic_31_to_30_days(self):
        """Aug 31 + 1 month must clamp to Sep 30."""
        d = datetime.date(2026, 8, 31)
        res = add_calendar_months(d, 1)
        self.assertEqual(res, datetime.date(2026, 9, 30))

    def test_calendar_arithmetic_across_year_boundary(self):
        """Oct 10, 2026 + 4 months must equal Feb 10, 2027."""
        d = datetime.date(2026, 10, 10)
        res = add_calendar_months(d, 4)
        self.assertEqual(res, datetime.date(2027, 2, 10))

    def test_best_before_months_from_verified_mfg(self):
        """Best before 4 months from date of manufacture calculates from verified MFG date."""
        text = "Best before 4 months from date of manufacture"
        results = RelativeExpiryResolver.parse_relative_clauses(text, verified_mfg_date="2026-10-10")
        self.assertEqual(len(results), 1)
        rel = results[0]
        self.assertEqual(rel.date_type, "best_before")
        self.assertEqual(rel.normalized_date, "2027-02-10")
        self.assertTrue(rel.is_calculated)
        self.assertFalse(rel.needs_review)
        self.assertIn("verified manufacturing date", rel.evidence)

    def test_best_before_months_from_mfg_abbreviation(self):
        """Best before 6 months from MFG calculates accurately."""
        text = "Best before 6 months from MFG"
        results = RelativeExpiryResolver.parse_relative_clauses(text, verified_mfg_date="2026-05-31")
        self.assertEqual(len(results), 1)
        rel = results[0]
        self.assertEqual(rel.normalized_date, "2026-11-30")
        self.assertTrue(rel.is_calculated)

    def test_shelf_life_duration_from_manufacturing(self):
        """Shelf life: 12 months from manufacturing calculates accurately."""
        text = "Shelf life: 12 months from manufacturing"
        results = RelativeExpiryResolver.parse_relative_clauses(text, verified_mfg_date="2026-03-15")
        self.assertEqual(len(results), 1)
        rel = results[0]
        self.assertEqual(rel.normalized_date, "2027-03-15")
        self.assertFalse(rel.needs_review)

    def test_missing_reference_date_flags_review_without_inventing_date(self):
        """If 'Best before 4 months' has no verified reference date, do not invent calendar date."""
        text = "Best before 4 months"
        results = RelativeExpiryResolver.parse_relative_clauses(text, verified_mfg_date=None)
        self.assertEqual(len(results), 1)
        rel = results[0]
        self.assertIsNone(rel.normalized_date)
        self.assertFalse(rel.is_calculated)
        self.assertTrue(rel.needs_review)
        self.assertIn("verified manufacturing date is missing", rel.review_reason)

    def test_use_within_30_days_of_opening_not_converted_to_expiry_date(self):
        """'Use within 30 days of opening' is an after-opening instruction, not calendar expiry."""
        text = "Use within 30 days of opening"
        results = RelativeExpiryResolver.parse_relative_clauses(text, verified_mfg_date="2026-10-10")
        self.assertEqual(len(results), 1)
        rel = results[0]
        self.assertEqual(rel.date_type, "after_opening")
        self.assertIsNone(rel.normalized_date)
        self.assertTrue(rel.needs_review)
        self.assertIn("opening date is not recorded", rel.review_reason)

    def test_post_validate_resolves_relative_expiry_with_verified_mfg(self):
        """FoodAnalysisResult.post_validate calculates selected_expiry_date when relative text and MFG are present."""
        initial = FoodAnalysisResult(
            product_name="Harvest Gold Bread",
            brand="Harvest Gold",
            food_category="Bakery",
            date_candidates=[
                DateCandidate(
                    raw_text="MFD 10/10/2026",
                    date_type="manufacturing",
                    normalized_date="2026-10-10",
                    confidence=0.95,
                    evidence="Printed on packaging side",
                ),
                DateCandidate(
                    raw_text="Best before 4 months from date of manufacture",
                    date_type="best_before",
                    normalized_date=None,
                    confidence=0.9,
                    evidence="Printed on back label",
                ),
            ],
            analysis_status="success",
            needs_review=False,
        )
        validated = FoodAnalysisResult.post_validate(initial)
        self.assertEqual(validated.selected_expiry_date, "2027-02-10")
        bb_candidate = next(c for c in validated.date_candidates if "Best before" in c.raw_text)
        self.assertEqual(bb_candidate.normalized_date, "2027-02-10")


class TestStructuredTimingAndApiLatency(unittest.TestCase):
    """Phase 1: Tests verifying structured latency metrics in API scan responses."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_timing.db"
        self.db = InventoryDatabase(db_path=self.db_path)

        self.mock_analyzer = MagicMock(spec=GeminiAnalyzer)
        self.mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            product_name="Amul Taaza Milk",
            brand="Amul",
            food_category="Dairy",
            selected_expiry_date="2026-10-20",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 20/10/2026",
                    date_type="expiry",
                    normalized_date="2026-10-20",
                    confidence=0.95,
                    evidence="Printed on carton",
                )
            ],
            analysis_status="success",
            needs_review=False,
            models_attempted=["gemini-3.5-flash-lite"],
            retries_count=0,
        )

        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_analyzer] = lambda: self.mock_analyzer
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.temp_dir.cleanup()

    def test_scan_response_includes_structured_timing_metadata(self):
        """POST /api/scans must return timing metadata with upload, ocr, gemini, db, and total latency."""
        # Create a small valid JPEG image
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        _, img_encoded = cv2.imencode(".jpg", img)

        res = self.client.post(
            "/api/scans",
            files={"image": ("test.jpg", img_encoded.tobytes(), "image/jpeg")},
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()

        self.assertIn("timing", data)
        self.assertIsNotNone(data["timing"])
        timing = data["timing"]
        self.assertIn("upload_preprocess_ms", timing)
        self.assertIn("ocr_ms", timing)
        self.assertIn("gemini_ms", timing)
        self.assertIn("db_ms", timing)
        self.assertIn("total_ms", timing)
        self.assertIn("models_attempted", timing)
        self.assertIn("retries_count", timing)

        self.assertGreaterEqual(timing["total_ms"], 0.0)
        self.assertEqual(timing["models_attempted"], ["gemini-3.5-flash-lite"])


if __name__ == "__main__":
    unittest.main()
