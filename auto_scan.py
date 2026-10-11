"""
AnnaRakshak — Automatic Scan Trigger (Step 4: Text-Verified Gate)
==================================================================
Watches a webcam and automatically captures one image ONLY when:
  1. Visible qualifying text is detected on a food package using Apple Vision OCR; AND
  2. The detected text remains steady and consistent across multiple consecutive checks.

CRITICAL RULES:
  - Movement alone must NEVER trigger a capture.
  - A moving shadow with no detected text must NEVER trigger a capture.
  - An empty background must NEVER trigger a capture, even if still indefinitely.
  - The live camera preview runs non-blockingly at full frame rate (OCR in background worker).
  - Saved captures are clean original frames without any HUD overlay.

State Machine Flow
------------------
  UNCALIBRATED
      * Initial state (unless --skip-calib is set).
      * Press [c] to arm the scanner.
      * -> SEARCHING FOR TEXT

  SEARCHING FOR TEXT
      * Scanner is actively scanning frames for visible text.
      * Moving shadows, empty scene, and textless motion produce 0 captures.
      * Qualifying text detected -> TEXT DETECTED

  TEXT DETECTED
      * Initial candidate text recognized.
      * If text disappears -> resets to SEARCHING FOR TEXT.
      * If text is held steady on next check -> VERIFYING TEXT STABILITY

  VERIFYING TEXT STABILITY
      * Verifying that text region remains consistent across consecutive OCR checks.
      * If text moves excessively (drift > max_drift) -> resets verification.
      * If text disappears -> resets to SEARCHING FOR TEXT.
      * When consecutive_checks >= required_consecutive_checks (default 3):
        -> CAPTURES exactly one image -> CAPTURED — WAIT FOR REMOVAL

  CAPTURED — WAIT FOR REMOVAL
      * One clean frame saved to captures/.
      * Duplicate captures are strictly locked while text remains in view.
      * When text has been absent for removal_duration (default 0.8s):
        -> Rearms scanner -> SEARCHING FOR TEXT
"""

from __future__ import annotations

import argparse
import enum
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# Re-use camera helpers from camera_test.py
from camera_test import (
    find_first_camera,
    list_system_cameras,
    open_camera,
    probe_resolution,
    MAX_SCAN_INDEX,
)

# OCR abstraction layer
from ocr_engine import (
    AppleVisionOCREngine,
    BaseOCREngine,
    MockOCREngine,
    OCRResult,
    TextRegion,
)

# Gemini AI analyzer
from gemini_analyzer import (
    AsyncGeminiWorker,
    FoodAnalysisResult,
    GeminiAnalyzer,
    format_date_candidates_review,
)

# SQLite Inventory Database
from inventory_db import InventoryDatabase

# ---------------------------------------------------------------------------
# Configurable defaults
# ---------------------------------------------------------------------------

DEFAULT_CAPTURE_STABILITY_SECONDS = 2.5
"""Seconds of continuous steady qualifying text required before automatic capture."""

DEFAULT_CONSECUTIVE_CHECKS = 3
"""Number of consecutive consistent OCR checks required before capture."""

DEFAULT_MIN_CONFIDENCE     = 0.35
"""Minimum OCR confidence score (0.0 to 1.0) to qualify as valid text."""

DEFAULT_MIN_TEXT_AREA      = 0.001
"""Minimum normalized bounding-box area (w * h) to reject microscopic noise."""

DEFAULT_MIN_TEXT_LEN       = 2
"""Minimum string length for detected text."""

DEFAULT_MAX_DRIFT          = 0.15
"""Maximum normalized center drift between checks before resetting stability."""

DEFAULT_OCR_INTERVAL_S     = 0.25
"""Minimum seconds between OCR queries in background worker (~4 Hz)."""

DEFAULT_REMOVAL_DURATION_S = 0.8
"""Seconds text must remain absent before rearming the scanner."""

DEFAULT_MOTION_THRESHOLD   = 2.5
DEFAULT_STABLE_DURATION_S  = 1.5
DEFAULT_FG_RATIO           = 0.015
DEFAULT_FG_PIXEL_THRESHOLD = 20
DEFAULT_CAL_FRAMES         = 15

CAPTURES_DIR = Path(__file__).parent / "captures"
BLUR_KERNEL  = (5, 5)
WINDOW_TITLE = "AnnaRakshak - Text-Verified Scan Trigger"

# BGR colour palette
C_GREEN  = (0,  220,  90)
C_ORANGE = (0,  165, 255)
C_RED    = (30,  60, 220)
C_WHITE  = (230, 230, 230)
C_BLUE   = (255, 160,  30)
C_CYAN   = (235, 205,  50)
C_YELLOW = (0,  215, 245)
C_GREY   = (140, 140, 140)


# ---------------------------------------------------------------------------
# State machine definition
# ---------------------------------------------------------------------------

class ScanState(enum.Enum):
    """
    State machine states for AnnaRakshak automatic scanner.
    Includes backward-compatible aliases for Step 2 and Step 3 test suites.
    """
    UNCALIBRATED                 = "UNCALIBRATED [press C]"
    SEARCHING_FOR_TEXT           = "SEARCHING FOR TEXT"
    TEXT_DETECTED                = "TEXT DETECTED"
    VERIFYING_TEXT_STABILITY     = "VERIFYING TEXT STABILITY"
    CAPTURED_WAITING_FOR_REMOVAL = "CAPTURED - WAIT FOR REMOVAL"

    # Backward compatibility aliases
    CALIBRATE_BACKGROUND         = "UNCALIBRATED [press C]"
    NEEDS_CALIBRATION            = "UNCALIBRATED [press C]"
    NO_OBJECT_DETECTED           = "SEARCHING FOR TEXT"
    IDLE                         = "SEARCHING FOR TEXT"
    OBJECT_DETECTED              = "TEXT DETECTED"
    WAITING_FOR_STABILITY        = "VERIFYING TEXT STABILITY"
    STABILIZING                  = "VERIFYING TEXT STABILITY"
    CAPTURED                     = "CAPTURED - WAIT FOR REMOVAL"


# ---------------------------------------------------------------------------
# Non-blocking Asynchronous OCR Worker
# ---------------------------------------------------------------------------

class AsyncOCRWorker:
    """
    Runs text detection asynchronously in a background thread.
    Maintains a single-slot buffer so the worker never queues stale frames
    and the camera preview never blocks.
    """

    def __init__(self, engine: BaseOCREngine, poll_interval_s: float = DEFAULT_OCR_INTERVAL_S) -> None:
        self.engine = engine
        self.poll_interval_s = poll_interval_s

        self._pending_frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._new_frame_event = threading.Event()

        self._latest_result: OCRResult | None = None
        self._is_busy = False
        self._last_submit_time = 0.0

        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="OCRWorker")
        self._thread.start()

    def submit_frame(self, frame_bgr: np.ndarray, now: float | None = None) -> bool:
        """Submit a frame to be processed if interval has elapsed and worker is idle."""
        now = time.monotonic() if now is None else now
        if now - self._last_submit_time < self.poll_interval_s:
            return False

        with self._lock:
            if self._is_busy:
                return False
            self._pending_frame = frame_bgr.copy()
            self._last_submit_time = now
            self._is_busy = True
            self._new_frame_event.set()
            return True

    def get_latest_result(self) -> OCRResult | None:
        """Retrieve the most recent OCR result thread-safely."""
        with self._lock:
            return self._latest_result

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._is_busy

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._new_frame_event.wait(timeout=0.1):
                continue
            self._new_frame_event.clear()

            with self._lock:
                frame = self._pending_frame
                self._pending_frame = None

            if frame is None:
                with self._lock:
                    self._is_busy = False
                continue

            try:
                res = self.engine.detect_text(frame)
            except Exception as e:
                res = OCRResult(error=str(e))

            with self._lock:
                self._latest_result = res
                self._is_busy = False

    def shutdown(self) -> None:
        """Cleanly terminate worker thread and OCR subprocess."""
        self._stop_event.set()
        self._new_frame_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self.engine.shutdown()


# ---------------------------------------------------------------------------
# TextScanEngine (Step 4: Text-Verified Gate)
# ---------------------------------------------------------------------------

class TextScanEngine:
    """
    Two-stage text-verified trigger engine.
    Requires visible, steady text on a package before authorizing capture.
    """

    def __init__(
        self,
        ocr_engine: BaseOCREngine | None = None,
        required_consecutive_checks: int = DEFAULT_CONSECUTIVE_CHECKS,
        capture_stability_seconds: float = DEFAULT_CAPTURE_STABILITY_SECONDS,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        min_text_area: float = DEFAULT_MIN_TEXT_AREA,
        min_text_len: int = DEFAULT_MIN_TEXT_LEN,
        max_drift: float = DEFAULT_MAX_DRIFT,
        removal_duration: float = DEFAULT_REMOVAL_DURATION_S,
        skip_calibration: bool = False,
    ) -> None:
        self.ocr_engine = ocr_engine
        self.required_consecutive_checks = required_consecutive_checks
        self.capture_stability_seconds = capture_stability_seconds
        self.min_confidence = min_confidence
        self.min_text_area = min_text_area
        self.min_text_len = min_text_len
        self.max_drift = max_drift
        self.removal_duration = removal_duration

        self.state: ScanState = (
            ScanState.SEARCHING_FOR_TEXT if skip_calibration else ScanState.UNCALIBRATED
        )
        self.consecutive_checks: int = 0
        self.baseline_region: TextRegion | None = None
        self.latest_ocr_result: OCRResult | None = None
        self.qualifying_regions: list[TextRegion] = []

        self.absence_since: float | None = None
        self.removal_elapsed: float = 0.0
        self.detection_since: float | None = None

        # For compatibility with progress indicators
        self.stable_elapsed: float = 0.0
        self.stable_since: float | None = None

    def calibrate(self, frames: list[np.ndarray] | None = None) -> bool:
        """Arm scanner and transition from UNCALIBRATED to SEARCHING_FOR_TEXT."""
        self.state = ScanState.SEARCHING_FOR_TEXT
        self.consecutive_checks = 0
        self.baseline_region = None
        self.absence_since = None
        self.removal_elapsed = 0.0
        self.stable_elapsed = 0.0
        self.stable_since = None
        return True

    def needs_calibration(self) -> None:
        """Reset state back to UNCALIBRATED."""
        self.state = ScanState.UNCALIBRATED
        self.consecutive_checks = 0
        self.baseline_region = None
        self.absence_since = None
        self.removal_elapsed = 0.0
        self.qualifying_regions = []
        self.stable_elapsed = 0.0
        self.stable_since = None

    def reset_state(self) -> None:
        """Reset checking counters while remaining in SEARCHING_FOR_TEXT."""
        self.consecutive_checks = 0
        self.baseline_region = None
        self.absence_since = None
        self.removal_elapsed = 0.0
        self.stable_elapsed = 0.0
        self.stable_since = None
        if self.state != ScanState.UNCALIBRATED:
            self.state = ScanState.SEARCHING_FOR_TEXT

    def filter_qualifying_text(self, result: OCRResult | None) -> list[TextRegion]:
        """Extract qualifying text regions that meet confidence, area, and length thresholds."""
        if not result or not result.regions:
            return []
        valid: list[TextRegion] = []
        for r in result.regions:
            txt = r.text.strip()
            if (
                len(txt) >= self.min_text_len
                and r.confidence >= self.min_confidence
                and r.area >= self.min_text_area
            ):
                valid.append(r)
        return valid

    def update(
        self,
        frame_bgr: np.ndarray,
        now: float | None = None,
        ocr_result: OCRResult | None = None,
    ) -> bool:
        """
        Process one frame.
        ocr_result can be provided synchronously (in unit tests) or from the
        AsyncOCRWorker (in live camera loop).
        Returns True exactly once when qualifying text is stably verified.
        """
        if now is None:
            now = time.monotonic()

        if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
            return False

        if self.state == ScanState.UNCALIBRATED:
            return False

        # If synchronous ocr_engine is attached and no result was supplied, call it directly
        if ocr_result is None and self.ocr_engine is not None and isinstance(self.ocr_engine, MockOCREngine):
            ocr_result = self.ocr_engine.detect_text(frame_bgr)

        # Update cached result if an OCR update arrived
        if ocr_result is not None:
            self.latest_ocr_result = ocr_result
            self.qualifying_regions = self.filter_qualifying_text(ocr_result)

        has_qualifying = len(self.qualifying_regions) > 0
        triggered = False

        # -- SEARCHING_FOR_TEXT -----------------------------------------------
        if self.state == ScanState.SEARCHING_FOR_TEXT:
            self.consecutive_checks = 0
            self.baseline_region = None
            self.absence_since = None
            self.removal_elapsed = 0.0
            self.stable_elapsed = 0.0
            self.stable_since = None

            if has_qualifying:
                self.baseline_region = self.qualifying_regions[0]
                self.consecutive_checks = 1
                self.detection_since = now
                self.stable_since = now
                self.stable_elapsed = 0.0
                self.state = ScanState.TEXT_DETECTED

        # -- TEXT_DETECTED ----------------------------------------------------
        elif self.state == ScanState.TEXT_DETECTED:
            if not has_qualifying:
                # Text disappeared -> reset immediately
                self.consecutive_checks = 0
                self.baseline_region = None
                self.stable_since = None
                self.stable_elapsed = 0.0
                self.state = ScanState.SEARCHING_FOR_TEXT
            else:
                current_region = self.qualifying_regions[0]
                assert self.baseline_region is not None
                drift = float(np.hypot(
                    current_region.center[0] - self.baseline_region.center[0],
                    current_region.center[1] - self.baseline_region.center[1],
                ))
                if drift > self.max_drift:
                    # Excessive movement -> reset baseline and stability timer
                    self.baseline_region = current_region
                    self.consecutive_checks = 1
                    self.stable_since = now
                    self.stable_elapsed = 0.0
                else:
                    self.consecutive_checks += 1
                    if self.stable_since is None:
                        self.stable_since = now
                    self.stable_elapsed = max(0.0, now - self.stable_since)
                    self.state = ScanState.VERIFYING_TEXT_STABILITY
                    if (
                        self.stable_elapsed >= (self.capture_stability_seconds - 1e-4)
                        and self.consecutive_checks >= self.required_consecutive_checks
                    ):
                        # TRIGGER CAPTURE
                        self.state = ScanState.CAPTURED_WAITING_FOR_REMOVAL
                        self.consecutive_checks = 0
                        self.baseline_region = None
                        self.absence_since = None
                        self.removal_elapsed = 0.0
                        self.stable_since = None
                        self.stable_elapsed = 0.0
                        triggered = True

        # -- VERIFYING_TEXT_STABILITY -----------------------------------------
        elif self.state == ScanState.VERIFYING_TEXT_STABILITY:
            if not has_qualifying:
                # Text disappeared mid-verification -> reset to SEARCHING
                self.consecutive_checks = 0
                self.baseline_region = None
                self.stable_since = None
                self.stable_elapsed = 0.0
                self.state = ScanState.SEARCHING_FOR_TEXT
            else:
                current_region = self.qualifying_regions[0]
                assert self.baseline_region is not None
                drift = float(np.hypot(
                    current_region.center[0] - self.baseline_region.center[0],
                    current_region.center[1] - self.baseline_region.center[1],
                ))
                if drift > self.max_drift:
                    # Moved excessively -> drop back to TEXT_DETECTED and reset stability timer
                    self.baseline_region = current_region
                    self.consecutive_checks = 1
                    self.stable_since = now
                    self.stable_elapsed = 0.0
                    self.state = ScanState.TEXT_DETECTED
                else:
                    self.consecutive_checks += 1
                    if self.stable_since is None:
                        self.stable_since = now
                    self.stable_elapsed = max(0.0, now - self.stable_since)
                    if (
                        self.stable_elapsed >= (self.capture_stability_seconds - 1e-4)
                        and self.consecutive_checks >= self.required_consecutive_checks
                    ):
                        # TRIGGER CAPTURE
                        self.state = ScanState.CAPTURED_WAITING_FOR_REMOVAL
                        self.consecutive_checks = 0
                        self.baseline_region = None
                        self.absence_since = None
                        self.removal_elapsed = 0.0
                        self.stable_since = None
                        self.stable_elapsed = 0.0
                        triggered = True

        # -- CAPTURED_WAITING_FOR_REMOVAL -------------------------------------
        elif self.state == ScanState.CAPTURED_WAITING_FOR_REMOVAL:
            self.consecutive_checks = 0
            self.stable_since = None
            self.stable_elapsed = 0.0

            if not has_qualifying:
                if self.absence_since is None:
                    self.absence_since = now
                self.removal_elapsed = now - self.absence_since
                if self.removal_elapsed >= (self.removal_duration - 1e-4):
                    # Rearm scanner
                    self.state = ScanState.SEARCHING_FOR_TEXT
                    self.absence_since = None
                    self.removal_elapsed = 0.0
            else:
                # Text still present -> reset absence timer (prevent duplicate capture)
                self.absence_since = None
                self.removal_elapsed = 0.0

        return triggered


# ---------------------------------------------------------------------------
# Step 2 & 3 Components (Preserved for backward compatibility)
# ---------------------------------------------------------------------------

class ForegroundDetector:
    """Detects candidate foreground objects against a calibrated empty background."""

    def __init__(
        self,
        fg_ratio:         float = DEFAULT_FG_RATIO,
        pixel_threshold:  int   = DEFAULT_FG_PIXEL_THRESHOLD,
        cal_frames:       int   = DEFAULT_CAL_FRAMES,
        min_contour_area: int   = 0,
    ) -> None:
        self.fg_ratio         = fg_ratio
        self.pixel_threshold  = pixel_threshold
        self.cal_frames       = cal_frames
        self.min_contour_area = min_contour_area

        self._background: np.ndarray | None = None
        self.foreground_ratio: float = 0.0
        self.is_calibrated:   bool   = False

    def reset_calibration(self) -> None:
        self._background      = None
        self.is_calibrated    = False
        self.foreground_ratio = 0.0

    def calibrate(self, frames: list[np.ndarray]) -> bool:
        if not frames:
            self.reset_calibration()
            return False
        valid = [f for f in frames if f is not None and isinstance(f, np.ndarray) and f.size > 0]
        if not valid:
            self.reset_calibration()
            return False
        try:
            processed = [self._preprocess(f).astype(np.float32) for f in valid]
            first_shape = processed[0].shape
            if any(p.shape != first_shape for p in processed):
                self.reset_calibration()
                return False
            self._background   = np.mean(processed, axis=0)
            self.is_calibrated = True
            return True
        except Exception:
            self.reset_calibration()
            return False

    def has_object(self, frame_bgr: np.ndarray) -> bool:
        if not self.is_calibrated or self._background is None:
            self.foreground_ratio = 0.0
            return False
        if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
            return False
        try:
            gray = self._preprocess(frame_bgr)
            if gray.shape != self._background.shape:
                return False
            bg_uint8 = np.clip(self._background, 0, 255).astype(np.uint8)
            diff = cv2.absdiff(gray, bg_uint8)
            _, thresh = cv2.threshold(diff, self.pixel_threshold, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            clean_mask = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            fg_pixels = int(cv2.countNonZero(clean_mask))
            total_pixels = clean_mask.size
            self.foreground_ratio = (fg_pixels / total_pixels) if total_pixels > 0 else 0.0
            return self.foreground_ratio >= self.fg_ratio
        except Exception:
            return False

    @staticmethod
    def _preprocess(frame_bgr: np.ndarray) -> np.ndarray:
        if len(frame_bgr.shape) == 3 and frame_bgr.shape[2] == 3:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        elif len(frame_bgr.shape) == 2:
            gray = frame_bgr
        else:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGRA2GRAY)
        return cv2.GaussianBlur(gray, BLUR_KERNEL, 0)


class StabilityDetector:
    """Measures frame-to-frame motion using consecutive absolute differences."""

    def __init__(
        self,
        motion_threshold: float = DEFAULT_MOTION_THRESHOLD,
        stable_duration:  float = DEFAULT_STABLE_DURATION_S,
        removal_duration: float = DEFAULT_REMOVAL_DURATION_S,
    ) -> None:
        self.motion_threshold = motion_threshold
        self.stable_duration  = stable_duration
        self.removal_duration = removal_duration

        self.state: ScanState = ScanState.WAITING_FOR_STABILITY
        self._prev_gray: np.ndarray | None = None
        self._stable_since:   float | None = None
        self._moving_since:   float | None = None
        self.motion_score:    float = 0.0
        self.stable_elapsed:  float = 0.0
        self.removal_elapsed: float = 0.0

    def reset(self) -> None:
        self.state           = ScanState.WAITING_FOR_STABILITY
        self._prev_gray      = None
        self._stable_since   = None
        self._moving_since   = None
        self.motion_score    = 0.0
        self.stable_elapsed  = 0.0
        self.removal_elapsed = 0.0

    def compute_motion(self, frame_bgr: np.ndarray) -> float:
        if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
            return 0.0
        try:
            gray = self._preprocess(frame_bgr)
            if self._prev_gray is None or gray.shape != self._prev_gray.shape:
                self._prev_gray = gray
                self.motion_score = 0.0
                return 0.0
            score = float(np.mean(cv2.absdiff(gray, self._prev_gray)))
            self._prev_gray = gray
            self.motion_score = score
            return score
        except Exception:
            return 0.0

    def is_stable(self, frame_bgr: np.ndarray, now: float | None = None) -> bool:
        score = self.compute_motion(frame_bgr)
        return score < self.motion_threshold

    def update(self, frame_bgr: np.ndarray, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        motion = self.compute_motion(frame_bgr)
        is_still = motion < self.motion_threshold
        triggered = False

        if self.state == ScanState.WAITING_FOR_STABILITY:
            if is_still:
                if self._stable_since is None:
                    self._stable_since = now
                self.stable_elapsed = now - self._stable_since
                if self.stable_elapsed >= self.stable_duration:
                    self.state = ScanState.CAPTURED_WAITING_FOR_REMOVAL
                    self._stable_since = None
                    self.stable_elapsed = 0.0
                    triggered = True
            else:
                self._stable_since = None
                self.stable_elapsed = 0.0

        elif self.state == ScanState.CAPTURED_WAITING_FOR_REMOVAL:
            if not is_still:
                if self._moving_since is None:
                    self._moving_since = now
                self.removal_elapsed = now - self._moving_since
                if self.removal_elapsed >= self.removal_duration:
                    self.state = ScanState.WAITING_FOR_STABILITY
                    self._moving_since = None
                    self.removal_elapsed = 0.0
            else:
                self._moving_since = None
                self.removal_elapsed = 0.0

        return triggered

    @staticmethod
    def _preprocess(frame_bgr: np.ndarray) -> np.ndarray:
        if len(frame_bgr.shape) == 3 and frame_bgr.shape[2] == 3:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        elif len(frame_bgr.shape) == 2:
            gray = frame_bgr
        else:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGRA2GRAY)
        return cv2.GaussianBlur(gray, BLUR_KERNEL, 0)


class ScanEngine:
    """Preserved Step 3 engine (Foreground + Stability) for backward compatibility."""

    def __init__(self, fg: ForegroundDetector, stability: StabilityDetector) -> None:
        self.fg        = fg
        self.stability = stability

        self.state:           ScanState     = ScanState.CALIBRATE_BACKGROUND
        self.stable_since:    float | None  = None
        self.stable_elapsed:  float         = 0.0
        self.absence_since:   float | None  = None
        self.removal_elapsed: float         = 0.0

    def calibrate(self, frames: list[np.ndarray]) -> bool:
        ok = self.fg.calibrate(frames)
        self.stability.reset()
        self.stable_since    = None
        self.stable_elapsed  = 0.0
        self.absence_since   = None
        self.removal_elapsed = 0.0
        if ok:
            self.state = ScanState.NO_OBJECT_DETECTED
        else:
            self.state = ScanState.CALIBRATE_BACKGROUND
        return ok

    def needs_calibration(self) -> None:
        self.fg.reset_calibration()
        self.stability.reset()
        self.stable_since    = None
        self.stable_elapsed  = 0.0
        self.absence_since   = None
        self.removal_elapsed = 0.0
        self.state           = ScanState.CALIBRATE_BACKGROUND

    def reset_state(self) -> None:
        self.stability.reset()
        self.stable_since    = None
        self.stable_elapsed  = 0.0
        self.absence_since   = None
        self.removal_elapsed = 0.0
        if self.fg.is_calibrated:
            self.state = ScanState.NO_OBJECT_DETECTED
        else:
            self.state = ScanState.CALIBRATE_BACKGROUND

    def update(self, frame_bgr: np.ndarray, now: float | None = None) -> bool:
        if now is None:
            now = time.monotonic()
        if frame_bgr is None or not isinstance(frame_bgr, np.ndarray) or frame_bgr.size == 0:
            return False
        if not self.fg.is_calibrated or self.state == ScanState.CALIBRATE_BACKGROUND:
            self.state           = ScanState.CALIBRATE_BACKGROUND
            self.stable_since    = None
            self.stable_elapsed  = 0.0
            self.absence_since   = None
            self.removal_elapsed = 0.0
            return False

        motion_score = self.stability.compute_motion(frame_bgr)
        is_still = motion_score < self.stability.motion_threshold
        object_present = self.fg.has_object(frame_bgr)
        triggered = False

        if self.state == ScanState.NO_OBJECT_DETECTED:
            self.stable_since    = None
            self.stable_elapsed  = 0.0
            self.absence_since   = None
            self.removal_elapsed = 0.0
            if object_present:
                if is_still:
                    self.state          = ScanState.WAITING_FOR_STABILITY
                    self.stable_since   = now
                    self.stable_elapsed = 0.0
                else:
                    self.state = ScanState.OBJECT_DETECTED

        elif self.state == ScanState.OBJECT_DETECTED:
            if not object_present:
                self.stable_since   = None
                self.stable_elapsed = 0.0
                self.state          = ScanState.NO_OBJECT_DETECTED
            elif is_still:
                self.state          = ScanState.WAITING_FOR_STABILITY
                self.stable_since   = now
                self.stable_elapsed = 0.0
            else:
                self.stable_since   = None
                self.stable_elapsed = 0.0

        elif self.state == ScanState.WAITING_FOR_STABILITY:
            if not object_present:
                self.stable_since   = None
                self.stable_elapsed = 0.0
                self.state          = ScanState.NO_OBJECT_DETECTED
            elif not is_still:
                self.stable_since   = None
                self.stable_elapsed = 0.0
                self.state          = ScanState.OBJECT_DETECTED
            else:
                if self.stable_since is None:
                    self.stable_since = now
                self.stable_elapsed = now - self.stable_since
                if self.stable_elapsed >= self.stability.stable_duration:
                    self.state           = ScanState.CAPTURED_WAITING_FOR_REMOVAL
                    self.stable_since    = None
                    self.stable_elapsed  = 0.0
                    self.absence_since   = None
                    self.removal_elapsed = 0.0
                    triggered            = True

        elif self.state == ScanState.CAPTURED_WAITING_FOR_REMOVAL:
            self.stable_since   = None
            self.stable_elapsed = 0.0
            if not object_present:
                if self.absence_since is None:
                    self.absence_since = now
                self.removal_elapsed = now - self.absence_since
                if self.removal_elapsed >= self.stability.removal_duration:
                    self.state           = ScanState.NO_OBJECT_DETECTED
                    self.absence_since   = None
                    self.removal_elapsed = 0.0
            else:
                self.absence_since   = None
                self.removal_elapsed = 0.0

        return triggered


# ---------------------------------------------------------------------------
# HUD Rendering
# ---------------------------------------------------------------------------

def _dark_bar(frame: np.ndarray, y0: int, bar_height: int, alpha: float = 0.60) -> None:
    h, w = frame.shape[:2]
    bar_height = min(bar_height, h - y0)
    if bar_height <= 0:
        return
    roi     = frame[y0: y0 + bar_height, 0:w]
    dark    = np.zeros_like(roi)
    blended = cv2.addWeighted(roi, 1.0 - alpha, dark, alpha, 0)
    frame[y0: y0 + bar_height, 0:w] = blended


def _text(frame: np.ndarray, text: str, pos: tuple[int, int],
          colour: tuple = C_WHITE, scale: float = 0.52,
          thickness: int = 1) -> None:
    cv2.putText(frame, text, pos,
                cv2.FONT_HERSHEY_SIMPLEX, scale, colour, thickness,
                cv2.LINE_AA)


_STATE_COLOUR = {
    ScanState.UNCALIBRATED:                 C_RED,
    ScanState.SEARCHING_FOR_TEXT:           C_GREY,
    ScanState.TEXT_DETECTED:                C_YELLOW,
    ScanState.VERIFYING_TEXT_STABILITY:     C_CYAN,
    ScanState.CAPTURED_WAITING_FOR_REMOVAL: C_GREEN,
}


def draw_overlay(
    frame:        np.ndarray,
    engine:       TextScanEngine,
    cam_index:    int,
    width:        int,
    height:       int,
    fps:          float,
    capture_path: str,
    worker:       AsyncOCRWorker | None = None,
    gemini_worker: AsyncGeminiWorker | None = None,
) -> None:
    """Render full HUD status, text diagnostics, Gemini analysis, progress bar, and controls."""
    h, w = frame.shape[:2]

    # -- Top Header Bar -------------------------------------------------------
    _dark_bar(frame, 0, 64)
    _text(frame, "AnnaRakshak - Text-Verified Automatic Scan Trigger",
          (10, 18), C_GREEN, 0.56, 1)

    sc = _STATE_COLOUR.get(engine.state, C_WHITE)
    _text(frame, f"State: {engine.state.value}", (10, 44), sc, 0.60, 2)

    # -- Progress Bar ---------------------------------------------------------
    bar_y, bar_h = 64, 8
    cv2.rectangle(frame, (0, bar_y), (w, bar_y + bar_h), (45, 45, 45), -1)

    if engine.state in (ScanState.TEXT_DETECTED, ScanState.VERIFYING_TEXT_STABILITY):
        stab_dur = getattr(engine, "capture_stability_seconds", 2.5)
        stab_elapsed = getattr(engine, "stable_elapsed", 0.0)
        progress = min(max(stab_elapsed / max(stab_dur, 0.1), 0.0), 1.0)
        colour = C_CYAN if progress < 1.0 else C_GREEN
        cv2.rectangle(frame, (0, bar_y), (int(w * progress), bar_y + bar_h), colour, -1)
    elif engine.state == ScanState.CAPTURED_WAITING_FOR_REMOVAL and engine.removal_duration > 0:
        progress = min(engine.removal_elapsed / engine.removal_duration, 1.0)
        cv2.rectangle(frame, (0, bar_y), (int(w * progress), bar_y + bar_h), C_ORANGE, -1)

    # -- Bottom Status Bar (5 lines) ------------------------------------------
    bar_bottom_h = 122
    _dark_bar(frame, h - bar_bottom_h, bar_bottom_h)

    # Line 1: Detected Text & Confidence Snippet
    if engine.qualifying_regions:
        best = engine.qualifying_regions[0]
        snippet = best.text[:32]
        txt_col = C_GREEN if engine.state == ScanState.VERIFYING_TEXT_STABILITY else C_YELLOW
        txt_str = (
            f"Text: \"{snippet}\"  (conf: {best.confidence:.2f}, area: {best.area*100:.1f}%) "
            f" [Checks: {engine.consecutive_checks}/{engine.required_consecutive_checks}]"
        )
    else:
        txt_col = C_GREY
        txt_str = f"Text: [NO TEXT DETECTED]  (Checks: 0/{engine.required_consecutive_checks})"
    _text(frame, txt_str, (10, h - 100), txt_col, 0.48)

    # Line 2: OCR Status & Performance Diagnostics
    ocr_res = engine.latest_ocr_result
    if ocr_res and ocr_res.error:
        ocr_col = C_RED
        ocr_str = f"OCR: Error ({ocr_res.error})"
    elif ocr_res:
        busy_tag = "Processing..." if (worker and worker.is_busy) else "Idle"
        ocr_col = C_WHITE
        ocr_str = (
            f"OCR: Apple Vision ({ocr_res.latency_ms:.0f}ms, {busy_tag}) | "
            f"Raw text blocks: {len(ocr_res.regions)}"
        )
    else:
        ocr_col = C_WHITE
        ocr_str = "OCR: Initializing Apple Vision worker..."
    _text(frame, ocr_str, (10, h - 80), ocr_col, 0.46)

    # Line 3: State Guidance Message (strictly generic text — never misleading)
    if engine.state == ScanState.UNCALIBRATED:
        guide_str = "Status: Scanner uncalibrated. Press [c] to arm."
        guide_col = C_YELLOW
    elif engine.state == ScanState.SEARCHING_FOR_TEXT:
        guide_str = "Status: Searching for package text... (motion alone will not trigger)."
        guide_col = C_WHITE
    elif engine.state == ScanState.TEXT_DETECTED:
        stab_dur = getattr(engine, "capture_stability_seconds", 2.5)
        stab_elapsed = getattr(engine, "stable_elapsed", 0.0)
        pct = int(min(1.0, stab_elapsed / max(stab_dur, 0.1)) * 100)
        guide_str = f"Status: Package detected. Hold steady... ({stab_elapsed:.1f}s / {stab_dur:.1f}s, {pct}%)"
        guide_col = C_YELLOW
    elif engine.state == ScanState.VERIFYING_TEXT_STABILITY:
        stab_dur = getattr(engine, "capture_stability_seconds", 2.5)
        stab_elapsed = getattr(engine, "stable_elapsed", 0.0)
        pct = int(min(1.0, stab_elapsed / max(stab_dur, 0.1)) * 100)
        guide_str = (
            f"Status: HOLD STEADY TO CAPTURE... {stab_elapsed:.1f}s / {stab_dur:.1f}s ({pct}%) "
            f"[{engine.consecutive_checks} checks]"
        )
        guide_col = C_CYAN if pct < 80 else C_GREEN
    elif engine.state == ScanState.CAPTURED_WAITING_FOR_REMOVAL:
        guide_str = (
            f"Status: Generic text verified & captured! Remove package "
            f"({engine.removal_elapsed:.1f}s / {engine.removal_duration:.1f}s to rearm)."
        )
        guide_col = C_GREEN
    else:
        guide_str = f"Status: {engine.state.value}"
        guide_col = C_WHITE
    _text(frame, guide_str, (10, h - 60), guide_col, 0.48)

    # Line 4: Gemini Analysis Status & Result
    if gemini_worker:
        g_status = gemini_worker.status
        g_res = gemini_worker.latest_result
        if g_status == "ANALYZING WITH GEMINI":
            g_col = C_CYAN
            g_str = "Gemini: [ANALYZING WITH GEMINI] Interpreting food product & dates..."
        elif g_status == "IMAGE CAPTURED":
            g_col = C_YELLOW
            g_str = "Gemini: [IMAGE CAPTURED] Queued for Gemini analysis..."
        elif g_status.startswith("RETRYING"):
            g_col = C_ORANGE
            g_str = f"Gemini: [{g_status}] Waiting with backoff & jitter..."
        elif g_status == "EXPIRY DATE FOUND" and g_res:
            g_col = C_GREEN
            g_str = f"Gemini: [EXPIRY DATE FOUND] {g_res.summary}"
        elif g_status == "PRODUCT IDENTIFIED" and g_res:
            g_col = C_GREEN
            g_str = f"Gemini: [PRODUCT IDENTIFIED] {g_res.summary}"
        elif g_status == "NEEDS MANUAL REVIEW" and g_res:
            g_col = C_YELLOW
            g_str = f"Gemini: [NEEDS MANUAL REVIEW] {g_res.summary}"
        elif g_status == "GEMINI REQUEST FAILED":
            g_col = C_RED
            reason = (g_res.review_reason if g_res else "Request failed")[:55]
            g_str = f"Gemini: [GEMINI REQUEST FAILED] {reason}"
        else:
            g_col = C_GREY
            g_str = "Gemini: Ready (will analyze on capture)"
    else:
        g_col = C_GREY
        g_str = "Gemini: Disabled (--no-gemini)"
    _text(frame, g_str, (10, h - 38), g_col, 0.46)

    # Line 5: Camera details & Controls
    cam_info = (f"Camera #{cam_index}  {width}x{height}  {fps:.1f}fps  |  "
                f"[c] Arm/Calibrate  [r] Reset  [s] Snapshot  [a] Reanalyze  [q] Quit")
    _text(frame, cam_info, (10, h - 16), C_WHITE, 0.42)

    # Saved capture notification overlay
    if engine.state == ScanState.CAPTURED_WAITING_FOR_REMOVAL and capture_path:
        _dark_bar(frame, h - (bar_bottom_h + 24), 22, alpha=0.75)
        _text(frame, f"SAVED CAPTURE: {Path(capture_path).name}",
              (10, h - (bar_bottom_h + 8)), C_GREEN, 0.52, 1)


# ---------------------------------------------------------------------------
# Image Saving Helper
# ---------------------------------------------------------------------------

def save_capture(frame: np.ndarray, label: str = "") -> str:
    """Save clean raw frame without HUD to captures/ directory."""
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    ts     = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = f"_{label}" if label else ""
    path   = CAPTURES_DIR / f"{ts}{suffix}.jpg"
    cv2.imwrite(str(path), frame)
    return str(path)


# ---------------------------------------------------------------------------
# Diagnostics & Errors
# ---------------------------------------------------------------------------

def _camera_error(msg: str) -> None:
    print(f"\n[ERROR] {msg}\n")
    print("Troubleshooting steps:")
    print("  1. For built-in FaceTime camera: verify Terminal camera permission.")
    print("  2. System Settings -> Privacy & Security -> Camera -> allow Terminal.")
    print("  3. Close FaceTime, Zoom, or other apps using the camera.")
    print("  4. Run: python auto_scan.py --list")
    print("  5. Run: python auto_scan.py --index 0 (or --index 1)\n")


# ---------------------------------------------------------------------------
# Main Application Entry Point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AnnaRakshak — Text-verified automatic scan trigger using Apple Vision OCR."
    )
    parser.add_argument(
        "--index", type=int, default=None,
        help="Camera index to open (default: auto-detect built-in/first camera).",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List cameras visible to macOS and exit.",
    )
    parser.add_argument(
        "--consecutive-checks", type=int, default=DEFAULT_CONSECUTIVE_CHECKS,
        dest="consecutive_checks",
        help=f"Consecutive successful OCR checks required (default {DEFAULT_CONSECUTIVE_CHECKS}).",
    )
    parser.add_argument(
        "--capture-stability-seconds", type=float, default=DEFAULT_CAPTURE_STABILITY_SECONDS,
        dest="capture_stability_seconds",
        help=f"Continuous stability duration in seconds required before capture (default {DEFAULT_CAPTURE_STABILITY_SECONDS}s).",
    )
    parser.add_argument(
        "--min-conf", type=float, default=DEFAULT_MIN_CONFIDENCE,
        dest="min_conf",
        help=f"Minimum OCR confidence 0.0-1.0 (default {DEFAULT_MIN_CONFIDENCE}).",
    )
    parser.add_argument(
        "--min-text-area", type=float, default=DEFAULT_MIN_TEXT_AREA,
        dest="min_text_area",
        help=f"Minimum normalized text bbox area (default {DEFAULT_MIN_TEXT_AREA}).",
    )
    parser.add_argument(
        "--max-drift", type=float, default=DEFAULT_MAX_DRIFT,
        dest="max_drift",
        help=f"Maximum allowed position drift 0.0-1.0 (default {DEFAULT_MAX_DRIFT}).",
    )
    parser.add_argument(
        "--ocr-interval", type=float, default=DEFAULT_OCR_INTERVAL_S,
        dest="ocr_interval",
        help=f"Seconds between OCR checks (default {DEFAULT_OCR_INTERVAL_S}s).",
    )
    parser.add_argument(
        "--removal", type=float, default=DEFAULT_REMOVAL_DURATION_S,
        help=f"Seconds text must be absent to rearm (default {DEFAULT_REMOVAL_DURATION_S}s).",
    )
    parser.add_argument(
        "--skip-calib", action="store_true",
        help="Start directly in SEARCHING FOR TEXT without requiring [c] press.",
    )
    parser.add_argument(
        "--no-gemini", action="store_true",
        help="Disable background Gemini API analysis.",
    )
    parser.add_argument(
        "--gemini-model", type=str, default=None,
        help="Override Gemini model identifier (default: GEMINI_MODEL env or gemini-3.8-flash).",
    )
    args = parser.parse_args()

    if args.list:
        names = list_system_cameras()
        if names:
            print(f"Cameras visible to macOS ({len(names)} found):")
            for i, n in enumerate(names):
                print(f"  [{i}] {n}")
            print("\nUse --index 0 or --index 1 to select.")
        else:
            print("No cameras found by system_profiler (or not on macOS).")
        return 0

    # Camera opening
    if args.index is not None:
        cap = open_camera(args.index)
        if cap is None:
            _camera_error(f"Could not open camera at index {args.index}.")
            return 1
        cam_index = args.index
    else:
        result = find_first_camera()
        if result is None:
            _camera_error(f"No camera found at any index (0-{MAX_SCAN_INDEX}).")
            return 1
        cam_index, cap = result

    width, height = probe_resolution(cap)

    # Initialize OCR Engine and background worker
    try:
        ocr_engine = AppleVisionOCREngine()
        print("[AnnaRakshak] Apple Vision OCR engine initialized successfully.")
    except Exception as e:
        print(f"[AnnaRakshak] Warning: could not initialize Apple Vision OCR: {e}")
        print("[AnnaRakshak] Falling back to Mock OCR engine.")
        ocr_engine = MockOCREngine()

    worker = AsyncOCRWorker(ocr_engine, poll_interval_s=args.ocr_interval)

    engine = TextScanEngine(
        ocr_engine=ocr_engine,
        required_consecutive_checks=args.consecutive_checks,
        capture_stability_seconds=args.capture_stability_seconds,
        min_confidence=args.min_conf,
        min_text_area=args.min_text_area,
        max_drift=args.max_drift,
        removal_duration=args.removal,
        skip_calibration=args.skip_calib,
    )

    # Initialize Gemini Analyzer and background worker
    gemini_analyzer: GeminiAnalyzer | None = None
    gemini_worker: AsyncGeminiWorker | None = None
    if not args.no_gemini:
        gemini_analyzer = GeminiAnalyzer(model_name=args.gemini_model)
        gemini_worker = AsyncGeminiWorker(gemini_analyzer)
        api_status = "Configured" if gemini_analyzer.api_key else "Missing GEMINI_API_KEY (.env)"
        print(f"[AnnaRakshak] Gemini Analyzer initialized (Model: {gemini_analyzer.model_name}, API Key: {api_status})")
    else:
        print("[AnnaRakshak] Gemini Analysis disabled by --no-gemini.")

    # Initialize local SQLite inventory database
    inv_db = InventoryDatabase()
    print(f"[AnnaRakshak] Local inventory database ready at {inv_db.db_path.name}")

    print("=" * 70)
    print("AnnaRakshak — Text-Verified Automatic Scan Trigger")
    print("=" * 70)
    print(f"Camera Index      : {cam_index}")
    print(f"Resolution        : {width}x{height}")
    print(f"OCR Engine        : Apple Vision (macOS Neural Engine)")
    print(f"Gemini Analysis   : {'Enabled' if gemini_worker else 'Disabled'} ({gemini_analyzer.model_name if gemini_analyzer else 'N/A'})")
    print(f"Stability Required: {args.capture_stability_seconds:.1f}s continuous stability ({args.consecutive_checks} checks)")
    print(f"Min Confidence    : {args.min_conf:.2f}")
    print(f"Min Text Area     : {args.min_text_area * 100:.2f}% of frame")
    print(f"Max Drift Allowed : {args.max_drift * 100:.1f}%")
    print(f"OCR Interval      : {args.ocr_interval}s")
    print(f"Removal Duration  : {args.removal}s")
    print(f"Captures Directory: {CAPTURES_DIR.resolve()}")
    print("-" * 70)
    if not args.skip_calib:
        print("INITIAL ARMING:")
        print("  Press [c] in the preview window to arm the text detector.")
    else:
        print("ACTIVE: Searching for visible package text.")
    print("=" * 70 + "\n")

    # Warm-up frames
    for _ in range(5):
        cap.read()

    fps: float = 0.0
    frame_count: int = 0
    fps_interval = 30
    t_fps = time.monotonic()
    last_clean_frame: np.ndarray | None = None
    last_capture_path: str = ""
    last_reported_gemini_res: FoodAnalysisResult | None = None

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("[AnnaRakshak] Warning: frame read failed — retrying...")
                time.sleep(0.04)
                continue

            frame_count += 1
            if frame_count % fps_interval == 0:
                elapsed = time.monotonic() - t_fps
                fps = fps_interval / elapsed if elapsed > 0 else fps
                t_fps = time.monotonic()

            last_clean_frame = frame.copy()

            # Submit frame to background OCR worker (non-blocking)
            worker.submit_frame(last_clean_frame)

            # Retrieve latest available OCR result
            latest_ocr = worker.get_latest_result()

            # Process state machine
            triggered = engine.update(last_clean_frame, ocr_result=latest_ocr)

            if triggered:
                last_capture_path = save_capture(last_clean_frame, label="auto")
                print(f"[AnnaRakshak] CAPTURED -> {last_capture_path}")
                if gemini_worker:
                    queued = gemini_worker.submit_capture(last_capture_path)
                    if queued:
                        print("[AnnaRakshak] [IMAGE CAPTURED] Submitted to Gemini worker for analysis...")
                    else:
                        print("[AnnaRakshak] Gemini worker busy; capture saved locally for manual analysis.")

            # Check if Gemini worker completed a new analysis
            if gemini_worker:
                curr_res = gemini_worker.latest_result
                if curr_res is not None and curr_res is not last_reported_gemini_res:
                    last_reported_gemini_res = curr_res
                    scan_id: int | None = None
                    try:
                        scan_id = inv_db.record_scan(
                            image_path=gemini_worker.latest_image_path,
                            result=curr_res,
                            error_message=curr_res.review_reason if curr_res.analysis_status == "error" else None,
                        )
                    except Exception as e:
                        print(f"[AnnaRakshak] Warning: Could not record scan to database: {e}")

                    print("\n" + "=" * 65)
                    print(f"[AnnaRakshak] GEMINI ANALYSIS RESULT — {gemini_worker.status}:")
                    if scan_id is not None:
                        print(f"Recorded in scan history as Scan #{scan_id}")
                    print("-" * 65)
                    print(curr_res.model_dump_json(indent=2))
                    print("-" * 65)
                    print(format_date_candidates_review(curr_res))
                    if curr_res.needs_review and curr_res.review_reason:
                        print(f"Review Reason: {curr_res.review_reason}")
                    print("-" * 65)
                    print(f"Summary: {curr_res.summary}")
                    if scan_id is not None:
                        print(f"To inspect or confirm into inventory: python inventory.py add-scan {scan_id}")
                    print("=" * 65 + "\n")

            draw_overlay(frame, engine, cam_index, width, height, fps,
                         last_capture_path, worker=worker, gemini_worker=gemini_worker)
            cv2.imshow(WINDOW_TITLE, frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                print("[AnnaRakshak] Quitting.")
                break

            elif key == ord("c"):
                engine.calibrate()
                last_capture_path = ""
                print("[AnnaRakshak] Scanner armed! Present package with visible text.")

            elif key == ord("r"):
                engine.needs_calibration()
                last_capture_path = ""
                print("[AnnaRakshak] Reset to UNCALIBRATED. Press [c] to arm.")

            elif key == ord("s"):
                if last_clean_frame is not None:
                    snap_path = save_capture(last_clean_frame, label="snapshot")
                    last_capture_path = snap_path
                    print(f"[AnnaRakshak] Snapshot saved -> {snap_path}")
                    if gemini_worker:
                        gemini_worker.submit_capture(snap_path)

            elif key == ord("a"):
                target_path = last_capture_path or (gemini_worker.latest_image_path if gemini_worker else "")
                if target_path and Path(target_path).exists():
                    if gemini_worker:
                        accepted = gemini_worker.reanalyze_image(target_path)
                        if accepted:
                            print(f"[AnnaRakshak] Reanalyzing capture -> {target_path}")
                        else:
                            print("[AnnaRakshak] Gemini worker is currently busy. Try again shortly.")
                    else:
                        print("[AnnaRakshak] Gemini worker disabled (--no-gemini).")
                else:
                    print("[AnnaRakshak] No previous capture available to reanalyze. Capture an image first.")

    except KeyboardInterrupt:
        print("\n[AnnaRakshak] Interrupted by user.")

    finally:
        if gemini_worker:
            gemini_worker.shutdown()
        worker.shutdown()
        cap.release()
        cv2.destroyAllWindows()
        print("[AnnaRakshak] Camera, OCR, and Gemini workers released. Window closed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
