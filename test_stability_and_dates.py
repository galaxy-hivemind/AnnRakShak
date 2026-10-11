"""
AnnaRakshak — Offline Regression Test Suite for Capture Stability & Date Extraction
=====================================================================================
Covers Bug Fixes:
  Part A:
    1. Preserving and surfacing multiple date candidates end-to-end.
    2. Missing/ambiguous dates requiring review.
    3. Proper formatting of human-readable Date candidates review block.
    4. Safe inventory add-scan workflow with candidate selection and user confirmation.
    5. Re-analysis of saved images without accidental scan-history duplication.
  Part B:
    1. Continuous 2.5s elapsed monotonic time stability requirement.
    2. Blocking premature capture before 2.5s.
    3. Triggering capture at 2.5s.
    4. Movement resetting stability timer.
    5. Disappearing text resetting stability timer.
    6. Repeated frames preventing duplicate capture.
    7. Removal rearming the scanner.
    8. Custom configurable stability duration.

Zero physical camera, network access, or real Gemini API keys required.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from auto_scan import DEFAULT_CAPTURE_STABILITY_SECONDS, ScanState, TextScanEngine
from gemini_analyzer import (
    DateCandidate,
    FoodAnalysisResult,
    GeminiAnalyzer,
    format_date_candidates_review,
)
from inventory_db import InventoryDatabase
from ocr_engine import MockOCREngine, OCRResult, TextRegion


def make_dummy_frame() -> np.ndarray:
    return np.zeros((120, 160, 3), dtype=np.uint8)


class TestCaptureStabilityDuration(unittest.TestCase):
    """Verifies that TextScanEngine enforces the 2.5-second stability requirement."""

    def test_default_stability_threshold_is_2_5_seconds(self) -> None:
        engine = TextScanEngine()
        self.assertEqual(engine.capture_stability_seconds, 2.5)
        self.assertEqual(DEFAULT_CAPTURE_STABILITY_SECONDS, 2.5)

    def test_no_capture_before_2_5_seconds_elapsed(self) -> None:
        """A package held steady must NOT capture at 0.5s, 1.0s, 2.0s, or 2.4s."""
        engine = TextScanEngine(
            capture_stability_seconds=2.5,
            required_consecutive_checks=3,
            skip_calibration=True,
        )
        reg = TextRegion("HONITUS ADULSA", 0.92, 0.3, 0.3, 0.4, 0.2)
        res = OCRResult(regions=[reg])
        frame = make_dummy_frame()

        timestamps = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.4]
        for t in timestamps:
            triggered = engine.update(frame, now=t, ocr_result=res)
            self.assertFalse(triggered, f"Triggered prematurely at t={t}s! Expected >= 2.5s.")
            self.assertIn(engine.state, (ScanState.TEXT_DETECTED, ScanState.VERIFYING_TEXT_STABILITY))

    def test_capture_triggers_at_2_5_seconds(self) -> None:
        """Package held steady for >= 2.5 seconds must trigger capture exactly once."""
        engine = TextScanEngine(
            capture_stability_seconds=2.5,
            required_consecutive_checks=3,
            skip_calibration=True,
        )
        reg = TextRegion("HONITUS ADULSA", 0.92, 0.3, 0.3, 0.4, 0.2)
        res = OCRResult(regions=[reg])
        frame = make_dummy_frame()

        # Check 1 (t=0.0): text detected
        self.assertFalse(engine.update(frame, now=0.0, ocr_result=res))
        # Check 2 (t=1.0): still verifying
        self.assertFalse(engine.update(frame, now=1.0, ocr_result=res))
        # Check 3 (t=2.0): still verifying
        self.assertFalse(engine.update(frame, now=2.0, ocr_result=res))
        # Check 4 (t=2.5): reached threshold -> triggers!
        triggered = engine.update(frame, now=2.5, ocr_result=res)
        self.assertTrue(triggered, "Must trigger capture when 2.5s stability is reached.")
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_movement_resets_stability_timer(self) -> None:
        """Excessive package motion resets the stability elapsed timer."""
        engine = TextScanEngine(
            capture_stability_seconds=2.5,
            required_consecutive_checks=3,
            max_drift=0.10,
            skip_calibration=True,
        )
        frame = make_dummy_frame()

        # Position A: center at (0.2, 0.2)
        reg_a = TextRegion("HONITUS", 0.9, 0.2, 0.2, 0.2, 0.1)
        res_a = OCRResult(regions=[reg_a])

        # Hold steady for 2.0 seconds at Position A
        engine.update(frame, now=0.0, ocr_result=res_a)
        engine.update(frame, now=1.0, ocr_result=res_a)
        engine.update(frame, now=2.0, ocr_result=res_a)
        self.assertAlmostEqual(engine.stable_elapsed, 2.0, places=2)

        # At t=2.1, package moves to (0.7, 0.7) -> drift > max_drift
        reg_b = TextRegion("HONITUS", 0.9, 0.7, 0.7, 0.2, 0.1)
        res_b = OCRResult(regions=[reg_b])
        trig_move = engine.update(frame, now=2.1, ocr_result=res_b)
        self.assertFalse(trig_move)
        # Stability timer must have reset to 0.0
        self.assertAlmostEqual(engine.stable_elapsed, 0.0, places=2)
        self.assertEqual(engine.state, ScanState.TEXT_DETECTED)

        # At t=2.5 (only 0.4s since move), must NOT trigger
        trig_early = engine.update(frame, now=2.5, ocr_result=res_b)
        self.assertFalse(trig_early)

        # Must hold steady for another full 2.5s (until t=4.6)
        trig_full = engine.update(frame, now=4.6, ocr_result=res_b)
        self.assertTrue(trig_full)
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_disappearing_text_resets_stability_timer(self) -> None:
        """Package disappearing resets stability timer back to SEARCHING_FOR_TEXT."""
        engine = TextScanEngine(
            capture_stability_seconds=2.5,
            required_consecutive_checks=3,
            skip_calibration=True,
        )
        frame = make_dummy_frame()
        res_text = OCRResult(regions=[TextRegion("MILK", 0.9, 0.2, 0.2, 0.2, 0.1)])
        res_empty = OCRResult(regions=[])

        engine.update(frame, now=0.0, ocr_result=res_text)
        engine.update(frame, now=2.0, ocr_result=res_text)
        self.assertAlmostEqual(engine.stable_elapsed, 2.0, places=2)

        # Text disappears at t=2.2
        engine.update(frame, now=2.2, ocr_result=res_empty)
        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)
        self.assertAlmostEqual(engine.stable_elapsed, 0.0, places=2)

        # Text reappears at t=2.5 -> starts new timer from 0
        engine.update(frame, now=2.5, ocr_result=res_text)
        self.assertEqual(engine.state, ScanState.TEXT_DETECTED)
        self.assertAlmostEqual(engine.stable_elapsed, 0.0, places=2)

        # At t=3.0 (only 0.5s), no capture
        self.assertFalse(engine.update(frame, now=3.0, ocr_result=res_text))

    def test_repeated_frames_do_not_duplicate_capture(self) -> None:
        """Holding package steady after capture must NEVER trigger second capture."""
        engine = TextScanEngine(
            capture_stability_seconds=1.0,
            required_consecutive_checks=2,
            skip_calibration=True,
        )
        frame = make_dummy_frame()
        res = OCRResult(regions=[TextRegion("CHEESE", 0.95, 0.2, 0.2, 0.2, 0.1)])

        # Capture triggers at t=1.0
        engine.update(frame, now=0.0, ocr_result=res)
        self.assertTrue(engine.update(frame, now=1.0, ocr_result=res))
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        # Continue feeding same text for 10 seconds
        for i in range(20):
            trig = engine.update(frame, now=1.0 + (i * 0.5), ocr_result=res)
            self.assertFalse(trig, "Must never trigger duplicate capture while package remains!")
            self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_removing_package_rearms_scanner(self) -> None:
        """Removing package for removal_duration re-arms the scanner."""
        engine = TextScanEngine(
            capture_stability_seconds=1.0,
            required_consecutive_checks=2,
            removal_duration=0.5,
            skip_calibration=True,
        )
        frame = make_dummy_frame()
        res_text = OCRResult(regions=[TextRegion("YOGURT", 0.95, 0.2, 0.2, 0.2, 0.1)])
        res_empty = OCRResult(regions=[])

        # Capture #1
        engine.update(frame, now=0.0, ocr_result=res_text)
        self.assertTrue(engine.update(frame, now=1.0, ocr_result=res_text))

        # Remove package at t=1.2
        engine.update(frame, now=1.2, ocr_result=res_empty)
        # Not rearmed yet at 0.3s removal
        engine.update(frame, now=1.5, ocr_result=res_empty)
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        # Rearmed at t=1.75 (> 0.5s removal duration)
        engine.update(frame, now=1.75, ocr_result=res_empty)
        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)

    def test_custom_configured_stability_duration(self) -> None:
        """Configuring custom stability durations (e.g. 4.0s) behaves accurately."""
        engine = TextScanEngine(
            capture_stability_seconds=4.0,
            required_consecutive_checks=2,
            skip_calibration=True,
        )
        frame = make_dummy_frame()
        res = OCRResult(regions=[TextRegion("ALMOND MILK", 0.9, 0.2, 0.2, 0.2, 0.1)])

        engine.update(frame, now=0.0, ocr_result=res)
        self.assertFalse(engine.update(frame, now=3.9, ocr_result=res))
        self.assertTrue(engine.update(frame, now=4.0, ocr_result=res))


class TestDateCandidatesFlowAndPersistence(unittest.TestCase):
    """Verifies that all detected date candidates flow correctly into persistence and CLI."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_flow.db"
        self.db = InventoryDatabase(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_multiple_date_candidates_survive_pipeline(self) -> None:
        """Scan with manufacturing and expiry candidates preserves all candidates in DB."""
        candidates = [
            DateCandidate(
                raw_text="04/2026",
                date_type="manufacturing",
                normalized_date=None,
                confidence=0.92,
                evidence="Mfd. 04/2026 printed on top flap",
            ),
            DateCandidate(
                raw_text="03/2028",
                date_type="expiry",
                normalized_date=None,
                confidence=0.95,
                evidence="Exp. 03/2028 printed below batch BD0114",
            ),
        ]
        res = FoodAnalysisResult(
            product_name="Adulsa Cough Syrup",
            brand="Dabur Honitus",
            food_category="Beverage",
            date_candidates=candidates,
            selected_expiry_date=None,
            analysis_status="needs_review",
            needs_review=True,
            review_reason="Month and year only; missing day digits",
        )

        scan_id = self.db.record_scan(
            image_path="/path/to/syrup.jpg",
            result=res,
        )

        # Retrieve candidates for this scan
        stored_cands = self.db.get_scan_date_candidates(scan_id)
        self.assertEqual(len(stored_cands), 2)

        mfg = stored_cands[0]
        self.assertEqual(mfg.raw_text, "04/2026")
        self.assertEqual(mfg.date_type, "manufacturing")
        self.assertIsNone(mfg.normalized_date)
        self.assertIn("Mfd", mfg.evidence)

        exp = stored_cands[1]
        self.assertEqual(exp.raw_text, "03/2028")
        self.assertEqual(exp.date_type, "expiry")
        self.assertIsNone(exp.normalized_date)
        self.assertIn("Exp", exp.evidence)

    def test_format_date_candidates_review_output(self) -> None:
        """Verifies the exact format required for the Date candidates review block."""
        res = FoodAnalysisResult(
            product_name="Sample Juice",
            brand="Tropicana",
            food_category="Beverage",
            date_candidates=[
                DateCandidate(
                    raw_text="03/2028",
                    date_type="expiry",
                    normalized_date=None,
                    confidence=0.90,
                    evidence="Exp. date is printed as 03/2028",
                ),
            ],
            selected_expiry_date=None,
            analysis_status="needs_review",
            needs_review=True,
            review_reason="Month/Year only",
        )

        review_str = format_date_candidates_review(res)
        self.assertIn("Date candidates:", review_str)
        self.assertIn("Candidate 1:", review_str)
        self.assertIn("Original text: 03/2028", review_str)
        self.assertIn("Type: expiry", review_str)
        self.assertIn("Normalized date: unavailable", review_str)
        self.assertIn("Confidence: 0.90", review_str)
        self.assertIn("Evidence: Exp. date is printed as 03/2028", review_str)

    def test_add_scan_displays_and_attaches_candidates(self) -> None:
        """Adding a product from scan attaches candidate dates to the new product record."""
        candidates = [
            DateCandidate(
                raw_text="EXP 2026-12-31",
                date_type="expiry",
                normalized_date="2026-12-31",
                confidence=0.98,
                evidence="Printed on rear panel",
            )
        ]
        res = FoodAnalysisResult(
            product_name="Green Tea",
            brand="Tetley",
            food_category="Beverage",
            date_candidates=candidates,
            selected_expiry_date="2026-12-31",
            analysis_status="success",
            needs_review=False,
            review_reason=None,
        )

        scan_id = self.db.record_scan(
            image_path="/path/to/tea.jpg",
            result=res,
        )

        # Attach to inventory product
        prod_id = self.db.add_product(
            product_name="Green Tea",
            brand="Tetley",
            food_category="Beverage",
            date_type="expiry",
            normalized_date="2026-12-31",
            date_status="confirmed",
            date_source="printed",
            candidate_dates=self.db.get_scan_date_candidates(scan_id),
        )

        # Verify product candidates
        prod_cands = self.db.get_product_date_candidates(prod_id)
        self.assertEqual(len(prod_cands), 1)
        self.assertEqual(prod_cands[0].raw_text, "EXP 2026-12-31")
        self.assertEqual(prod_cands[0].scan_id, scan_id)

    def test_missing_dates_requires_review(self) -> None:
        """When no dates are detected, result is flagged for review and reason is populated."""
        res = FoodAnalysisResult(
            product_name="Adulsa Syrup",
            brand="Dabur",
            food_category="Beverage",
            date_candidates=[],
            selected_expiry_date=None,
            analysis_status="success",  # Erroneous success status from model
            needs_review=False,
            review_reason=None,
        )

        validated = FoodAnalysisResult.post_validate(res)
        self.assertTrue(validated.needs_review)
        self.assertIsNotNone(validated.review_reason)
        self.assertIn("No printed expiry", validated.review_reason or "")

    def test_reanalysis_does_not_duplicate_scan_history(self) -> None:
        """Running analyze_image directly does not insert rows into scan_history."""
        initial_scans = len(self.db.get_recent_scans())

        # Mock analyzer
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.parsed = FoodAnalysisResult(
            product_name="Mock Item",
            analysis_status="success",
            selected_expiry_date="2027-01-01",
            needs_review=False,
        )
        mock_client.models.generate_content.return_value = mock_resp

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
            tmp.write(b"fake jpeg data")
            tmp.flush()
            analyzer.analyze_image(tmp.name)

        # Scans in DB should not have changed
        current_scans = len(self.db.get_recent_scans())
        self.assertEqual(initial_scans, current_scans)


if __name__ == "__main__":
    unittest.main(verbosity=2)
