"""
AnnaRakshak — Relative Expiry and Shelf-Life Interpretation
===========================================================
Deterministic parsing and calendar arithmetic for relative packaging dates,
such as:
  - "Best before 4 months from date of manufacture"
  - "Best before 6 months from MFG"
  - "Shelf life: 12 months from manufacturing"
  - "Use within 30 days of opening" (after-opening instruction)

Strict Rules:
  1. GROUNDED CALCULATION: Calculate an expiry date from a duration ONLY when the
     packaging text establishes a reference date AND that reference date (e.g. MFG)
     is reliably verified on the packaging.
  2. NO SPECULATIVE REFERENCE DATES: Never calculate relative expiry from today's date,
     scan date, or purchase date.
  3. CALENDAR-MONTH ARITHMETIC: Uses true calendar-month addition, clamping to month-end
     (e.g., Jan 31 + 1 month = Feb 28 in non-leap year, Feb 29 in leap year).
  4. MISSING REFERENCE DATE: If "Best before 4 months" has no verified reference date,
     preserve duration, set normalized_date = None, and flag needs_review = True.
  5. AFTER-OPENING INSTRUCTIONS: "Use within 30 days of opening" must NOT be converted
     into an expiry date unless opening date is explicitly established; record as
     after-opening instruction and flag review.
  6. ZERO SILENT CONVERSIONS: Never confuse manufacturing date with expiry date.
"""

from __future__ import annotations

import calendar
import datetime
import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class RelativeExpiryResult:
    raw_text: str
    date_type: Literal["best_before", "expiry", "use_by", "after_opening", "manufacturing"]
    duration_value: int | None
    duration_unit: Literal["days", "months", "years"] | None
    reference_type: str | None  # "manufacture", "packaging", "opening", "unknown"
    normalized_date: str | None  # ISO YYYY-MM-DD or None
    is_calculated: bool
    confidence: float
    evidence: str
    needs_review: bool
    review_reason: str | None = None


def add_calendar_months(source_date: datetime.date, months_to_add: int) -> datetime.date:
    """
    Add calendar months to a date, preserving day-of-month and clamping to month end.
    Example:
      2026-01-31 + 1 month -> 2026-02-28 (non-leap year)
      2024-01-31 + 1 month -> 2024-02-29 (leap year)
      2026-08-31 + 1 month -> 2026-09-30 (30 days in September)
      2026-10-10 + 4 months -> 2027-02-10
    """
    total_months = source_date.year * 12 + (source_date.month - 1) + months_to_add
    target_year = total_months // 12
    target_month = (total_months % 12) + 1
    max_days = calendar.monthrange(target_year, target_month)[1]
    target_day = min(source_date.day, max_days)
    return datetime.date(target_year, target_month, target_day)


def parse_iso_date(date_val: str | datetime.date | None) -> datetime.date | None:
    """Parse string or date into datetime.date safely."""
    if not date_val:
        return None
    if isinstance(date_val, datetime.date):
        return date_val
    try:
        clean = str(date_val).strip()
        parts = clean.split("-")
        if len(parts) == 3:
            return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Regex Patterns for Relative Expiry
# ---------------------------------------------------------------------------

# 1. "Use within X days/months of opening"
AFTER_OPENING_PATTERN = re.compile(
    r"\buse\s+within\s+(\d+)\s*(days?|months?|weeks?)\s*(?:of|after)\s*opening\b",
    re.IGNORECASE,
)

# 2. "Best before X months from (date of) manufacture/mfg/pkd"
BEST_BEFORE_DURATION_PATTERN = re.compile(
    r"\b(?:best\s+before|bb|use\s+within|expiry\s+period\s*[:\-]?)\s*"
    r"(\d+)\s*(months?|days?|years?)\s*"
    r"(?:from\s+(?:the\s+)?(?:date\s+of\s+)?(manufacture|mfg|packaging|pkd|packing|production))?",
    re.IGNORECASE,
)

# 3. "Shelf life: X months from manufacture/mfg"
SHELF_LIFE_PATTERN = re.compile(
    r"\bshelf\s*life\s*[:\-]?\s*(\d+)\s*(months?|days?|years?)\s*"
    r"(?:from\s+(?:the\s+)?(?:date\s+of\s+)?(manufacture|mfg|packaging|pkd|packing|production))?",
    re.IGNORECASE,
)


class RelativeExpiryResolver:
    """
    Resolves relative shelf life text against verified manufacturing dates.
    """

    @classmethod
    def parse_relative_clauses(
        cls,
        text: str,
        verified_mfg_date: str | datetime.date | None = None,
        opening_date: str | datetime.date | None = None,
    ) -> list[RelativeExpiryResult]:
        """
        Extract all relative shelf-life and after-opening expressions from packaging text.
        Calculates an expiry date only if the verified reference date is supplied.
        """
        results: list[RelativeExpiryResult] = []
        mfg_date_obj = parse_iso_date(verified_mfg_date)
        opening_date_obj = parse_iso_date(opening_date)

        # Track character spans of after-opening matches to avoid double-matching
        opening_spans: list[tuple[int, int]] = []
        for match in AFTER_OPENING_PATTERN.finditer(text):
            opening_spans.append((match.start(), match.end()))
            raw_match = match.group(0).strip()
            num_val = int(match.group(1))
            unit_raw = match.group(2).lower()
            unit: Literal["days", "months", "years"] = "months" if "month" in unit_raw else "days"

            if opening_date_obj:
                if unit == "months":
                    calc_date = add_calendar_months(opening_date_obj, num_val)
                else:
                    calc_date = opening_date_obj + datetime.timedelta(days=num_val)
                results.append(
                    RelativeExpiryResult(
                        raw_text=raw_match,
                        date_type="after_opening",
                        duration_value=num_val,
                        duration_unit=unit,
                        reference_type="opening",
                        normalized_date=calc_date.isoformat(),
                        is_calculated=True,
                        confidence=0.95,
                        evidence=f"Calculated from verified opening date {opening_date_obj.isoformat()}",
                        needs_review=False,
                    )
                )
            else:
                # Do NOT convert into calendar expiry date
                results.append(
                    RelativeExpiryResult(
                        raw_text=raw_match,
                        date_type="after_opening",
                        duration_value=num_val,
                        duration_unit=unit,
                        reference_type="opening",
                        normalized_date=None,
                        is_calculated=False,
                        confidence=0.90,
                        evidence="After-opening shelf-life instruction detected; opening date not recorded",
                        needs_review=True,
                        review_reason=(
                            f"Label specifies '{raw_match}'. Expiry applies after product opening; "
                            "opening date is not recorded."
                        ),
                    )
                )

        # 2. Check for "Best before X months [from MFG]"
        for match in BEST_BEFORE_DURATION_PATTERN.finditer(text):
            # Skip if this match overlaps with an after-opening instruction
            m_start, m_end = match.start(), match.end()
            if any(os <= m_start < oe or os < m_end <= oe for os, oe in opening_spans):
                continue
            raw_match = match.group(0).strip()
            num_val = int(match.group(1))
            unit_raw = match.group(2).lower()
            ref_raw = match.group(3)

            unit = "years" if "year" in unit_raw else ("months" if "month" in unit_raw else "days")
            ref_type = "manufacture" if (ref_raw and any(k in ref_raw.lower() for k in ["mfg", "manufactur", "pack", "pkd", "product"])) else "unknown"

            if mfg_date_obj:
                # We have a verified reference date
                if unit == "months":
                    calc_date = add_calendar_months(mfg_date_obj, num_val)
                elif unit == "years":
                    calc_date = add_calendar_months(mfg_date_obj, num_val * 12)
                else:
                    calc_date = mfg_date_obj + datetime.timedelta(days=num_val)

                results.append(
                    RelativeExpiryResult(
                        raw_text=raw_match,
                        date_type="best_before",
                        duration_value=num_val,
                        duration_unit=unit,
                        reference_type="manufacture",
                        normalized_date=calc_date.isoformat(),
                        is_calculated=True,
                        confidence=0.95,
                        evidence=(
                            f"Calculated {num_val} {unit} from verified manufacturing date "
                            f"{mfg_date_obj.isoformat()} via calendar arithmetic"
                        ),
                        needs_review=False,
                    )
                )
            else:
                # No verified manufacturing date present
                results.append(
                    RelativeExpiryResult(
                        raw_text=raw_match,
                        date_type="best_before",
                        duration_value=num_val,
                        duration_unit=unit,
                        reference_type=ref_type,
                        normalized_date=None,
                        is_calculated=False,
                        confidence=0.85,
                        evidence=f"Relative duration detected ('{raw_match}') without verified reference date",
                        needs_review=True,
                        review_reason=(
                            f"Label states '{raw_match}', but verified manufacturing date is missing; "
                            "calendar expiry date cannot be calculated without reference date."
                        ),
                    )
                )

        # 3. Check for "Shelf life: X months [from manufacturing]"
        for match in SHELF_LIFE_PATTERN.finditer(text):
            raw_match = match.group(0).strip()
            # Avoid duplicate if matched by pattern 2
            if any(r.raw_text == raw_match for r in results):
                continue
            num_val = int(match.group(1))
            unit_raw = match.group(2).lower()
            ref_raw = match.group(3)

            unit = "years" if "year" in unit_raw else ("months" if "month" in unit_raw else "days")
            ref_type = "manufacture" if (ref_raw and any(k in ref_raw.lower() for k in ["mfg", "manufactur", "pack", "pkd"])) else "unknown"

            if mfg_date_obj:
                if unit == "months":
                    calc_date = add_calendar_months(mfg_date_obj, num_val)
                elif unit == "years":
                    calc_date = add_calendar_months(mfg_date_obj, num_val * 12)
                else:
                    calc_date = mfg_date_obj + datetime.timedelta(days=num_val)

                results.append(
                    RelativeExpiryResult(
                        raw_text=raw_match,
                        date_type="best_before",
                        duration_value=num_val,
                        duration_unit=unit,
                        reference_type="manufacture",
                        normalized_date=calc_date.isoformat(),
                        is_calculated=True,
                        confidence=0.95,
                        evidence=(
                            f"Calculated {num_val} {unit} shelf life from verified manufacturing date "
                            f"{mfg_date_obj.isoformat()} via calendar arithmetic"
                        ),
                        needs_review=False,
                    )
                )
            else:
                results.append(
                    RelativeExpiryResult(
                        raw_text=raw_match,
                        date_type="best_before",
                        duration_value=num_val,
                        duration_unit=unit,
                        reference_type=ref_type,
                        normalized_date=None,
                        is_calculated=False,
                        confidence=0.85,
                        evidence=f"Shelf-life duration detected ('{raw_match}') without verified manufacturing date",
                        needs_review=True,
                        review_reason=(
                            f"Label states '{raw_match}', but verified manufacturing date is missing; "
                            "calendar expiry date cannot be calculated."
                        ),
                    )
                )

        return results
