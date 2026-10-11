"""
AnnaRakshak — Gemini Food Packaging & Expiry Date Analyzer
===========================================================
Integrates Google's official `google-genai` SDK to perform structured
food-product identification and strict expiry-date interpretation on
captured images.

Strict Date Rules:
  1. GROUNDING: Only report dates clearly visible in the image; never hallucinate.
  2. DISTINCTION: Distinguish 'expiry'/'use_by' from 'best_before' and 'manufacturing'.
     Manufacturing and packed dates must NEVER be treated as expiry dates.
  3. NO INFERRED DAYS: If only Month and Year are printed (e.g. OCT 2026),
     do NOT invent a day (01 or 31). normalized_date must be None.
  4. AMBIGUITY: If multiple dates exist, or text is blurry/obstructed/confusing,
     set needs_review = True with a clear review_reason.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import random
import re
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
import httpx
from pydantic import BaseModel, Field

# Load environment variables from .env if present
load_dotenv()

logger = logging.getLogger("AnnaRakshak.Gemini")

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Retry defaults
DEFAULT_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "3"))
DEFAULT_INITIAL_BACKOFF = float(os.environ.get("GEMINI_INITIAL_BACKOFF", "1.0"))
DEFAULT_BACKOFF_FACTOR = float(os.environ.get("GEMINI_BACKOFF_FACTOR", "2.0"))
DEFAULT_MAX_BACKOFF = float(os.environ.get("GEMINI_MAX_BACKOFF", "8.0"))

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404}


def is_retryable_exception(exc: Exception) -> tuple[bool, str]:
    """
    Classify whether an exception is transient and safe to retry.
    Returns (is_retryable, failure_reason_category).
    Guarantees secrets/API keys are never returned as part of the reason.
    """
    # 1. SSL & Connection/Socket issues (e.g. UNEXPECTED_EOF_WHILE_READING)
    if isinstance(exc, (ssl.SSLError, ConnectionError, socket.timeout, socket.gaierror)):
        return True, "SSL/Network connection error"

    # 2. HTTPX network/timeout errors
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True, "HTTP network/timeout error"

    # 3. Google GenAI APIError / ServerError / ClientError
    status_code = getattr(exc, "code", None)
    if status_code is not None:
        try:
            status_code = int(status_code)
        except (ValueError, TypeError):
            status_code = None

    if status_code in NON_RETRYABLE_STATUS_CODES:
        return False, f"Permanent HTTP error ({status_code})"

    if status_code in TRANSIENT_STATUS_CODES:
        return True, f"HTTP transient status code ({status_code})"

    # 4. Inspect string patterns safely without leaking tokens
    msg = str(exc)
    msg_lower = msg.lower()

    if any(k in msg_lower for k in ("unauthenticated", "api_key_invalid", "permission_denied", "forbidden", "not found", "bad request")):
        return False, "Permanent client error or invalid authentication"

    if any(k in msg_lower for k in (
        "unexpected_eof_while_reading",
        "eof occurred",
        "connection reset",
        "connection broken",
        "broken pipe",
        "timeout",
        "timed out",
        "resource_exhausted",
        "quota exceeded",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "unavailable",
        "high demand",
    )):
        return True, "Transient network, timeout, or rate-limit error"

    return False, "Non-retryable application error"


def parse_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After header or server retry delay advice if present."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        headers = getattr(resp, "headers", None)
        if headers and hasattr(headers, "get"):
            ra = headers.get("retry-after") or headers.get("Retry-After")
            if ra:
                try:
                    delay = float(ra)
                    if delay > 0:
                        return min(delay, 60.0)
                except ValueError:
                    pass
    return None


SYSTEM_INSTRUCTION = """\
You are an expert food safety packaging analyst for AnnaRakshak.
Your task is to analyze images of food packages and extract product details and printed dates with strict precision and zero hallucinations.

STRICT EXTRACTION RULES:
1. THOROUGH VISUAL EXAMINATION:
   - Carefully inspect the ENTIRE package visible in the frame, especially small-print date areas:
     box top flap, bottom flap, bottle neck, cap/lid, crimped edges, back/side label panels,
     and ink-jet or dot-matrix printed date codes.
   - Extract EVERY visibly printed date and all nearby label text into 'date_candidates'.
   - Preserve the exact printed characters in 'raw_text' (e.g. '04/2026', 'EXP 03/2028', '15-OCT-2026').
   - Ground 'evidence' in nearby printed words (e.g. 'Printed next to Exp.: on top label panel').

2. DATE CLASSIFICATION & INDIAN PACKAGING TERMS:
   - 'manufacturing' or 'packed_on': Marked with Mfg, MFD, Mfg Date, Manufactured, PKD, Packed, Packaging Date, Batch Mfd.
     CRITICAL: NEVER classify a manufacturing or packing date as an expiry date!
   - 'expiry' or 'use_by': Marked with EXP, Exp Date, Expiry, Use By, UB, Expires, Valid Till.
   - 'best_before': Marked with Best Before, BB, Best By, Best before X months from packaging.
     Do NOT treat best-before as interchangeable with explicit expiry/use-by.
   - 'unknown': A date with no legible preceding label or clear indicator.

3. DATE FORMATS & AMBIGUITY:
   - Recognize common date formats: DD/MM/YY, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, MM/YYYY, MM-YYYY, DD MMM YYYY, MMM YYYY.
   - If Day, Month, and Year are clearly legible, set normalized_date to 'YYYY-MM-DD'.
   - If only Month and Year are printed (e.g. '03/2028' or 'OCT 2026'): do NOT guess or invent an arbitrary day (like 01 or 31).
     Set normalized_date = null and preserve the exact 'MM/YYYY' string in raw_text.
   - Treat ambiguous numeric dates conservatively: if day vs month is ambiguous, set normalized_date = null and list in date_candidates.
   - Alphanumeric lot numbers, batch codes (e.g. 'BD0114', 'L2410'), MRP, and barcodes are NOT dates.

4. SELECTION OF EXPIRY DATE:
   - Set 'selected_expiry_date' (YYYY-MM-DD) ONLY when supported by clear, unambiguous evidence of an explicit expiry or use-by date with full year, month, and day.
   - If only manufacturing dates, only best-before dates, or only month/year dates exist: set selected_expiry_date = null.

5. REVIEW & QUALITY FLAGS:
   - If no dates are visible on the presented portion of the package, set needs_review = true, review_reason = 'No printed expiry or manufacturing dates visible on the presented portion of the package; date panel may be on another side or out of frame.'
   - If the label or date area is blurry, faint, smeared, or small-print is illegible, set analysis_status = 'needs_review', needs_review = true, and explain clearly in review_reason.
   - If the object is not a food product, set analysis_status = 'not_a_food_product' and needs_review = true.
   - If no text or label is readable, set analysis_status = 'unreadable' and needs_review = true.
"""


# ---------------------------------------------------------------------------
# Structured Output Schema (Pydantic)
# ---------------------------------------------------------------------------

class DateCandidate(BaseModel):
    """Represents a single date marking found printed on the packaging."""
    raw_text: str = Field(description="Exact date text printed on the label as seen in the image.")
    date_type: Literal["expiry", "use_by", "best_before", "manufacturing", "packed_on", "unknown"] = Field(
        description="Type of date printed on the packaging."
    )
    normalized_date: str | None = Field(
        default=None,
        description="ISO format YYYY-MM-DD if explicitly and unambiguously readable; null if day is missing or ambiguous.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence score between 0.0 and 1.0 reflecting clarity of this date.",
    )
    evidence: str = Field(description="Brief explanation grounded strictly in visible label text.")


class FoodAnalysisResult(BaseModel):
    """Comprehensive structured analysis result from Gemini."""
    product_name: str | None = Field(default=None, description="Identifiable product name, or null.")
    brand: str | None = Field(default=None, description="Brand name or manufacturer, or null.")
    food_category: str | None = Field(
        default=None,
        description="Category such as Dairy, Bakery, Beverage, Snacks, Produce, Grains, Canned Goods, Condiments, or null.",
    )
    date_candidates: list[DateCandidate] = Field(
        default_factory=list,
        description="List of all date candidates identified on the package.",
    )
    selected_expiry_date: str | None = Field(
        default=None,
        description="ISO YYYY-MM-DD format expiry/use-by date only if supported by unambiguous evidence; otherwise null.",
    )
    analysis_status: Literal["success", "needs_review", "unreadable", "not_a_food_product", "error"] = Field(
        description="Overall status of the analysis."
    )
    needs_review: bool = Field(description="True if human verification is required due to ambiguity, blurriness, or errors.")
    review_reason: str | None = Field(default=None, description="Concise explanation when needs_review is true, or null.")

    @property
    def summary(self) -> str:
        """One-line summary for preview overlays."""
        if self.analysis_status == "error":
            return f"Error: {self.review_reason or 'Analysis failed'}"
        name = self.product_name or "Unknown Item"
        brand = f" ({self.brand})" if self.brand else ""
        if self.selected_expiry_date:
            flag = " [Review Needed]" if self.needs_review else ""
            return f"{name}{brand} — Exp: {self.selected_expiry_date}{flag}"
        if self.needs_review:
            reason = self.review_reason or "Review required"
            return f"{name}{brand} — Needs Review: {reason}"
        return f"{name}{brand} — Status: {self.analysis_status}"

    @classmethod
    def post_validate(cls, result: FoodAnalysisResult) -> FoodAnalysisResult:
        """
        Enforce strict programmatic post-validation on analysis results:
        1. Validate ISO format YYYY-MM-DD for selected_expiry_date.
        2. Ensure manufacturing or packed_on dates are NEVER selected as expiry dates.
        3. If raw text lacks day digits (e.g. 'OCT 2026'), normalized_date must be None.
        4. If multiple conflicting expiry dates exist, enforce needs_review = True.
        """
        import re

        # Rule 1: Validate selected_expiry_date format
        if result.selected_expiry_date:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", result.selected_expiry_date):
                result.selected_expiry_date = None
                result.needs_review = True
                result.review_reason = (
                    result.review_reason
                    or "Selected expiry date does not follow strict YYYY-MM-DD format."
                )

        # Rule 2: Ensure manufacturing / packed dates are NEVER selected as expiry
        if result.selected_expiry_date:
            mfg_matches = [
                c for c in result.date_candidates
                if c.date_type in ("manufacturing", "packed_on")
                and c.normalized_date == result.selected_expiry_date
            ]
            exp_matches = [
                c for c in result.date_candidates
                if c.date_type in ("expiry", "use_by")
                and c.normalized_date == result.selected_expiry_date
            ]
            if mfg_matches and not exp_matches:
                result.selected_expiry_date = None
                result.needs_review = True
                result.review_reason = "Manufacturing or packing date was identified; not an expiry date."

        # Rule 3: Check candidate dates format
        for c in result.date_candidates:
            if c.normalized_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", c.normalized_date):
                c.normalized_date = None
                result.needs_review = True
                result.review_reason = (
                    result.review_reason
                    or "Date candidate does not have a valid YYYY-MM-DD date."
                )

        # Rule 4: If multiple conflicting expiry candidates exist
        exp_dates = {
            c.normalized_date for c in result.date_candidates
            if c.date_type in ("expiry", "use_by") and c.normalized_date is not None
        }
        if len(exp_dates) > 1:
            result.needs_review = True
            result.selected_expiry_date = None
            result.review_reason = (
                result.review_reason
                or f"Multiple conflicting expiry dates found ({', '.join(sorted(exp_dates))})."
            )

        # Rule 5: If no unambiguous expiry date is selected, review is required
        if result.selected_expiry_date is None:
            result.needs_review = True
            if not result.review_reason:
                if len(result.date_candidates) == 0:
                    result.review_reason = "No printed expiry or date markings detected on visible packaging."
                else:
                    has_exp = any(c.date_type in ("expiry", "use_by") for c in result.date_candidates)
                    has_bb = any(c.date_type == "best_before" for c in result.date_candidates)
                    has_mfg = any(c.date_type in ("manufacturing", "packed_on") for c in result.date_candidates)
                    if has_exp:
                        result.review_reason = "Expiry date candidate detected but lacks precise full day or requires manual confirmation."
                    elif has_bb and not has_mfg:
                        result.review_reason = "Best-before date detected; requires verification for safety expiry."
                    elif has_mfg and not has_bb:
                        result.review_reason = "Only manufacturing or packing date detected; no expiry date visible."
                    else:
                        result.review_reason = "Date candidates detected but require manual confirmation."

        return result


def format_date_candidates_review(result: FoodAnalysisResult) -> str:
    """
    Format a clean, readable date inspection block for terminal review.
    Format:
      Date candidates:
      • Candidate 1:
        - Original text: exact text read from the image
        - Type: expiry / use_by / best_before / manufacturing / packed_on / unknown
        - Normalized date: ISO date or unavailable
        - Confidence: model-reported score
        - Evidence: nearby printed label or reason for uncertainty
    """
    lines = ["Date candidates:"]
    if not result.date_candidates:
        lines.append("  (None detected on visible packaging)")
    else:
        for idx, c in enumerate(result.date_candidates, 1):
            norm_str = c.normalized_date if c.normalized_date else "unavailable"
            lines.append(f"  • Candidate {idx}:")
            lines.append(f"    - Original text: {c.raw_text}")
            lines.append(f"    - Type: {c.date_type}")
            lines.append(f"    - Normalized date: {norm_str}")
            lines.append(f"    - Confidence: {c.confidence:.2f}")
            lines.append(f"    - Evidence: {c.evidence}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini Analyzer
# ---------------------------------------------------------------------------

class GeminiAnalyzer:
    """
    Analyzes captured food package images using Google's google-genai SDK.
    Supports dependency injection for mocking in unit tests.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        client: Any | None = None,
        max_retries: int | None = None,
        initial_backoff: float | None = None,
        backoff_factor: float | None = None,
        max_backoff: float | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model_name or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self._injected_client = client
        self.max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
        self.initial_backoff = initial_backoff if initial_backoff is not None else DEFAULT_INITIAL_BACKOFF
        self.backoff_factor = backoff_factor if backoff_factor is not None else DEFAULT_BACKOFF_FACTOR
        self.max_backoff = max_backoff if max_backoff is not None else DEFAULT_MAX_BACKOFF
        self._sleeper = sleeper or time.sleep

    @property
    def client(self) -> genai.Client | None:
        """Lazy-loaded or injected GenAI client."""
        if self._injected_client is not None:
            return self._injected_client
        if not self.api_key:
            return None
        try:
            return genai.Client(api_key=self.api_key)
        except Exception as e:
            logger.error("Failed to initialize genai.Client: %s", e)
            return None

    @staticmethod
    def validate_image_file(image_path: Path | str) -> tuple[bool, str | None]:
        """Validate that the image path exists, is a file, and has a supported extension."""
        path = Path(image_path)
        if not path.exists():
            return False, f"Image file not found: {path}"
        if not path.is_file():
            return False, f"Path is not a regular file: {path}"
        if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            return False, f"Unsupported image extension '{path.suffix}'. Supported: {SUPPORTED_IMAGE_EXTENSIONS}"
        if path.stat().st_size == 0:
            return False, f"Image file is empty (0 bytes): {path}"
        return True, None

    def analyze_image(
        self,
        image_path: Path | str,
        on_retry: Callable[[int, int, float, str], None] | None = None,
    ) -> FoodAnalysisResult:
        """
        Analyze a captured food package image.
        Implements bounded exponential backoff with full jitter for transient errors.
        Respects server Retry-After guidance when provided.
        Returns a validated FoodAnalysisResult without raising exceptions.
        """
        path = Path(image_path)

        # Validate file
        valid, err = self.validate_image_file(path)
        if not valid:
            return FoodAnalysisResult(
                analysis_status="error",
                needs_review=True,
                review_reason=err or "Invalid image file",
            )

        # Check API client
        client = self.client
        if client is None:
            return FoodAnalysisResult(
                analysis_status="error",
                needs_review=True,
                review_reason="GEMINI_API_KEY is not configured. Set GEMINI_API_KEY in .env or environment.",
            )

        # Determine MIME type
        ext = path.suffix.lower()
        mime_type = "image/png" if ext == ".png" else "image/jpeg"

        models_to_try = [self.model_name]
        for fb in FALLBACK_MODELS:
            if fb not in models_to_try:
                models_to_try.append(fb)

        last_err: Exception | None = None

        for current_model in models_to_try:
            model_exhausted = False
            for attempt in range(self.max_retries + 1):
                try:
                    image_bytes = path.read_bytes()

                    config = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=FoodAnalysisResult,
                        temperature=0.1,
                        system_instruction=SYSTEM_INSTRUCTION,
                    )

                    prompt = (
                        "Carefully inspect this food package image across all visible areas (including top, bottom, neck, cap, edges, and small print). "
                        "Identify the product name, brand, food category, and ALL printed dates (manufacturing, packing, expiry, use-by, best-before). "
                        "Extract each printed date into date_candidates with exact raw_text, accurate date_type, and nearby evidence. "
                        "Follow all strict date interpretation rules without hallucination."
                    )

                    response = client.models.generate_content(
                        model=current_model,
                        contents=[
                            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                            prompt,
                        ],
                        config=config,
                    )

                    if hasattr(response, "parsed") and isinstance(response.parsed, FoodAnalysisResult):
                        return FoodAnalysisResult.post_validate(response.parsed)

                    if hasattr(response, "text") and response.text:
                        res = FoodAnalysisResult.model_validate_json(response.text)
                        return FoodAnalysisResult.post_validate(res)

                    return FoodAnalysisResult(
                        analysis_status="error",
                        needs_review=True,
                        review_reason="Empty response received from Gemini API",
                    )

                except Exception as e:
                    last_err = e
                    retryable, reason_cat = is_retryable_exception(e)

                    # Check for model not found / unavailable where switching model is preferred
                    err_str = str(e)
                    is_model_unavailable = any(k in err_str for k in ("404", "NOT_FOUND", "503", "UNAVAILABLE", "high demand"))
                    if is_model_unavailable and current_model != models_to_try[-1]:
                        logger.warning(
                            "Model '%s' unavailable (%s). Switching to fallback model...",
                            current_model, err_str.split("\n")[0]
                        )
                        model_exhausted = True
                        break

                    if not retryable:
                        # Permanent error (e.g., auth, bad request, invalid API key) — do not retry
                        logger.warning(
                            "Non-retryable error encountered for model '%s': %s",
                            current_model, reason_cat
                        )
                        break

                    # If we have reached the maximum retry count for this model
                    if attempt >= self.max_retries:
                        logger.warning(
                            "Retry budget exhausted (%d/%d retries) on model '%s' for reason: %s",
                            attempt, self.max_retries, current_model, reason_cat
                        )
                        break

                    # Compute backoff with full jitter and Retry-After header consideration
                    server_delay = parse_retry_after(e)
                    if server_delay is not None:
                        delay = min(server_delay, self.max_backoff)
                    else:
                        base_delay = min(self.initial_backoff * (self.backoff_factor ** attempt), self.max_backoff)
                        delay = random.uniform(base_delay * 0.5, base_delay * 1.5)

                    logger.warning(
                        "Gemini request transient failure (attempt %d/%d, model '%s', delay: %.2fs): %s",
                        attempt + 1, self.max_retries, current_model, delay, reason_cat
                    )

                    if on_retry:
                        try:
                            on_retry(attempt + 1, self.max_retries, delay, reason_cat)
                        except Exception:
                            pass

                    self._sleeper(delay)

            if not model_exhausted:
                # If we broke out without exhausting retries/models (and didn't return), break models loop
                break

        err_msg = str(last_err) if last_err else "Unknown error"
        logger.error("Gemini API call failed: %s", err_msg)
        # Differentiate common failure modes
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            reason = "Gemini API rate limit or quota exceeded. Please try again later."
        elif "UNAUTHENTICATED" in err_msg or "API_KEY_INVALID" in err_msg or "403" in err_msg:
            reason = "Gemini API key is invalid or unauthorized."
        elif "503" in err_msg or "UNAVAILABLE" in err_msg:
            reason = "Gemini API is temporarily experiencing high demand (503). Please retry in a few seconds."
        elif "timeout" in err_msg.lower():
            reason = "Gemini API request timed out."
        elif any(k in err_msg.lower() for k in ("unexpected_eof_while_reading", "eof occurred in violation of protocol")):
            reason = "Gemini API SSL/connection interrupted (unexpected EOF)."
        else:
            reason = f"Gemini API request failed: {err_msg}"

        return FoodAnalysisResult(
            analysis_status="error",
            needs_review=True,
            review_reason=reason,
        )



# ---------------------------------------------------------------------------
# Asynchronous Background Gemini Analysis Worker
# ---------------------------------------------------------------------------

class AsyncGeminiWorker:
    """
    Non-blocking background worker that submits captures to Gemini without
    blocking the camera preview loop.
    """

    def __init__(self, analyzer: GeminiAnalyzer) -> None:
        self.analyzer = analyzer
        self._queue: queue.Queue[str] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._latest_result: FoodAnalysisResult | None = None
        self._latest_image_path: str = ""
        self._current_status: str = "IDLE"
        self._is_analyzing = False

        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="GeminiWorker")
        self._thread.start()

    @property
    def status(self) -> str:
        with self._lock:
            return self._current_status

    @property
    def latest_result(self) -> FoodAnalysisResult | None:
        with self._lock:
            return self._latest_result

    @property
    def latest_image_path(self) -> str:
        with self._lock:
            return self._latest_image_path

    @property
    def is_analyzing(self) -> bool:
        with self._lock:
            return self._is_analyzing

    def submit_capture(self, image_path: str) -> bool:
        """
        Submit a captured image path for Gemini analysis.
        Returns True if accepted into the queue, False if busy.
        """
        with self._lock:
            if self._is_analyzing or not self._queue.empty():
                return False
            self._current_status = "IMAGE CAPTURED"
            self._latest_image_path = image_path

        try:
            self._queue.put_nowait(image_path)
            return True
        except queue.Full:
            return False

    def reanalyze_image(self, image_path: str) -> bool:
        """
        Reanalyze a specific existing image capture.
        Returns True if accepted into worker queue, False if busy.
        """
        return self.submit_capture(image_path)

    def _worker_loop(self) -> None:
        def on_retry(attempt: int, max_retries: int, delay: float, reason_cat: str) -> None:
            with self._lock:
                self._current_status = f"RETRYING ({attempt}/{max_retries})"

        while not self._stop_event.is_set():
            try:
                image_path = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            with self._lock:
                self._is_analyzing = True
                self._current_status = "ANALYZING WITH GEMINI"

            try:
                try:
                    result = self.analyzer.analyze_image(image_path, on_retry=on_retry)
                except TypeError:
                    result = self.analyzer.analyze_image(image_path)
            except Exception as e:
                result = FoodAnalysisResult(
                    analysis_status="error",
                    needs_review=True,
                    review_reason=f"Worker exception: {e}",
                )

            with self._lock:
                self._latest_result = result
                self._is_analyzing = False
                if result.analysis_status == "error":
                    self._current_status = "GEMINI REQUEST FAILED"
                elif result.needs_review:
                    self._current_status = "NEEDS MANUAL REVIEW"
                elif result.selected_expiry_date:
                    self._current_status = "EXPIRY DATE FOUND"
                elif result.product_name:
                    self._current_status = "PRODUCT IDENTIFIED"
                else:
                    self._current_status = "ANALYSIS COMPLETE"

            self._queue.task_done()

    def shutdown(self) -> None:
        """Cleanly stop worker thread."""
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)



# ---------------------------------------------------------------------------
# Manual CLI Test Entry Point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AnnaRakshak — Analyze food package image using Gemini API."
    )
    parser.add_argument(
        "--image", type=str, required=True,
        help="Path to saved image file to analyze.",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help=f"Gemini model identifier (default: {DEFAULT_MODEL}).",
    )
    args = parser.parse_args()

    analyzer = GeminiAnalyzer(model_name=args.model)

    print("=" * 65)
    print("AnnaRakshak — Gemini Food Packaging Analysis")
    print("=" * 65)
    print(f"Target Image : {args.image}")
    print(f"Gemini Model : {analyzer.model_name}")
    print(f"API Key Set  : {bool(analyzer.api_key)}")
    print("-" * 65)

    t0 = time.monotonic()
    result = analyzer.analyze_image(args.image)
    duration = time.monotonic() - t0

    print(f"\nResponse received in {duration:.2f}s:\n")
    print(result.model_dump_json(indent=2))
    print("\n" + "=" * 65)
    print("HUMAN READABLE SUMMARY:")
    print("-" * 65)
    print(f"Product Name : {result.product_name or 'N/A'}")
    print(f"Brand        : {result.brand or 'N/A'}")
    print(f"Category     : {result.food_category or 'N/A'}")
    print(f"Status       : {result.analysis_status.upper()}")
    print(f"Needs Review : {result.needs_review}")
    if result.review_reason:
        print(f"Review Reason: {result.review_reason}")
    print(f"Expiry Date  : {result.selected_expiry_date or 'None'}")
    print("-" * 65)
    print(format_date_candidates_review(result))
    if result.needs_review:
        print("-" * 65)
        print(f"Original image preserved at: {args.image}")
    print("=" * 65)

    return 0 if result.analysis_status != "error" else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
