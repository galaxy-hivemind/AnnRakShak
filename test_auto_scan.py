"""
AnnaRakshak — Comprehensive Unit & Integration Tests
=====================================================
Tests across all phases:
  1. Standalone StabilityDetector (Step 2 test suites)
  2. Stage A ForegroundDetector (Step 3 background subtraction)
  3. Two-Stage ScanEngine (Step 3 object gate + stability gate)
  4. Text-Verified TextScanEngine (Step 4 OCR gate + stability gate)
  5. Apple Vision OCR Integration (macOS native Vision text recognition)

Key verification requirements tested:
  - Empty frames never trigger capture.
  - Shadow-like motion without text never triggers capture.
  - Text detection starts the verification process.
  - Low-confidence or very small text is rejected.
  - Text that disappears during verification resets the process.
  - Excessively moving text resets verification.
  - Stable qualifying text triggers exactly one capture.
  - Text remaining visible after capture does not trigger duplicate captures.
  - Text disappearance allows rearming.
  - OCR errors do not crash the preview or cause a capture.
  - The state machine can be tested using a mocked OCR interface without a physical camera.
  - Apple Vision OCR detects text on synthetic images.

Run with:
    source .venv/bin/activate
    python test_auto_scan.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).parent))

from auto_scan import (
    ForegroundDetector,
    ScanEngine,
    ScanState,
    StabilityDetector,
    TextScanEngine,
)
from ocr_engine import (
    AppleVisionOCREngine,
    MockOCREngine,
    OCRResult,
    TextRegion,
)

# ---------------------------------------------------------------------------
# Synthetic frame factories
# ---------------------------------------------------------------------------

def solid_frame(value: int, shape: tuple = (480, 640, 3)) -> np.ndarray:
    """Return a BGR frame where every pixel has the same grey value."""
    return np.full(shape, np.clip(value, 0, 255), dtype=np.uint8)


def make_still_frames(n: int, value: int = 80) -> list[np.ndarray]:
    """n identical frames — zero motion."""
    return [solid_frame(value) for _ in range(n)]


def make_moving_frames(n: int, start: int = 80, step: int = 20) -> list[np.ndarray]:
    """n frames where value changes by step each time — high motion."""
    return [solid_frame((start + i * step) % 200 + 10) for i in range(n)]


def make_frame_with_object(
    bg_val: int = 80,
    fg_val: int = 180,
    box: tuple[int, int, int, int] = (100, 100, 300, 300),
    shape: tuple = (480, 640, 3),
) -> np.ndarray:
    """Return a frame with background bg_val and a foreground patch of fg_val."""
    frame = np.full(shape, bg_val, dtype=np.uint8)
    y1, x1, y2, x2 = box
    frame[y1:y2, x1:x2] = fg_val
    return frame


def make_noisy_frame(
    bg_val: int = 80,
    num_noise_pixels: int = 50,
    shape: tuple = (480, 640, 3),
) -> np.ndarray:
    """Return a frame with background bg_val plus isolated random noisy pixels."""
    frame = np.full(shape, bg_val, dtype=np.uint8)
    rng = np.random.default_rng(seed=42)
    ys = rng.integers(0, shape[0], size=num_noise_pixels)
    xs = rng.integers(0, shape[1], size=num_noise_pixels)
    frame[ys, xs] = 255
    return frame


def make_frame_with_text(text: str = "ORGANIC MILK 1L", shape: tuple = (480, 640, 3)) -> np.ndarray:
    """Return a frame with clean visible text drawn onto it."""
    frame = np.full(shape, 240, dtype=np.uint8)
    cv2.putText(frame, text, (80, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (10, 10, 10), 3)
    return frame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def feed(detector, frames: list[np.ndarray], timestamps: list[float]) -> list[bool]:
    """Feed frames and timestamps into detector.update() and return triggers."""
    return [detector.update(f, now=t) for f, t in zip(frames, timestamps)]


# ===========================================================================
# PRESERVED STEP 2 TESTS: StabilityDetector standalone logic
# ===========================================================================

class TestStabilityDetectorInit(unittest.TestCase):

    def test_initial_state(self):
        d = StabilityDetector(motion_threshold=3.0, stable_duration=1.5)
        self.assertEqual(d.state, ScanState.WAITING_FOR_STABILITY)
        self.assertIsNone(d._prev_gray)
        self.assertAlmostEqual(d.motion_score, 0.0)

    def test_first_frame_never_triggers(self):
        d = StabilityDetector()
        triggered = d.update(solid_frame(100), now=0.0)
        self.assertFalse(triggered)
        self.assertEqual(d.state, ScanState.WAITING_FOR_STABILITY)


class TestStillScene(unittest.TestCase):
    """Scene remains stable long enough -> one capture (Step 2 test)."""

    THRESHOLD = 1.0
    STABLE    = 1.5
    REMOVAL   = 0.8

    def _detector(self):
        return StabilityDetector(
            motion_threshold = self.THRESHOLD,
            stable_duration  = self.STABLE,
            removal_duration = self.REMOVAL,
        )

    def test_no_capture_before_stable_duration(self):
        d = self._detector()
        frames = make_still_frames(10)
        times  = [i * 0.1 for i in range(10)]
        results = feed(d, frames, times)
        self.assertFalse(any(results), "Should not capture before stable_duration")
        self.assertNotEqual(d.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_capture_after_stable_duration(self):
        d = self._detector()
        frames = make_still_frames(20)
        times  = [i * 0.1 for i in range(20)]
        results = feed(d, frames, times)
        self.assertTrue(any(results), "Should have triggered one capture")
        self.assertEqual(results.count(True), 1, "Exactly one capture")
        self.assertEqual(d.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_motion_score_is_zero_for_identical_frames(self):
        d = self._detector()
        d.update(solid_frame(80), now=0.0)
        d.update(solid_frame(80), now=0.1)
        self.assertAlmostEqual(d.motion_score, 0.0, places=3)


class TestMovingScene(unittest.TestCase):
    """Scene keeps moving -> no capture (Step 2 test)."""

    def test_no_capture_when_always_moving(self):
        d = StabilityDetector(motion_threshold=1.0, stable_duration=1.5)
        frames = make_moving_frames(30, start=10, step=20)
        times  = [i * 0.1 for i in range(30)]
        results = feed(d, frames, times)
        self.assertFalse(any(results))
        self.assertEqual(d.state, ScanState.WAITING_FOR_STABILITY)


class TestNoDuplicateCapture(unittest.TestCase):
    """After capture, same still scene must NOT trigger again (Step 2 test)."""

    def test_no_second_capture_without_removal(self):
        d = StabilityDetector(motion_threshold=1.0,
                              stable_duration=1.5, removal_duration=0.8)
        frames = make_still_frames(20)
        times  = [i * 0.1 for i in range(20)]
        feed(d, frames, times)
        self.assertEqual(d.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        extra_frames = make_still_frames(20)
        extra_times  = [2.0 + i * 0.1 for i in range(20)]
        results = feed(d, extra_frames, extra_times)
        self.assertFalse(any(results), "No second capture while package is still there")


class TestRemovalAndRearm(unittest.TestCase):
    """Package removed and presented again -> exactly two captures total (Step 2 test)."""

    def test_rearm_after_removal(self):
        d = StabilityDetector(motion_threshold=1.0,
                              stable_duration=1.0, removal_duration=0.5)
        clock = [0.0]

        def tick(dt: float, frame: np.ndarray):
            clock[0] += dt
            return d.update(frame, now=clock[0])

        STILL    = solid_frame(80)
        MOVING_A = solid_frame(150)
        MOVING_B = solid_frame(200)

        captures = 0
        for _ in range(12):
            if tick(0.1, STILL):
                captures += 1

        self.assertEqual(captures, 1, "First capture expected")
        self.assertEqual(d.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        moving_frames = [MOVING_A if i % 2 == 0 else MOVING_B for i in range(8)]
        for mf in moving_frames:
            tick(0.1, mf)

        self.assertEqual(d.state, ScanState.WAITING_FOR_STABILITY,
                         "Should have rearmed after removal")

        for _ in range(14):
            if tick(0.1, STILL):
                captures += 1

        self.assertEqual(captures, 2, "Second capture expected after rearm")


class TestReset(unittest.TestCase):
    """Manual reset returns detector to initial state (Step 2 test)."""

    def test_reset_from_captured_state(self):
        d = StabilityDetector(motion_threshold=1.0, stable_duration=0.5)
        frames = make_still_frames(10)
        times  = [i * 0.1 for i in range(10)]
        feed(d, frames, times)
        self.assertEqual(d.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        d.reset()
        self.assertEqual(d.state, ScanState.WAITING_FOR_STABILITY)
        self.assertIsNone(d._prev_gray)
        self.assertAlmostEqual(d.motion_score, 0.0)
        self.assertAlmostEqual(d.stable_elapsed, 0.0)

    def test_no_trigger_immediately_after_reset(self):
        d = StabilityDetector(motion_threshold=1.0, stable_duration=1.5)
        d.reset()
        triggered = d.update(solid_frame(100), now=0.0)
        self.assertFalse(triggered)


class TestCameraFailure(unittest.TestCase):
    """Detector must not crash when fed unexpected data (Step 2 test)."""

    def test_graceful_with_all_zeros_frame(self):
        d = StabilityDetector()
        frame_zero = np.zeros((480, 640, 3), dtype=np.uint8)
        try:
            d.update(frame_zero, now=0.0)
            d.update(frame_zero, now=0.1)
        except Exception as e:
            self.fail(f"update() raised unexpectedly: {e}")


# ===========================================================================
# PRESERVED STEP 3 TESTS: Stage A ForegroundDetector Logic
# ===========================================================================

class TestForegroundDetector(unittest.TestCase):

    def test_uncalibrated_never_detects_object(self):
        fg = ForegroundDetector(fg_ratio=0.01)
        self.assertFalse(fg.is_calibrated)
        self.assertFalse(fg.has_object(solid_frame(200)))
        self.assertEqual(fg.foreground_ratio, 0.0)

    def test_empty_scene_matches_background(self):
        fg = ForegroundDetector(fg_ratio=0.015, pixel_threshold=20)
        cal_frames = [solid_frame(80) for _ in range(10)]
        self.assertTrue(fg.calibrate(cal_frames))
        self.assertTrue(fg.is_calibrated)

        has_obj = fg.has_object(solid_frame(80))
        self.assertFalse(has_obj)
        self.assertEqual(fg.foreground_ratio, 0.0)

    def test_foreground_object_detected(self):
        fg = ForegroundDetector(fg_ratio=0.015, pixel_threshold=20)
        cal_frames = [solid_frame(80) for _ in range(10)]
        fg.calibrate(cal_frames)

        obj_frame = make_frame_with_object(bg_val=80, fg_val=180, box=(100, 100, 300, 300))
        has_obj = fg.has_object(obj_frame)
        self.assertTrue(has_obj)
        self.assertGreater(fg.foreground_ratio, 0.05)

    def test_minor_noise_rejected(self):
        fg = ForegroundDetector(fg_ratio=0.015, pixel_threshold=20)
        cal_frames = [solid_frame(80) for _ in range(10)]
        fg.calibrate(cal_frames)

        noisy = make_noisy_frame(bg_val=80, num_noise_pixels=50)
        has_obj = fg.has_object(noisy)
        self.assertFalse(has_obj)

    def test_calibrate_empty_or_invalid_handled_gracefully(self):
        fg = ForegroundDetector()
        self.assertFalse(fg.calibrate([]))
        self.assertFalse(fg.is_calibrated)
        self.assertFalse(fg.calibrate([None]))  # type: ignore
        self.assertFalse(fg.is_calibrated)

    def test_reset_calibration(self):
        fg = ForegroundDetector()
        fg.calibrate([solid_frame(80) for _ in range(5)])
        self.assertTrue(fg.is_calibrated)
        fg.reset_calibration()
        self.assertFalse(fg.is_calibrated)
        self.assertIsNone(fg._background)


# ===========================================================================
# PRESERVED STEP 3 TESTS: Two-Stage ScanEngine
# ===========================================================================

class TestTwoStageScanEngine(unittest.TestCase):

    def _make_engine(
        self,
        motion_threshold: float = 2.0,
        stable_duration: float = 1.5,
        removal_duration: float = 0.8,
        fg_ratio: float = 0.015,
        pixel_threshold: int = 20,
    ) -> ScanEngine:
        fg = ForegroundDetector(
            fg_ratio=fg_ratio,
            pixel_threshold=pixel_threshold,
            cal_frames=10,
        )
        stability = StabilityDetector(
            motion_threshold=motion_threshold,
            stable_duration=stable_duration,
            removal_duration=removal_duration,
        )
        return ScanEngine(fg=fg, stability=stability)

    def test_uncalibrated_engine_never_captures(self):
        engine = self._make_engine()
        self.assertEqual(engine.state, ScanState.CALIBRATE_BACKGROUND)

        for i in range(30):
            triggered = engine.update(solid_frame(80), now=i * 0.1)
            self.assertFalse(triggered)

        self.assertEqual(engine.state, ScanState.CALIBRATE_BACKGROUND)

    def test_empty_stable_background_never_captures(self):
        engine = self._make_engine(stable_duration=1.5)
        engine.calibrate([solid_frame(80) for _ in range(10)])
        self.assertEqual(engine.state, ScanState.NO_OBJECT_DETECTED)

        triggers = []
        for i in range(60):
            t = i * 0.1
            trig = engine.update(solid_frame(80), now=t)
            triggers.append(trig)

        self.assertFalse(any(triggers))
        self.assertEqual(engine.state, ScanState.NO_OBJECT_DETECTED)
        self.assertEqual(engine.stable_elapsed, 0.0)

    def test_foreground_object_must_be_detected_before_stability_timer_starts(self):
        engine = self._make_engine(stable_duration=1.5)
        engine.calibrate([solid_frame(80) for _ in range(10)])

        EMPTY_FRAME = solid_frame(80)
        OBJECT_FRAME = make_frame_with_object(bg_val=80, fg_val=180, box=(100, 100, 300, 300))

        for i in range(30):
            t = i * 0.1
            trig = engine.update(EMPTY_FRAME, now=t)
            self.assertFalse(trig)

        self.assertEqual(engine.state, ScanState.NO_OBJECT_DETECTED)
        self.assertEqual(engine.stable_elapsed, 0.0)

        trig = engine.update(OBJECT_FRAME, now=3.1)
        self.assertFalse(trig)
        self.assertEqual(engine.state, ScanState.OBJECT_DETECTED)

        trig = engine.update(OBJECT_FRAME, now=3.2)
        self.assertFalse(trig)
        self.assertEqual(engine.state, ScanState.WAITING_FOR_STABILITY)

        for i in range(1, 11):
            t = 3.2 + i * 0.1
            trig = engine.update(OBJECT_FRAME, now=t)
            self.assertFalse(trig)

        trig_final = False
        for i in range(11, 16):
            t = 3.2 + i * 0.1
            if engine.update(OBJECT_FRAME, now=t):
                trig_final = True
                break

        self.assertTrue(trig_final)
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_stable_detected_object_triggers_exactly_one_capture(self):
        engine = self._make_engine(stable_duration=1.0)
        engine.calibrate([solid_frame(80) for _ in range(10)])

        OBJECT_FRAME = make_frame_with_object(bg_val=80, fg_val=180)
        captures = 0
        for i in range(30):
            t = i * 0.1
            if engine.update(OBJECT_FRAME, now=t):
                captures += 1

        self.assertEqual(captures, 1)
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_moving_object_does_not_trigger_capture(self):
        engine = self._make_engine(motion_threshold=2.0, stable_duration=1.0)
        engine.calibrate([solid_frame(80) for _ in range(10)])

        OBJ_A = make_frame_with_object(bg_val=80, fg_val=150)
        OBJ_B = make_frame_with_object(bg_val=80, fg_val=220)

        captures = 0
        for i in range(30):
            t = i * 0.1
            frame = OBJ_A if (i % 2 == 0) else OBJ_B
            if engine.update(frame, now=t):
                captures += 1

        self.assertEqual(captures, 0)
        self.assertEqual(engine.state, ScanState.OBJECT_DETECTED)

    def test_object_disappearing_during_stabilization_resets_timer(self):
        engine = self._make_engine(stable_duration=1.5)
        engine.calibrate([solid_frame(80) for _ in range(10)])

        EMPTY_FRAME = solid_frame(80)
        OBJECT_FRAME = make_frame_with_object(bg_val=80, fg_val=180)

        for i in range(11):
            t = i * 0.1
            engine.update(OBJECT_FRAME, now=t)

        self.assertEqual(engine.state, ScanState.WAITING_FOR_STABILITY)

        engine.update(EMPTY_FRAME, now=1.1)
        self.assertEqual(engine.state, ScanState.NO_OBJECT_DETECTED)
        self.assertEqual(engine.stable_elapsed, 0.0)

        trig = engine.update(OBJECT_FRAME, now=1.2)
        self.assertFalse(trig)
        self.assertEqual(engine.state, ScanState.OBJECT_DETECTED)

        trig = engine.update(OBJECT_FRAME, now=1.3)
        self.assertFalse(trig)
        self.assertEqual(engine.state, ScanState.WAITING_FOR_STABILITY)

    def test_removing_object_rearms_scanner(self):
        engine = self._make_engine(stable_duration=1.0, removal_duration=0.5)
        engine.calibrate([solid_frame(80) for _ in range(10)])

        EMPTY_FRAME = solid_frame(80)
        OBJECT_FRAME = make_frame_with_object(bg_val=80, fg_val=180)

        clock = [0.0]
        def tick(dt: float, frame: np.ndarray) -> bool:
            clock[0] += dt
            return engine.update(frame, now=clock[0])

        captures = 0
        for _ in range(15):
            if tick(0.1, OBJECT_FRAME):
                captures += 1

        self.assertEqual(captures, 1)
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        for _ in range(8):
            tick(0.1, EMPTY_FRAME)

        self.assertEqual(engine.state, ScanState.NO_OBJECT_DETECTED)

        for _ in range(15):
            if tick(0.1, OBJECT_FRAME):
                captures += 1

        self.assertEqual(captures, 2)

    def test_engine_needs_calibration_resets_properly(self):
        engine = self._make_engine()
        engine.calibrate([solid_frame(80) for _ in range(10)])
        self.assertEqual(engine.state, ScanState.NO_OBJECT_DETECTED)
        engine.needs_calibration()
        self.assertEqual(engine.state, ScanState.CALIBRATE_BACKGROUND)

    def test_engine_graceful_with_invalid_inputs(self):
        engine = self._make_engine()
        engine.calibrate([solid_frame(80) for _ in range(5)])
        self.assertFalse(engine.update(None))  # type: ignore
        self.assertFalse(engine.update(np.array([], dtype=np.uint8)))


# ===========================================================================
# STEP 4 TESTS: Text-Verified TextScanEngine (OCR Verification Gate)
# ===========================================================================

class TestTextScanEngine(unittest.TestCase):
    """
    Exhaustive tests verifying all Step 4 OCR trigger requirements:
      - Empty frames never trigger capture.
      - Shadow motion without text never triggers capture.
      - Text detection starts verification process.
      - Low confidence or small text rejected.
      - Text disappearance resets process.
      - Excessive text movement resets process.
      - Stable qualifying text triggers exactly one capture.
      - Duplicate captures strictly prevented.
      - Text disappearance allows rearming.
      - OCR errors do not crash preview or cause capture.
    """

    def _make_engine(
        self,
        required_consecutive_checks: int = 3,
        min_confidence: float = 0.35,
        min_text_area: float = 0.001,
        max_drift: float = 0.15,
        removal_duration: float = 0.8,
        skip_calibration: bool = True,
        capture_stability_seconds: float | None = None,
    ) -> tuple[TextScanEngine, MockOCREngine]:
        mock_ocr = MockOCREngine()
        if capture_stability_seconds is None:
            capture_stability_seconds = max(0.0, (required_consecutive_checks - 1) * 0.25)
        engine = TextScanEngine(
            ocr_engine=mock_ocr,
            required_consecutive_checks=required_consecutive_checks,
            capture_stability_seconds=capture_stability_seconds,
            min_confidence=min_confidence,
            min_text_area=min_text_area,
            max_drift=max_drift,
            removal_duration=removal_duration,
            skip_calibration=skip_calibration,
        )
        return engine, mock_ocr

    def test_uncalibrated_state_blocks_captures(self):
        engine, mock = self._make_engine(skip_calibration=False)
        self.assertEqual(engine.state, ScanState.UNCALIBRATED)

        # Even with valid text, uncalibrated state blocks capture
        region = TextRegion("MILK", 0.9, 0.2, 0.2, 0.2, 0.1)
        res = OCRResult(regions=[region])

        for i in range(10):
            trig = engine.update(solid_frame(80), now=i * 0.1, ocr_result=res)
            self.assertFalse(trig)

        self.assertEqual(engine.state, ScanState.UNCALIBRATED)

        # Calibrate / arm scanner
        engine.calibrate()
        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)

    def test_empty_frames_never_trigger_capture(self):
        """CRITICAL: Empty background with no text NEVER triggers capture."""
        engine, _ = self._make_engine()
        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)

        empty_result = OCRResult(regions=[])
        triggers = []
        for i in range(50):
            trig = engine.update(solid_frame(80), now=i * 0.1, ocr_result=empty_result)
            triggers.append(trig)

        self.assertFalse(any(triggers), "Empty frame must never trigger capture!")
        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)
        self.assertEqual(engine.consecutive_checks, 0)

    def test_shadow_motion_without_text_never_triggers_capture(self):
        """CRITICAL: Changing pixels/shadows with no text NEVER trigger capture."""
        engine, _ = self._make_engine()

        empty_result = OCRResult(regions=[])
        triggers = []
        # Simulate moving shadow: alternating pixel intensities from 50 to 180
        for i in range(50):
            val = (50 + i * 15) % 200
            frame = solid_frame(val)
            trig = engine.update(frame, now=i * 0.1, ocr_result=empty_result)
            triggers.append(trig)

        self.assertFalse(any(triggers), "Shadow motion without text must NEVER trigger capture!")
        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)

    def test_text_detection_starts_verification_process(self):
        engine, _ = self._make_engine(required_consecutive_checks=3)

        region = TextRegion("ORGANIC MILK", 0.85, 0.2, 0.3, 0.3, 0.08)
        valid_result = OCRResult(regions=[region])

        # Check 1: Text detected
        trig1 = engine.update(solid_frame(80), now=0.0, ocr_result=valid_result)
        self.assertFalse(trig1)
        self.assertEqual(engine.state, ScanState.TEXT_DETECTED)
        self.assertEqual(engine.consecutive_checks, 1)

        # Check 2: Consistent text -> VERIFYING_TEXT_STABILITY
        trig2 = engine.update(solid_frame(80), now=0.25, ocr_result=valid_result)
        self.assertFalse(trig2)
        self.assertEqual(engine.state, ScanState.VERIFYING_TEXT_STABILITY)
        self.assertEqual(engine.consecutive_checks, 2)

    def test_low_confidence_text_rejected(self):
        engine, _ = self._make_engine(min_confidence=0.40)

        # Region with low confidence (0.25 < 0.40)
        low_conf_reg = TextRegion("BLURRY", 0.25, 0.2, 0.2, 0.2, 0.1)
        result = OCRResult(regions=[low_conf_reg])

        for i in range(10):
            trig = engine.update(solid_frame(80), now=i * 0.1, ocr_result=result)
            self.assertFalse(trig)

        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)
        self.assertEqual(engine.consecutive_checks, 0)

    def test_small_text_region_rejected(self):
        engine, _ = self._make_engine(min_text_area=0.005)

        # Region with microscopic area (0.01 * 0.01 = 0.0001 < 0.005)
        tiny_reg = TextRegion("TINY", 0.95, 0.1, 0.1, 0.01, 0.01)
        result = OCRResult(regions=[tiny_reg])

        for i in range(10):
            trig = engine.update(solid_frame(80), now=i * 0.1, ocr_result=result)
            self.assertFalse(trig)

        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)

    def test_text_disappearing_during_verification_resets_process(self):
        engine, _ = self._make_engine(required_consecutive_checks=3)

        valid_reg = TextRegion("EXP 2026", 0.8, 0.2, 0.2, 0.25, 0.1)
        res_valid = OCRResult(regions=[valid_reg])
        res_empty = OCRResult(regions=[])

        # Checks 1 & 2: valid text
        engine.update(solid_frame(80), now=0.0, ocr_result=res_valid)
        engine.update(solid_frame(80), now=0.25, ocr_result=res_valid)
        self.assertEqual(engine.state, ScanState.VERIFYING_TEXT_STABILITY)
        self.assertEqual(engine.consecutive_checks, 2)

        # Check 3: text disappeared
        engine.update(solid_frame(80), now=0.50, ocr_result=res_empty)
        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)
        self.assertEqual(engine.consecutive_checks, 0)
        self.assertIsNone(engine.baseline_region)

        # Text returns later: must start from 1 again (not 3)
        trig = engine.update(solid_frame(80), now=0.75, ocr_result=res_valid)
        self.assertFalse(trig, "Must not capture because check count was reset to 0")
        self.assertEqual(engine.consecutive_checks, 1)

    def test_excessively_moving_text_resets_verification(self):
        engine, _ = self._make_engine(required_consecutive_checks=3, max_drift=0.10)

        # Position A: (0.1, 0.1)
        reg_a = TextRegion("YOGURT", 0.85, 0.10, 0.10, 0.20, 0.10)
        # Position B: (0.60, 0.60) -> drift = hypot(0.5, 0.5) = 0.70 >> 0.10 max_drift
        reg_b = TextRegion("YOGURT", 0.85, 0.60, 0.60, 0.20, 0.10)

        engine.update(solid_frame(80), now=0.0, ocr_result=OCRResult(regions=[reg_a]))
        self.assertEqual(engine.state, ScanState.TEXT_DETECTED)
        self.assertEqual(engine.consecutive_checks, 1)

        # Next check: moved excessively
        engine.update(solid_frame(80), now=0.25, ocr_result=OCRResult(regions=[reg_b]))
        # Checks remain at 1 because baseline reset to the new position
        self.assertEqual(engine.consecutive_checks, 1)
        self.assertEqual(engine.state, ScanState.TEXT_DETECTED)

    def test_stable_qualifying_text_triggers_exactly_one_capture(self):
        engine, _ = self._make_engine(required_consecutive_checks=3)

        reg = TextRegion("WHOLE WHEAT BREAD", 0.90, 0.2, 0.2, 0.3, 0.1)
        res = OCRResult(regions=[reg])

        t1 = engine.update(solid_frame(80), now=0.00, ocr_result=res)
        self.assertFalse(t1)
        self.assertEqual(engine.consecutive_checks, 1)

        t2 = engine.update(solid_frame(80), now=0.25, ocr_result=res)
        self.assertFalse(t2)
        self.assertEqual(engine.consecutive_checks, 2)

        # Third check -> triggers capture!
        t3 = engine.update(solid_frame(80), now=0.50, ocr_result=res)
        self.assertTrue(t3, "Must trigger capture on 3rd consecutive check")
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_text_remaining_visible_does_not_duplicate_capture(self):
        engine, _ = self._make_engine(required_consecutive_checks=2)

        reg = TextRegion("OATS 1KG", 0.90, 0.2, 0.2, 0.2, 0.1)
        res = OCRResult(regions=[reg])

        engine.update(solid_frame(80), now=0.0, ocr_result=res)
        t_capture = engine.update(solid_frame(80), now=0.25, ocr_result=res)
        self.assertTrue(t_capture)
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        # Continue feeding same text for 20 frames
        extra_triggers = []
        for i in range(20):
            trig = engine.update(solid_frame(80), now=0.5 + i * 0.1, ocr_result=res)
            extra_triggers.append(trig)

        self.assertFalse(any(extra_triggers), "Must NOT duplicate capture while text remains")
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

    def test_text_disappearance_allows_rearming(self):
        engine, _ = self._make_engine(required_consecutive_checks=2, removal_duration=0.5)

        reg = TextRegion("ALMOND BUTTER", 0.90, 0.2, 0.2, 0.25, 0.1)
        res_text = OCRResult(regions=[reg])
        res_empty = OCRResult(regions=[])

        # Capture #1
        engine.update(solid_frame(80), now=0.0, ocr_result=res_text)
        self.assertTrue(engine.update(solid_frame(80), now=0.25, ocr_result=res_text))
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)

        # Remove package (0.6s of absence > removal_duration 0.5s)
        clock = 0.5
        for _ in range(6):
            clock += 0.1
            engine.update(solid_frame(80), now=clock, ocr_result=res_empty)

        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT,
                         "Scanner must rearm after text absence")

        # Capture #2 with new item
        clock += 0.1
        engine.update(solid_frame(80), now=clock, ocr_result=res_text)
        clock += 0.25
        self.assertTrue(engine.update(solid_frame(80), now=clock, ocr_result=res_text),
                        "Second capture expected after rearm")

    def test_ocr_errors_do_not_crash_or_cause_capture(self):
        engine, _ = self._make_engine()

        error_result = OCRResult(error="Vision daemon connection timeout")
        try:
            for i in range(10):
                trig = engine.update(solid_frame(80), now=i * 0.1, ocr_result=error_result)
                self.assertFalse(trig)
            self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)
        except Exception as e:
            self.fail(f"OCR error crashed engine: {e}")

    def test_state_machine_with_mock_ocr_lifecycle(self):
        """Tests full lifecycle using MockOCREngine without physical camera."""
        mock_ocr = MockOCREngine()
        engine = TextScanEngine(ocr_engine=mock_ocr, required_consecutive_checks=2, capture_stability_seconds=0.2)
        engine.calibrate()

        # 1. Empty scene
        mock_ocr.clear()
        self.assertFalse(engine.update(solid_frame(80), now=0.0))
        self.assertEqual(engine.state, ScanState.SEARCHING_FOR_TEXT)

        # 2. Add text
        mock_ocr.set_regions([TextRegion("BUTTER", 0.95, 0.2, 0.2, 0.2, 0.1)])
        self.assertFalse(engine.update(solid_frame(80), now=0.2))
        self.assertEqual(engine.state, ScanState.TEXT_DETECTED)

        # 3. Second check -> capture
        self.assertTrue(engine.update(solid_frame(80), now=0.4))
        self.assertEqual(engine.state, ScanState.CAPTURED_WAITING_FOR_REMOVAL)


# ===========================================================================
# STEP 4 INTEGRATION TEST: Apple Vision Native OCR Engine
# ===========================================================================

class TestAppleVisionIntegration(unittest.TestCase):
    """Verifies that native Apple Vision OCR executes and recognizes text on macOS."""

    def test_apple_vision_text_detection(self):
        try:
            ocr = AppleVisionOCREngine()
        except Exception as e:
            self.skipTest(f"Apple Vision OCR binary not available: {e}")

        # Render test image with clear text
        img = make_frame_with_text("ORGANIC MILK 1L")
        result = ocr.detect_text(img)
        ocr.shutdown()

        self.assertIsNone(result.error)
        self.assertTrue(result.has_text, "Apple Vision should detect text in synthetic image")
        detected_texts = [r.text.upper() for r in result.regions]
        self.assertTrue(
            any("MILK" in t or "ORGANIC" in t for t in detected_texts),
            f"Expected 'MILK' or 'ORGANIC' in detected texts: {detected_texts}"
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    try:
        import test_gemini_analyzer
        suite.addTests(loader.loadTestsFromModule(test_gemini_analyzer))
    except ImportError:
        pass
    try:
        import test_inventory
        suite.addTests(loader.loadTestsFromModule(test_inventory))
    except ImportError:
        pass
    try:
        import test_stability_and_dates
        suite.addTests(loader.loadTestsFromModule(test_stability_and_dates))
    except ImportError:
        pass
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
