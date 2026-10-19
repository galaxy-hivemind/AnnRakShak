"""
AnnaRakshak — Multi-Image Evidence Merger
==========================================
Deterministic evidence fusion engine for multi-image product package scans.
Combines initial product packaging captures with supplementary images (e.g. back panel,
date stamp flap, ingredient panel) while preserving provenance, respecting user edits,
and strictly detecting conflicts without guessing or hallucinating.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from confidence_evaluator import GENERIC_NAME_BLACKLIST, VALID_CATEGORIES
from gemini_analyzer import DateCandidate, FoodAnalysisResult

logger = logging.getLogger("AnnaRakshak.EvidenceMerger")


@dataclass
class MergeResult:
    """Consolidated outcome of merging original and supplementary scan evidence."""
    merged_result: FoodAnalysisResult
    has_conflicts: bool
    conflict_reasons: list[str] = field(default_factory=list)
    fields_updated: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)


def is_valid_name(name: str | None) -> bool:
    """Return True if product name is non-empty and not a generic placeholder."""
    if not name or not isinstance(name, str):
        return False
    clean = name.strip()
    return len(clean) >= 2 and clean.lower() not in GENERIC_NAME_BLACKLIST


def is_valid_category(cat: str | None) -> bool:
    """Return True if food category is recognized."""
    if not cat or not isinstance(cat, str):
        return False
    return cat.strip().lower() in VALID_CATEGORIES


def merge_scan_results(
    original: FoodAnalysisResult,
    supplementary: FoodAnalysisResult,
    user_overrides: dict[str, Any] | None = None,
) -> MergeResult:
    """
    Deterministically merge the original scan result with supplementary capture evidence.

    Rules enforced:
    1. Preserve correctly identified product name, brand, category, quantity.
    2. Populate previously missing fields with new evidence.
    3. Weaker new evidence does NOT overwrite confident established evidence.
    4. User overrides take precedence over any model-generated fields.
    5. Conflicting dates or contradictory facts trigger manual review (never silently chosen).
    6. Manufacturing dates are NEVER converted into expiry dates.
    7. No hallucination: unsupported dates are not inferred merely because a 2nd image was taken.
    8. Complete date provenance is preserved.
    """
    overrides = user_overrides or {}
    conflict_reasons: list[str] = []
    fields_updated: list[str] = []

    # 1. Product Name Merging
    if overrides.get("name") and str(overrides["name"]).strip():
        final_name = str(overrides["name"]).strip()
    elif is_valid_name(original.product_name):
        final_name = original.product_name
        # If supplementary also has a valid name, check for substantial contradiction
        if is_valid_name(supplementary.product_name):
            orig_low = original.product_name.strip().lower()
            supp_low = supplementary.product_name.strip().lower()
            if orig_low != supp_low and orig_low not in supp_low and supp_low not in orig_low:
                # Substantial conflict in detected product name
                conflict_reasons.append(
                    f"Conflicting product names detected: '{original.product_name}' vs '{supplementary.product_name}'"
                )
    elif is_valid_name(supplementary.product_name):
        final_name = supplementary.product_name
        fields_updated.append("product_name")
    else:
        final_name = original.product_name or supplementary.product_name

    # 2. Brand Merging
    if overrides.get("brand") is not None and str(overrides["brand"]).strip():
        final_brand = str(overrides["brand"]).strip()
    elif original.brand and original.brand.strip():
        final_brand = original.brand
        if supplementary.brand and supplementary.brand.strip():
            orig_b = original.brand.strip().lower()
            supp_b = supplementary.brand.strip().lower()
            if orig_b != supp_b and orig_b not in supp_b and supp_b not in orig_b:
                conflict_reasons.append(
                    f"Conflicting brands detected across captures: '{original.brand}' vs '{supplementary.brand}'"
                )
    elif supplementary.brand and supplementary.brand.strip():
        final_brand = supplementary.brand
        fields_updated.append("brand")
    else:
        final_brand = original.brand or supplementary.brand

    # 3. Category Merging
    if overrides.get("category") and str(overrides["category"]).strip():
        final_category = str(overrides["category"]).strip()
    elif is_valid_category(original.food_category):
        final_category = original.food_category
        if is_valid_category(supplementary.food_category):
            if original.food_category.strip().lower() != supplementary.food_category.strip().lower():
                conflict_reasons.append(
                    f"Conflicting categories detected: '{original.food_category}' vs '{supplementary.food_category}'"
                )
    elif is_valid_category(supplementary.food_category):
        final_category = supplementary.food_category
        fields_updated.append("food_category")
    else:
        final_category = original.food_category or supplementary.food_category

    # 4. Quantity Merging
    if overrides.get("quantity") is not None and str(overrides["quantity"]).strip():
        final_quantity = str(overrides["quantity"]).strip()
    elif original.quantity and original.quantity.strip():
        final_quantity = original.quantity
    elif supplementary.quantity and supplementary.quantity.strip():
        final_quantity = supplementary.quantity
        fields_updated.append("quantity")
    else:
        final_quantity = original.quantity or supplementary.quantity

    # 5. Date Candidates & Provenance Merging
    combined_candidates: list[DateCandidate] = []
    seen_candidates: set[tuple[str, str, str | None]] = set()

    # Add original candidates
    for c in (original.date_candidates or []):
        key = (c.raw_text.strip().lower(), c.date_type.strip().lower(), c.normalized_date)
        if key not in seen_candidates:
            seen_candidates.add(key)
            combined_candidates.append(c)

    # Add supplementary candidates, tagging evidence for provenance
    for c in (supplementary.date_candidates or []):
        key = (c.raw_text.strip().lower(), c.date_type.strip().lower(), c.normalized_date)
        if key in seen_candidates:
            # If duplicate candidate exists, keep the one with higher confidence
            for idx, existing in enumerate(combined_candidates):
                e_key = (existing.raw_text.strip().lower(), existing.date_type.strip().lower(), existing.normalized_date)
                if e_key == key and c.confidence > existing.confidence:
                    combined_candidates[idx] = c
            continue

        # Tag provenance if not already tagged
        tagged_evidence = c.evidence
        if "[Supplementary capture]" not in tagged_evidence:
            tagged_evidence = f"[Supplementary capture] {tagged_evidence}".strip()

        cand_copy = DateCandidate(
            raw_text=c.raw_text,
            date_type=c.date_type,
            normalized_date=c.normalized_date,
            confidence=c.confidence,
            evidence=tagged_evidence,
        )
        seen_candidates.add(key)
        combined_candidates.append(cand_copy)

    # 6. Expiry & Manufacturing Date Consistency & Conflict Checks
    orig_expiry_dates = {
        c.normalized_date for c in (original.date_candidates or [])
        if c.date_type in ("expiry", "use_by", "best_before") and c.normalized_date
    }
    supp_expiry_dates = {
        c.normalized_date for c in (supplementary.date_candidates or [])
        if c.date_type in ("expiry", "use_by", "best_before") and c.normalized_date
    }

    # Check for direct expiry date conflict between captures
    if orig_expiry_dates and supp_expiry_dates:
        common = orig_expiry_dates.intersection(supp_expiry_dates)
        if not common and orig_expiry_dates != supp_expiry_dates:
            conflict_reasons.append(
                f"Conflicting expiry dates detected across packaging captures: "
                f"'{', '.join(sorted(orig_expiry_dates))}' vs '{', '.join(sorted(supp_expiry_dates))}'"
            )

    # Check for manufacturing date conflicts
    orig_mfg_dates = {
        c.normalized_date for c in (original.date_candidates or [])
        if c.date_type in ("manufacturing", "packed_on") and c.normalized_date
    }
    supp_mfg_dates = {
        c.normalized_date for c in (supplementary.date_candidates or [])
        if c.date_type in ("manufacturing", "packed_on") and c.normalized_date
    }
    if orig_mfg_dates and supp_mfg_dates:
        if orig_mfg_dates != supp_mfg_dates:
            conflict_reasons.append(
                f"Conflicting manufacturing dates detected across packaging captures: "
                f"'{', '.join(sorted(orig_mfg_dates))}' vs '{', '.join(sorted(supp_mfg_dates))}'"
            )

    # Determine consolidated selected expiry date
    final_selected_expiry = original.selected_expiry_date
    all_expiry_candidates = [
        c for c in combined_candidates
        if c.date_type in ("expiry", "use_by", "best_before") and c.normalized_date
    ]

    all_expiry_dates = {c.normalized_date for c in all_expiry_candidates if c.normalized_date}

    if len(all_expiry_dates) > 1 and not conflict_reasons:
        conflict_reasons.append(
            f"Multiple conflicting expiry dates found on packaging: {', '.join(sorted(all_expiry_dates))}"
        )

    if not final_selected_expiry and all_expiry_candidates and not conflict_reasons:
        # Choose best candidate
        best_cand = max(all_expiry_candidates, key=lambda c: c.confidence)
        final_selected_expiry = best_cand.normalized_date
        fields_updated.append("selected_expiry_date")
    elif final_selected_expiry and final_selected_expiry not in all_expiry_dates and all_expiry_dates:
        # If original selected expiry is no longer supported or contradicts
        if not conflict_reasons:
            conflict_reasons.append(
                f"Selected expiry date '{final_selected_expiry}' contradicts detected candidate dates: {', '.join(sorted(all_expiry_dates))}"
            )

    # Check timeline consistency (EXP must not be before MFG)
    all_mfg_candidates = [
        c for c in combined_candidates
        if c.date_type in ("manufacturing", "packed_on") and c.normalized_date
    ]
    if final_selected_expiry:
        for mfg in all_mfg_candidates:
            if mfg.normalized_date and final_selected_expiry < mfg.normalized_date:
                conflict_reasons.append(
                    f"Expiry date ({final_selected_expiry}) is earlier than manufacturing date ({mfg.normalized_date})"
                )

    # 7. Compile Missing Fields
    missing_fields: list[str] = []
    if not is_valid_name(final_name):
        missing_fields.append("product_name")
    if not is_valid_category(final_category):
        missing_fields.append("food_category")
    if not final_selected_expiry and not all_expiry_candidates:
        missing_fields.append("expiry_date")
    if not final_brand:
        missing_fields.append("brand")
    if not final_quantity:
        missing_fields.append("quantity")

    # 8. Needs Review & Review Reason
    has_conflicts = len(conflict_reasons) > 0
    if has_conflicts:
        final_needs_review = True
        final_review_reason = " | ".join(conflict_reasons)
        final_status = "needs_review"
    elif original.analysis_status == "error" and supplementary.analysis_status == "error":
        final_needs_review = True
        final_review_reason = supplementary.review_reason or original.review_reason or "Analysis failed on both images"
        final_status = "error"
    elif not final_selected_expiry and all_mfg_candidates:
        final_needs_review = True
        final_review_reason = "Manufacturing date identified; expiry date remains unverified."
        final_status = "needs_review"
    elif not final_selected_expiry:
        final_needs_review = True
        final_review_reason = "Expiry date missing or uncertain."
        final_status = "needs_review"
    elif not is_valid_name(final_name):
        final_needs_review = True
        final_review_reason = "Product name missing or unverified."
        final_status = "needs_review"
    else:
        # If there are no conflicts, expiry is present, name is valid
        final_needs_review = False
        final_review_reason = None
        final_status = "success"

    # Merge timing and model telemetry
    combined_models = list(original.models_attempted or [])
    for m in (supplementary.models_attempted or []):
        if m not in combined_models:
            combined_models.append(m)

    # Barcode merging
    final_barcode = (
        overrides.get("barcode")
        or getattr(original, "barcode", None)
        or getattr(supplementary, "barcode", None)
    )

    merged = FoodAnalysisResult(
        product_name=final_name,
        brand=final_brand,
        food_category=final_category,
        quantity=final_quantity,
        barcode=final_barcode,
        date_candidates=combined_candidates,
        selected_expiry_date=final_selected_expiry,
        analysis_status=final_status,
        needs_review=final_needs_review,
        review_reason=final_review_reason,
        timing_ms=round(original.timing_ms + supplementary.timing_ms, 2),
        models_attempted=combined_models,
        retries_count=original.retries_count + supplementary.retries_count,
        classification_source=original.classification_source or supplementary.classification_source,
        classification_evidence=original.classification_evidence or supplementary.classification_evidence,
    )

    return MergeResult(
        merged_result=merged,
        has_conflicts=has_conflicts,
        conflict_reasons=conflict_reasons,
        fields_updated=fields_updated,
        missing_fields=missing_fields,
    )
