"""
AnnaRakshak — Confidence Evaluation Engine
===========================================
Deterministic, evidence-based confidence evaluator that decides whether a scan
can be automatically saved to inventory (Path A) or must enter manual review (Path B).

Decision Principles:
1. Product Identity: Must have a clear, identifiable name (not generic or placeholder).
2. Category Plausibility: Must belong to a recognized food or medicine category.
3. Expiry Evidence: Must have a readable, unambiguous expiry or best-before date
   with high candidate confidence.
4. Consistency: No conflicting expiry dates or contradictory timeline (e.g. EXP earlier than MFG).
5. No Concealed Uncertainty: A high overall score cannot override a critical missing field
   or ambiguous expiry evidence.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


# Configurable threshold defaults (can be overridden via environment variables)
DEFAULT_AUTO_SAVE_THRESHOLD = float(os.getenv("ANNARAKSHAK_AUTO_SAVE_THRESHOLD", "0.80"))
DEFAULT_MIN_DATE_CONFIDENCE = float(os.getenv("ANNARAKSHAK_MIN_DATE_CONFIDENCE", "0.80"))
DEFAULT_MIN_CATEGORY_CONFIDENCE = float(os.getenv("ANNARAKSHAK_MIN_CATEGORY_CONFIDENCE", "0.70"))

GENERIC_NAME_BLACKLIST = {
    "unknown",
    "unknown item",
    "unknown product",
    "unreadable",
    "item",
    "product",
    "food",
    "food product",
    "package",
    "packaging",
    "none",
    "null",
    "test",
    "sample",
}

VALID_CATEGORIES = {
    "dairy",
    "dairy & eggs",
    "beverage",
    "beverages",
    "grains",
    "grains & cereals",
    "snacks",
    "produce",
    "fresh produce",
    "pantry",
    "pantry staples",
    "medicine",
}


@dataclass
class ConfidenceAssessment:
    """Structured assessment of scan confidence and auto-save eligibility."""
    should_auto_save: bool
    confidence_score: float
    decision_reason: str
    field_confidences: dict[str, float] = field(default_factory=dict)
    critical_issues: list[str] = field(default_factory=list)
    primary_date: str | None = None
    primary_date_type: str | None = None


def evaluate_scan_confidence(
    result: Any,
    auto_save_threshold: float = DEFAULT_AUTO_SAVE_THRESHOLD,
    min_date_confidence: float = DEFAULT_MIN_DATE_CONFIDENCE,
    min_category_confidence: float = DEFAULT_MIN_CATEGORY_CONFIDENCE,
) -> ConfidenceAssessment:
    """
    Deterministically evaluates a FoodAnalysisResult for auto-save eligibility.

    Returns a ConfidenceAssessment with:
    - should_auto_save: True only if all critical requirements are satisfied and composite score >= threshold
    - confidence_score: Composite score between 0.0 and 1.0
    - decision_reason: Human-readable explanation of the decision
    - field_confidences: Field-level breakdown
    - critical_issues: List of issues that blocked auto-save (if any)
    - primary_date: Selected normalized expiry date for inventory tracking
    - primary_date_type: Type of primary date (expiry, use_by, best_before)
    """
    critical_issues: list[str] = []
    field_confidences: dict[str, float] = {}

    # 1. Gate: Overall analysis status
    analysis_status = getattr(result, "analysis_status", "error")
    if analysis_status != "success":
        critical_issues.append(f"Analysis status is '{analysis_status}', not 'success'")

    # 2. Gate: General needs_review flag from model or post-validation
    needs_review = getattr(result, "needs_review", True)
    review_reason = getattr(result, "review_reason", None)
    if needs_review and review_reason:
        critical_issues.append(f"Model review flagged: {review_reason}")

    # 3. Product Name Evaluation
    raw_name = getattr(result, "product_name", None)
    name_score = 0.0
    if raw_name and isinstance(raw_name, str):
        clean_name = raw_name.strip()
        if len(clean_name) >= 2 and clean_name.lower() not in GENERIC_NAME_BLACKLIST:
            name_score = 1.0
        else:
            critical_issues.append(f"Product name '{clean_name}' is too generic or invalid")
    else:
        critical_issues.append("Missing product name")
    field_confidences["product_name"] = name_score

    # 4. Product Category Evaluation
    raw_category = getattr(result, "food_category", None)
    cat_score = 0.0
    if raw_category and isinstance(raw_category, str):
        clean_cat = raw_category.strip().lower()
        if clean_cat in VALID_CATEGORIES:
            cat_score = 0.95
        else:
            critical_issues.append(f"Category '{raw_category}' is not recognized")
    else:
        critical_issues.append("Missing food category")
    field_confidences["food_category"] = cat_score

    # 5. Date Candidates & Expiry Evidence Evaluation
    candidates = getattr(result, "date_candidates", []) or []
    expiry_candidates = [
        c for c in candidates
        if getattr(c, "date_type", "") in ("expiry", "use_by", "best_before")
    ]
    mfg_candidates = [
        c for c in candidates
        if getattr(c, "date_type", "") in ("manufacturing", "packed_on")
    ]

    date_score = 0.0
    primary_date: str | None = None
    primary_date_type: str | None = None

    if not expiry_candidates:
        if mfg_candidates:
            critical_issues.append("Only manufacturing/packed date detected; expiry date is missing")
        else:
            critical_issues.append("No expiry or best-before date detected on packaging")
    else:
        # Check for conflicting normalized expiry dates
        valid_dates = {
            c.normalized_date for c in expiry_candidates
            if getattr(c, "normalized_date", None)
        }

        if len(valid_dates) == 0:
            critical_issues.append("Expiry date detected but lacks precise YYYY-MM-DD day format")
        elif len(valid_dates) > 1:
            critical_issues.append(f"Conflicting expiry dates detected: {', '.join(sorted(valid_dates))}")
        else:
            # Single unambiguous normalized expiry date found
            best_cand = max(
                expiry_candidates,
                key=lambda c: float(getattr(c, "confidence", 0.0)) if getattr(c, "normalized_date", None) else -1.0,
            )
            cand_conf = float(getattr(best_cand, "confidence", 0.0))
            cand_norm = getattr(best_cand, "normalized_date", None)
            cand_type = getattr(best_cand, "date_type", "expiry")

            # Check strict ISO format YYYY-MM-DD
            if cand_norm and re.match(r"^\d{4}-\d{2}-\d{2}$", cand_norm):
                if cand_conf >= min_date_confidence:
                    date_score = cand_conf
                    primary_date = cand_norm
                    primary_date_type = cand_type
                else:
                    critical_issues.append(
                        f"Expiry date candidate confidence ({cand_conf:.2f}) is below threshold ({min_date_confidence:.2f})"
                    )
            else:
                critical_issues.append("Expiry date normalized value does not match YYYY-MM-DD format")

    # 6. Timeline Consistency (EXP must not be before MFG)
    if primary_date and mfg_candidates:
        for mfg in mfg_candidates:
            mfg_norm = getattr(mfg, "normalized_date", None)
            if mfg_norm and re.match(r"^\d{4}-\d{2}-\d{2}$", mfg_norm):
                if primary_date < mfg_norm:
                    critical_issues.append(f"Expiry date ({primary_date}) is earlier than manufacturing date ({mfg_norm})")

    field_confidences["expiry_date"] = date_score

    # 7. Brand presence (supplemental, not blocking)
    raw_brand = getattr(result, "brand", None)
    brand_score = 1.0 if (raw_brand and raw_brand.strip()) else 0.5
    field_confidences["brand"] = brand_score

    # 8. Composite Confidence Score Calculation
    # Weights: Date (40%), Name (30%), Category (20%), Brand (10%)
    composite = (0.40 * date_score) + (0.30 * name_score) + (0.20 * cat_score) + (0.10 * brand_score)
    composite = round(composite, 2)

    # 9. Decision Synthesis
    if not critical_issues and composite >= auto_save_threshold:
        should_auto_save = True
        decision_reason = (
            f"High confidence ({int(composite * 100)}%): "
            f"Unambiguous product identity, category, and printed expiry date ({primary_date}). Automatically saved."
        )
    else:
        should_auto_save = False
        if critical_issues:
            decision_reason = f"Manual review required: {critical_issues[0]}"
        else:
            decision_reason = f"Confidence score ({composite:.2f}) is below auto-save threshold ({auto_save_threshold:.2f})"

    return ConfidenceAssessment(
        should_auto_save=should_auto_save,
        confidence_score=composite,
        decision_reason=decision_reason,
        field_confidences=field_confidences,
        critical_issues=critical_issues,
        primary_date=primary_date,
        primary_date_type=primary_date_type,
    )
