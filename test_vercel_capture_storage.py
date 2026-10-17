"""
Unit and integration tests for environment-aware capture storage and cleanup on Vercel / serverless.
Validates:
1. Environment-aware capture path resolution (local dev vs Vercel /tmp vs custom env).
2. Cleanup configuration logic (local dev keeps files, Vercel/serverless deletes files).
3. Scan endpoint execution with temporary captures and cleanup on successful analysis.
4. Scan endpoint execution and cleanup on exception/error paths.
5. Local development mode preserves captures for /image retrieval.
6. Safe file removal error handling.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import cv2
from fastapi.testclient import TestClient

from api import (
    app,
    get_captures_dir,
    is_serverless_environment,
    should_cleanup_captures,
    _safe_remove_file,
)
from gemini_analyzer import FoodAnalysisResult, DateCandidate
from inventory_db import InventoryDatabase


class TestVercelCaptureStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="annarakshak_test_captures_")
        self.db_dir = tempfile.mkdtemp(prefix="annarakshak_test_db_")
        self.db_path = Path(self.db_dir) / "test_inventory.db"
        self.db = InventoryDatabase(db_path=self.db_path)
        app.state.db = self.db

        self.mock_analyzer = MagicMock()
        app.state.analyzer = self.mock_analyzer

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        shutil.rmtree(self.db_dir, ignore_errors=True)

    def _generate_test_jpeg(self) -> bytes:
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.putText(img, "TEST", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        _, encoded = cv2.imencode(".jpg", img)
        return encoded.tobytes()

    # -----------------------------------------------------------------------
    # 1. Path & Environment Detection Tests
    # -----------------------------------------------------------------------

    def test_is_serverless_environment_detection(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_serverless_environment())

        with patch.dict(os.environ, {"VERCEL": "1"}):
            self.assertTrue(is_serverless_environment())

        with patch.dict(os.environ, {"VERCEL_ENV": "production"}):
            self.assertTrue(is_serverless_environment())

        with patch.dict(os.environ, {"AWS_LAMBDA_FUNCTION_NAME": "my-func"}):
            self.assertTrue(is_serverless_environment())

    def test_get_captures_dir_local_default(self):
        with patch.dict(os.environ, {}, clear=True):
            captures = get_captures_dir()
            self.assertTrue(str(captures).endswith("captures"))
            self.assertFalse(str(captures).startswith("/tmp"))

    def test_get_captures_dir_vercel_serverless(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            captures = get_captures_dir()
            self.assertEqual(captures, Path("/tmp/annarakshak/captures").resolve())

    def test_get_captures_dir_custom_override(self):
        custom_path = "/custom/mounted/captures"
        with patch.dict(os.environ, {"ANNARAKSHAK_CAPTURES_DIR": custom_path}):
            captures = get_captures_dir()
            self.assertEqual(captures, Path(custom_path).resolve())

    def test_should_cleanup_captures_logic(self):
        # Default local dev: should not clean up
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(should_cleanup_captures())

        # Vercel serverless: should clean up by default
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            self.assertTrue(should_cleanup_captures())

        # Explicit override to True
        with patch.dict(os.environ, {"ANNARAKSHAK_CLEANUP_CAPTURES": "true"}):
            self.assertTrue(should_cleanup_captures())

        # Explicit override to False even on Vercel
        with patch.dict(os.environ, {"VERCEL": "1", "ANNARAKSHAK_CLEANUP_CAPTURES": "false"}):
            self.assertFalse(should_cleanup_captures())

    # -----------------------------------------------------------------------
    # 2. Scanning Pipeline with Cleanup on Success
    # -----------------------------------------------------------------------

    def test_scan_pipeline_serverless_cleans_up_on_success(self):
        mock_result = FoodAnalysisResult(
            product_name="Serverless Oats",
            brand="Cloud Grain",
            food_category="Grains",
            analysis_status="success",
            needs_review=False,
            selected_expiry_date="2027-12-31",
            date_candidates=[
                DateCandidate(
                    raw_text="EXP 31/12/2027",
                    date_type="expiry",
                    normalized_date="2027-12-31",
                    confidence=0.98,
                    evidence="Printed on side",
                )
            ],
            models_attempted=["gemini-3.5-flash-lite"],
            retries_count=0,
        )

        def mock_analyze(image_path, **kwargs):
            # Assert file exists during Gemini analysis
            self.assertTrue(Path(image_path).exists(), "Temporary capture must exist during analysis")
            return mock_result

        self.mock_analyzer.analyze_image.side_effect = mock_analyze

        with patch.dict(
            os.environ,
            {
                "ANNARAKSHAK_CAPTURES_DIR": self.temp_dir,
                "ANNARAKSHAK_CLEANUP_CAPTURES": "true",
            },
        ):
            jpeg_data = self._generate_test_jpeg()
            res = self.client.post(
                "/api/scans",
                files={"image": ("test_scan.jpg", jpeg_data, "image/jpeg")},
            )
            self.assertEqual(res.status_code, 201)
            data = res.json()
            self.assertEqual(data["product_name"], "Serverless Oats")
            self.assertEqual(data["selected_expiry_date"], "2027-12-31")

            # Check that database recorded the scan
            scan_id = data["id"]
            db_scan = self.db.get_scan(scan_id)
            self.assertIsNotNone(db_scan)

            # Check that the temporary file was cleaned up after request completed
            self.assertFalse(
                Path(db_scan.image_path).exists(),
                "Temporary capture must be deleted after processing when cleanup is enabled",
            )
            # The temp directory itself should have 0 files left
            remaining_files = list(Path(self.temp_dir).glob("*.jpg"))
            self.assertEqual(len(remaining_files), 0)

    # -----------------------------------------------------------------------
    # 3. Scanning Pipeline with Cleanup on Exception
    # -----------------------------------------------------------------------

    def test_scan_pipeline_serverless_cleans_up_on_exception(self):
        def mock_analyze_fail(image_path, **kwargs):
            self.assertTrue(Path(image_path).exists(), "Temporary capture must exist before failure")
            raise RuntimeError("Simulated Gemini unhandled crash")

        self.mock_analyzer.analyze_image.side_effect = mock_analyze_fail

        with patch.dict(
            os.environ,
            {
                "ANNARAKSHAK_CAPTURES_DIR": self.temp_dir,
                "ANNARAKSHAK_CLEANUP_CAPTURES": "true",
            },
        ):
            jpeg_data = self._generate_test_jpeg()
            res = self.client.post(
                "/api/scans",
                files={"image": ("crash_scan.jpg", jpeg_data, "image/jpeg")},
            )
            self.assertEqual(res.status_code, 500)

            # Verify that any file created was unlinked even after exception
            remaining_files = list(Path(self.temp_dir).glob("*.jpg"))
            self.assertEqual(
                len(remaining_files),
                0,
                "Temporary capture must be deleted even if an unhandled exception occurs",
            )

    # -----------------------------------------------------------------------
    # 4. Local Development Mode Preserves Capture File
    # -----------------------------------------------------------------------

    def test_scan_pipeline_local_preserves_capture_and_allows_image_retrieval(self):
        mock_result = FoodAnalysisResult(
            product_name="Local Cereal",
            brand="Local Brand",
            food_category="Grains",
            analysis_status="success",
            needs_review=False,
            selected_expiry_date="2027-05-10",
        )
        self.mock_analyzer.analyze_image.return_value = mock_result

        with patch.dict(
            os.environ,
            {
                "ANNARAKSHAK_CAPTURES_DIR": self.temp_dir,
                "ANNARAKSHAK_CLEANUP_CAPTURES": "false",
            },
        ):
            jpeg_data = self._generate_test_jpeg()
            res = self.client.post(
                "/api/scans",
                files={"image": ("cereal.jpg", jpeg_data, "image/jpeg")},
            )
            self.assertEqual(res.status_code, 201)
            data = res.json()
            scan_id = data["id"]

            db_scan = self.db.get_scan(scan_id)
            self.assertIsNotNone(db_scan)
            saved_file = Path(db_scan.image_path)
            self.assertTrue(saved_file.exists(), "Local development must preserve capture file")

            # Verify GET /api/scans/{scan_id}/image succeeds
            img_res = self.client.get(f"/api/scans/{scan_id}/image")
            self.assertEqual(img_res.status_code, 200)
            self.assertEqual(img_res.headers["content-type"], "image/jpeg")

    # -----------------------------------------------------------------------
    # 5. Safe Removal File Utility
    # -----------------------------------------------------------------------

    def test_safe_remove_file(self):
        # Removing None or empty string does not raise
        _safe_remove_file(None)
        _safe_remove_file("")

        # Removing nonexistent file does not raise
        _safe_remove_file(Path(self.temp_dir) / "nonexistent.jpg")

        # Removing existing file deletes it
        dummy = Path(self.temp_dir) / "dummy.txt"
        dummy.write_text("hello")
        self.assertTrue(dummy.exists())
        _safe_remove_file(dummy)
        self.assertFalse(dummy.exists())


if __name__ == "__main__":
    unittest.main()
