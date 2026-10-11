"""
AnnaRakshak — SQLite Inventory & Date Status Unit Tests
========================================================
Comprehensive offline test suite verifying:
  1. Schema initialization & idempotent re-initialization.
  2. Product CRUD (add, list, search, get, edit, delete).
  3. Multi-connection persistence.
  4. Date validation (rejection of malformed dates).
  5. Strict date status calculations & boundary conditions (inclusive warning window).
  6. Manufacturing vs expiry date distinction (no silent conversion).
  7. Best-before distinct quality status.
  8. Duplicate product protection & forced override.
  9. Scan history recording & review safety (no auto-confirmation).
 10. Transaction integrity & error handling.
 11. Inventory CLI command behavior (list, search, show, add, confirm-date, delete, scans).

All tests use temporary database paths and run completely offline.
"""

from __future__ import annotations

import datetime
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from inventory_db import (
    DEFAULT_WARNING_DAYS,
    DuplicateProductError,
    InvalidDateError,
    InventoryDatabase,
    ProductNotFoundError,
    calculate_date_status,
)


class TestDatabaseInitialization(unittest.TestCase):
    """Verifies schema creation and idempotent re-initialization."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_inventory.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_schema_creates_tables_and_indexes(self) -> None:
        db = InventoryDatabase(self.db_path)
        self.assertTrue(self.db_path.exists())

        with db._get_connection() as conn:
            tables = [
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            self.assertIn("products", tables)
            self.assertIn("scan_history", tables)
            self.assertIn("date_candidates", tables)

    def test_idempotent_reinitialization(self) -> None:
        db1 = InventoryDatabase(self.db_path)
        pid = db1.add_product("Almond Milk", date_type="expiry", normalized_date="2026-11-20")

        # Re-initialize on same path
        db2 = InventoryDatabase(self.db_path)
        prod = db2.get_product(pid)
        self.assertIsNotNone(prod)
        self.assertEqual(prod.product_name, "Almond Milk")


class TestProductCRUD(unittest.TestCase):
    """Tests product creation, retrieval, searching, editing, and deletion."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_crud.db"
        self.db = InventoryDatabase(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_add_and_retrieve_product(self) -> None:
        pid = self.db.add_product(
            product_name="Greek Yogurt 500g",
            brand="Chobani",
            food_category="Dairy",
            date_type="use_by",
            normalized_date="2026-10-25",
            date_status="confirmed",
            date_source="user_confirmed",
            notes="Stored in top fridge shelf",
        )
        self.assertIsInstance(pid, int)

        prod = self.db.get_product(pid)
        self.assertIsNotNone(prod)
        self.assertEqual(prod.product_name, "Greek Yogurt 500g")
        self.assertEqual(prod.brand, "Chobani")
        self.assertEqual(prod.food_category, "Dairy")
        self.assertEqual(prod.date_type, "use_by")
        self.assertEqual(prod.normalized_date, "2026-10-25")
        self.assertEqual(prod.date_status, "confirmed")
        self.assertEqual(prod.notes, "Stored in top fridge shelf")

    def test_add_product_blank_name_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.db.add_product("")

        with self.assertRaises(ValueError):
            self.db.add_product("   ")

    def test_list_and_filter_products(self) -> None:
        self.db.add_product("Eggs 12pk", date_type="expiry", normalized_date="2026-10-18", date_status="confirmed")
        self.db.add_product("Cheddar Cheese", date_type="best_before", normalized_date="2026-12-01", date_status="unverified")
        self.db.add_product("Cookies", date_type="unknown", normalized_date=None, date_status="needs_review")

        all_items = self.db.list_products()
        self.assertEqual(len(all_items), 3)

        confirmed_only = self.db.list_products(filter_status="confirmed")
        self.assertEqual(len(confirmed_only), 1)
        self.assertEqual(confirmed_only[0].product_name, "Eggs 12pk")

        needs_review = self.db.list_products(filter_status="needs_review")
        self.assertEqual(len(needs_review), 1)
        self.assertEqual(needs_review[0].product_name, "Cookies")

    def test_search_products(self) -> None:
        self.db.add_product("Whole Wheat Bread", brand="Harvest Gold", food_category="Bakery")
        self.db.add_product("Oat Milk 1L", brand="Oatly", food_category="Beverage")
        self.db.add_product("Brown Eggs", brand="Eggoz", food_category="Poultry")

        # Search by product name
        res1 = self.db.search_products("wheat")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0].product_name, "Whole Wheat Bread")

        # Search by brand
        res2 = self.db.search_products("oatly")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0].product_name, "Oat Milk 1L")

        # Search by category
        res3 = self.db.search_products("bakery")
        self.assertEqual(len(res3), 1)
        self.assertEqual(res3[0].brand, "Harvest Gold")

        # Search with no match
        res4 = self.db.search_products("nonexistent_item")
        self.assertEqual(len(res4), 0)

    def test_update_product(self) -> None:
        pid = self.db.add_product("Milk", brand="Amul", food_category="Dairy")
        ok = self.db.update_product(pid, product_name="Pasteurized Whole Milk", brand="Amul Gold", notes="Fresh carton")
        self.assertTrue(ok)

        updated = self.db.get_product(pid)
        self.assertEqual(updated.product_name, "Pasteurized Whole Milk")
        self.assertEqual(updated.brand, "Amul Gold")
        self.assertEqual(updated.notes, "Fresh carton")

    def test_update_nonexistent_product_raises_error(self) -> None:
        with self.assertRaises(ProductNotFoundError):
            self.db.update_product(99999, product_name="Ghost Item")

    def test_delete_product(self) -> None:
        pid = self.db.add_product("Yogurt", date_type="expiry", normalized_date="2026-10-30")
        self.assertIsNotNone(self.db.get_product(pid))

        self.assertTrue(self.db.delete_product(pid))
        self.assertIsNone(self.db.get_product(pid))

        with self.assertRaises(ProductNotFoundError):
            self.db.delete_product(pid)

    def test_confirm_product_date(self) -> None:
        pid = self.db.add_product(
            "Cake Mix",
            date_type="unknown",
            normalized_date=None,
            date_status="needs_review",
            date_source="printed",
        )
        ok = self.db.confirm_product_date(
            pid,
            normalized_date="2026-11-15",
            date_type="best_before",
            notes="Manually verified top flap stamp",
        )
        self.assertTrue(ok)

        p = self.db.get_product(pid)
        self.assertEqual(p.normalized_date, "2026-11-15")
        self.assertEqual(p.date_type, "best_before")
        self.assertEqual(p.date_status, "confirmed")
        self.assertEqual(p.date_source, "user_confirmed")
        self.assertIn("top flap stamp", p.notes)


class TestPersistenceAcrossConnections(unittest.TestCase):
    """Verifies that data committed persists across separate DB connections."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_persist.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_separate_connection_persistence(self) -> None:
        db1 = InventoryDatabase(self.db_path)
        pid = db1.add_product("Butter 500g", brand="Kerrygold", normalized_date="2026-12-31")

        # Open completely independent instance
        db2 = InventoryDatabase(self.db_path)
        p = db2.get_product(pid)
        self.assertIsNotNone(p)
        self.assertEqual(p.product_name, "Butter 500g")
        self.assertEqual(p.brand, "Kerrygold")
        self.assertEqual(p.normalized_date, "2026-12-31")


class TestDateValidationAndRejection(unittest.TestCase):
    """Verifies that malformed or impossible dates are rejected."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = InventoryDatabase(Path(self.temp_dir.name) / "test_dates.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_valid_iso_dates_accepted(self) -> None:
        pid = self.db.add_product("Bread", normalized_date="2026-10-31")
        self.assertEqual(self.db.get_product(pid).normalized_date, "2026-10-31")

    def test_malformed_dates_rejected(self) -> None:
        invalid_dates = [
            "2026-13-01",  # month 13
            "2026-02-31",  # Feb 31
            "31/10/2026",  # non-ISO format
            "2026/10/31",  # slashes
            "October 2026",  # missing day
            "2026-10",  # missing day
            "not-a-date",
        ]
        for bad_date in invalid_dates:
            with self.subTest(bad_date=bad_date):
                with self.assertRaises(InvalidDateError):
                    self.db.add_product("Item", normalized_date=bad_date)

    def test_confirm_date_rejects_malformed_dates(self) -> None:
        pid = self.db.add_product("Milk", normalized_date="2026-10-20")
        with self.assertRaises(InvalidDateError):
            self.db.confirm_product_date(pid, normalized_date="invalid-date")


class TestDateStatusCalculations(unittest.TestCase):
    """
    Tests the pure calculate_date_status function across all boundary conditions
    using an injected reference date (2026-10-11).
    """

    REF_DATE = datetime.date(2026, 10, 11)

    def test_missing_or_empty_dates_return_unknown(self) -> None:
        self.assertEqual(calculate_date_status(None, "expiry", ref_date=self.REF_DATE), "unknown")
        self.assertEqual(calculate_date_status("", "expiry", ref_date=self.REF_DATE), "unknown")
        self.assertEqual(calculate_date_status("   ", "expiry", ref_date=self.REF_DATE), "unknown")

    def test_manufacturing_dates_never_treated_as_expiry(self) -> None:
        # Manufacturing and packed dates must return 'not_an_expiry_date'
        self.assertEqual(
            calculate_date_status("2026-10-01", "manufacturing", ref_date=self.REF_DATE),
            "not_an_expiry_date",
        )
        self.assertEqual(
            calculate_date_status("2026-10-11", "packed_on", ref_date=self.REF_DATE),
            "not_an_expiry_date",
        )

    def test_best_before_distinct_status(self) -> None:
        # Best before date in the past
        self.assertEqual(
            calculate_date_status("2026-10-05", "best_before", ref_date=self.REF_DATE),
            "best_before_passed",
        )
        # Best before date today
        self.assertEqual(
            calculate_date_status("2026-10-11", "best_before", ref_date=self.REF_DATE),
            "best_before_today",
        )
        # Best before within warning days (7 days -> 2026-10-18)
        self.assertEqual(
            calculate_date_status("2026-10-15", "best_before", ref_date=self.REF_DATE),
            "best_before_soon",
        )
        # Best before well into the future
        self.assertEqual(
            calculate_date_status("2026-11-01", "best_before", ref_date=self.REF_DATE),
            "best_before_future",
        )

    def test_expiry_date_boundaries(self) -> None:
        # 1. Expired (yesterday)
        self.assertEqual(
            calculate_date_status("2026-10-10", "expiry", ref_date=self.REF_DATE),
            "expired",
        )
        # 2. Expires today
        self.assertEqual(
            calculate_date_status("2026-10-11", "expiry", ref_date=self.REF_DATE),
            "expires_today",
        )
        # 3. Expiring soon (tomorrow, +1 day)
        self.assertEqual(
            calculate_date_status("2026-10-12", "expiry", ref_date=self.REF_DATE),
            "expiring_soon",
        )
        # 4. Expiring soon (exactly on warning threshold, +7 days = 2026-10-18 inclusive boundary)
        self.assertEqual(
            calculate_date_status("2026-10-18", "expiry", ref_date=self.REF_DATE, warning_days=7),
            "expiring_soon",
        )
        # 5. Not expiring soon (+8 days = 2026-10-19)
        self.assertEqual(
            calculate_date_status("2026-10-19", "expiry", ref_date=self.REF_DATE, warning_days=7),
            "not_expiring_soon",
        )
        # 6. Future (+30 days)
        self.assertEqual(
            calculate_date_status("2026-11-10", "expiry", ref_date=self.REF_DATE),
            "not_expiring_soon",
        )

    def test_use_by_equivalent_to_expiry(self) -> None:
        self.assertEqual(calculate_date_status("2026-10-10", "use_by", ref_date=self.REF_DATE), "expired")
        self.assertEqual(calculate_date_status("2026-10-11", "use_by", ref_date=self.REF_DATE), "expires_today")
        self.assertEqual(calculate_date_status("2026-10-15", "use_by", ref_date=self.REF_DATE), "expiring_soon")


class TestDuplicateProtection(unittest.TestCase):
    """Verifies that duplicate products trigger warnings unless force=True."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = InventoryDatabase(Path(self.temp_dir.name) / "test_dup.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_duplicate_product_rejected_without_force(self) -> None:
        self.db.add_product("Brown Bread", brand="Bonn", normalized_date="2026-10-18")

        # Attempt to add exact same product and date
        with self.assertRaises(DuplicateProductError) as ctx:
            self.db.add_product("Brown Bread", brand="Bonn", normalized_date="2026-10-18")
        self.assertIn("Potential duplicate", str(ctx.exception))

    def test_duplicate_product_accepted_with_force(self) -> None:
        id1 = self.db.add_product("Brown Bread", brand="Bonn", normalized_date="2026-10-18")
        id2 = self.db.add_product("Brown Bread", brand="Bonn", normalized_date="2026-10-18", force=True)
        self.assertNotEqual(id1, id2)
        self.assertEqual(len(self.db.list_products()), 2)


class TestScanHistoryAndReviewSafety(unittest.TestCase):
    """Verifies scan history persistence and ensures unverified scans do not become confirmed products."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = InventoryDatabase(Path(self.temp_dir.name) / "test_scans.db")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_record_scan_history_and_candidates(self) -> None:
        # Mock a result object mimicking FoodAnalysisResult
        class MockCandidate:
            raw_text = "01/09/26"
            date_type = "manufacturing"
            normalized_date = "2026-09-01"
            confidence = 0.90
            evidence = "Date of Mfg."

        class MockResult:
            product_name = "Bakery Cookies"
            brand = "Sai Chanduram"
            food_category = "Bakery"
            analysis_status = "success"
            needs_review = True
            review_reason = "Only manufacturing date present"
            selected_expiry_date = None
            date_candidates = [MockCandidate()]

        scan_id = self.db.record_scan("captures/sample.jpg", MockResult())
        self.assertIsInstance(scan_id, int)

        scan = self.db.get_scan(scan_id)
        self.assertIsNotNone(scan)
        self.assertEqual(scan.product_name, "Bakery Cookies")
        self.assertEqual(scan.brand, "Sai Chanduram")
        self.assertTrue(scan.needs_review)
        self.assertIn("manufacturing date", scan.review_reason)

        # CRITICAL SAFETY CHECK: scan was recorded in scan_history, but products table remains EMPTY
        products = self.db.list_products()
        self.assertEqual(len(products), 0, "Scan must NOT automatically become an inventory product!")


class TestInventoryCLI(unittest.TestCase):
    """Tests the inventory.py CLI commands."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_cli.db")
        self.py = sys.executable

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = [self.py, "inventory.py", "--db", self.db_path, *args]
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent))

    def test_cli_empty_list(self) -> None:
        res = self._run_cli("list")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Inventory is currently empty", res.stdout)

    def test_cli_add_and_list(self) -> None:
        res_add = self._run_cli("add", "--name", "Organic Milk", "--brand", "Horizon", "--date", "2026-10-25")
        self.assertEqual(res_add.returncode, 0)
        self.assertIn("Successfully added product ID #1", res_add.stdout)

        res_list = self._run_cli("list")
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("Organic Milk", res_list.stdout)
        self.assertIn("Horizon", res_list.stdout)

    def test_cli_search_and_show(self) -> None:
        self._run_cli("add", "--name", "Cheddar Cheese", "--brand", "Amul", "--category", "Dairy")

        res_search = self._run_cli("search", "cheddar")
        self.assertEqual(res_search.returncode, 0)
        self.assertIn("Cheddar Cheese", res_search.stdout)

        res_show = self._run_cli("show", "1")
        self.assertEqual(res_show.returncode, 0)
        self.assertIn("Product Name       : Cheddar Cheese", res_show.stdout)
        self.assertIn("Category           : Dairy", res_show.stdout)

    def test_cli_confirm_date(self) -> None:
        self._run_cli("add", "--name", "Bread", "--status", "unverified")
        res_conf = self._run_cli("confirm-date", "1", "--date", "2026-10-30", "--type", "expiry")
        self.assertEqual(res_conf.returncode, 0)
        self.assertIn("successfully confirmed as 2026-10-30", res_conf.stdout)

        res_show = self._run_cli("show", "1")
        self.assertIn("Recorded Date      : 2026-10-30", res_show.stdout)
        self.assertIn("confirmed", res_show.stdout)

    def test_cli_delete(self) -> None:
        self._run_cli("add", "--name", "Quick Item")
        res_del = self._run_cli("delete", "1", "-y")
        self.assertEqual(res_del.returncode, 0)
        self.assertIn("deleted", res_del.stdout)

        res_list = self._run_cli("list")
        self.assertIn("Inventory is currently empty", res_list.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
