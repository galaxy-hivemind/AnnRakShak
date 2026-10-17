"""
AnnaRakshak — OCR Engine Abstraction Layer
==========================================
Encapsulates text detection behind a uniform interface (BaseOCREngine).

Engines provided:
  1. AppleVisionOCREngine: Uses macOS native Vision framework via compiled
     mac_vision_ocr Swift binary. Zero external pip dependencies, runs locally
     on Apple Silicon Neural Engine.
  2. MockOCREngine: Deterministic mock for unit testing and offline simulation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("AnnaRakshak.OCR")

PROJECT_DIR = Path(__file__).parent
SWIFT_SOURCE = PROJECT_DIR / "mac_vision_ocr.swift"
SWIFT_BINARY = PROJECT_DIR / "mac_vision_ocr"


@dataclass
class TextRegion:
    """Represents a single recognized text bounding box with normalized coordinates [0, 1]."""
    text: str
    confidence: float
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)


@dataclass
class OCRResult:
    """Container for the output of an OCR detection pass."""
    regions: list[TextRegion] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str | None = None
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def has_text(self) -> bool:
        return len(self.regions) > 0

    @property
    def top_text(self) -> str:
        if not self.regions:
            return ""
        # Sort by confidence descending
        sorted_regs = sorted(self.regions, key=lambda r: r.confidence, reverse=True)
        return sorted_regs[0].text

    @property
    def summary_text(self) -> str:
        if not self.regions:
            return ""
        snippets = [f"{r.text} ({r.confidence:.2f})" for r in self.regions[:2]]
        return " | ".join(snippets)


class BaseOCREngine(ABC):
    """Abstract interface for local text detection."""

    @abstractmethod
    def detect_text(self, frame_bgr: np.ndarray) -> OCRResult:
        """Run OCR on a single BGR frame."""
        pass

    def shutdown(self) -> None:
        """Release any persistent subprocesses or resources."""
        pass


class AppleVisionOCREngine(BaseOCREngine):
    """
    Native macOS Vision text-recognition engine.
    Uses Apple's VNRecognizeTextRequest via compiled Swift helper.
    """

    def __init__(self, binary_path: Path | str | None = None, use_streaming: bool = True) -> None:
        self.binary_path = Path(binary_path) if binary_path else SWIFT_BINARY
        self.use_streaming = use_streaming
        self._proc: subprocess.Popen[str] | None = None
        self._temp_dir = tempfile.mkdtemp(prefix="annarakshak_ocr_")
        self._temp_img = os.path.join(self._temp_dir, "frame.jpg")

        self._ensure_binary()
        if self.use_streaming:
            self._start_process()

    def _ensure_binary(self) -> None:
        """Verify binary exists, or compile from Swift source if swiftc is available."""
        if self.binary_path.exists() and os.access(self.binary_path, os.X_OK):
            return

        if not SWIFT_SOURCE.exists():
            raise FileNotFoundError(f"Swift source not found: {SWIFT_SOURCE}")

        swiftc = shutil.which("swiftc")
        if not swiftc:
            raise RuntimeError(
                "Apple Vision OCR binary missing and 'swiftc' compiler not found. "
                "Install Xcode Command Line Tools or compile mac_vision_ocr manually."
            )

        cmd = [swiftc, "-O", str(SWIFT_SOURCE), "-o", str(self.binary_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to compile mac_vision_ocr: {res.stderr}")

        os.chmod(self.binary_path, 0o755)

    def _start_process(self) -> None:
        """Start persistent mac_vision_ocr --stdin process."""
        try:
            self._proc = subprocess.Popen(
                [str(self.binary_path), "--stdin"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            logger.warning("Could not start streaming OCR process: %s. Falling back to standalone.", e)
            self._proc = None

    def detect_text(self, frame_bgr: np.ndarray) -> OCRResult:
        if frame_bgr is None or frame_bgr.size == 0:
            return OCRResult(error="Empty frame")

        t0 = time.monotonic()

        try:
            # Write frame to temp file
            ok = cv2.imwrite(self._temp_img, frame_bgr)
            if not ok:
                return OCRResult(error="Failed to encode frame as JPEG")

            raw_json = ""

            if self.use_streaming and self._proc and self._proc.poll() is None:
                try:
                    assert self._proc.stdin is not None
                    assert self._proc.stdout is not None
                    self._proc.stdin.write(f"{self._temp_img}\n")
                    self._proc.stdin.flush()
                    raw_json = self._proc.stdout.readline()
                except Exception as e:
                    logger.warning("Streaming OCR failed, restarting process: %s", e)
                    self._start_process()

            # Standalone fallback if streaming was unavailable or failed
            if not raw_json.strip():
                run_res = subprocess.run(
                    [str(self.binary_path), self._temp_img],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                if run_res.returncode != 0:
                    return OCRResult(
                        error=f"mac_vision_ocr error: {run_res.stderr.strip()}",
                        latency_ms=(time.monotonic() - t0) * 1000.0,
                    )
                raw_json = run_res.stdout

            data = json.loads(raw_json)
            regions = [
                TextRegion(
                    text=item["text"],
                    confidence=float(item.get("confidence", 0.0)),
                    x=float(item.get("x", 0.0)),
                    y=float(item.get("y", 0.0)),
                    width=float(item.get("width", 0.0)),
                    height=float(item.get("height", 0.0)),
                )
                for item in data
            ]

            latency_ms = (time.monotonic() - t0) * 1000.0
            return OCRResult(regions=regions, latency_ms=latency_ms)

        except Exception as e:
            return OCRResult(
                error=f"OCR execution failed: {e}",
                latency_ms=(time.monotonic() - t0) * 1000.0,
            )

    def shutdown(self) -> None:
        if self._proc:
            try:
                if self._proc.poll() is None:
                    if self._proc.stdin and not self._proc.stdin.closed:
                        try:
                            self._proc.stdin.write("EXIT\n")
                            self._proc.stdin.flush()
                        except Exception:
                            pass
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=1.0)
                    except Exception:
                        self._proc.kill()
            except Exception:
                pass
            finally:
                for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                    if pipe and not getattr(pipe, "closed", True):
                        try:
                            pipe.close()
                        except Exception:
                            pass
                self._proc = None

        try:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        except Exception:
            pass


class MockOCREngine(BaseOCREngine):
    """Deterministic mock OCR engine for unit testing and offline simulation."""

    def __init__(
        self,
        mock_regions: list[TextRegion] | None = None,
        mock_error: str | None = None,
        latency_ms: float = 5.0,
    ) -> None:
        self.mock_regions: list[TextRegion] = mock_regions or []
        self.mock_error: str | None = mock_error
        self.latency_ms: float = latency_ms

    def set_regions(self, regions: list[TextRegion]) -> None:
        self.mock_regions = regions

    def set_error(self, error: str | None) -> None:
        self.mock_error = error

    def clear(self) -> None:
        self.mock_regions = []
        self.mock_error = None

    def detect_text(self, frame_bgr: np.ndarray) -> OCRResult:
        if self.mock_error:
            return OCRResult(error=self.mock_error, latency_ms=self.latency_ms)
        return OCRResult(
            regions=list(self.mock_regions),
            latency_ms=self.latency_ms,
        )
