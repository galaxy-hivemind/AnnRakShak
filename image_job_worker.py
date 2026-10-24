"""
AnnaRakshak — Background Product Image Discovery Worker
======================================================
Asynchronously discovers, validates, and updates product images in the background
without blocking scan or confirmation workflows.

Guarantees:
  1. Non-blocking Save: Products are saved promptly before external catalog queries run.
  2. Bounded Retries & Cooldowns:
     - Attempt 1: Immediate (0s delay).
     - Attempt 2: ~30 seconds after transient failure.
     - Attempt 3: ~2 minutes (120s) after transient failure.
     - Attempt 4: ~10 minutes (600s) after transient failure.
     - After 4 attempts: Status set to 'failed'.
     - Respects provider Retry-After header on HTTP 429.
  3. No-Match Distinction: A completed search yielding no suitable image transitions
     to 'no_match' without triggering wasteful network retries.
  4. Stale-Job & Manual Protection:
     - Never overwrites user-selected manual images.
     - Never recreates deleted products.
     - Never overwrites products whose identity changed after job creation.
     - Updates only image-related fields; never modifies dates, quantities, or notes.
  5. Recovery of Stalled Jobs: Recovers orphaned jobs stuck in 'searching'.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import time
from typing import Any

import httpx

from inventory_db import InventoryDatabase
from product_image_resolver import (
    ImageMetadata,
    ImageResolutionStatus,
    ProductImageResolver,
    get_image_resolver,
)

logger = logging.getLogger("AnnaRakshak.ImageJobWorker")

# Cooldown backoff delays for attempts [attempt 1 (0s), attempt 2 (30s), attempt 3 (120s), attempt 4 (600s)]
RETRY_COOLDOWNS_SECONDS = [0.0, 30.0, 120.0, 600.0]
DEFAULT_MAX_ATTEMPTS = 4
STALLED_JOB_TIMEOUT_SECONDS = 300


def calculate_retry_delay(attempt_count: int, retry_after: float | None = None) -> float:
    """
    Calculate the cooldown delay in seconds based on attempt count and optional Retry-After header.
    """
    idx = min(max(attempt_count, 0), len(RETRY_COOLDOWNS_SECONDS) - 1)
    base_delay = RETRY_COOLDOWNS_SECONDS[idx]
    if retry_after is not None and retry_after > 0:
        return max(base_delay, min(float(retry_after), 1800.0))
    return base_delay


def is_transient_error(exc: Exception) -> tuple[bool, float | None]:
    """
    Classify whether an exception is a transient retryable failure.
    Returns (is_retryable, retry_after_seconds_or_none).
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, TimeoutError)):
        return True, None

    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        retry_after = None
        if "Retry-After" in exc.response.headers:
            try:
                retry_after = float(exc.response.headers["Retry-After"])
            except (ValueError, TypeError):
                retry_after = None

        if code == 429:
            return True, retry_after
        if 500 <= code <= 599:
            return True, retry_after
        return False, None

    err_str = str(exc).lower()
    transient_indicators = [
        "timeout", "timed out", "connection reset", "connection refused",
        "temporary failure", "network unreachable", "503", "502", "504", "429",
    ]
    if any(ind in err_str for ind in transient_indicators):
        return True, None

    return False, None


def extract_barcode_from_product(product: Any) -> str | None:
    """Extract barcode from product notes, metadata, or linked scan."""
    if hasattr(product, "notes") and product.notes:
        m = re.search(r"Barcode:\s*([0-9A-Za-z]+)", product.notes)
        if m:
            return m.group(1).strip()
    return None


def process_image_discovery_job(
    job_id: int,
    db: InventoryDatabase,
    resolver: ProductImageResolver | None = None,
    deadline: float | None = None,
    enable_ai_fallback: bool | None = None,
) -> bool:
    """
    Process a single image discovery job.
    Idempotent and concurrency-safe via atomic status claim.
    """
    # 1. Atomic Claim
    claimed = db.claim_image_job(job_id)
    if not claimed:
        logger.debug("Job %d could not be claimed (already claimed or terminal).", job_id)
        return False

    job = db.get_image_job(job_id)
    if not job:
        logger.warning("Job %d claimed but record not found.", job_id)
        return False

    product_id = job.product_id
    product = db.get_product(product_id)

    # 2. Safety Pre-checks
    if not product:
        logger.info("Product %d deleted; cancelling discovery job %d.", product_id, job_id)
        db.apply_resolved_product_image(product_id, job_id, image_path="", image_metadata=None)
        return False

    if product.image_source_type == "manual":
        logger.info("Product %d has manual image; cancelling discovery job %d.", product_id, job_id)
        db.cancel_image_jobs_for_product(product_id, reason="Manual image selection preserved")
        return False

    # Check identity agreement
    curr_ident = f"{(product.brand or '').strip()} {product.product_name.strip()}".strip()
    if job.normalized_identity != curr_ident and job.normalized_identity != product.product_name.strip():
        logger.info("Product %d identity modified; cancelling obsolete job %d.", product_id, job_id)
        db.cancel_image_jobs_for_product(product_id, reason="Product identity changed")
        return False

    # 3. Resolve Product Details and Scanned Photo
    barcode = extract_barcode_from_product(product)
    image_resolver = resolver or get_image_resolver()

    source_img = None
    if product.scan_id:
        scan_rec = db.get_scan(product.scan_id)
        if scan_rec and scan_rec.image_path and os.path.exists(scan_rec.image_path):
            source_img = scan_rec.image_path
    if not source_img and product.image_path and os.path.exists(product.image_path):
        source_img = product.image_path

    # 4. Perform Image Discovery: Priority 1 — Web Search (Image barcode & Google/catalog progressive text search)
    try:
        meta: ImageMetadata = image_resolver.resolve_product_image(
            product_name=product.product_name,
            brand=product.brand,
            barcode=barcode,
            category=product.food_category,
            is_supplementary=False,
            deadline=deadline,
            source_image_path=source_img,
        )

        if meta.is_verified and (meta.image_url or meta.local_path):
            # Suitable candidate discovered, validated, and saved
            image_target = meta.image_url or meta.local_path
            src_type = "catalog" if "catalog" in meta.source or "open_" in meta.source else "web"
            success = db.apply_resolved_product_image(
                product_id=product_id,
                job_id=job_id,
                image_path=str(image_target),
                image_metadata=meta.to_dict(),
                image_source_type=src_type,
            )
            logger.info("Job %d resolved via web search for product %d: %s (applied=%s)", job_id, product_id, image_target, success)
            return success
        else:
            # Priority 2: Cropping the scanned image (Final Endpoint)
            # If product is already cropped and exists on disk, preserve it as the final endpoint
            if product.image_source_type == "crop" and product.image_path and os.path.exists(product.image_path):
                logger.info("Job %d web search found no match; retaining existing cropped image %s for product %d ('%s')", job_id, product.image_path, product_id, curr_ident)
                db.apply_no_match_product_image(product_id, job_id)
                return True

            if source_img and os.path.exists(source_img):
                logger.info("Job %d web search found no match; cropping scanned image as final endpoint for product %d ('%s')...", job_id, product_id, curr_ident)
                try:
                    from ai_image_generator import get_ai_image_generator
                    ai_gen = get_ai_image_generator()
                    crop_res = ai_gen.generate_ai_crop_studio_image(
                        product_name=product.product_name,
                        brand=product.brand,
                        category=product.food_category,
                        product_id=product_id,
                        source_image_path=source_img,
                    )
                    if crop_res.success and crop_res.image_path:
                        meta_dict = {
                            "source": "ai_crop_isolated",
                            "model": crop_res.model_name,
                            "width": crop_res.width,
                            "height": crop_res.height,
                            "content_type": crop_res.content_type,
                            "is_verified": True,
                        }
                        success = db.apply_resolved_product_image(
                            product_id=product_id,
                            job_id=job_id,
                            image_path=crop_res.image_path,
                            image_metadata=meta_dict,
                            image_source_type="crop",
                        )
                        logger.info("Job %d resolved with cropped scanned image for product %d: %s (applied=%s)", job_id, product_id, crop_res.image_path, success)
                        return success
                except Exception as crop_err:
                    logger.warning("Scanned image crop encountered error: %s", crop_err)

            # Tier 3: Collection of 200 Common Household Items Fallback
            from household_catalog import find_best_household_item
            household_item = find_best_household_item(product.product_name, product.brand, product.food_category)
            if household_item:
                logger.info("Job %d matched Tier 3 household catalog item '%s' for product %d ('%s')", job_id, household_item.name, product_id, curr_ident)
                meta_dict = {
                    "source": "household_catalog",
                    "item_id": household_item.id,
                    "item_name": household_item.name,
                    "category": household_item.category,
                    "is_verified": True,
                }
                success = db.apply_resolved_product_image(
                    product_id=product_id,
                    job_id=job_id,
                    image_path=household_item.image_path,
                    image_metadata=meta_dict,
                    image_source_type="catalog_preset",
                )
                return success

            # Fallback: Only if NO scanned image was present and no household item matched
            logger.info("Applying default category image for product %d ('%s') as no scanned image or household match was available.", product_id, curr_ident)
            db.apply_no_match_product_image(product_id, job_id)
            return True

    except Exception as exc:
        is_retryable, retry_after = is_transient_error(exc)
        delay = calculate_retry_delay(job.attempt_count, retry_after=retry_after)
        err_msg = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "Job %d failed on attempt %d/%d (retryable=%s, cooldown=%.1fs): %s",
            job_id, job.attempt_count, job.max_attempts, is_retryable, delay, err_msg,
        )
        db.schedule_job_retry(
            job_id=job_id,
            error_message=err_msg,
            delay_seconds=delay,
            is_retryable=is_retryable,
        )
        return False


DEFAULT_SERVERLESS_TIME_BUDGET_SECONDS = 8.0
MIN_JOB_BUDGET_SECONDS = 2.0


def process_due_image_jobs(
    db: InventoryDatabase,
    limit: int = 10,
    resolver: ProductImageResolver | None = None,
    time_budget_seconds: float | None = None,
    min_job_budget_seconds: float = MIN_JOB_BUDGET_SECONDS,
) -> int:
    """
    Query and process all due image discovery jobs up to limit.
    Also triggers recovery for stalled jobs.
    If time_budget_seconds is specified, stops claiming new jobs when the
    elapsed time leaves less than min_job_budget_seconds in the budget.
    Returns the number of jobs processed.
    """
    # 1. Recover stalled jobs
    try:
        recovered = db.recover_stalled_jobs(stalled_seconds=STALLED_JOB_TIMEOUT_SECONDS)
        if recovered > 0:
            logger.info("Recovered %d stalled image discovery jobs.", recovered)
    except Exception as e:
        logger.warning("Error recovering stalled image jobs: %s", e)

    start_time = time.monotonic()

    due_jobs = db.get_due_image_jobs(limit=limit)
    if not due_jobs:
        return 0

    processed_count = 0
    for job in due_jobs:
        job_deadline = None
        # Check remaining time budget before claiming the next job
        if time_budget_seconds is not None:
            elapsed = time.monotonic() - start_time
            remaining = time_budget_seconds - elapsed
            if remaining < min_job_budget_seconds:
                logger.info(
                    "Time budget reached (%.2fs elapsed / %.2fs budget, %.2fs remaining < %.2fs threshold). "
                    "Processed %d of %d due jobs; stopping before claiming job %d.",
                    elapsed,
                    time_budget_seconds,
                    remaining,
                    min_job_budget_seconds,
                    processed_count,
                    len(due_jobs),
                    job.id,
                )
                break
            job_deadline = start_time + time_budget_seconds

        try:
            process_image_discovery_job(job.id, db, resolver=resolver, deadline=job_deadline)
            processed_count += 1
        except Exception as e:
            logger.error("Unhandled error processing image job %d: %s", job.id, e, exc_info=True)

    return processed_count
