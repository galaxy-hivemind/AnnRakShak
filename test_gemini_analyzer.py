"""
AnnaRakshak — Gemini Analyzer Offline Test Suite
=================================================
Mocks all Google GenAI SDK network interactions to verify:
  1. Image file validation (missing, invalid extension, 0 bytes).
  2. Missing API key handling.
  3. Valid structured output parsing.
  4. Distinguishing manufacturing / packed dates from expiry dates.
  5. Incomplete dates (month/year only, no day inference).
  6. Ambiguous / conflicting multiple dates.
  7. Unreadable labels and non-food items.
  8. Malformed responses and JSON parse errors.
  9. Network errors, timeouts, and 429 rate limits.
 10. AsyncGeminiWorker bounded queue, non-blocking execution, and error resilience.
 11. Scanner engine state machine resilience upon Gemini failure.

Zero network access or real API keys required.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np

from auto_scan import ScanState, TextScanEngine
from gemini_analyzer import (
    AsyncGeminiWorker,
    DateCandidate,
    FoodAnalysisResult,
    GeminiAnalyzer,
)
from ocr_engine import OCRResult, TextRegion


class MockGenerateContentResponse:
    """Mock response object mimicking google.genai response."""

    def __init__(self, text: str | None = None, parsed: Any | None = None) -> None:
        self.text = text
        self.parsed = parsed


class TestImageFileValidation(unittest.TestCase):
    """Tests for image file path validation before calling Gemini."""

    def setUp(self) -> None:
        self.analyzer = GeminiAnalyzer(api_key="mock_key")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_nonexistent_image_file(self) -> None:
        bad_path = self.temp_path / "does_not_exist.jpg"
        result = self.analyzer.analyze_image(bad_path)
        self.assertEqual(result.analysis_status, "error")
        self.assertTrue(result.needs_review)
        self.assertIn("not found", (result.review_reason or "").lower())

    def test_directory_instead_of_file(self) -> None:
        result = self.analyzer.analyze_image(self.temp_path)
        self.assertEqual(result.analysis_status, "error")
        self.assertTrue(result.needs_review)
        self.assertIn("not a regular file", (result.review_reason or "").lower())

    def test_unsupported_file_extension(self) -> None:
        txt_file = self.temp_path / "label.txt"
        txt_file.write_text("Best before 2026-11-20")
        result = self.analyzer.analyze_image(txt_file)
        self.assertEqual(result.analysis_status, "error")
        self.assertTrue(result.needs_review)
        self.assertIn("unsupported", (result.review_reason or "").lower())

    def test_empty_zero_byte_file(self) -> None:
        empty_file = self.temp_path / "empty.jpg"
        empty_file.touch()
        result = self.analyzer.analyze_image(empty_file)
        self.assertEqual(result.analysis_status, "error")
        self.assertTrue(result.needs_review)
        self.assertIn("empty", (result.review_reason or "").lower())

    def test_valid_image_file_passes_validation(self) -> None:
        img_file = self.temp_path / "sample.jpg"
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(str(img_file), img)
        valid, err = self.analyzer.validate_image_file(img_file)
        self.assertTrue(valid)
        self.assertIsNone(err)


class TestApiKeyHandling(unittest.TestCase):
    """Tests handling of missing or invalid API keys."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.test_img = self.temp_path / "sample.jpg"
        cv2.imwrite(str(self.test_img), np.zeros((100, 100, 3), dtype=np.uint8))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_api_key_returns_graceful_error(self) -> None:
        # Explicitly pass empty API key and ensure env var does not interfere
        orig_key = os.environ.get("GEMINI_API_KEY")
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]

        try:
            analyzer = GeminiAnalyzer(api_key="")
            result = analyzer.analyze_image(self.test_img)
            self.assertEqual(result.analysis_status, "error")
            self.assertTrue(result.needs_review)
            self.assertIn("GEMINI_API_KEY is not configured", result.review_reason or "")
        finally:
            if orig_key is not None:
                os.environ["GEMINI_API_KEY"] = orig_key


class TestStructuredOutputParsing(unittest.TestCase):
    """Tests parsing of Gemini structured responses."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.test_img = self.temp_path / "sample.jpg"
        cv2.imwrite(str(self.test_img), np.zeros((100, 100, 3), dtype=np.uint8))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_mock_client(self, parsed_result: FoodAnalysisResult | None = None, raw_json: str | None = None):
        mock_client = MagicMock()
        mock_response = MagicMock()
        if parsed_result is not None:
            mock_response.parsed = parsed_result
            mock_response.text = parsed_result.model_dump_json()
        elif raw_json is not None:
            mock_response.parsed = None
            mock_response.text = raw_json
        mock_client.models.generate_content.return_value = mock_response
        return mock_client

    def test_valid_product_and_expiry_date(self) -> None:
        expected = FoodAnalysisResult(
            product_name="Whole Milk 1L",
            brand="Amul Taaza",
            food_category="Dairy",
            date_candidates=[
                DateCandidate(
                    raw_text="USE BY 28/10/2026",
                    date_type="use_by",
                    normalized_date="2026-10-28",
                    confidence=0.98,
                    evidence="Clearly printed on top seal",
                )
            ],
            selected_expiry_date="2026-10-28",
            analysis_status="success",
            needs_review=False,
            review_reason=None,
        )

        mock_client = self._make_mock_client(parsed_result=expected)
        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)

        result = analyzer.analyze_image(self.test_img)

        self.assertEqual(result.product_name, "Whole Milk 1L")
        self.assertEqual(result.brand, "Amul Taaza")
        self.assertEqual(result.food_category, "Dairy")
        self.assertEqual(result.selected_expiry_date, "2026-10-28")
        self.assertEqual(result.analysis_status, "success")
        self.assertFalse(result.needs_review)
        self.assertIn("Amul Taaza", result.summary)
        self.assertIn("2026-10-28", result.summary)

    def test_raw_json_string_fallback_parsing(self) -> None:
        json_data = json.dumps({
            "product_name": "Greek Yogurt",
            "brand": "Epigamia",
            "food_category": "Dairy",
            "date_candidates": [
                {
                    "raw_text": "EXP 2026-12-15",
                    "date_type": "expiry",
                    "normalized_date": "2026-12-15",
                    "confidence": 0.95,
                    "evidence": "Back label",
                }
            ],
            "selected_expiry_date": "2026-12-15",
            "analysis_status": "success",
            "needs_review": False,
            "review_reason": None,
        })

        mock_client = self._make_mock_client(raw_json=json_data)
        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)

        result = analyzer.analyze_image(self.test_img)
        self.assertEqual(result.product_name, "Greek Yogurt")
        self.assertEqual(result.selected_expiry_date, "2026-12-15")
        self.assertEqual(result.analysis_status, "success")


class TestStrictDateInterpretationRules(unittest.TestCase):
    """Tests critical date interpretation safeguards."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.test_img = self.temp_path / "sample.jpg"
        cv2.imwrite(str(self.test_img), np.zeros((100, 100, 3), dtype=np.uint8))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_manufacturing_date_never_selected_as_expiry(self) -> None:
        """Manufacturing date must NEVER be treated as expiry date."""
        mock_res = FoodAnalysisResult(
            product_name="Corn Flakes",
            brand="Kellogg's",
            food_category="Cereal",
            date_candidates=[
                DateCandidate(
                    raw_text="MFG 2026-05-10",
                    date_type="manufacturing",
                    normalized_date="2026-05-10",
                    confidence=0.95,
                    evidence="Printed below batch code",
                )
            ],
            selected_expiry_date="2026-05-10",  # Erroneous selection by model
            analysis_status="success",
            needs_review=False,
            review_reason=None,
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = mock_res
        mock_client.models.generate_content.return_value = mock_response

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        result = analyzer.analyze_image(self.test_img)

        # Safeguard MUST clear expiry date and require human review
        self.assertIsNone(result.selected_expiry_date, "Manufacturing date must NOT be selected as expiry")
        self.assertTrue(result.needs_review)
        self.assertIn("manufacturing", (result.review_reason or "").lower())

    def test_incomplete_date_month_year_only_no_inferred_day(self) -> None:
        """If label has only month/year (e.g. 2026-10), day must not be inferred."""
        mock_res = FoodAnalysisResult(
            product_name="Instant Noodles",
            brand="Maggi",
            food_category="Grains",
            date_candidates=[
                DateCandidate(
                    raw_text="BEST BEFORE OCT 2026",
                    date_type="best_before",
                    normalized_date="2026-10",  # Missing day
                    confidence=0.90,
                    evidence="Only month and year printed",
                )
            ],
            selected_expiry_date="2026-10",  # Invalid day-less date
            analysis_status="success",
            needs_review=False,
            review_reason=None,
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = mock_res
        mock_client.models.generate_content.return_value = mock_response

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        result = analyzer.analyze_image(self.test_img)

        self.assertIsNone(result.selected_expiry_date)
        self.assertTrue(result.needs_review)
        self.assertIsNone(result.date_candidates[0].normalized_date)

    def test_ambiguous_conflicting_expiry_dates_require_review(self) -> None:
        """Multiple conflicting expiry candidates must trigger needs_review."""
        mock_res = FoodAnalysisResult(
            product_name="Cheddar Cheese",
            brand="Kraft",
            food_category="Dairy",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 2026-11-01",
                    date_type="expiry",
                    normalized_date="2026-11-01",
                    confidence=0.80,
                    evidence="Stamp on front",
                ),
                DateCandidate(
                    raw_text="USE BY 2026-12-05",
                    date_type="use_by",
                    normalized_date="2026-12-05",
                    confidence=0.85,
                    evidence="Stamp on back barcode",
                ),
            ],
            selected_expiry_date="2026-11-01",
            analysis_status="success",
            needs_review=False,
            review_reason=None,
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = mock_res
        mock_client.models.generate_content.return_value = mock_response

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        result = analyzer.analyze_image(self.test_img)

        self.assertTrue(result.needs_review)
        self.assertIsNone(result.selected_expiry_date)
        self.assertIn("conflicting", (result.review_reason or "").lower())

    def test_unreadable_label_returns_needs_review(self) -> None:
        mock_res = FoodAnalysisResult(
            product_name=None,
            brand=None,
            food_category=None,
            date_candidates=[],
            selected_expiry_date=None,
            analysis_status="unreadable",
            needs_review=True,
            review_reason="Label is completely blurry and text cannot be recognized",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = mock_res
        mock_client.models.generate_content.return_value = mock_response

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        result = analyzer.analyze_image(self.test_img)

        self.assertEqual(result.analysis_status, "unreadable")
        self.assertTrue(result.needs_review)
        self.assertIsNone(result.selected_expiry_date)

    def test_non_food_object_returns_not_a_food_product(self) -> None:
        mock_res = FoodAnalysisResult(
            product_name="AA Alkaline Batteries",
            brand="Duracell",
            food_category=None,
            date_candidates=[],
            selected_expiry_date=None,
            analysis_status="not_a_food_product",
            needs_review=True,
            review_reason="Item is an electronic accessory, not a food product",
        )

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = mock_res
        mock_client.models.generate_content.return_value = mock_response

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        result = analyzer.analyze_image(self.test_img)

        self.assertEqual(result.analysis_status, "not_a_food_product")
        self.assertTrue(result.needs_review)


class TestNetworkFailureAndErrorHandling(unittest.TestCase):
    """Tests that network errors, 429 quota limits, and timeouts are handled safely."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.test_img = self.temp_path / "sample.jpg"
        cv2.imwrite(str(self.test_img), np.zeros((100, 100, 3), dtype=np.uint8))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_rate_limit_or_quota_exhausted_handled(self) -> None:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED: quota exceeded")

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        result = analyzer.analyze_image(self.test_img)

        self.assertEqual(result.analysis_status, "error")
        self.assertTrue(result.needs_review)
        self.assertIn("rate limit", (result.review_reason or "").lower())

    def test_request_timeout_handled(self) -> None:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Client timeout while waiting for response")

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        result = analyzer.analyze_image(self.test_img)

        self.assertEqual(result.analysis_status, "error")
        self.assertTrue(result.needs_review)
        self.assertIn("timed out", (result.review_reason or "").lower())

    def test_malformed_json_response_handled(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.parsed = None
        mock_response.text = "This is not json at all!"
        mock_client.models.generate_content.return_value = mock_response

        analyzer = GeminiAnalyzer(api_key="mock_key", client=mock_client)
        result = analyzer.analyze_image(self.test_img)

        self.assertEqual(result.analysis_status, "error")
        self.assertTrue(result.needs_review)


class TestAsyncGeminiWorker(unittest.TestCase):
    """Tests non-blocking execution and bounded queue capacity of AsyncGeminiWorker."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.test_img = self.temp_path / "sample.jpg"
        cv2.imwrite(str(self.test_img), np.zeros((100, 100, 3), dtype=np.uint8))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_worker_lifecycle_and_bounded_queue(self) -> None:
        mock_analyzer = MagicMock()
        mock_res = FoodAnalysisResult(
            product_name="Orange Juice",
            brand="Tropicana",
            food_category="Beverage",
            date_candidates=[],
            selected_expiry_date="2026-11-30",
            analysis_status="success",
            needs_review=False,
            review_reason=None,
        )

        # Introduce small artificial delay in mock to test concurrency
        def slow_analyze(path):
            time.sleep(0.15)
            return mock_res

        mock_analyzer.analyze_image.side_effect = slow_analyze

        worker = AsyncGeminiWorker(mock_analyzer)

        try:
            self.assertEqual(worker.status, "IDLE")

            # First submission succeeds
            submitted_1 = worker.submit_capture(str(self.test_img))
            self.assertTrue(submitted_1)
            self.assertIn(worker.status, ("IMAGE CAPTURED", "ANALYZING WITH GEMINI"))

            # Second submission while worker is busy should be rejected (bounded capacity = 1)
            submitted_2 = worker.submit_capture(str(self.test_img))
            self.assertFalse(submitted_2, "Must reject second submit while busy to prevent backlog")

            # Wait for worker to finish
            for _ in range(50):
                if not worker.is_analyzing and worker.latest_result is not None:
                    break
                time.sleep(0.02)

            self.assertFalse(worker.is_analyzing)
            self.assertIsNotNone(worker.latest_result)
            self.assertEqual(worker.latest_result.product_name, "Orange Juice")
            self.assertEqual(worker.status, "EXPIRY DATE FOUND")

        finally:
            worker.shutdown()

    def test_worker_failure_does_not_crash(self) -> None:
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.side_effect = RuntimeError("Fatal crash inside analyzer")

        worker = AsyncGeminiWorker(mock_analyzer)

        try:
            worker.submit_capture(str(self.test_img))
            for _ in range(30):
                if not worker.is_analyzing and worker.latest_result is not None:
                    break
                time.sleep(0.02)

            self.assertEqual(worker.status, "GEMINI REQUEST FAILED")
            self.assertIsNotNone(worker.latest_result)
            self.assertEqual(worker.latest_result.analysis_status, "error")

        finally:
            worker.shutdown()


class TestScannerResilienceOnGeminiFailure(unittest.TestCase):
    """Verifies that a Gemini failure cannot duplicate captures or crash the scanner engine."""

    def test_scanner_state_remains_intact_if_gemini_fails(self) -> None:
        engine = TextScanEngine(required_consecutive_checks=2, capture_stability_seconds=0.25)
        engine.calibrate()

        reg = TextRegion("BROWN BREAD", 0.92, 0.2, 0.2, 0.3, 0.1)
        res = OCRResult(regions=[reg])

        # Step 1: Detect text
        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        self.assertFalse(engine.update(dummy_frame, now=0.0, ocr_result=res))
        self.assertEqual(engine.state, ScanState.TEXT_DETECTED)

        # Step 2: Trigger capture
        triggered = engine.update(dummy_frame, now=0.25, ocr_result=res)
        self.assertTrue(triggered)
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        # Simulate Gemini failure occurring simultaneously
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_image.return_value = FoodAnalysisResult(
            analysis_status="error",
            needs_review=True,
            review_reason="API key invalid",
        )
        worker = AsyncGeminiWorker(mock_analyzer)
        try:
            worker.submit_capture("some_path.jpg")
            time.sleep(0.05)
            self.assertEqual(worker.status, "GEMINI REQUEST FAILED")

            # Verify scanner engine state has NOT been disturbed
            self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

            # Package remains present -> no duplicate capture
            for i in range(10):
                trig = engine.update(dummy_frame, now=0.3 + i * 0.1, ocr_result=res)
                self.assertFalse(trig, "Scanner must NOT trigger duplicate capture after Gemini failure")

            # Package removed -> rearm
            empty_res = OCRResult(regions=[])
            for i in range(10):
                engine.update(dummy_frame, now=1.5 + i * 0.1, ocr_result=empty_res)

            self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT,
                             "Scanner must cleanly rearm even after Gemini error")

        finally:
            worker.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
