"""
AnnaRakshak — REST HTTP API for Lovable Frontend
=================================================
FastAPI backend connecting the AnnaRakshak inventory SQLite repository,
date status intelligence, and Gemini packaging reanalysis to the frontend.

Principles:
  - 100% Local: Backed by local SQLite database.
  - Zero Silent Conversions: Manufacturing dates are never treated as expiry.
    Best-before quality dates are preserved separately from explicit expiry.
  - Safe Concurrency & Security:
      * Narrow CORS configuration for authorized frontend origins.
      * No camera access over HTTP.
      * API keys strictly protected on the backend.
      * No raw stack traces or internal paths leaked to clients.
      * Non-blocking reanalysis executed via asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import cv2
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import numpy as np
from pydantic import BaseModel, Field, field_validator

from gemini_analyzer import FoodAnalysisResult, GeminiAnalyzer
from ocr_engine import AppleVisionOCREngine, OCRResult
from inventory_db import (
    DEFAULT_DB_PATH,
    DEFAULT_WARNING_DAYS,
    DateCandidateRecord,
    DuplicateProductError,
    InvalidDateError,
    InventoryDatabase,
    ProductNotFoundError,
    ProductRecord,
    ScanHistoryRecord,
    calculate_date_status,
    mask_database_url,
)

# Load environment configuration
load_dotenv()

logger = logging.getLogger("AnnaRakshak.API")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Configuration Helpers
# ---------------------------------------------------------------------------

DEFAULT_FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://localhost:8081",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://.*\.vercel\.app$"


def get_cors_origins() -> list[str]:
    """Retrieve allowed CORS origins from FRONTEND_ORIGINS or default list."""
    raw = os.getenv("FRONTEND_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_FRONTEND_ORIGINS)
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins if origins else list(DEFAULT_FRONTEND_ORIGINS)


# ---------------------------------------------------------------------------
# Pydantic Request & Response Schemas
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    database: str = "connected"
    total_products: int
    version: str = "1.0.0"


class DateCandidateItem(BaseModel):
    id: int | None = None
    product_id: int | None = None
    scan_id: int | None = None
    raw_text: str
    date_type: str
    normalized_date: str | None = None
    confidence: float = 1.0
    evidence: str = ""
    created_at: str


class ProductResponse(BaseModel):
    id: int
    product_name: str
    brand: str | None = None
    food_category: str | None = None
    date_type: str
    date_text: str | None = None
    normalized_date: str | None = None
    date_status: str
    current_status: str
    date_source: str
    analysis_status: str | None = None
    image_path: str | None = None
    notes: str | None = None
    created_at: str
    updated_at: str
    date_candidates: list[DateCandidateItem] = []


class ProductCreate(BaseModel):
    product_name: str = Field(..., description="Descriptive food product name.")
    brand: str | None = Field(default=None, description="Brand or manufacturer.")
    food_category: str | None = Field(default=None, description="Food category (e.g., Dairy, Bakery).")
    date_type: str = Field(
        default="expiry",
        description="Type of date: expiry, use_by, best_before, manufacturing, packed_on, unknown.",
    )
    date_text: str | None = Field(default=None, description="Original raw date text printed on packaging.")
    normalized_date: str | None = Field(
        default=None,
        description="ISO format YYYY-MM-DD or null.",
    )
    date_status: str = Field(default="confirmed", description="Status: confirmed or unverified.")
    date_source: str = Field(default="manual", description="Source: manual, printed, user_confirmed.")
    notes: str | None = Field(default=None, description="Optional user notes.")
    force: bool = Field(default=False, description="Set True to override duplicate product warnings.")

    @field_validator("product_name")
    @classmethod
    def validate_product_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Product name cannot be blank.")
        return clean

    @field_validator("normalized_date")
    @classmethod
    def validate_normalized_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        try:
            parts = clean.split("-")
            if len(parts) != 3 or len(parts[0]) != 4:
                raise ValueError()
            datetime.date.fromisoformat(clean)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format '{value}'. Must be ISO format YYYY-MM-DD.")
        return clean

    @field_validator("date_type")
    @classmethod
    def validate_date_type(cls, value: str) -> str:
        clean = value.strip().lower()
        allowed = {"expiry", "use_by", "best_before", "manufacturing", "packed_on", "unknown"}
        if clean not in allowed:
            raise ValueError(f"Invalid date_type '{value}'. Must be one of: {sorted(allowed)}")
        return clean


class ProductUpdate(BaseModel):
    product_name: str | None = None
    brand: str | None = None
    food_category: str | None = None
    notes: str | None = None
    date_type: str | None = None
    normalized_date: str | None = None
    image_path: str | None = None

    @field_validator("product_name")
    @classmethod
    def validate_product_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("Product name cannot be empty.")
        return clean

    @field_validator("normalized_date")
    @classmethod
    def validate_normalized_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        try:
            parts = clean.split("-")
            if len(parts) != 3 or len(parts[0]) != 4:
                raise ValueError()
            datetime.date.fromisoformat(clean)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format '{value}'. Must be ISO format YYYY-MM-DD.")
        return clean

    @field_validator("date_type")
    @classmethod
    def validate_date_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip().lower()
        allowed = {"expiry", "use_by", "best_before", "manufacturing", "packed_on", "unknown"}
        if clean not in allowed:
            raise ValueError(f"Invalid date_type '{value}'. Must be one of: {sorted(allowed)}")
        return clean


class DashboardResponse(BaseModel):
    total_products: int
    expired_count: int
    expiring_soon_count: int
    best_before_soon_count: int
    best_before_passed_count: int
    safe_count: int
    needs_review_count: int
    total_scans: int
    recent_scans_count: int
    categories: dict[str, int]


class AlertItem(BaseModel):
    product_id: int
    product_name: str
    brand: str | None = None
    food_category: str | None = None
    date_type: str
    normalized_date: str | None = None
    date_status: str
    urgency: Literal["critical", "warning", "info"]
    message: str
    days_remaining: int | None = None


class ScanTiming(BaseModel):
    upload_preprocess_ms: float = 0.0
    ocr_ms: float = 0.0
    gemini_ms: float = 0.0
    db_ms: float = 0.0
    total_ms: float = 0.0
    models_attempted: list[str] = Field(default_factory=list)
    retries_count: int = 0


class ScanResponse(BaseModel):
    id: int
    timestamp: str
    image_path: str
    product_name: str | None = None
    brand: str | None = None
    food_category: str | None = None
    analysis_status: str
    needs_review: bool
    review_reason: str | None = None
    selected_expiry_date: str | None = None
    error_message: str | None = None
    raw_json: str | None = None
    date_candidates: list[DateCandidateItem] = []
    timing: ScanTiming | None = None


class DeleteResponse(BaseModel):
    success: bool
    message: str
    deleted_id: int


# ---------------------------------------------------------------------------
# Database & Dependency Injection
# ---------------------------------------------------------------------------
# Storage & Environment Configuration Helpers
# ---------------------------------------------------------------------------

def is_serverless_environment() -> bool:
    """Return True if running inside Vercel, AWS Lambda, or similar serverless container."""
    return (
        os.getenv("VERCEL") == "1"
        or bool(os.getenv("VERCEL_ENV"))
        or bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    )


def get_captures_dir() -> Path:
    """
    Determine the storage directory for scan images:
    - If ANNARAKSHAK_CAPTURES_DIR is explicitly configured, use it (resolved to absolute path).
    - If running in a serverless environment (e.g. Vercel), use a writable directory under /tmp:
      Path("/tmp/annarakshak/captures").
    - Otherwise (local development), use Path(__file__).parent / "captures".
    """
    custom = os.getenv("ANNARAKSHAK_CAPTURES_DIR")
    if custom and custom.strip():
        return Path(custom.strip()).resolve()
    if is_serverless_environment():
        return Path("/tmp/annarakshak/captures").resolve()
    return (Path(__file__).parent / "captures").resolve()


def should_cleanup_captures() -> bool:
    """
    Determine whether capture files should be deleted after processing:
    - If ANNARAKSHAK_CLEANUP_CAPTURES is set, respect it ("1", "true", "yes" -> True, "0", "false", "no" -> False).
    - If running on Vercel/serverless, defaults to True to prevent /tmp disk exhaustion.
    - Otherwise (local development), defaults to False to preserve capture files on disk for inspection and re-analysis.
    """
    env_val = os.getenv("ANNARAKSHAK_CLEANUP_CAPTURES")
    if env_val is not None:
        return env_val.strip().lower() in ("1", "true", "yes")
    return is_serverless_environment()


def _safe_remove_file(file_path: Path | str | None) -> None:
    """Safely delete a file if it exists, without raising errors."""
    if not file_path:
        return
    try:
        p = Path(file_path)
        if p.exists() and p.is_file():
            p.unlink()
    except Exception as e:
        logger.warning("Could not remove capture file %s: %s", file_path, e)


def get_database() -> InventoryDatabase:
    """
    Construct the database instance based on environment:
    - If DATABASE_URL or ANNARAKSHAK_DATABASE_URL is set: connects to persistent PostgreSQL.
    - If running on Vercel (VERCEL='1' or VERCEL_ENV set) and no DATABASE_URL:
      raises RuntimeError explaining that persistent PostgreSQL configuration is required.
    - Otherwise (local development): initializes project-local SQLite with absolute path resolution.
    """
    database_url = os.getenv("DATABASE_URL") or os.getenv("ANNARAKSHAK_DATABASE_URL")
    is_vercel = is_serverless_environment()

    if database_url and database_url.strip():
        logger.info("Initializing PostgreSQL database from DATABASE_URL (%s)", mask_database_url(database_url))
        return InventoryDatabase(database_url=database_url.strip())

    if is_vercel:
        msg = (
            "Vercel serverless environment detected (read-only filesystem), but DATABASE_URL is not configured.\n"
            "AnnaRakshak requires persistent storage in production.\n"
            "Please configure the DATABASE_URL environment variable in Vercel Project Settings -> Environment Variables "
            "pointing to your hosted PostgreSQL database (e.g. Neon, Supabase, or AWS RDS)."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    # Local development with SQLite
    raw_path = os.getenv("ANNARAKSHAK_DB_PATH", str(DEFAULT_DB_PATH))
    db_path = Path(raw_path).resolve()
    logger.info("Initializing local SQLite database at: %s", db_path)
    return InventoryDatabase(db_path=db_path)


def get_db(request: Request) -> InventoryDatabase:
    """Dependency provider for the InventoryDatabase instance (lazily initializes if missing)."""
    if not hasattr(request.app.state, "db") or request.app.state.db is None:
        request.app.state.db = get_database()
    return request.app.state.db


def get_analyzer(request: Request) -> GeminiAnalyzer:
    """Dependency provider for GeminiAnalyzer instance."""
    return request.app.state.analyzer


def serialize_product(
    p: ProductRecord,
    candidates: list[DateCandidateRecord] | None = None,
    ref_date: datetime.date | None = None,
) -> ProductResponse:
    """Helper to convert ProductRecord into ProductResponse with computed live status."""
    return ProductResponse(
        id=p.id,
        product_name=p.product_name,
        brand=p.brand,
        food_category=p.food_category,
        date_type=p.date_type,
        date_text=p.date_text,
        normalized_date=p.normalized_date,
        date_status=p.date_status,
        current_status=p.current_status(ref_date=ref_date),
        date_source=p.date_source,
        analysis_status=p.analysis_status,
        image_path=p.image_path,
        notes=p.notes,
        created_at=p.created_at,
        updated_at=p.updated_at,
        date_candidates=[DateCandidateItem(**c.to_dict()) for c in (candidates or [])],
    )


def serialize_scan(
    s: ScanHistoryRecord,
    candidates: list[DateCandidateRecord] | None = None,
    timing: ScanTiming | None = None,
) -> ScanResponse:
    """Helper to convert ScanHistoryRecord into ScanResponse with attached candidates and timing."""
    return ScanResponse(
        id=s.id,
        timestamp=s.timestamp,
        image_path=s.image_path,
        product_name=s.product_name,
        brand=s.brand,
        food_category=s.food_category,
        analysis_status=s.analysis_status,
        needs_review=s.needs_review,
        review_reason=s.review_reason,
        selected_expiry_date=s.selected_expiry_date,
        error_message=s.error_message,
        raw_json=s.raw_json,
        date_candidates=[DateCandidateItem(**c.to_dict()) for c in (candidates or [])],
        timing=timing,
    )


# ---------------------------------------------------------------------------
# FastAPI App Lifecycle & Factory
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application state, database, Gemini analyzer, and persistent OCR engine."""
    if not hasattr(app.state, "db") or app.state.db is None:
        app.state.db = get_database()
    if not hasattr(app.state, "analyzer") or app.state.analyzer is None:
        app.state.analyzer = GeminiAnalyzer()
    if not hasattr(app.state, "ocr_engine") or app.state.ocr_engine is None:
        try:
            app.state.ocr_engine = AppleVisionOCREngine()
        except Exception as e:
            logger.warning("Could not initialize shared AppleVisionOCREngine: %s", e)
            app.state.ocr_engine = None

    try:
        yield
    finally:
        if hasattr(app.state, "db") and app.state.db is not None:
            try:
                app.state.db.close()
            except Exception:
                pass
        if hasattr(app.state, "ocr_engine") and app.state.ocr_engine is not None:
            try:
                app.state.ocr_engine.shutdown()
            except Exception:
                pass


app = FastAPI(
    title="AnnaRakshak Inventory API",
    description="Local HTTP API for household food inventory tracking and package date intelligence.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------------------------

allowed_origins = get_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception Handlers
# ---------------------------------------------------------------------------

@app.exception_handler(DuplicateProductError)
async def duplicate_product_handler(_: Request, exc: DuplicateProductError):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc), "existing_id": exc.existing_id},
    )


@app.exception_handler(ProductNotFoundError)
async def product_not_found_handler(_: Request, exc: ProductNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.exception_handler(InvalidDateError)
async def invalid_date_handler(_: Request, exc: InvalidDateError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception during %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please consult backend logs."},
    )


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse, tags=["System"])
def health_check(db: InventoryDatabase = Depends(get_db)) -> HealthResponse:
    """Check backend operational health, database connectivity, and item count."""
    try:
        with db._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as count FROM products").fetchone()
            count = row["count"] if row else 0
        return HealthResponse(
            status="ok",
            database="connected",
            total_products=count,
            version="1.0.0",
        )
    except Exception as e:
        logger.error("Database health check failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable.",
        )


@app.get("/api/dashboard", response_model=DashboardResponse, tags=["Dashboard"])
def get_dashboard(
    warning_days: int = Query(default=DEFAULT_WARNING_DAYS, ge=1, le=90),
    db: InventoryDatabase = Depends(get_db),
) -> DashboardResponse:
    """
    Retrieve real-time dashboard metrics:
    Aggregates product statuses, category breakdowns, and scan counters.
    Maintains strict separation between explicit expiry and best-before quality statuses.
    """
    products = db.list_products(sort_by="date")
    ref_date = datetime.date.today()

    expired_count = 0
    expiring_soon_count = 0
    best_before_soon_count = 0
    best_before_passed_count = 0
    safe_count = 0
    needs_review_count = 0
    categories: dict[str, int] = {}

    for p in products:
        stat = p.current_status(ref_date=ref_date, warning_days=warning_days)

        if stat in ("expired", "expires_today"):
            expired_count += 1
        elif stat == "expiring_soon":
            expiring_soon_count += 1
        elif stat in ("best_before_passed", "best_before_today"):
            best_before_passed_count += 1
        elif stat == "best_before_soon":
            best_before_soon_count += 1
        elif stat in ("not_expiring_soon", "best_before_future"):
            safe_count += 1

        if (
            p.date_status in ("unverified", "needs_review")
            or p.date_type == "unknown"
            or p.normalized_date is None
        ):
            needs_review_count += 1

        cat = (p.food_category or "Uncategorized").strip()
        categories[cat] = categories.get(cat, 0) + 1

    total_scans = 0
    try:
        with db._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as count FROM scan_history").fetchone()
            total_scans = row["count"] if row else 0
    except Exception as e:
        logger.warning("Failed to count scan_history: %s", e)

    recent_scans = db.get_recent_scans(limit=5)

    return DashboardResponse(
        total_products=len(products),
        expired_count=expired_count,
        expiring_soon_count=expiring_soon_count,
        best_before_soon_count=best_before_soon_count,
        best_before_passed_count=best_before_passed_count,
        safe_count=safe_count,
        needs_review_count=needs_review_count,
        total_scans=total_scans,
        recent_scans_count=len(recent_scans),
        categories=categories,
    )


@app.get("/api/products", response_model=list[ProductResponse], tags=["Products"])
def list_products(
    status_filter: str | None = Query(default=None, alias="status", description="Filter by stored date_status or computed status"),
    search: str | None = Query(default=None, description="Search term across name, brand, category, notes"),
    category: str | None = Query(default=None, description="Exact or case-insensitive category filter"),
    sort_by: str = Query(default="date", pattern="^(date|name|id)$", description="Sort order: date, name, or id"),
    db: InventoryDatabase = Depends(get_db),
) -> list[ProductResponse]:
    """List products with optional search query, category, and date status filters."""
    ref_date = datetime.date.today()

    if search and search.strip():
        products = db.search_products(search.strip())
    else:
        products = db.list_products(sort_by="date" if sort_by == "date" else "id")

    # Post-filtering for category
    if category and category.strip():
        cat_lower = category.strip().lower()
        products = [p for p in products if p.food_category and p.food_category.lower() == cat_lower]

    # Post-filtering for status
    if status_filter and status_filter.strip():
        s_lower = status_filter.strip().lower()
        filtered = []
        for p in products:
            live_stat = p.current_status(ref_date=ref_date)
            stored_stat = (p.date_status or "").lower()
            if s_lower == "safe":
                if live_stat in ("not_expiring_soon", "best_before_future"):
                    filtered.append(p)
            elif s_lower == "needs_review":
                if stored_stat in ("unverified", "needs_review") or p.normalized_date is None or p.date_type == "unknown":
                    filtered.append(p)
            elif s_lower in (stored_stat, live_stat):
                filtered.append(p)
        products = filtered

    # Sorting
    if sort_by == "name":
        products.sort(key=lambda x: x.product_name.lower())
    elif sort_by == "id":
        products.sort(key=lambda x: x.id, reverse=True)
    elif sort_by == "date":
        # Handled by DB query or stable sort
        products.sort(key=lambda x: (x.normalized_date is None, x.normalized_date or "", x.id))

    return [serialize_product(p, ref_date=ref_date) for p in products]


@app.get("/api/products/{product_id}", response_model=ProductResponse, tags=["Products"])
def get_product(
    product_id: int,
    db: InventoryDatabase = Depends(get_db),
) -> ProductResponse:
    """Retrieve details of a single product by primary key, including candidate dates."""
    p = db.get_product(product_id)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found.",
        )
    candidates = db.get_product_date_candidates(product_id)
    return serialize_product(p, candidates=candidates)


@app.post("/api/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED, tags=["Products"])
def create_product(
    payload: ProductCreate,
    db: InventoryDatabase = Depends(get_db),
) -> ProductResponse:
    """
    Add a new product to inventory.
    Guards against identical duplicates unless force=True is provided.
    """
    product_id = db.add_product(
        product_name=payload.product_name,
        date_type=payload.date_type,
        brand=payload.brand,
        food_category=payload.food_category,
        date_text=payload.date_text,
        normalized_date=payload.normalized_date,
        date_status=payload.date_status,
        date_source=payload.date_source,
        notes=payload.notes,
        force=payload.force,
    )
    p = db.get_product(product_id)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve newly created product.",
        )
    return serialize_product(p)


@app.patch("/api/products/{product_id}", response_model=ProductResponse, tags=["Products"])
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: InventoryDatabase = Depends(get_db),
) -> ProductResponse:
    """
    Update editable product fields.
    If normalized_date or date_type is updated, uses confirm_product_date to maintain
    rigorous date transition semantics.
    """
    existing = db.get_product(product_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found.",
        )

    # 1. Update date if normalized_date or date_type is provided
    date_changed = (payload.normalized_date is not None) or (payload.date_type is not None)
    if date_changed:
        target_norm = payload.normalized_date if payload.normalized_date is not None else existing.normalized_date
        target_type = payload.date_type if payload.date_type is not None else existing.date_type
        db.confirm_product_date(
            product_id=product_id,
            normalized_date=target_norm,
            date_type=target_type,
            notes=payload.notes,
        )

    # 2. Update descriptive metadata
    update_fields: dict[str, Any] = {}
    if payload.product_name is not None:
        update_fields["product_name"] = payload.product_name
    if payload.brand is not None:
        update_fields["brand"] = payload.brand
    if payload.food_category is not None:
        update_fields["food_category"] = payload.food_category
    if payload.image_path is not None:
        update_fields["image_path"] = payload.image_path
    if payload.notes is not None and not date_changed:
        # If date wasn't updated, update notes directly
        update_fields["notes"] = payload.notes

    if update_fields:
        db.update_product(product_id, **update_fields)

    updated = db.get_product(product_id)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found.",
        )
    candidates = db.get_product_date_candidates(product_id)
    return serialize_product(updated, candidates=candidates)


@app.delete("/api/products/{product_id}", response_model=DeleteResponse, tags=["Products"])
def delete_product(
    product_id: int,
    db: InventoryDatabase = Depends(get_db),
) -> DeleteResponse:
    """
    Delete a product from inventory.
    Follows database semantics: cascades candidate dates tied to this product,
    while strictly preserving scan_history and scan-level evidence.
    """
    db.delete_product(product_id)
    return DeleteResponse(
        success=True,
        message=f"Product {product_id} successfully deleted.",
        deleted_id=product_id,
    )


@app.get("/api/scans", response_model=list[ScanResponse], tags=["Scans"])
def list_scans(
    limit: int = Query(default=20, ge=1, le=100, description="Maximum number of scans to return"),
    db: InventoryDatabase = Depends(get_db),
) -> list[ScanResponse]:
    """Retrieve recent package scans in reverse chronological order."""
    scans = db.get_recent_scans(limit=limit)
    return [serialize_scan(s) for s in scans]


@app.get("/api/scans/{scan_id}", response_model=ScanResponse, tags=["Scans"])
def get_scan(
    scan_id: int,
    db: InventoryDatabase = Depends(get_db),
) -> ScanResponse:
    """Retrieve a single scan record with its associated candidate dates."""
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan with ID {scan_id} not found.",
        )
    candidates = db.get_scan_date_candidates(scan_id)
    return serialize_scan(scan, candidates=candidates)


@app.get("/api/scans/{scan_id}/date-candidates", response_model=list[DateCandidateItem], tags=["Scans"])
def get_scan_date_candidates(
    scan_id: int,
    db: InventoryDatabase = Depends(get_db),
) -> list[DateCandidateItem]:
    """Retrieve printed date candidate evidence extracted during a specific scan."""
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan with ID {scan_id} not found.",
        )
    candidates = db.get_scan_date_candidates(scan_id)
    return [DateCandidateItem(**c.to_dict()) for c in candidates]


@app.post("/api/scans/{scan_id}/reanalyze", response_model=ScanResponse, tags=["Scans"])
async def reanalyze_scan(
    scan_id: int,
    request: Request,
    db: InventoryDatabase = Depends(get_db),
    analyzer: GeminiAnalyzer = Depends(get_analyzer),
) -> ScanResponse:
    """
    Re-run Gemini image analysis on an existing saved scan capture.
    Executes asynchronously in a worker thread so the API event loop remains responsive.
    Updates scan_history and candidate dates in place without creating duplicate scans.
    """
    t0 = time.perf_counter()
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan with ID {scan_id} not found.",
        )

    img_path = Path(scan.image_path)
    if not img_path.exists() or not img_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scan image capture does not exist or is inaccessible on disk: {scan.image_path}",
        )

    # Optional local OCR if available
    shared_ocr = getattr(request.app.state, "ocr_engine", None)
    ocr_text = None
    t_ocr_0 = time.perf_counter()
    try:
        frame_bgr = cv2.imread(str(img_path))
        if frame_bgr is not None:
            ocr_res = await asyncio.to_thread(run_local_ocr, frame_bgr, shared_ocr)
            if ocr_res and ocr_res.has_text:
                ocr_text = ocr_res.summary_text
    except Exception:
        pass
    ocr_ms = (time.perf_counter() - t_ocr_0) * 1000.0

    # Offload analysis to worker thread to avoid blocking FastAPI event loop
    t_gem_0 = time.perf_counter()
    if ocr_text:
        result: FoodAnalysisResult = await asyncio.to_thread(analyzer.analyze_image, str(img_path), ocr_text=ocr_text)
    else:
        result: FoodAnalysisResult = await asyncio.to_thread(analyzer.analyze_image, str(img_path))
    gemini_ms = (time.perf_counter() - t_gem_0) * 1000.0

    t_db_0 = time.perf_counter()
    error_message = result.review_reason if result.analysis_status == "error" else None
    db.update_scan(scan_id, result=result, error_message=error_message)
    db_ms = (time.perf_counter() - t_db_0) * 1000.0
    total_ms = (time.perf_counter() - t0) * 1000.0

    updated_scan = db.get_scan(scan_id)
    if not updated_scan:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve updated scan after reanalysis.",
        )
    candidates = db.get_scan_date_candidates(scan_id)
    timing_meta = ScanTiming(
        upload_preprocess_ms=0.0,
        ocr_ms=round(ocr_ms, 2),
        gemini_ms=round(gemini_ms, 2),
        db_ms=round(db_ms, 2),
        total_ms=round(total_ms, 2),
        models_attempted=result.models_attempted,
        retries_count=result.retries_count,
    )
    logger.info(
        "Scan %d reanalyzed in %.1fms (ocr=%.1fms, gemini=%.1fms, db=%.1fms, models=%s, retries=%d)",
        scan_id, total_ms, ocr_ms, gemini_ms, db_ms, result.models_attempted, result.retries_count
    )
    return serialize_scan(updated_scan, candidates=candidates, timing=timing_meta)


def run_local_ocr(frame_bgr: np.ndarray, engine: AppleVisionOCREngine | None = None) -> OCRResult | None:
    """Run local Apple Vision OCR if available, reusing shared engine instance when provided."""
    try:
        active_engine = engine or AppleVisionOCREngine()
        result = active_engine.detect_text(frame_bgr)
        if engine is None:
            active_engine.shutdown()
        return result
    except Exception as e:
        logger.debug("Local Apple Vision OCR detection pass skipped/failed: %s", e)
        return None


@app.post("/api/scans", response_model=ScanResponse, status_code=status.HTTP_201_CREATED, tags=["Scans"])
async def create_scan(
    request: Request,
    db: InventoryDatabase = Depends(get_db),
    analyzer: GeminiAnalyzer = Depends(get_analyzer),
) -> ScanResponse:
    """
    Process a newly captured or uploaded packaging image.
    Validates image data, optimizes resolution, saves the frame to captures/,
    runs local OCR and Gemini AI analysis asynchronously, and stores the results and
    candidate dates in SQLite with structured latency metrics.
    """
    t_total_0 = time.perf_counter()
    t_prep_0 = time.perf_counter()

    content_type = request.headers.get("content-type", "")
    image_bytes: bytes = b""

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_file = form.get("image") or form.get("file")
        if not uploaded_file or not hasattr(uploaded_file, "read"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multipart request must include an 'image' or 'file' field.",
            )
        image_bytes = await uploaded_file.read()
    elif "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed JSON body.",
            )
        raw_val = body.get("image") or body.get("image_base64") or body.get("image_data")
        if not raw_val or not isinstance(raw_val, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON request must contain an 'image' or 'image_base64' string.",
            )
        if "base64," in raw_val:
            raw_val = raw_val.split("base64,")[1]
        try:
            image_bytes = base64.b64decode(raw_val)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid base64 image data: {e}",
            )
    else:
        body = await request.body()
        if body:
            image_bytes = body
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request must be multipart/form-data with 'image' file or application/json with 'image' string.",
            )

    # 1. Size Validation (Max 15 MB)
    if len(image_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image is empty (0 bytes).",
        )
    max_size = 15 * 1024 * 1024
    if len(image_bytes) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image file too large. Maximum allowed size is 15 MB.",
        )

    # 2. Image Decode & Validation
    frame_bgr = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame_bgr is None or frame_bgr.size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image data. File could not be decoded as an image (JPEG, PNG, WebP supported).",
        )

    # 3. Optimize image resolution for fast processing while preserving 100% OCR sharpness
    h, w = frame_bgr.shape[:2]
    max_dim = max(h, w)
    if max_dim > 1600:
        scale = 1600.0 / max_dim
        new_w = int(w * scale)
        new_h = int(h * scale)
        frame_bgr = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # Re-encode as JPEG (quality 85) for efficient disk storage and AI network transfer
    success, encoded_jpg = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if success:
        optimized_bytes = encoded_jpg.tobytes()
    else:
        optimized_bytes = image_bytes

    # Save to environment-aware captures directory
    captures_dir = get_captures_dir()
    try:
        captures_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("Failed to create captures directory at %s: %s", captures_dir, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to initialize image capture directory: {e}",
        )

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_tag = uuid.uuid4().hex[:6]
    image_filename = f"scan_{timestamp_str}_{unique_tag}.jpg"
    image_path = captures_dir / image_filename

    cleanup_needed = should_cleanup_captures()
    image_written = False

    try:
        image_path.write_bytes(optimized_bytes)
        image_written = True

        upload_preprocess_ms = (time.perf_counter() - t_prep_0) * 1000.0

        # 4. Local OCR Pass (reusing shared persistent Apple Vision engine)
        t_ocr_0 = time.perf_counter()
        shared_ocr = getattr(request.app.state, "ocr_engine", None)
        ocr_result = await asyncio.to_thread(run_local_ocr, frame_bgr, shared_ocr)
        ocr_ms = (time.perf_counter() - t_ocr_0) * 1000.0
        ocr_text = ocr_result.summary_text if (ocr_result and ocr_result.has_text) else None
        if ocr_text:
            logger.info("Local OCR extracted text (%d regions): %s", len(ocr_result.regions), ocr_text[:120])

        # 5. Gemini AI Analysis (asynchronous in worker thread with OCR context)
        t_gem_0 = time.perf_counter()
        if ocr_text:
            result: FoodAnalysisResult = await asyncio.to_thread(analyzer.analyze_image, str(image_path), ocr_text=ocr_text)
        else:
            result: FoodAnalysisResult = await asyncio.to_thread(analyzer.analyze_image, str(image_path))
        gemini_ms = (time.perf_counter() - t_gem_0) * 1000.0

        # 6. Record to Database
        t_db_0 = time.perf_counter()
        error_message = result.review_reason if result.analysis_status == "error" else None
        scan_id = db.record_scan(
            image_path=str(image_path),
            result=result,
            error_message=error_message,
        )
        db_ms = (time.perf_counter() - t_db_0) * 1000.0
        total_ms = (time.perf_counter() - t_total_0) * 1000.0

        created_scan = db.get_scan(scan_id)
        if not created_scan:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve scan after saving to database.",
            )
        candidates = db.get_scan_date_candidates(scan_id)

        timing_meta = ScanTiming(
            upload_preprocess_ms=round(upload_preprocess_ms, 2),
            ocr_ms=round(ocr_ms, 2),
            gemini_ms=round(gemini_ms, 2),
            db_ms=round(db_ms, 2),
            total_ms=round(total_ms, 2),
            models_attempted=result.models_attempted,
            retries_count=result.retries_count,
        )

        logger.info(
            "Scan %d completed in %.1fms (preprocess=%.1fms, ocr=%.1fms, gemini=%.1fms, db=%.1fms, models=%s, retries=%d)",
            scan_id, total_ms, upload_preprocess_ms, ocr_ms, gemini_ms, db_ms, result.models_attempted, result.retries_count
        )

        return serialize_scan(created_scan, candidates=candidates, timing=timing_meta)
    finally:
        if cleanup_needed and image_written:
            _safe_remove_file(image_path)


@app.get("/api/scans/{scan_id}/image", tags=["Scans"])
def get_scan_image(
    scan_id: int,
    db: InventoryDatabase = Depends(get_db),
) -> FileResponse:
    """Retrieve the original captured image file for a given scan."""
    scan = db.get_scan(scan_id)
    if not scan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan with ID {scan_id} not found.",
        )
    img_path = Path(scan.image_path)
    if not img_path.exists() or not img_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan image file not found on disk: {scan.image_path}",
        )
    ext = img_path.suffix.lower()
    media_type = "image/jpeg"
    if ext == ".png":
        media_type = "image/png"
    elif ext == ".webp":
        media_type = "image/webp"
    return FileResponse(path=str(img_path), media_type=media_type)


@app.get("/api/alerts", response_model=list[AlertItem], tags=["Alerts"])
def get_alerts(
    warning_days: int = Query(default=DEFAULT_WARNING_DAYS, ge=1, le=90, description="Warning threshold in days"),
    db: InventoryDatabase = Depends(get_db),
) -> list[AlertItem]:
    """
    Retrieve prioritized list of items requiring user attention:
      - Critical: expired, best-before date passed, expires/BB today.
      - Warning: expiring soon, best-before date approaching.
      - Info: unverified dates, missing dates, or items requiring manual review.
    Sorted by urgency and remaining shelf life.
    """
    products = db.list_products(sort_by="date")
    ref_date = datetime.date.today()
    alerts: list[AlertItem] = []

    for p in products:
        stat = p.current_status(ref_date=ref_date, warning_days=warning_days)
        days: int | None = None
        if p.normalized_date:
            try:
                target = datetime.date.fromisoformat(p.normalized_date)
                days = (target - ref_date).days
            except ValueError:
                days = None

        if stat == "expired":
            alerts.append(
                AlertItem(
                    product_id=p.id,
                    product_name=p.product_name,
                    brand=p.brand,
                    food_category=p.food_category,
                    date_type=p.date_type,
                    normalized_date=p.normalized_date,
                    date_status=stat,
                    urgency="critical",
                    message=f"Expired {abs(days)} day(s) ago ({p.normalized_date})" if days is not None else "Product has expired",
                    days_remaining=days,
                )
            )
        elif stat == "expires_today":
            alerts.append(
                AlertItem(
                    product_id=p.id,
                    product_name=p.product_name,
                    brand=p.brand,
                    food_category=p.food_category,
                    date_type=p.date_type,
                    normalized_date=p.normalized_date,
                    date_status=stat,
                    urgency="critical",
                    message="Expires today! Use immediately",
                    days_remaining=0,
                )
            )
        elif stat == "best_before_passed":
            alerts.append(
                AlertItem(
                    product_id=p.id,
                    product_name=p.product_name,
                    brand=p.brand,
                    food_category=p.food_category,
                    date_type=p.date_type,
                    normalized_date=p.normalized_date,
                    date_status=stat,
                    urgency="critical",
                    message=f"Best-before quality date passed {abs(days)} day(s) ago ({p.normalized_date})" if days is not None else "Best-before quality date passed",
                    days_remaining=days,
                )
            )
        elif stat == "best_before_today":
            alerts.append(
                AlertItem(
                    product_id=p.id,
                    product_name=p.product_name,
                    brand=p.brand,
                    food_category=p.food_category,
                    date_type=p.date_type,
                    normalized_date=p.normalized_date,
                    date_status=stat,
                    urgency="critical",
                    message="Best-before date is today",
                    days_remaining=0,
                )
            )
        elif stat == "expiring_soon":
            alerts.append(
                AlertItem(
                    product_id=p.id,
                    product_name=p.product_name,
                    brand=p.brand,
                    food_category=p.food_category,
                    date_type=p.date_type,
                    normalized_date=p.normalized_date,
                    date_status=stat,
                    urgency="warning",
                    message=f"Expires in {days} day(s) ({p.normalized_date})",
                    days_remaining=days,
                )
            )
        elif stat == "best_before_soon":
            alerts.append(
                AlertItem(
                    product_id=p.id,
                    product_name=p.product_name,
                    brand=p.brand,
                    food_category=p.food_category,
                    date_type=p.date_type,
                    normalized_date=p.normalized_date,
                    date_status=stat,
                    urgency="warning",
                    message=f"Best-before approaching in {days} day(s) ({p.normalized_date})",
                    days_remaining=days,
                )
            )
        elif (
            p.date_status in ("unverified", "needs_review")
            or p.date_type == "unknown"
            or p.normalized_date is None
        ):
            alerts.append(
                AlertItem(
                    product_id=p.id,
                    product_name=p.product_name,
                    brand=p.brand,
                    food_category=p.food_category,
                    date_type=p.date_type,
                    normalized_date=p.normalized_date,
                    date_status="needs_review",
                    urgency="info",
                    message="Date unconfirmed or missing; manual review required",
                    days_remaining=None,
                )
            )

    # Sort: critical first, then warning, then info; then by days_remaining ascending
    urgency_rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(
        key=lambda a: (
            urgency_rank.get(a.urgency, 99),
            a.days_remaining if a.days_remaining is not None else 999999,
            a.product_id,
        )
    )

    return alerts


# ---------------------------------------------------------------------------
# Development Server Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    logger.info("Starting AnnaRakshak API on %s:%d", host, port)
    uvicorn.run("api:app", host=host, port=port, reload=False)
