"""
Unit tests for AnnaRakshak Database Persistence Layer
======================================================
Tests SQLite local operations, PostgreSQL compatibility adapter,
Vercel environment detection, safe path resolution, and password masking.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sqlite3
from inventory_db import (
    DEFAULT_DB_PATH,
    DateCandidateRecord,
    DuplicateProductError,
    InventoryDatabase,
    PostgresConnectionWrapper,
    ProductNotFoundError,
    mask_database_url,
    SQLITE_SCHEMA,
    SQLITE_BASE_SCHEMA,
    SQLITE_INDEXES,
    POSTGRES_SCHEMA,
    POSTGRES_BASE_SCHEMA,
    POSTGRES_MIGRATIONS,
    POSTGRES_CONSTRAINTS,
    POSTGRES_INDEXES,
)
import api


class TestDatabasePersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_inventory.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sqlite_local_crud_and_idempotence(self) -> None:
        """Verify local SQLite CRUD operations and that repeated initialization preserves data."""
        db = InventoryDatabase(db_path=self.db_path)
        self.assertFalse(db.is_postgres)
        self.assertEqual(db.db_path, self.db_path.resolve())

        # 1. Add product
        p_id = db.add_product(
            product_name="Organic Almond Milk",
            date_type="expiry",
            brand="Silk",
            food_category="Dairy",
            normalized_date="2026-11-20",
            notes="Fridge shelf",
        )
        self.assertIsInstance(p_id, int)

        # 2. Duplicate detection
        with self.assertRaises(DuplicateProductError):
            db.add_product(
                product_name="Organic Almond Milk",
                brand="Silk",
                normalized_date="2026-11-20",
                force=False,
            )

        # 3. Read product
        prod = db.get_product(p_id)
        self.assertIsNotNone(prod)
        self.assertEqual(prod.product_name, "Organic Almond Milk")
        self.assertEqual(prod.brand, "Silk")

        # 4. Search product
        results = db.search_products("Almond")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, p_id)

        # 5. Record scan
        mock_result = MagicMock()
        mock_result.product_name = "Organic Almond Milk"
        mock_result.brand = "Silk"
        mock_result.food_category = "Dairy"
        mock_result.analysis_status = "success"
        mock_result.needs_review = False
        mock_result.review_reason = None
        mock_result.selected_expiry_date = "2026-11-20"
        mock_result.model_dump_json.return_value = '{"test": true}'
        candidate = MagicMock()
        candidate.raw_text = "EXP 20/11/2026"
        candidate.date_type = "expiry"
        candidate.normalized_date = "2026-11-20"
        candidate.confidence = 0.95
        candidate.evidence = "Cap stamp"
        mock_result.date_candidates = [candidate]

        scan_id = db.record_scan("captures/test_scan.jpg", result=mock_result)
        self.assertIsInstance(scan_id, int)
        scan = db.get_scan(scan_id)
        self.assertIsNotNone(scan)
        self.assertEqual(scan.product_name, "Organic Almond Milk")

        # 6. Idempotent reinitialization must NOT destroy data
        db.init_db()
        prod_after = db.get_product(p_id)
        self.assertIsNotNone(prod_after)
        self.assertEqual(prod_after.product_name, "Organic Almond Milk")

        # 7. Update and Delete
        db.update_product(p_id, notes="Updated shelf")
        prod_updated = db.get_product(p_id)
        self.assertEqual(prod_updated.notes, "Updated shelf")

        db.delete_product(p_id)
        self.assertIsNone(db.get_product(p_id))

    def test_sqlite_nested_directory_creation(self) -> None:
        """Ensure missing parent directories are created automatically for SQLite."""
        nested_path = Path(self.temp_dir.name) / "sub1" / "sub2" / "inventory.db"
        self.assertFalse(nested_path.parent.exists())

        db = InventoryDatabase(db_path=nested_path)
        self.assertTrue(nested_path.parent.exists())
        self.assertTrue(nested_path.exists())

    def test_mask_database_url(self) -> None:
        """Ensure sensitive credentials in database URLs are never logged."""
        raw_url = "postgresql://myuser:secretpassword123@ep-project-1234.us-east-2.aws.neon.tech/neondb?sslmode=require"
        masked = mask_database_url(raw_url)
        self.assertNotIn("secretpassword123", masked)
        self.assertIn("myuser:****@ep-project-1234.us-east-2.aws.neon.tech", masked)
        self.assertIn("sslmode=require", masked)

        # Empty or invalid URLs
        self.assertEqual(mask_database_url(""), "")
        self.assertEqual(mask_database_url(None), "")

    def test_postgres_connection_wrapper(self) -> None:
        """Verify PostgresConnectionWrapper translates parameter markers and LIKE to ILIKE."""
        mock_raw_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_raw_conn.cursor.return_value = mock_cursor

        wrapper = PostgresConnectionWrapper(mock_raw_conn)
        wrapper.execute("SELECT * FROM products WHERE id = ? AND brand LIKE ?", (1, "Amul"))

        # Check that '?' became '%s' and 'LIKE' became 'ILIKE'
        called_sql = mock_cursor.execute.call_args[0][0]
        self.assertIn("id = %s", called_sql)
        self.assertIn("brand ILIKE %s", called_sql)
        self.assertNotIn("?", called_sql)

    @patch("inventory_db.ThreadedConnectionPool")
    def test_postgres_initialization_and_queries(self, mock_pool_cls: MagicMock) -> None:
        """Verify PostgreSQL initialization, RETURNING id handling, and connection pool lifecycle."""
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool

        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_pool.getconn.return_value = mock_conn

        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        # When init_db runs
        mock_cur.execute.return_value = None

        db_url = "postgresql://user:pass@ep-neon.us-east-2.aws.neon.tech/neondb"
        db = InventoryDatabase(database_url=db_url)
        self.assertTrue(db.is_postgres)

        # 1. Test add_product with RETURNING id
        mock_cur.fetchone.return_value = (42,)
        new_id = db.add_product(
            product_name="Postgres Milk",
            date_type="expiry",
            force=True,
        )
        self.assertEqual(new_id, 42)
        # Check RETURNING id was used
        insert_call = [c[0][0] for c in mock_cur.execute.call_args_list if "INSERT INTO products" in str(c[0][0])]
        self.assertTrue(any("RETURNING id" in sql for sql in insert_call))

        # 2. Test record_scan with RETURNING id
        mock_cur.fetchone.return_value = (99,)
        scan_id = db.record_scan("captures/pg_scan.jpg")
        self.assertEqual(scan_id, 99)

        # 3. Test close releases pool
        db.close()
        mock_pool.closeall.assert_called_once()

    def test_vercel_missing_database_url_raises_clear_error(self) -> None:
        """Verify that running on Vercel without DATABASE_URL raises an informative error."""
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            if "DATABASE_URL" in os.environ:
                del os.environ["DATABASE_URL"]
            if "ANNARAKSHAK_DATABASE_URL" in os.environ:
                del os.environ["ANNARAKSHAK_DATABASE_URL"]

            with self.assertRaises(RuntimeError) as ctx:
                api.get_database()

            err_msg = str(ctx.exception)
            self.assertIn("Vercel serverless environment detected", err_msg)
            self.assertIn("DATABASE_URL", err_msg)
            self.assertIn("read-only filesystem", err_msg)

    def test_vercel_with_database_url_initializes_postgres(self) -> None:
        """Verify that running on Vercel with DATABASE_URL initializes PostgreSQL."""
        test_url = "postgresql://user:pass@ep-neon.tech/neondb"
        with patch.dict(os.environ, {"VERCEL": "1", "DATABASE_URL": test_url}):
            with patch("inventory_db.ThreadedConnectionPool") as mock_pool_cls:
                mock_pool = MagicMock()
                mock_pool_cls.return_value = mock_pool
                mock_conn = MagicMock()
                mock_conn.closed = False
                mock_pool.getconn.return_value = mock_conn

                db = api.get_database()
                self.assertTrue(db.is_postgres)
                self.assertEqual(db.database_url, test_url)
                db.close()

    def test_sqlite_migration_from_legacy_schema(self) -> None:
        """
        Verify that opening an existing SQLite database created with an old schema
        (lacking scan_id on products, product_id on scan_history, and scan_id on date_candidates)
        automatically and safely migrates the columns and creates all indexes without data loss.
        """
        legacy_path = Path(self.temp_dir.name) / "legacy_test.db"
        conn = sqlite3.connect(str(legacy_path))
        conn.executescript("""
            CREATE TABLE products (
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
            CREATE TABLE scan_history (
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
            CREATE TABLE date_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                raw_text TEXT NOT NULL,
                date_type TEXT NOT NULL,
                normalized_date TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                evidence TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO products (product_name, date_type, created_at, updated_at)
            VALUES ('Legacy Apple', 'expiry', '2026-01-01', '2026-01-01');
            INSERT INTO scan_history (timestamp, image_path, analysis_status)
            VALUES ('2026-01-01', 'captures/legacy.jpg', 'success');
            INSERT INTO date_candidates (product_id, raw_text, date_type, created_at)
            VALUES (1, 'EXP 2026-12-31', 'expiry', '2026-01-01');
        """)
        conn.close()

        # Initialize InventoryDatabase against the legacy database
        db = InventoryDatabase(db_path=legacy_path)

        # 1. Verify data preserved
        prod = db.get_product(1)
        self.assertIsNotNone(prod)
        self.assertEqual(prod.product_name, "Legacy Apple")
        self.assertIsNone(prod.scan_id)

        scan = db.get_scan(1)
        self.assertIsNotNone(scan)
        self.assertEqual(scan.image_path, "captures/legacy.jpg")
        self.assertIsNone(scan.product_id)

        # 2. Verify table info has the new columns
        with sqlite3.connect(str(legacy_path)) as c:
            p_cols = [r[1] for r in c.execute("PRAGMA table_info(products)").fetchall()]
            s_cols = [r[1] for r in c.execute("PRAGMA table_info(scan_history)").fetchall()]
            d_cols = [r[1] for r in c.execute("PRAGMA table_info(date_candidates)").fetchall()]
            self.assertIn("scan_id", p_cols)
            self.assertIn("product_id", s_cols)
            self.assertIn("scan_id", d_cols)

            # Verify all indexes were created
            idx_names = [r[1] for r in c.execute("SELECT * FROM pragma_index_list('products')").fetchall()]
            self.assertIn("idx_products_scan", idx_names)

        # 3. Verify new operations with scan_id work seamlessly
        new_p_id = db.add_product(
            product_name="New Banana",
            date_type="expiry",
            scan_id=1,
            force=True,
        )
        new_prod = db.get_product(new_p_id)
        self.assertIsNotNone(new_prod)
        self.assertEqual(new_prod.scan_id, 1)

        db.close()

    def test_postgres_schema_ordering_and_no_circular_references(self) -> None:
        """
        Verify that POSTGRES_SCHEMA avoids circular references in CREATE TABLE
        and ensures migrations run before indexes.
        """
        # 1. products CREATE TABLE must NOT have inline REFERENCES scan_history(id)
        # to ensure table creation order does not fail on fresh databases
        self.assertNotIn(
            "scan_id INTEGER REFERENCES scan_history",
            POSTGRES_BASE_SCHEMA,
            "Base table creation should not contain circular inline REFERENCES"
        )

        # 2. POSTGRES_MIGRATIONS must add scan_id, product_id
        self.assertIn("ALTER TABLE products ADD COLUMN IF NOT EXISTS scan_id", POSTGRES_MIGRATIONS)
        self.assertIn("ALTER TABLE scan_history ADD COLUMN IF NOT EXISTS product_id", POSTGRES_MIGRATIONS)
        self.assertIn("ALTER TABLE date_candidates ADD COLUMN IF NOT EXISTS scan_id", POSTGRES_MIGRATIONS)

        # 3. In POSTGRES_SCHEMA, the migration MUST appear BEFORE the index on scan_id
        pos_migration = POSTGRES_SCHEMA.find("ALTER TABLE products ADD COLUMN IF NOT EXISTS scan_id")
        pos_index = POSTGRES_SCHEMA.find("CREATE INDEX IF NOT EXISTS idx_products_scan ON products(scan_id)")
        self.assertTrue(pos_migration < pos_index, "Column migration must appear BEFORE index creation")

    @patch("inventory_db.ThreadedConnectionPool")
    def test_postgres_initialization_executes_in_safe_sequence(self, mock_pool_cls: MagicMock) -> None:
        """
        Verify that PostgreSQL initialization executes statements in the safe sequence:
        base tables -> migrations -> constraints -> indexes.
        """
        mock_pool = MagicMock()
        mock_pool_cls.return_value = mock_pool
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_pool.getconn.return_value = mock_conn

        executed_scripts: list[str] = []
        mock_cur = MagicMock()
        mock_cur.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value = mock_cur

        def fake_execute(sql: str, params: Any = None) -> None:
            executed_scripts.append(sql)

        mock_cur.execute.side_effect = fake_execute

        db_url = "postgresql://user:pass@ep-neon.us-east-2.aws.neon.tech/neondb"
        db = InventoryDatabase(database_url=db_url)
        self.assertTrue(db.is_postgres)

        # Verify execution order:
        # 1. Base table creation must be called
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS products" in s for s in executed_scripts))
        # 2. Migrations must be called
        self.assertTrue(any("ALTER TABLE products ADD COLUMN IF NOT EXISTS scan_id" in s for s in executed_scripts))
        # 3. Constraints must be called
        self.assertTrue(any("fk_products_scan" in s for s in executed_scripts))
        # 4. Indexes must be called
        self.assertTrue(any("CREATE INDEX IF NOT EXISTS idx_products_scan" in s for s in executed_scripts))

        # Check sequence: migration script is executed before index script
        mig_idx = next(i for i, s in enumerate(executed_scripts) if "ALTER TABLE products ADD COLUMN IF NOT EXISTS scan_id" in s)
        idx_idx = next(i for i, s in enumerate(executed_scripts) if "CREATE INDEX IF NOT EXISTS idx_products_scan" in s)
        self.assertLess(mig_idx, idx_idx, "Migration must execute before index creation")

        db.close()


if __name__ == "__main__":
    unittest.main()
