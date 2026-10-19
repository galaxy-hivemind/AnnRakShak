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
    scan_id: int | None = None

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
    product_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["supplementary_images"] = self.supplementary_images
        d["image_metadata"] = self.image_metadata
        return d

    @property
    def supplementary_images(self) -> list[str]:
        """Return list of supplementary image paths associated with this scan."""
        if not self.raw_json:
            return []
        try:
            import json
            parsed = json.loads(self.raw_json)
            val = parsed.get("supplementary_images", [])
            return val if isinstance(val, list) else []
        except Exception:
            return []

    @property
    def image_metadata(self) -> dict[str, Any] | None:
        """Return image resolution metadata associated with this scan."""
        if not self.raw_json:
            return None
        try:
            import json
            parsed = json.loads(self.raw_json)
            val = parsed.get("image_metadata")
            return val if isinstance(val, dict) else None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Database Schemas & Connection Wrappers
# ---------------------------------------------------------------------------

SQLITE_BASE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id INTEGER,
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
        updated_at TEXT NOT NULL,
        FOREIGN KEY (scan_id) REFERENCES scan_history(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
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
        raw_json TEXT,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
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
"""

SQLITE_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);
    CREATE INDEX IF NOT EXISTS idx_products_date ON products(normalized_date);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(food_category);
    CREATE INDEX IF NOT EXISTS idx_products_scan ON products(scan_id);
    CREATE INDEX IF NOT EXISTS idx_scan_history_product ON scan_history(product_id);
    CREATE INDEX IF NOT EXISTS idx_date_candidates_product ON date_candidates(product_id);
    CREATE INDEX IF NOT EXISTS idx_date_candidates_scan ON date_candidates(scan_id);
    CREATE INDEX IF NOT EXISTS idx_scan_history_timestamp ON scan_history(timestamp);
"""

SQLITE_SCHEMA = f"""{SQLITE_BASE_SCHEMA}
{SQLITE_INDEXES}"""

POSTGRES_BASE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        scan_id INTEGER,
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
        product_id INTEGER,
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
        product_id INTEGER,
        scan_id INTEGER,
        raw_text TEXT NOT NULL,
        date_type TEXT NOT NULL,
        normalized_date TEXT,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        evidence TEXT,
        created_at TEXT NOT NULL
    );
"""

POSTGRES_MIGRATIONS = """
    ALTER TABLE products ADD COLUMN IF NOT EXISTS scan_id INTEGER;
    ALTER TABLE scan_history ADD COLUMN IF NOT EXISTS product_id INTEGER;
    ALTER TABLE date_candidates ADD COLUMN IF NOT EXISTS scan_id INTEGER;
    ALTER TABLE date_candidates ADD COLUMN IF NOT EXISTS product_id INTEGER;
"""

POSTGRES_CONSTRAINTS = """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_products_scan') THEN
            ALTER TABLE products ADD CONSTRAINT fk_products_scan
                FOREIGN KEY (scan_id) REFERENCES scan_history(id) ON DELETE SET NULL NOT VALID;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_scan_history_product') THEN
            ALTER TABLE scan_history ADD CONSTRAINT fk_scan_history_product
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL NOT VALID;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_date_candidates_product') THEN
            ALTER TABLE date_candidates ADD CONSTRAINT fk_date_candidates_product
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE NOT VALID;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_date_candidates_scan') THEN
            ALTER TABLE date_candidates ADD CONSTRAINT fk_date_candidates_scan
                FOREIGN KEY (scan_id) REFERENCES scan_history(id) ON DELETE SET NULL NOT VALID;
        END IF;
    END $$;
"""

POSTGRES_INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);
    CREATE INDEX IF NOT EXISTS idx_products_date ON products(normalized_date);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(food_category);
    CREATE INDEX IF NOT EXISTS idx_products_scan ON products(scan_id);
    CREATE INDEX IF NOT EXISTS idx_scan_history_product ON scan_history(product_id);
    CREATE INDEX IF NOT EXISTS idx_date_candidates_product ON date_candidates(product_id);
    CREATE INDEX IF NOT EXISTS idx_date_candidates_scan ON date_candidates(scan_id);
    CREATE INDEX IF NOT EXISTS idx_scan_history_timestamp ON scan_history(timestamp);
"""

POSTGRES_SCHEMA = f"""{POSTGRES_BASE_SCHEMA}
{POSTGRES_MIGRATIONS}
{POSTGRES_CONSTRAINTS}
{POSTGRES_INDEXES}"""


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

    @staticmethod
    def _migrate_sqlite_columns(conn: Any) -> None:
        """Ensure all required columns exist in SQLite tables before creating indexes."""
        def column_exists(table: str, col: str) -> bool:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return any(r[1] == col for r in rows)

        if not column_exists("products", "scan_id"):
            conn.execute("ALTER TABLE products ADD COLUMN scan_id INTEGER REFERENCES scan_history(id) ON DELETE SET NULL")
        if not column_exists("scan_history", "product_id"):
            conn.execute("ALTER TABLE scan_history ADD COLUMN product_id INTEGER REFERENCES products(id) ON DELETE SET NULL")
        if not column_exists("date_candidates", "scan_id"):
            conn.execute("ALTER TABLE date_candidates ADD COLUMN scan_id INTEGER REFERENCES scan_history(id) ON DELETE SET NULL")

    def init_db(self) -> None:
        """Create tables and indexes idempotently, and migrate existing schemas."""
        if self.is_postgres:
            with self._get_connection() as conn:
                # 1. Base table creation (idempotent, no circular foreign keys in CREATE TABLE)
                conn.executescript(POSTGRES_BASE_SCHEMA)
                # 2. Schema migrations (add missing columns to existing tables BEFORE indexes)
                conn.executescript(POSTGRES_MIGRATIONS)
                # 3. Foreign key constraints (idempotently add FKs after all tables exist)
                try:
                    conn.executescript(POSTGRES_CONSTRAINTS)
                except Exception as e:
                    logger.warning("Could not apply PostgreSQL foreign key constraints: %s", e)
                # 4. Indexes (created after all columns are guaranteed to exist)
                conn.executescript(POSTGRES_INDEXES)
        else:
            assert self.db_path is not None
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("Could not create parent directory for %s: %s", self.db_path, e)
            with self._get_connection() as conn:
                # 1. Base table creation
                conn.executescript(SQLITE_BASE_SCHEMA)
                # 2. Column migrations (run before indexes)
                self._migrate_sqlite_columns(conn)
                # 3. Indexes (created after columns exist)
                conn.executescript(SQLITE_INDEXES)

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
        image_metadata: dict[str, Any] | None = None,
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
            if hasattr(result, "model_dump"):
                try:
                    dumped = result.model_dump()
                    if image_metadata is not None:
                        dumped["image_metadata"] = image_metadata
                    import json
                    raw_json = json.dumps(dumped)
                except Exception:
                    if hasattr(result, "model_dump_json"):
                        raw_json = result.model_dump_json()
            elif hasattr(result, "model_dump_json"):
                raw_json = result.model_dump_json()
            candidates = getattr(result, "date_candidates", []) or []
        elif image_metadata is not None:
            import json
            raw_json = json.dumps({"image_metadata": image_metadata})

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
                       error_message, raw_json, product_id
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
                    product_id=r["product_id"] if (hasattr(r, "keys") and "product_id" in r.keys()) else None,
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
                       error_message, raw_json, product_id
                FROM scan_history WHERE id = ?
                """,
                (scan_id,),
            ).fetchone()
            if not r:
                return None
            prod_id = None
            if hasattr(r, "keys") and "product_id" in r.keys():
                prod_id = r["product_id"]
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
                product_id=prod_id,
            )

    def update_scan(
        self,
        scan_id: int,
        result: Any | None = None,
        error_message: str | None = None,
        supplementary_image_path: str | None = None,
        image_metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Update an existing scan history record and its candidate dates after reanalysis or supplementary capture.
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

        # Retain existing image_metadata if a new one is not explicitly supplied
        effective_image_meta = image_metadata if image_metadata is not None else existing.image_metadata

        if result is not None:
            product_name = getattr(result, "product_name", None)
            brand = getattr(result, "brand", None)
            food_category = getattr(result, "food_category", None)
            analysis_status = getattr(result, "analysis_status", "unknown")
            needs_review = 1 if getattr(result, "needs_review", True) else 0
            review_reason = getattr(result, "review_reason", None)
            selected_expiry_date = getattr(result, "selected_expiry_date", None)
            
            # Preserve existing supplementary images and append newly captured one if supplied
            existing_supp = list(existing.supplementary_images)
            if supplementary_image_path and str(supplementary_image_path) not in existing_supp:
                existing_supp.append(str(supplementary_image_path))

            if hasattr(result, "model_dump"):
                try:
                    dumped = result.model_dump()
                    dumped["supplementary_images"] = existing_supp
                    if effective_image_meta is not None:
                        dumped["image_metadata"] = effective_image_meta
                    import json
                    raw_json = json.dumps(dumped)
                except Exception:
                    if hasattr(result, "model_dump_json"):
                        raw_json = result.model_dump_json()
            elif hasattr(result, "model_dump_json"):
                raw_json = result.model_dump_json()

            candidates = getattr(result, "date_candidates", []) or []
        elif effective_image_meta is not None or supplementary_image_path is not None:
            import json
            base = {}
            if existing.raw_json:
                try:
                    base = json.loads(existing.raw_json)
                except Exception:
                    base = {}
            existing_supp = list(existing.supplementary_images)
            if supplementary_image_path and str(supplementary_image_path) not in existing_supp:
                existing_supp.append(str(supplementary_image_path))
            base["supplementary_images"] = existing_supp
            if effective_image_meta is not None:
                base["image_metadata"] = effective_image_meta
            raw_json = json.dumps(base)

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
        scan_id: int | None = None,
    ) -> int:
        """
        Add a verified or user-confirmed product into the inventory.
        Validates date format, guards against duplicate entries unless force=True,
        and atomically links scan_history when scan_id is provided.
        Idempotent: if a product for scan_id already exists, updates it without duplicate.
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

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._get_connection() as conn:
            # Idempotent check for scan confirmation: if a product already exists for this scan_id, update it
            if scan_id is not None:
                cursor = conn.execute("SELECT id FROM products WHERE scan_id = ?", (scan_id,))
                existing_row = cursor.fetchone()
                if existing_row:
                    prod_id = existing_row["id"] if hasattr(existing_row, "keys") else existing_row[0]
                    conn.execute(
                        """
                        UPDATE products
                        SET product_name = ?, brand = ?, food_category = ?, date_type = ?,
                            date_text = ?, normalized_date = ?, date_status = ?, date_source = ?,
                            analysis_status = ?, image_path = COALESCE(?, image_path),
                            notes = ?, updated_at = ?
                        WHERE id = ?
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
                            prod_id,
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE scan_history
                        SET product_id = ?, product_name = ?, brand = ?, food_category = ?,
                            selected_expiry_date = ?, needs_review = 0, review_reason = NULL
                        WHERE id = ?
                        """,
                        (
                            prod_id,
                            clean_name,
                            brand.strip() if brand else None,
                            food_category.strip() if food_category else None,
                            clean_normalized,
                            scan_id,
                        ),
                    )
                    if scan_id is not None:
                        existing_cands = conn.execute(
                            "SELECT COUNT(*) FROM date_candidates WHERE scan_id = ?",
                            (scan_id,),
                        ).fetchone()
                        count = existing_cands[0] if existing_cands else 0
                        if count > 0:
                            conn.execute(
                                "UPDATE date_candidates SET product_id = ? WHERE scan_id = ?",
                                (prod_id, scan_id),
                            )
                        elif candidate_dates:
                            conn.execute("DELETE FROM date_candidates WHERE product_id = ?", (prod_id,))
                            for c in candidate_dates:
                                raw_text = getattr(c, "raw_text", str(c))
                                c_type = getattr(c, "date_type", "unknown")
                                c_norm = getattr(c, "normalized_date", None)
                                c_conf = float(getattr(c, "confidence", 1.0))
                                c_evid = getattr(c, "evidence", "")
                                conn.execute(
                                    """
                                    INSERT INTO date_candidates (
                                        product_id, scan_id, raw_text, date_type,
                                        normalized_date, confidence, evidence, created_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (prod_id, scan_id, raw_text, c_type, c_norm, c_conf, c_evid, now),
                                )
                    elif candidate_dates:
                        conn.execute("DELETE FROM date_candidates WHERE product_id = ?", (prod_id,))
                        for c in candidate_dates:
                            raw_text = getattr(c, "raw_text", str(c))
                            c_type = getattr(c, "date_type", "unknown")
                            c_norm = getattr(c, "normalized_date", None)
                            c_conf = float(getattr(c, "confidence", 1.0))
                            c_evid = getattr(c, "evidence", "")
                            c_scan = getattr(c, "scan_id", None)
                            conn.execute(
                                """
                                INSERT INTO date_candidates (
                                    product_id, scan_id, raw_text, date_type,
                                    normalized_date, confidence, evidence, created_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (prod_id, c_scan, raw_text, c_type, c_norm, c_conf, c_evid, now),
                            )
                    return prod_id

            # Duplicate protection when not confirming an existing scan or when force=False
            if not force and scan_id is None:
                dups = self.find_potential_duplicates(clean_name, brand, clean_normalized)
                if dups:
                    dup = dups[0]
                    msg = (
                        f"Potential duplicate product exists (ID: {dup.id}, '{dup.product_name}', "
                        f"Brand: {dup.brand or 'N/A'}, Date: {dup.normalized_date or 'None'}). "
                        "Use force=True to confirm duplicate addition."
                    )
                    raise DuplicateProductError(msg, existing_id=dup.id)

            if self.is_postgres:
                cursor = conn.execute(
                    """
                    INSERT INTO products (
                        scan_id, product_name, brand, food_category, date_type, date_text,
                        normalized_date, date_status, date_source, analysis_status,
                        image_path, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        scan_id,
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
                        scan_id, product_name, brand, food_category, date_type, date_text,
                        normalized_date, date_status, date_source, analysis_status,
                        image_path, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scan_id,
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

            # Update scan_history atomically when scan_id is provided
            if scan_id is not None:
                conn.execute(
                    """
                    UPDATE scan_history
                    SET product_id = ?, product_name = ?, brand = ?, food_category = ?,
                        selected_expiry_date = ?, needs_review = 0, review_reason = NULL
                    WHERE id = ?
                    """,
                    (
                        product_id,
                        clean_name,
                        brand.strip() if brand else None,
                        food_category.strip() if food_category else None,
                        clean_normalized,
                        scan_id,
                    ),
                )

            # Attach or link candidate dates
            if scan_id is not None:
                existing_cands = conn.execute(
                    "SELECT COUNT(*) FROM date_candidates WHERE scan_id = ?",
                    (scan_id,),
                ).fetchone()
                count = existing_cands[0] if existing_cands else 0
                if count > 0:
                    conn.execute(
                        "UPDATE date_candidates SET product_id = ? WHERE scan_id = ?",
                        (product_id, scan_id),
                    )
                elif candidate_dates:
                    for c in candidate_dates:
                        raw_text = getattr(c, "raw_text", str(c))
                        c_type = getattr(c, "date_type", "unknown")
                        c_norm = getattr(c, "normalized_date", None)
                        c_conf = float(getattr(c, "confidence", 1.0))
                        c_evid = getattr(c, "evidence", "")
                        conn.execute(
                            """
                            INSERT INTO date_candidates (
                                product_id, scan_id, raw_text, date_type,
                                normalized_date, confidence, evidence, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (product_id, scan_id, raw_text, c_type, c_norm, c_conf, c_evid, now),
                        )
            elif candidate_dates:
                for c in candidate_dates:
                    raw_text = getattr(c, "raw_text", str(c))
                    c_type = getattr(c, "date_type", "unknown")
                    c_norm = getattr(c, "normalized_date", None)
                    c_conf = float(getattr(c, "confidence", 1.0))
                    c_evid = getattr(c, "evidence", "")
                    c_scan = getattr(c, "scan_id", None)
                    conn.execute(
                        """
                        INSERT INTO date_candidates (
                            product_id, scan_id, raw_text, date_type,
                            normalized_date, confidence, evidence, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (product_id, c_scan, raw_text, c_type, c_norm, c_conf, c_evid, now),
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
        Accepts: product_name, brand, food_category, notes, image_path, date_type, normalized_date, date_status.
        Synchronizes linked scan_history record if scan_id exists.
        """
        allowed = {
            "product_name",
            "brand",
            "food_category",
            "notes",
            "image_path",
            "date_type",
            "normalized_date",
            "date_status",
        }
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

            # Synchronize linked scan_history row if this product originated from a scan
            p_row = conn.execute("SELECT scan_id FROM products WHERE id = ?", (product_id,)).fetchone()
            scan_id = p_row["scan_id"] if p_row and hasattr(p_row, "keys") else (p_row[0] if p_row else None)
            if scan_id:
                scan_updates = {}
                if "product_name" in updates:
                    scan_updates["product_name"] = updates["product_name"]
                if "brand" in updates:
                    scan_updates["brand"] = updates["brand"]
                if "food_category" in updates:
                    scan_updates["food_category"] = updates["food_category"]
                if "normalized_date" in updates:
                    scan_updates["selected_expiry_date"] = updates["normalized_date"]

                if scan_updates:
                    scan_clauses = [f"{k} = ?" for k in scan_updates.keys()]
                    scan_vals = list(scan_updates.values())
                    scan_vals.append(scan_id)
                    conn.execute(
                        f"UPDATE scan_history SET {', '.join(scan_clauses)} WHERE id = ?",
                        scan_vals,
                    )

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

            # Synchronize linked scan_history row if this product originated from a scan
            p_row = conn.execute("SELECT scan_id FROM products WHERE id = ?", (product_id,)).fetchone()
            scan_id = p_row["scan_id"] if p_row and hasattr(p_row, "keys") else (p_row[0] if p_row else None)
            if scan_id and clean_normalized:
                conn.execute(
                    "UPDATE scan_history SET selected_expiry_date = ? WHERE id = ?",
                    (clean_normalized, scan_id),
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

    def delete_scan(self, scan_id: int, delete_associated_product: bool = True) -> tuple[bool, int | None]:
        """
        Delete a scan from scan_history, its date candidates, and associated capture file.
        If delete_associated_product is True, also deletes the product created by this scan,
        provided it has not been independently retained or modified.
        Safe against already-deleted records.
        Returns (success, deleted_product_id).
        """
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id, image_path, product_id, raw_json FROM scan_history WHERE id = ?", (scan_id,))
            scan_row = cursor.fetchone()
            if not scan_row:
                # Check if a product still references this scan_id even if scan_history record is gone
                p_row = conn.execute("SELECT id FROM products WHERE scan_id = ?", (scan_id,)).fetchone()
                if p_row and delete_associated_product:
                    prod_id = p_row["id"] if hasattr(p_row, "keys") else p_row[0]
                    conn.execute("DELETE FROM date_candidates WHERE product_id = ?", (prod_id,))
                    conn.execute("DELETE FROM products WHERE id = ?", (prod_id,))
                    return True, prod_id
                return False, None

            image_path = scan_row["image_path"] if hasattr(scan_row, "keys") else scan_row[1]
            prod_id = scan_row["product_id"] if hasattr(scan_row, "keys") else scan_row[2]
            raw_json = scan_row["raw_json"] if hasattr(scan_row, "keys") else (scan_row[3] if len(scan_row) > 3 else None)

            if prod_id is None:
                p_row = conn.execute("SELECT id FROM products WHERE scan_id = ?", (scan_id,)).fetchone()
                if p_row:
                    prod_id = p_row["id"] if hasattr(p_row, "keys") else p_row[0]

            deleted_prod_id = None
            if delete_associated_product and prod_id is not None:
                conn.execute("DELETE FROM date_candidates WHERE product_id = ?", (prod_id,))
                conn.execute("DELETE FROM products WHERE id = ?", (prod_id,))
                deleted_prod_id = prod_id

            conn.execute("DELETE FROM date_candidates WHERE scan_id = ?", (scan_id,))
            conn.execute("DELETE FROM scan_history WHERE id = ?", (scan_id,))

            if image_path:
                try:
                    p = Path(image_path)
                    if p.exists() and p.is_file():
                        p.unlink()
                except Exception as e:
                    logger.debug("Could not remove capture file %s: %s", image_path, e)

            if raw_json:
                try:
                    import json
                    parsed = json.loads(raw_json)
                    supp_list = parsed.get("supplementary_images", [])
                    if isinstance(supp_list, list):
                        for sp_path in supp_list:
                            try:
                                sp = Path(sp_path)
                                if sp.exists() and sp.is_file():
                                    sp.unlink()
                            except Exception as e:
                                logger.debug("Could not remove supplementary capture file %s: %s", sp_path, e)
                except Exception:
                    pass

            return True, deleted_prod_id

    @staticmethod
    def _row_to_product(row: Any) -> ProductRecord:
        scan_id = None
        if hasattr(row, "keys"):
            scan_id = row["scan_id"] if "scan_id" in row.keys() else None
        elif isinstance(row, dict):
            scan_id = row.get("scan_id")
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
            scan_id=scan_id,
        )
