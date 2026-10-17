"""
AnnaRakshak — SQLite Food Inventory Persistence Layer
======================================================
Provides local SQLite storage for scanned products, printed date candidates,
and scan history.

Key Architecture Principles:
  1. 100% LOCAL: Stored at project-local `annarakshak.db`. Zero cloud databases.
  2. SAFETY FIRST: Scans with `needs_review=True` or uncertain dates remain
     unconfirmed until explicit user confirmation.
  3. ZERO SILENT CONVERSIONS: Manufacturing and packed dates are NEVER converted
     into expiry dates. Best-before dates are preserved as distinct quality dates.
  4. NO HALLUCINATIONS: Shelf-life wording is never synthetically calculated
     into dates in this milestone.
  5. ROBUST CONCURRENCY: Uses WAL mode, parameterized queries, and transactions.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import os
import sqlite3
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Generator

try:
    import psycopg2
    import psycopg2.extras
    from psycopg2.pool import ThreadedConnectionPool
    PSYCOPG2_AVAILABLE = True
except ImportError:
    psycopg2 = None
    psycopg2_extras = None
    ThreadedConnectionPool = None
    PSYCOPG2_AVAILABLE = False

logger = logging.getLogger("AnnaRakshak.InventoryDB")

DEFAULT_DB_PATH = (Path(__file__).parent / "annarakshak.db").resolve()
DEFAULT_WARNING_DAYS = 7


def mask_database_url(url: str | None) -> str:
    """Mask password credentials in a database connection URL for safe logging."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.password:
            netloc = f"{parsed.username}:****@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        pass
    return "postgresql://****"


class DuplicateProductError(Exception):
    """Raised when an attempt is made to add an identical product without explicit confirmation."""
    def __init__(self, message: str, existing_id: int) -> None:
        super().__init__(message)
        self.existing_id = existing_id


class ProductNotFoundError(Exception):
    """Raised when a product with the requested ID does not exist."""
    pass


class InvalidDateError(Exception):
    """Raised when an invalid or malformed date string is provided."""
    pass


# ---------------------------------------------------------------------------
# Date Status Calculation
# ---------------------------------------------------------------------------

def calculate_date_status(
    normalized_date: str | None,
    date_type: str,
    ref_date: datetime.date | None = None,
    warning_days: int = DEFAULT_WARNING_DAYS,
) -> str:
    """
    Pure, deterministic function to calculate the expiry/shelf-life status of an item.

    Parameters:
      normalized_date: ISO format YYYY-MM-DD or None.
      date_type: One of 'expiry', 'use_by', 'best_before', 'manufacturing', 'packed_on', 'unknown'.
      ref_date: Optional reference date (defaults to today's local date).
      warning_days: Threshold in days to consider an item 'expiring_soon' (default 7).

    Returns:
      For 'expiry' and 'use_by':
        - 'expired': date < ref_date
        - 'expires_today': date == ref_date
        - 'expiring_soon': ref_date < date <= ref_date + warning_days (inclusive)
        - 'not_expiring_soon': date > ref_date + warning_days
      For 'best_before' (distinct quality guarantee status):
        - 'best_before_passed': date < ref_date
        - 'best_before_today': date == ref_date
        - 'best_before_soon': ref_date < date <= ref_date + warning_days
        - 'best_before_future': date > ref_date + warning_days
      For 'manufacturing' and 'packed_on':
        - 'not_an_expiry_date'
      For missing, invalid, or 'unknown':
        - 'unknown'
    """
    if not normalized_date or not normalized_date.strip():
        return "unknown"

    clean_date_type = (date_type or "unknown").strip().lower()

    # Manufacturing & packing dates must never be calculated as expiry
    if clean_date_type in ("manufacturing", "packed_on"):
        return "not_an_expiry_date"

    if clean_date_type == "unknown":
        return "unknown"

    # Strict ISO date validation
    try:
        parts = normalized_date.strip().split("-")
        if len(parts) != 3 or len(parts[0]) != 4:
            return "unknown"
        target_date = datetime.date.fromisoformat(normalized_date.strip())
    except (ValueError, TypeError):
        return "unknown"

    if ref_date is None:
        ref_date = datetime.date.today()

    diff_days = (target_date - ref_date).days

    # Distinct Best-Before classification
    if clean_date_type == "best_before":
        if diff_days < 0:
            return "best_before_passed"
        if diff_days == 0:
            return "best_before_today"
        if 0 < diff_days <= warning_days:
            return "best_before_soon"
        return "best_before_future"

    # Explicit Expiry / Use-By classification
    if clean_date_type in ("expiry", "use_by"):
        if diff_days < 0:
            return "expired"
        if diff_days == 0:
            return "expires_today"
        if 0 < diff_days <= warning_days:
            return "expiring_soon"
        return "not_expiring_soon"

    return "unknown"


# ---------------------------------------------------------------------------
# Data Records (Dataclasses)
# ---------------------------------------------------------------------------

@dataclass
class DateCandidateRecord:
    id: int | None
    product_id: int | None
    scan_id: int | None
    raw_text: str
    date_type: str
    normalized_date: str | None
    confidence: float
    evidence: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductRecord:
    id: int
    product_name: str
    brand: str | None
    food_category: str | None
    date_type: str
    date_text: str | None
    normalized_date: str | None
    date_status: str
    date_source: str
    analysis_status: str | None
    image_path: str | None
    notes: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def current_status(self, ref_date: datetime.date | None = None, warning_days: int = DEFAULT_WARNING_DAYS) -> str:
        """Calculate live status against today's or injected calendar date."""
        return calculate_date_status(self.normalized_date, self.date_type, ref_date, warning_days)


@dataclass
class ScanHistoryRecord:
    id: int
    timestamp: str
    image_path: str
    product_name: str | None
    brand: str | None
    food_category: str | None
    analysis_status: str
    needs_review: bool
    review_reason: str | None
    selected_expiry_date: str | None
    error_message: str | None
    raw_json: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Database Schemas & Connection Wrappers
# ---------------------------------------------------------------------------

SQLITE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        brand TEXT,
        food_category TEXT,
        date_type TEXT NOT NULL,
        date_text TEXT,
        normalized_date TEXT,
        date_status TEXT NOT NULL DEFAULT 'unverified',
        date_source TEXT NOT NULL DEFAULT 'printed',
        analysis_status TEXT,
        image_path TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        image_path TEXT NOT NULL,
        product_name TEXT,
        brand TEXT,
        food_category TEXT,
        analysis_status TEXT NOT NULL,
        needs_review INTEGER NOT NULL DEFAULT 0,
        review_reason TEXT,
        selected_expiry_date TEXT,
        error_message TEXT,
        raw_json TEXT
    );

    CREATE TABLE IF NOT EXISTS date_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        scan_id INTEGER,
        raw_text TEXT NOT NULL,
        date_type TEXT NOT NULL,
        normalized_date TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        evidence TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY (scan_id) REFERENCES scan_history(id) ON DELETE SET NULL
    );

    CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);
    CREATE INDEX IF NOT EXISTS idx_products_date ON products(normalized_date);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(food_category);
    CREATE INDEX IF NOT EXISTS idx_date_candidates_product ON date_candidates(product_id);
    CREATE INDEX IF NOT EXISTS idx_date_candidates_scan ON date_candidates(scan_id);
    CREATE INDEX IF NOT EXISTS idx_scan_history_timestamp ON scan_history(timestamp);
"""

POSTGRES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        product_name TEXT NOT NULL,
        brand TEXT,
        food_category TEXT,
        date_type TEXT NOT NULL,
        date_text TEXT,
        normalized_date TEXT,
        date_status TEXT NOT NULL DEFAULT 'unverified',
        date_source TEXT NOT NULL DEFAULT 'printed',
        analysis_status TEXT,
        image_path TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS scan_history (
        id SERIAL PRIMARY KEY,
        timestamp TEXT NOT NULL,
        image_path TEXT NOT NULL,
        product_name TEXT,
        brand TEXT,
        food_category TEXT,
        analysis_status TEXT NOT NULL,
        needs_review INTEGER NOT NULL DEFAULT 0,
        review_reason TEXT,
        selected_expiry_date TEXT,
        error_message TEXT,
        raw_json TEXT
    );

    CREATE TABLE IF NOT EXISTS date_candidates (
        id SERIAL PRIMARY KEY,
        product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
        scan_id INTEGER REFERENCES scan_history(id) ON DELETE SET NULL,
        raw_text TEXT NOT NULL,
        date_type TEXT NOT NULL,
        normalized_date TEXT,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        evidence TEXT,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);
    CREATE INDEX IF NOT EXISTS idx_products_date ON products(normalized_date);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(food_category);
    CREATE INDEX IF NOT EXISTS idx_date_candidates_product ON date_candidates(product_id);
    CREATE INDEX IF NOT EXISTS idx_date_candidates_scan ON date_candidates(scan_id);
    CREATE INDEX IF NOT EXISTS idx_scan_history_timestamp ON scan_history(timestamp);
"""


class PostgresConnectionWrapper:
    """Wrapper around psycopg2 connection providing sqlite3-compatible .execute() syntax."""

    def __init__(self, raw_conn: Any) -> None:
        self._conn = raw_conn
        self._last_cursor: Any = None

    def execute(self, sql: str, params: tuple | list | None = None) -> Any:
        pg_sql = sql.replace("?", "%s")
        if " LIKE " in pg_sql and " ILIKE " not in pg_sql:
            pg_sql = pg_sql.replace(" LIKE ", " ILIKE ")
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        self._last_cursor = cursor
        cursor.execute(pg_sql, params or ())
        return cursor

    def executescript(self, sql_script: str) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(sql_script)

    @property
    def lastrowid(self) -> int | None:
        if self._last_cursor:
            return getattr(self._last_cursor, "lastrowid", None)
        return None

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Inventory Database (SQLite & PostgreSQL)
# ---------------------------------------------------------------------------

class InventoryDatabase:
    """
    Thread-safe repository supporting local SQLite storage and hosted PostgreSQL (e.g. Neon).
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        database_url: str | None = None,
    ) -> None:
        self._pool: Any = None

        if database_url is not None:
            self.is_postgres = True
            self.database_url = database_url.strip()
            self.db_path = None
        elif db_path is not None:
            self.is_postgres = False
            self.database_url = None
            self.db_path = Path(db_path).resolve()
        else:
            env_db_url = os.getenv("DATABASE_URL") or os.getenv("ANNARAKSHAK_DATABASE_URL")
            if env_db_url and env_db_url.strip():
                self.is_postgres = True
                self.database_url = env_db_url.strip()
                self.db_path = None
            else:
                self.is_postgres = False
                self.database_url = None
                raw_path = os.getenv("ANNARAKSHAK_DB_PATH", str(DEFAULT_DB_PATH))
                self.db_path = Path(raw_path).resolve()

        if self.is_postgres:
            if not PSYCOPG2_AVAILABLE:
                raise RuntimeError(
                    "psycopg2 is required for PostgreSQL operation. Please install psycopg2-binary."
                )
            self._init_postgres_pool()
        else:
            assert self.db_path is not None
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("Could not create parent directory for %s: %s", self.db_path, e)

        self.init_db()

    def _get_clean_dsn(self) -> str:
        dsn = self.database_url or ""
        if "sslmode=" not in dsn and any(h in dsn for h in ("neon.tech", "supabase.co", "amazonaws.com", "render.com")):
            sep = "&" if "?" in dsn else "?"
            dsn = f"{dsn}{sep}sslmode=require"
        if dsn.startswith("postgres://"):
            dsn = "postgresql://" + dsn[len("postgres://"):]
        return dsn

    def _init_postgres_pool(self) -> None:
        dsn = self._get_clean_dsn()
        logger.info("Initializing PostgreSQL connection pool (%s)", mask_database_url(dsn))
        self._pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)

    @contextlib.contextmanager
    def _get_connection(self) -> Generator[Any, None, None]:
        """Establish a connection managing transactions and lifecycle across SQLite or PostgreSQL."""
        if self.is_postgres:
            conn = None
            try:
                conn = self._pool.getconn()
                if conn.closed:
                    conn = self._pool._connect()
                else:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
            except Exception:
                try:
                    if conn:
                        self._pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = psycopg2.connect(self._get_clean_dsn())

            wrapped = PostgresConnectionWrapper(conn)
            try:
                yield wrapped
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                try:
                    self._pool.putconn(conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
        else:
            assert self.db_path is not None
            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            try:
                with conn:
                    yield conn
            finally:
                conn.close()

    def init_db(self) -> None:
        """Create tables and indexes idempotently."""
        if self.is_postgres:
            with self._get_connection() as conn:
                conn.executescript(POSTGRES_SCHEMA)
        else:
            assert self.db_path is not None
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("Could not create parent directory for %s: %s", self.db_path, e)
            with self._get_connection() as conn:
                conn.executescript(SQLITE_SCHEMA)

    def close(self) -> None:
        """Release open connections and connection pools."""
        if self.is_postgres and self._pool is not None:
            try:
                self._pool.closeall()
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Scan History Operations
    # -----------------------------------------------------------------------

    def record_scan(
        self,
        image_path: str,
        result: Any | None = None,
        error_message: str | None = None,
    ) -> int:
        """
        Record a scan attempt from Gemini analyzer into scan_history.
        Also records associated date candidates if present.
        Returns the created scan_history ID.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        product_name = None
        brand = None
        food_category = None
        analysis_status = "error" if error_message else "unknown"
        needs_review = 1
        review_reason = None
        selected_expiry_date = None
        raw_json = None
        candidates = []

        if result is not None:
            product_name = getattr(result, "product_name", None)
            brand = getattr(result, "brand", None)
            food_category = getattr(result, "food_category", None)
            analysis_status = getattr(result, "analysis_status", "unknown")
            needs_review = 1 if getattr(result, "needs_review", True) else 0
            review_reason = getattr(result, "review_reason", None)
            selected_expiry_date = getattr(result, "selected_expiry_date", None)
            if hasattr(result, "model_dump_json"):
                raw_json = result.model_dump_json()
            candidates = getattr(result, "date_candidates", []) or []

        with self._get_connection() as conn:
            if self.is_postgres:
                cursor = conn.execute(
                    """
                    INSERT INTO scan_history (
                        timestamp, image_path, product_name, brand, food_category,
                        analysis_status, needs_review, review_reason, selected_expiry_date,
                        error_message, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        now, str(image_path), product_name, brand, food_category,
                        analysis_status, needs_review, review_reason, selected_expiry_date,
                        error_message, raw_json,
                    ),
                )
                row = cursor.fetchone()
                scan_id = row[0]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO scan_history (
                        timestamp, image_path, product_name, brand, food_category,
                        analysis_status, needs_review, review_reason, selected_expiry_date,
                        error_message, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now, str(image_path), product_name, brand, food_category,
                        analysis_status, needs_review, review_reason, selected_expiry_date,
                        error_message, raw_json,
                    ),
                )
                scan_id = cursor.lastrowid
            assert scan_id is not None

            # Record candidate dates attached to this scan
            for c in candidates:
                raw_text = getattr(c, "raw_text", "")
                date_type = getattr(c, "date_type", "unknown")
                normalized_date = getattr(c, "normalized_date", None)
                confidence = float(getattr(c, "confidence", 1.0))
                evidence = getattr(c, "evidence", "")
                conn.execute(
                    """
                    INSERT INTO date_candidates (
                        product_id, scan_id, raw_text, date_type,
                        normalized_date, confidence, evidence, created_at
                    ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (scan_id, raw_text, date_type, normalized_date, confidence, evidence, now),
                )

            return scan_id

    def get_recent_scans(self, limit: int = 20) -> list[ScanHistoryRecord]:
        """Retrieve recent scans ordered by timestamp descending."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, image_path, product_name, brand, food_category,
                       analysis_status, needs_review, review_reason, selected_expiry_date,
                       error_message, raw_json
                FROM scan_history
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                ScanHistoryRecord(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    image_path=r["image_path"],
                    product_name=r["product_name"],
                    brand=r["brand"],
                    food_category=r["food_category"],
                    analysis_status=r["analysis_status"],
                    needs_review=bool(r["needs_review"]),
                    review_reason=r["review_reason"],
                    selected_expiry_date=r["selected_expiry_date"],
                    error_message=r["error_message"],
                    raw_json=r["raw_json"],
                )
                for r in rows
            ]

    def get_scan(self, scan_id: int) -> ScanHistoryRecord | None:
        """Retrieve single scan record by ID."""
        with self._get_connection() as conn:
            r = conn.execute(
                """
                SELECT id, timestamp, image_path, product_name, brand, food_category,
                       analysis_status, needs_review, review_reason, selected_expiry_date,
                       error_message, raw_json
                FROM scan_history WHERE id = ?
                """,
                (scan_id,),
            ).fetchone()
            if not r:
                return None
            return ScanHistoryRecord(
                id=r["id"],
                timestamp=r["timestamp"],
                image_path=r["image_path"],
                product_name=r["product_name"],
                brand=r["brand"],
                food_category=r["food_category"],
                analysis_status=r["analysis_status"],
                needs_review=bool(r["needs_review"]),
                review_reason=r["review_reason"],
                selected_expiry_date=r["selected_expiry_date"],
                error_message=r["error_message"],
                raw_json=r["raw_json"],
            )

    def update_scan(
        self,
        scan_id: int,
        result: Any | None = None,
        error_message: str | None = None,
    ) -> bool:
        """
        Update an existing scan history record and its candidate dates after reanalysis.
        """
        existing = self.get_scan(scan_id)
        if not existing:
            return False

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        product_name = None
        brand = None
        food_category = None
        analysis_status = "error" if error_message else "unknown"
        needs_review = 1
        review_reason = None
        selected_expiry_date = None
        raw_json = None
        candidates = []

        if result is not None:
            product_name = getattr(result, "product_name", None)
            brand = getattr(result, "brand", None)
            food_category = getattr(result, "food_category", None)
            analysis_status = getattr(result, "analysis_status", "unknown")
            needs_review = 1 if getattr(result, "needs_review", True) else 0
            review_reason = getattr(result, "review_reason", None)
            selected_expiry_date = getattr(result, "selected_expiry_date", None)
            if hasattr(result, "model_dump_json"):
                raw_json = result.model_dump_json()
            candidates = getattr(result, "date_candidates", []) or []

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE scan_history
                SET timestamp = ?, product_name = ?, brand = ?, food_category = ?,
                    analysis_status = ?, needs_review = ?, review_reason = ?,
                    selected_expiry_date = ?, error_message = ?, raw_json = ?
                WHERE id = ?
                """,
                (
                    now, product_name, brand, food_category,
                    analysis_status, needs_review, review_reason,
                    selected_expiry_date, error_message, raw_json,
                    scan_id,
                ),
            )
            # Remove previous candidates for this scan and insert fresh ones
            conn.execute("DELETE FROM date_candidates WHERE scan_id = ?", (scan_id,))
            for c in candidates:
                raw_text = getattr(c, "raw_text", "")
                date_type = getattr(c, "date_type", "unknown")
                normalized_date = getattr(c, "normalized_date", None)
                confidence = float(getattr(c, "confidence", 1.0))
                evidence = getattr(c, "evidence", "")
                conn.execute(
                    """
                    INSERT INTO date_candidates (
                        product_id, scan_id, raw_text, date_type,
                        normalized_date, confidence, evidence, created_at
                    ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (scan_id, raw_text, date_type, normalized_date, confidence, evidence, now),
                )
            return True

    # -----------------------------------------------------------------------
    # Product Inventory Operations
    # -----------------------------------------------------------------------

    def find_potential_duplicates(
        self,
        product_name: str,
        brand: str | None = None,
        normalized_date: str | None = None,
    ) -> list[ProductRecord]:
        """
        Check for existing products with matching name, brand, and normalized_date.
        Case-insensitive match on product_name.
        """
        query = "SELECT * FROM products WHERE LOWER(product_name) = LOWER(?)"
        params: list[Any] = [product_name.strip()]

        if brand is not None:
            query += " AND (LOWER(brand) = LOWER(?) OR (brand IS NULL AND ? IS NULL))"
            params.extend([brand.strip(), brand])

        if normalized_date is not None:
            query += " AND (normalized_date = ? OR (normalized_date IS NULL AND ? IS NULL))"
            params.extend([normalized_date.strip(), normalized_date])

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_product(r) for r in rows]

    def add_product(
        self,
        product_name: str,
        date_type: str = "unknown",
        brand: str | None = None,
        food_category: str | None = None,
        date_text: str | None = None,
        normalized_date: str | None = None,
        date_status: str = "unverified",
        date_source: str = "printed",
        analysis_status: str | None = None,
        image_path: str | None = None,
        notes: str | None = None,
        candidate_dates: list[Any] | None = None,
        force: bool = False,
    ) -> int:
        """
        Add a verified or user-confirmed product into the inventory.
        Validates date format and guards against duplicate entries unless force=True.
        """
        clean_name = product_name.strip() if product_name else ""
        if not clean_name:
            raise ValueError("Product name cannot be blank.")

        clean_date_type = (date_type or "unknown").strip().lower()
        clean_normalized: str | None = None

        if normalized_date:
            clean_str = normalized_date.strip()
            try:
                datetime.date.fromisoformat(clean_str)
                clean_normalized = clean_str
            except (ValueError, TypeError) as e:
                raise InvalidDateError(f"Invalid normalized date '{normalized_date}'. Must be ISO format YYYY-MM-DD.") from e

        # Duplicate protection
        if not force:
            dups = self.find_potential_duplicates(clean_name, brand, clean_normalized)
            if dups:
                dup = dups[0]
                msg = (
                    f"Potential duplicate product exists (ID: {dup.id}, '{dup.product_name}', "
                    f"Brand: {dup.brand or 'N/A'}, Date: {dup.normalized_date or 'None'}). "
                    "Use force=True to confirm duplicate addition."
                )
                raise DuplicateProductError(msg, existing_id=dup.id)

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._get_connection() as conn:
            if self.is_postgres:
                cursor = conn.execute(
                    """
                    INSERT INTO products (
                        product_name, brand, food_category, date_type, date_text,
                        normalized_date, date_status, date_source, analysis_status,
                        image_path, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        clean_name,
                        brand.strip() if brand else None,
                        food_category.strip() if food_category else None,
                        clean_date_type,
                        date_text.strip() if date_text else None,
                        clean_normalized,
                        date_status,
                        date_source,
                        analysis_status,
                        str(image_path) if image_path else None,
                        notes.strip() if notes else None,
                        now,
                        now,
                    ),
                )
                row = cursor.fetchone()
                product_id = row[0]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO products (
                        product_name, brand, food_category, date_type, date_text,
                        normalized_date, date_status, date_source, analysis_status,
                        image_path, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_name,
                        brand.strip() if brand else None,
                        food_category.strip() if food_category else None,
                        clean_date_type,
                        date_text.strip() if date_text else None,
                        clean_normalized,
                        date_status,
                        date_source,
                        analysis_status,
                        str(image_path) if image_path else None,
                        notes.strip() if notes else None,
                        now,
                        now,
                    ),
                )
                product_id = cursor.lastrowid
            assert product_id is not None

            # Attach candidate dates if provided
            if candidate_dates:
                for c in candidate_dates:
                    raw_text = getattr(c, "raw_text", str(c))
                    c_type = getattr(c, "date_type", "unknown")
                    c_norm = getattr(c, "normalized_date", None)
                    c_conf = float(getattr(c, "confidence", 1.0))
                    c_evid = getattr(c, "evidence", "")
                    c_scan_id = getattr(c, "scan_id", None)
                    conn.execute(
                        """
                        INSERT INTO date_candidates (
                            product_id, scan_id, raw_text, date_type,
                            normalized_date, confidence, evidence, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (product_id, c_scan_id, raw_text, c_type, c_norm, c_conf, c_evid, now),
                    )

            return product_id

    def list_products(
        self,
        filter_status: str | None = None,
        sort_by: str = "date",
    ) -> list[ProductRecord]:
        """
        List all products in inventory.
        Optional filter_status: e.g. 'confirmed', 'unverified', 'needs_review'.
        """
        query = "SELECT * FROM products"
        params: list[Any] = []

        if filter_status:
            query += " WHERE date_status = ?"
            params.append(filter_status)

        if sort_by == "date":
            # Sort products by normalized_date (NULLs last) then created_at
            query += " ORDER BY CASE WHEN normalized_date IS NULL THEN 1 ELSE 0 END, normalized_date ASC, id ASC"
        else:
            query += " ORDER BY id DESC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_product(r) for r in rows]

    def search_products(self, query_str: str) -> list[ProductRecord]:
        """
        Search products across product_name, brand, and food_category.
        """
        q = f"%{query_str.strip()}%"
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM products
                WHERE product_name LIKE ?
                   OR brand LIKE ?
                   OR food_category LIKE ?
                   OR notes LIKE ?
                ORDER BY id ASC
                """,
                (q, q, q, q),
            ).fetchall()
            return [self._row_to_product(r) for r in rows]

    def get_product(self, product_id: int) -> ProductRecord | None:
        """Retrieve single product record by primary key."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if not row:
                return None
            return self._row_to_product(row)

    def get_product_date_candidates(self, product_id: int) -> list[DateCandidateRecord]:
        """Retrieve all candidate dates associated with a product."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, product_id, scan_id, raw_text, date_type,
                       normalized_date, confidence, evidence, created_at
                FROM date_candidates WHERE product_id = ?
                ORDER BY id ASC
                """,
                (product_id,),
            ).fetchall()
            return [
                DateCandidateRecord(
                    id=r["id"],
                    product_id=r["product_id"],
                    scan_id=r["scan_id"],
                    raw_text=r["raw_text"],
                    date_type=r["date_type"],
                    normalized_date=r["normalized_date"],
                    confidence=r["confidence"],
                    evidence=r["evidence"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def get_scan_date_candidates(self, scan_id: int) -> list[DateCandidateRecord]:
        """Retrieve all candidate dates associated with a scan history record."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, product_id, scan_id, raw_text, date_type,
                       normalized_date, confidence, evidence, created_at
                FROM date_candidates WHERE scan_id = ?
                ORDER BY id ASC
                """,
                (scan_id,),
            ).fetchall()
            return [
                DateCandidateRecord(
                    id=r["id"],
                    product_id=r["product_id"],
                    scan_id=r["scan_id"],
                    raw_text=r["raw_text"],
                    date_type=r["date_type"],
                    normalized_date=r["normalized_date"],
                    confidence=r["confidence"],
                    evidence=r["evidence"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def update_product(self, product_id: int, **fields: Any) -> bool:
        """
        Update editable product fields.
        Accepts: product_name, brand, food_category, notes, image_path.
        """
        allowed = {"product_name", "brand", "food_category", "notes", "image_path"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False

        if "product_name" in updates and not updates["product_name"]:
            raise ValueError("Product name cannot be empty.")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        updates["updated_at"] = now

        set_clauses = [f"{k} = ?" for k in updates.keys()]
        values = list(updates.values())
        values.append(product_id)

        with self._get_connection() as conn:
            res = conn.execute(
                f"UPDATE products SET {', '.join(set_clauses)} WHERE id = ?",
                values,
            )
            if res.rowcount == 0:
                raise ProductNotFoundError(f"Product ID {product_id} not found.")
            return True

    def confirm_product_date(
        self,
        product_id: int,
        normalized_date: str | None,
        date_type: str = "expiry",
        notes: str | None = None,
    ) -> bool:
        """
        Explicitly confirm or correct a product's date after user review.
        Transitions date_status to 'confirmed' and date_source to 'user_confirmed'.
        """
        clean_date_type = (date_type or "expiry").strip().lower()
        clean_normalized: str | None = None

        if normalized_date:
            try:
                datetime.date.fromisoformat(normalized_date.strip())
                clean_normalized = normalized_date.strip()
            except (ValueError, TypeError) as e:
                raise InvalidDateError(f"Invalid date format '{normalized_date}'. Must be ISO YYYY-MM-DD.") from e

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._get_connection() as conn:
            existing = conn.execute("SELECT notes FROM products WHERE id = ?", (product_id,)).fetchone()
            if not existing:
                raise ProductNotFoundError(f"Product ID {product_id} not found.")

            current_notes = existing["notes"] or ""
            new_notes = current_notes
            if notes:
                new_notes = f"{current_notes}\n[User confirmed]: {notes}".strip()

            res = conn.execute(
                """
                UPDATE products
                SET normalized_date = ?,
                    date_type = ?,
                    date_status = 'confirmed',
                    date_source = 'user_confirmed',
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (clean_normalized, clean_date_type, new_notes, now, product_id),
            )
            return res.rowcount > 0

    def delete_product(self, product_id: int) -> bool:
        """
        Delete a product and cascade its date candidates.
        """
        with self._get_connection() as conn:
            res = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            if res.rowcount == 0:
                raise ProductNotFoundError(f"Product ID {product_id} not found.")
            return True

    @staticmethod
    def _row_to_product(row: Any) -> ProductRecord:
        return ProductRecord(
            id=row["id"],
            product_name=row["product_name"],
            brand=row["brand"],
            food_category=row["food_category"],
            date_type=row["date_type"],
            date_text=row["date_text"],
            normalized_date=row["normalized_date"],
            date_status=row["date_status"],
            date_source=row["date_source"],
            analysis_status=row["analysis_status"],
            image_path=row["image_path"],
            notes=row["notes"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
