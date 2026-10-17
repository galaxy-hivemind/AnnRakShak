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

from inventory_db import (
    DEFAULT_DB_PATH,
    DateCandidateRecord,
    DuplicateProductError,
    InventoryDatabase,
    PostgresConnectionWrapper,
    ProductNotFoundError,
    mask_database_url,
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


if __name__ == "__main__":
    unittest.main()
