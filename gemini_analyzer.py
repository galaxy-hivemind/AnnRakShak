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
import threading
import time
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Load environment variables from .env if present
load_dotenv()

logger = logging.getLogger("AnnaRakshak.Gemini")

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

SYSTEM_INSTRUCTION = """\
You are an expert food safety packaging analyst for AnnaRakshak.
Your task is to analyze images of food packages and extract product details and printed dates with strict precision and zero hallucinations.

STRICT EXTRACTION RULES:
1. GROUNDING: Only report text and dates that are clearly and visibly printed on the package in the image. NEVER guess, invent, or assume typical shelf life.
2. DATE CLASSIFICATION:
   - 'expiry' or 'use_by': The date after which food is considered unsafe.
   - 'best_before': Quality guarantee date. Do NOT treat best before as interchangeable with expiry/use by.
   - 'manufacturing' or 'packed_on': The date the item was produced or packed. NEVER report this as the expiry date!
   - 'unknown': A date with no legible preceding label or clear indicator.
3. BATCH & LOT NUMBERS: Alphanumeric lot numbers, batch codes (e.g. 'L2410', 'B12'), and barcodes are NOT dates.
4. INCOMPLETE DATES:
   - If only Month and Year are printed (e.g. 'OCT 2026' or '10/26'), do NOT invent an arbitrary day (like '01' or '31'). Set normalized_date = null and explain in evidence.
   - If Day, Month, and Year are clearly printed, format normalized_date as 'YYYY-MM-DD'.
5. AMBIGUOUS OR CONFLICTING DATES:
   - If print is blurry, faint, smeared, or has multiple conflicting dates, list all candidates and set needs_review = true with a concise review_reason.
   - Only set selected_expiry_date (YYYY-MM-DD) if supported by clear, unambiguous evidence of an expiry or use-by date.
6. NON-FOOD OR UNREADABLE:
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

        return result


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
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model_name or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self._injected_client = client

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

    def analyze_image(self, image_path: Path | str) -> FoodAnalysisResult:
        """
        Analyze a captured food package image.
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
            try:
                image_bytes = path.read_bytes()

                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=FoodAnalysisResult,
                    temperature=0.1,
                    system_instruction=SYSTEM_INSTRUCTION,
                )

                prompt = (
                    "Carefully inspect this food package image. "
                    "Identify the product name, brand, category, and all printed dates. "
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
                err_msg = str(e)
                # If model is unavailable (503 / 404), log warning and attempt fallback model
                is_transient = any(k in err_msg for k in ("503", "UNAVAILABLE", "high demand", "404", "NOT_FOUND"))
                if is_transient and current_model != models_to_try[-1]:
                    logger.warning("Model '%s' unavailable (%s). Falling back to next model...", current_model, err_msg.split('\n')[0])
                    continue
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

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                image_path = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            with self._lock:
                self._is_analyzing = True
                self._current_status = "ANALYZING WITH GEMINI"

            try:
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
    print(f"Date Count   : {len(result.date_candidates)} candidate(s) found")
    for i, c in enumerate(result.date_candidates, 1):
        print(f"  [{i}] '{c.raw_text}' -> Type: {c.date_type}, Norm: {c.normalized_date}, Conf: {c.confidence:.2f}")
        print(f"      Evidence: {c.evidence}")
    print("=" * 65)

    return 0 if result.analysis_status != "error" else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
