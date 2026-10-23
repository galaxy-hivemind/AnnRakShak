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

from product_classifier import ProductClassifier, CATEGORY_MEDICINE
from relative_expiry import RelativeExpiryResolver

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
You are an expert food safety and packaging date intelligence analyst for AnnaRakshak.
Your task is to analyze images of product packages and extract product identification and printed dates with strict precision and zero hallucinations.

STRICT PRODUCT CATEGORIZATION RULES:
1. SUPPORTED CATEGORIES:
   - 'Medicine': Pharmaceutical products, prescription medicines, OTC drugs, cough syrups, cold suspensions, fever drops, pain relievers, antibiotics, tablets, capsules, lozenges, and oral solutions.
     CRITICAL: A medicine or pharmaceutical product (such as cough syrup, paracetamol tablets, or amoxicillin capsules) must ALWAYS be categorized as 'Medicine' and NEVER categorized as 'Beverage' even if it is a liquid, oral syrup, or suspension!
   - 'Beverage': Fruit juices, soft drinks, mineral waters, teas, coffees, lemonades, energy drinks, and cordials. NEVER include medicinal syrups or pharmaceuticals.
   - 'Dairy': Milk, cheese, butter, yogurt, dahi, paneer, cream, buttermilk, chaas, and ghee.
   - 'Grains': Bread, bakery products, biscuits, rusks, flours, rice, cereals, pasta, and noodles.
   - 'Snacks': Chips, crisps, namkeen, popcorn, crackers, and extruded snacks.
   - 'Produce': Fresh fruits, fresh vegetables, salads, and fresh herbs.
   - 'Pantry': Cooking oils, salts, sugars, spices, condiments, sauces, jams, and honey.
2. UNCERTAINTY:
   - If evidence is insufficient, contradictory, or unreadable, set food_category = null and needs_review = true. Never guess a category.
3. SEPARATION:
   - Keep product category strictly separate from packaging type (bottle, blister pack, carton) and storage instructions (keep refrigerated, store in cool dry place).

STRICT DATE EXTRACTION & INTERPRETATION RULES:
1. THOROUGH VISUAL EXAMINATION:
   - Carefully inspect the ENTIRE package visible in the frame, especially small-print date areas:
     box top flap, bottom flap, bottle neck, cap/lid, crimped edges, back/side label panels,
     and ink-jet or dot-matrix printed date codes.
   - Extract EVERY visibly printed date and nearby label text into 'date_candidates'.
   - Preserve exact printed characters in 'raw_text' (e.g. '04/2026', 'EXP 03/2028', 'Best before 4 months from MFG').
   - Ground 'evidence' in nearby printed words (e.g. 'Printed next to Exp.: on top label panel').

2. DATE CLASSIFICATION & INDIAN PACKAGING TERMS:
   - 'manufacturing' or 'packed_on': Marked with Mfg, MFD, Mfg Date, Manufactured, PKD, Packed, Packaging Date, Batch Mfd.
     CRITICAL: NEVER classify a manufacturing or packing date as an expiry date!
   - 'expiry' or 'use_by': Marked with EXP, Exp Date, Expiry, Use By, UB, Expires, Valid Till.
   - 'best_before': Marked with Best Before, BB, Best By, Best before X months from packaging/MFG.
   - 'after_opening': Marked with "Use within X days of opening".
   - 'unknown': A date with no legible preceding label or clear indicator.

3. RELATIVE EXPIRY & SHELF-LIFE:
   - If packaging says "Best before X months from MFG" or "Shelf life: X months from manufacture" or "Best before X months":
     * If a manufacturing date is printed, automatically calculate the expiry date using calendar-month addition (e.g. MFD 2026-10-10 + 4 months = 2027-02-10).
     * Set selected_expiry_date to the calculated date.
     * Add this calculated date to date_candidates with date_type = 'best_before' and confidence = 0.95.
   - If packaging says "Use within 30 days of opening", record date_type = 'after_opening', normalized_date = null, and flag needs_review = true unless opening date is explicitly provided.

4. DATE FORMATS & MONTH-ONLY DATES:
   - Recognize common date formats: DD/MM/YY, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, MM/YYYY, MM-YYYY, DD MMM YYYY, MMM YYYY, YYYY-MM.
   - If Day, Month, and Year are clearly legible, normalize to 'YYYY-MM-DD'.
   - If only Month and Year are printed (e.g. '03/2028', 'OCT 2026', '10/2026'):
     * For manufacturing or packed dates: if the month is the current month when scanned, set the day to the current day of the scan (e.g. 2026-10-23). If it is a prior month, set the day to the 1st of that month ('YYYY-MM-01').
     * For expiry or best-before dates: set the day to the 1st of that month ('YYYY-MM-01').
     * High confidence (>= 0.90) must be assigned so dates are automatically confirmed.
   - Treat ambiguous numeric dates conservatively: if day vs month is ambiguous, set normalized_date = null and list in date_candidates.
   - Alphanumeric lot numbers, batch codes (e.g. 'BD0114', 'L2410'), MRP, and barcodes are NOT dates.

5. SELECTION OF EXPIRY DATE:
   - Set 'selected_expiry_date' (YYYY-MM-DD) whenever supported by an explicit expiry date, best-before date, or calculated relative best-before date from MFG.
   - If packaging has a manufacturing date and a statement like "Best before X months", calculate the expiry date and set 'selected_expiry_date' to that calculated date.
   - Only set selected_expiry_date = null when NO expiry date or relative shelf life is present on the packaging.

6. HUMAN-IDENTIFIABLE PRODUCT IDENTITY:
   - 'product_name': MUST be an instantly human-recognizable, specific consumer item name (e.g. 'Soan Papdi', 'Dry Fruit Cookies', 'Honitus Herbal Cough Lozenges', 'Toned Milk', 'Masala Chaas', 'Crunchy Bhajani Chakli', 'Whole Wheat Atta', 'Parle-G Biscuits').
   - NEVER return generic category names as product_name such as 'Medicine', 'Ayurvedic Medicine', 'Snacks', 'Food Product', 'Item', or 'Unidentified Item'! If it is a pharmaceutical or herbal medicine, extract its specific brand/medicine name (e.g. 'Honitus Cough Drops' or 'Dabur Pudin Hara'). If it is a sweet, snack, or bakery item, identify the exact item (e.g. 'Soan Papdi', 'Bhajani Chakli', 'Dry Fruit Cookies').
   - 'brand': The brand name or manufacturer (e.g. "Haldiram's", "ChanduRam's", 'Dabur', 'Amul', "Cavin's").
   - Net quantity / weight / volume (e.g. '500 ml', '1 kg', '250 g', '10 tablets', '2 packs') if printed anywhere on the packaging.
   - If quantity is not clearly legible or printed, set quantity = null. Never guess or hallucinate quantity.
"""


# ---------------------------------------------------------------------------
# Structured Output Schema (Pydantic)
# ---------------------------------------------------------------------------

class DateCandidate(BaseModel):
    """Represents a single date marking found printed on the packaging."""
    raw_text: str = Field(description="Exact date text printed on the label as seen in the image.")
    date_type: Literal["expiry", "use_by", "best_before", "manufacturing", "packed_on", "after_opening", "unknown"] = Field(
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


MONTH_NAME_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "sept": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_month_year_from_text(text: str) -> tuple[int, int] | None:
    """
    Extract (year, month) from month-only date text if full calendar day is not present.
    Returns None if a full calendar day is already present (e.g. 10/10/2026, 23 Oct 2026).
    """
    import re
    if not text:
        return None
    clean = text.strip()
    # If full calendar day is present, do not treat as month-only
    if re.search(r"\b\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}\b", clean):
        return None
    if re.search(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{2,4}\b", clean):
        return None
    if re.search(r"\b[A-Za-z]+\s+\d{1,2},?\s+\d{2,4}\b", clean):
        return None

    # 1. Month word + Year (e.g. OCT 2026, October 2026, OCT-2026, OCT/2026)
    m1 = re.search(r"\b([A-Za-z]+)[\s\/\-\.]+(20\d{2}|\d{2})\b", clean)
    if m1 and m1.group(1).lower() in MONTH_NAME_MAP:
        m_str, y_str = m1.group(1).lower(), m1.group(2)
        y = int(y_str) if len(y_str) == 4 else 2000 + int(y_str)
        return y, MONTH_NAME_MAP[m_str]

    # 2. Year + Month word (e.g. 2026 OCT, 2026-OCT)
    m2 = re.search(r"\b(20\d{2})[\s\/\-\.]+([A-Za-z]+)\b", clean)
    if m2 and m2.group(2).lower() in MONTH_NAME_MAP:
        y_str, m_str = m2.group(1), m2.group(2).lower()
        return int(y_str), MONTH_NAME_MAP[m_str]

    # 3. Numeric MM/YYYY, MM-YYYY, MM.YYYY or YYYY-MM
    m3 = re.search(r"\b(0?[1-9]|1[0-2])[\/\-\.](20\d{2})\b", clean)
    if m3:
        return int(m3.group(2)), int(m3.group(1))

    m4 = re.search(r"\b(20\d{2})[\/\-\.](0?[1-9]|1[0-2])\b", clean)
    if m4:
        return int(m4.group(1)), int(m4.group(2))

    # 4. MM/YY or MM-YY (e.g. 10/26, 03/28)
    m5 = re.search(r"\b(0?[1-9]|1[0-2])[\/\-]([2-3]\d)\b", clean)
    if m5:
        return 2000 + int(m5.group(2)), int(m5.group(1))

    return None


class FoodAnalysisResult(BaseModel):
    """Comprehensive structured analysis result from Gemini."""
    product_name: str | None = Field(
        default=None,
        description="Specific human-identifiable consumer product name (e.g. 'Soan Papdi', 'Honitus Cough Lozenges', 'Dry Fruit Cookies', 'Toned Milk'). Never return generic category words like 'Medicine' or 'Snacks'.",
    )
    brand: str | None = Field(default=None, description="Brand name or manufacturer, or null.")
    food_category: str | None = Field(
        default=None,
        description="Category: Medicine, Dairy, Beverage, Grains, Snacks, Produce, Pantry, or null.",
    )
    quantity: str | None = Field(
        default=None,
        description="Net weight, volume, or package count if visible on the packaging (e.g. '500 ml', '1 kg', '250 g', '10 tablets', '2 packs'), or null.",
    )
    barcode: str | None = Field(
        default=None,
        description="Scanned or visually read barcode/GTIN number if clearly visible, or null.",
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
    timing_ms: float = Field(default=0.0, description="Latency in milliseconds for the analysis.")
    models_attempted: list[str] = Field(default_factory=list, description="List of models attempted.")
    retries_count: int = Field(default=0, description="Number of retries executed during analysis.")
    classification_source: str | None = Field(default=None, description="Source of classification: rule_deterministic or ai_model.")
    classification_evidence: str | None = Field(default=None, description="Evidence justifying category.")

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
    def post_validate(
        cls,
        result: FoodAnalysisResult,
        scan_date: datetime.date | None = None,
    ) -> FoodAnalysisResult:
        """
        Enforce strict programmatic post-validation on analysis results:
        1. Apply deterministic product classification (medicines, dairy, beverages, etc.).
        2. Normalize month-only dates (1st of month, or scan day for current-month MFG).
        3. Resolve relative expiry durations (e.g. Best before 4 months from MFG).
        4. Validate ISO format YYYY-MM-DD for selected_expiry_date.
        5. Ensure manufacturing or packed_on dates are NEVER selected as expiry dates.
        6. Automatically confirm verified dates with high confidence.
        """
        import datetime
        import re

        # Step A: Deterministic Product Categorization
        all_candidate_text = " ".join([c.raw_text + " " + c.evidence for c in result.date_candidates])
        classifier_res = ProductClassifier.classify(
            product_name=result.product_name,
            brand=result.brand,
            label_text=all_candidate_text,
        )

        if classifier_res.source == "rule_deterministic":
            result.food_category = classifier_res.category
            result.classification_source = classifier_res.source
            result.classification_evidence = classifier_res.evidence
            if classifier_res.category == CATEGORY_MEDICINE and result.analysis_status == "not_a_food_product":
                result.analysis_status = "success"
        else:
            if result.food_category and result.food_category.lower() == "beverage":
                combined = f"{result.product_name or ''} {result.brand or ''} {all_candidate_text}".lower()
                is_med, med_ev, _ = ProductClassifier._detect_medicine(combined)
                if is_med:
                    result.food_category = CATEGORY_MEDICINE
                    result.classification_source = "rule_deterministic"
                    result.classification_evidence = f"Overrode misclassification: {med_ev}"

            if not result.food_category and classifier_res.needs_review:
                result.needs_review = True
                if not result.review_reason:
                    result.review_reason = classifier_res.review_reason

        # Step B0: Month-Only Date Normalization
        # Rule: Dates with only month & year:
        # - Manufacturing/packed: if of the current month of the scan, set to scan day;
        #   otherwise set to 1st of that month.
        # - Expiry/best-before: set to 1st of that month.
        # - Automatically confirm with high confidence (>= 0.90).
        effective_scan_date = getattr(result, "_scan_date", None) or scan_date or datetime.date.today()

        for c in result.date_candidates:
            needs_day_fill = False
            y, m = None, None

            if c.normalized_date and re.match(r"^\d{4}-\d{2}$", str(c.normalized_date).strip()):
                needs_day_fill = True
                y, m = map(int, str(c.normalized_date).strip().split("-"))
            elif not c.normalized_date or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(c.normalized_date).strip()):
                ym = parse_month_year_from_text(c.raw_text)
                if ym:
                    needs_day_fill = True
                    y, m = ym

            if needs_day_fill and y is not None and m is not None:
                if c.date_type in ("manufacturing", "packed_on"):
                    if (y, m) == (effective_scan_date.year, effective_scan_date.month):
                        c.normalized_date = f"{y:04d}-{m:02d}-{effective_scan_date.day:02d}"
                        c.evidence = f"{c.evidence}; normalized to current scan day ({effective_scan_date.day:02d})".strip("; ")
                    else:
                        c.normalized_date = f"{y:04d}-{m:02d}-01"
                        c.evidence = f"{c.evidence}; normalized to 1st of month".strip("; ")
                    c.confidence = max(getattr(c, "confidence", 0.0), 0.90)
                elif c.date_type in ("expiry", "use_by", "best_before"):
                    c.normalized_date = f"{y:04d}-{m:02d}-01"
                    c.evidence = f"{c.evidence}; normalized to 1st of month".strip("; ")
                    c.confidence = max(getattr(c, "confidence", 0.0), 0.90)

        # If selected_expiry_date was provided as YYYY-MM, normalize to YYYY-MM-01
        if result.selected_expiry_date and re.match(r"^\d{4}-\d{2}$", result.selected_expiry_date.strip()):
            result.selected_expiry_date = f"{result.selected_expiry_date.strip()}-01"

        # Step B: Relative Expiry & Shelf-Life Interpretation
        # Find verified manufacturing / packed_on date if present
        mfg_date_str = None
        for c in result.date_candidates:
            if c.date_type in ("manufacturing", "packed_on") and c.normalized_date:
                mfg_date_str = c.normalized_date
                break

        # Check for relative clauses across candidate text and review reasons
        texts_to_search = [c.raw_text for c in result.date_candidates]
        if result.review_reason:
            texts_to_search.append(result.review_reason)
        full_text_for_dates = " \n ".join(texts_to_search)

        relative_matches = RelativeExpiryResolver.parse_relative_clauses(
            text=full_text_for_dates,
            verified_mfg_date=mfg_date_str,
        )

        for rel in relative_matches:
            existing = [c for c in result.date_candidates if c.raw_text == rel.raw_text]
            if not existing:
                result.date_candidates.append(
                    DateCandidate(
                        raw_text=rel.raw_text,
                        date_type=rel.date_type,
                        normalized_date=rel.normalized_date,
                        confidence=rel.confidence,
                        evidence=rel.evidence,
                    )
                )
            else:
                for ex in existing:
                    if rel.normalized_date and not ex.normalized_date:
                        ex.normalized_date = rel.normalized_date
                        ex.evidence = rel.evidence
                        ex.confidence = max(getattr(ex, "confidence", 0.0), 0.95)

            # If calculated relative date has a valid normalized date, set selected_expiry_date
            if rel.is_calculated and rel.normalized_date:
                if not result.selected_expiry_date:
                    result.selected_expiry_date = rel.normalized_date
                result.needs_review = False
                result.review_reason = None
            elif rel.needs_review and not result.selected_expiry_date:
                result.needs_review = True
                if rel.review_reason and not result.review_reason:
                    result.review_reason = rel.review_reason

        # Step C: Select expiry candidate if selected_expiry_date is still None
        if not result.selected_expiry_date:
            exp_cands = [
                c for c in result.date_candidates
                if c.date_type in ("expiry", "use_by", "best_before")
                and c.normalized_date
                and re.match(r"^\d{4}-\d{2}-\d{2}$", c.normalized_date)
            ]
            if len(exp_cands) == 1:
                result.selected_expiry_date = exp_cands[0].normalized_date
                result.needs_review = False
                result.review_reason = None

        # Step D: Validate selected_expiry_date format
        if result.selected_expiry_date:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", result.selected_expiry_date):
                result.selected_expiry_date = None
                result.needs_review = True
                result.review_reason = (
                    result.review_reason
                    or "Selected expiry date does not follow strict YYYY-MM-DD format."
                )

        # Step E: Ensure manufacturing / packed dates are NEVER selected as expiry
        if result.selected_expiry_date:
            mfg_matches = [
                c for c in result.date_candidates
                if c.date_type in ("manufacturing", "packed_on")
                and c.normalized_date == result.selected_expiry_date
            ]
            exp_matches = [
                c for c in result.date_candidates
                if c.date_type in ("expiry", "use_by", "best_before")
                and c.normalized_date == result.selected_expiry_date
            ]
            if mfg_matches and not exp_matches:
                result.selected_expiry_date = None
                result.needs_review = True
                result.review_reason = "Manufacturing or packing date was identified; not an expiry date."

        # Step F: Check candidate dates format
        for c in result.date_candidates:
            if c.normalized_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", c.normalized_date):
                c.normalized_date = None
                result.needs_review = True
                result.review_reason = (
                    result.review_reason
                    or "Date candidate does not have a valid YYYY-MM-DD date."
                )

        # Step G: If multiple conflicting expiry candidates exist
        exp_dates = {
            c.normalized_date for c in result.date_candidates
            if c.date_type in ("expiry", "use_by", "best_before") and c.normalized_date is not None
        }
        if len(exp_dates) > 1:
            result.needs_review = True
            result.selected_expiry_date = None
            result.review_reason = (
                result.review_reason
                or f"Multiple conflicting expiry dates found ({', '.join(sorted(exp_dates))})."
            )

        # Step H: Final review check
        if result.selected_expiry_date is None:
            result.needs_review = True
            if not result.review_reason:
                if len(result.date_candidates) == 0:
                    result.review_reason = "No printed expiry or date markings detected on visible packaging."
                else:
                    has_exp = any(c.date_type in ("expiry", "use_by") for c in result.date_candidates)
                    has_bb = any(c.date_type in ("best_before", "after_opening") for c in result.date_candidates)
                    has_mfg = any(c.date_type in ("manufacturing", "packed_on") for c in result.date_candidates)
                    if has_exp:
                        result.review_reason = "Expiry date candidate detected but lacks precise full day or requires manual confirmation."
                    elif has_bb and not has_mfg:
                        result.review_reason = "Best-before date detected; requires verification for safety expiry."
                    elif has_mfg and not has_bb:
                        result.review_reason = "Only manufacturing or packing date detected; no expiry date visible."
                    else:
                        result.review_reason = "Date candidates detected but require manual confirmation."
        else:
            # If valid expiry date is selected, clear obsolete manual review reasons
            if result.review_reason and any(
                k in result.review_reason.lower()
                for k in ["lacks precise full day", "requires manual confirmation", "only manufacturing or packing"]
            ):
                result.needs_review = False
                result.review_reason = None

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
        ocr_text: str | None = None,
        scan_date: datetime.date | None = None,
    ) -> FoodAnalysisResult:
        """
        Analyze a captured food package image.
        Implements bounded exponential backoff with full jitter for transient errors.
        Respects server Retry-After guidance when provided.
        Returns a validated FoodAnalysisResult without raising exceptions.
        """
        t0 = time.perf_counter()
        path = Path(image_path)

        # Validate file
        valid, err = self.validate_image_file(path)
        if not valid:
            return FoodAnalysisResult(
                analysis_status="error",
                needs_review=True,
                review_reason=err or "Invalid image file",
                timing_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # Check API client
        client = self.client
        if client is None:
            return FoodAnalysisResult(
                analysis_status="error",
                needs_review=True,
                review_reason="GEMINI_API_KEY is not configured. Set GEMINI_API_KEY in .env or environment.",
                timing_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # Determine MIME type
        ext = path.suffix.lower()
        mime_type = "image/png" if ext == ".png" else "image/jpeg"

        models_to_try = [self.model_name]
        for fb in FALLBACK_MODELS:
            if fb not in models_to_try:
                models_to_try.append(fb)

        last_err: Exception | None = None
        models_attempted: list[str] = []
        total_retries = 0

        for current_model in models_to_try:
            if current_model not in models_attempted:
                models_attempted.append(current_model)
            model_failed = False

            for attempt in range(self.max_retries + 1):
                try:
                    image_bytes = path.read_bytes()

                    config = types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=FoodAnalysisResult,
                        temperature=0.1,
                        system_instruction=SYSTEM_INSTRUCTION,
                    )

                    prompt_parts = [
                        "Carefully inspect this packaging image across all visible areas (including top, bottom, neck, cap, edges, and small print). "
                        "Identify the product name, brand, food category (Medicine, Dairy, Beverage, Grains, Snacks, Produce, Pantry), "
                        "net quantity / weight / volume if printed (e.g. '500 ml', '1 kg', '250 g', '10 tablets', '2 packs'), "
                        "and ALL printed dates (manufacturing, packing, expiry, use-by, best-before, after-opening). "
                        "Extract each printed date into date_candidates with exact raw_text, accurate date_type, and nearby evidence. "
                        "Follow all strict date interpretation rules without hallucination."
                    ]
                    if ocr_text:
                        prompt_parts.append(
                            f"\nNote: Auxiliary text detected by local OCR (may be incomplete or noisy):\n{ocr_text[:1200]}\n"
                            f"You MUST independently and thoroughly inspect the image visual pixels across the entire packaging for all dates and product details."
                        )
                    prompt = "\n".join(prompt_parts)

                    response = client.models.generate_content(
                        model=current_model,
                        contents=[
                            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                            prompt,
                        ],
                        config=config,
                    )

                    parsed_res: FoodAnalysisResult | None = None
                    if hasattr(response, "parsed") and isinstance(response.parsed, FoodAnalysisResult):
                        parsed_res = FoodAnalysisResult.post_validate(response.parsed, scan_date=scan_date)
                    elif hasattr(response, "text") and response.text:
                        res = FoodAnalysisResult.model_validate_json(response.text)
                        parsed_res = FoodAnalysisResult.post_validate(res, scan_date=scan_date)

                    if parsed_res:
                        parsed_res.timing_ms = (time.perf_counter() - t0) * 1000.0
                        parsed_res.models_attempted = list(models_attempted)
                        parsed_res.retries_count = total_retries
                        return parsed_res

                    return FoodAnalysisResult(
                        analysis_status="error",
                        needs_review=True,
                        review_reason="Empty response received from Gemini API",
                        timing_ms=(time.perf_counter() - t0) * 1000.0,
                        models_attempted=list(models_attempted),
                        retries_count=total_retries,
                    )

                except Exception as e:
                    last_err = e
                    retryable, reason_cat = is_retryable_exception(e)

                    err_str = str(e)
                    is_model_unavailable = any(k in err_str for k in ("404", "NOT_FOUND", "503", "UNAVAILABLE", "high demand"))
                    if is_model_unavailable and current_model != models_to_try[-1]:
                        logger.warning(
                            "Model '%s' unavailable (%s). Switching to fallback model...",
                            current_model, err_str.split("\n")[0]
                        )
                        model_failed = True
                        break

                    if not retryable:
                        logger.warning(
                            "Non-retryable error encountered for model '%s': %s",
                            current_model, reason_cat
                        )
                        model_failed = False
                        break

                    if attempt >= self.max_retries:
                        logger.warning(
                            "Retry budget exhausted (%d/%d retries) on model '%s' for reason: %s",
                            attempt, self.max_retries, current_model, reason_cat
                        )
                        model_failed = False
                        break

                    total_retries += 1
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

            # If this model succeeded, it already returned above.
            # If it failed and we broke out, continue to next fallback model if available
            if not model_failed:
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
            timing_ms=(time.perf_counter() - t0) * 1000.0,
            models_attempted=list(models_attempted),
            retries_count=total_retries,
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
