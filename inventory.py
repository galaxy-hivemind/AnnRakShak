"""
AnnaRakshak — Inventory Command-Line Interface (CLI)
===================================================
Provides convenient inspection, manual confirmation, search, and editing
of household food inventory stored in `annarakshak.db`.

Usage Examples:
  python inventory.py list
  python inventory.py search "milk"
  python inventory.py show 1
  python inventory.py add --name "Bread" --brand "Modern" --date 2026-10-15 --type expiry
  python inventory.py add-scan 3
  python inventory.py confirm-date 1 --date 2026-10-28 --type use_by
  python inventory.py edit 1 --category "Dairy"
  python inventory.py delete 1
  python inventory.py scans
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from inventory_db import (
    DEFAULT_DB_PATH,
    DEFAULT_WARNING_DAYS,
    DuplicateProductError,
    InvalidDateError,
    InventoryDatabase,
    ProductNotFoundError,
    calculate_date_status,
)


def _format_status_badge(status: str) -> str:
    """Format date status for terminal display."""
    badges = {
        "expired": "[EXPIRED]",
        "expires_today": "[EXPIRES TODAY]",
        "expiring_soon": "[EXPIRING SOON]",
        "not_expiring_soon": "[OK]",
        "best_before_passed": "[BB PASSED]",
        "best_before_today": "[BB TODAY]",
        "best_before_soon": "[BB SOON]",
        "best_before_future": "[BB OK]",
        "not_an_expiry_date": "[MFG/PACKED]",
        "unknown": "[UNKNOWN]",
    }
    return badges.get(status, f"[{status.upper()}]")


def cmd_list(db: InventoryDatabase, args: argparse.Namespace) -> int:
    products = db.list_products(filter_status=args.status)
    if not products:
        print("\nInventory is currently empty.")
        print("To add products, run 'python inventory.py add' or scan packages with 'python auto_scan.py'.\n")
        return 0

    print("=" * 95)
    print("AnnaRakshak — Household Food Inventory")
    print("=" * 95)
    print(f"{'ID':<4} | {'Product Name':<28} | {'Brand':<16} | {'Date Type':<12} | {'Date':<10} | {'Status':<14}")
    print("-" * 95)

    ref_date = datetime.date.today()
    for p in products:
        stat = p.current_status(ref_date=ref_date)
        badge = _format_status_badge(stat)
        p_name = p.product_name[:26] + ".." if len(p.product_name) > 28 else p.product_name
        brand = (p.brand or "—")[:14]
        d_type = p.date_type
        d_val = p.normalized_date or "None"
        print(f"{p.id:<4} | {p_name:<28} | {brand:<16} | {d_type:<12} | {d_val:<10} | {badge:<14}")

    print("-" * 95)
    print(f"Total: {len(products)} item(s) in inventory.\n")
    return 0


def cmd_search(db: InventoryDatabase, args: argparse.Namespace) -> int:
    query = args.query.strip()
    products = db.search_products(query)
    if not products:
        print(f"\nNo products found matching '{query}'.\n")
        return 0

    print(f"\nSearch results for '{query}' ({len(products)} found):")
    print("-" * 95)
    print(f"{'ID':<4} | {'Product Name':<28} | {'Brand':<16} | {'Date Type':<12} | {'Date':<10} | {'Status':<14}")
    print("-" * 95)

    ref_date = datetime.date.today()
    for p in products:
        stat = p.current_status(ref_date=ref_date)
        badge = _format_status_badge(stat)
        p_name = p.product_name[:26] + ".." if len(p.product_name) > 28 else p.product_name
        brand = (p.brand or "—")[:14]
        d_type = p.date_type
        d_val = p.normalized_date or "None"
        print(f"{p.id:<4} | {p_name:<28} | {brand:<16} | {d_type:<12} | {d_val:<10} | {badge:<14}")

    print("-" * 95 + "\n")
    return 0


def cmd_show(db: InventoryDatabase, args: argparse.Namespace) -> int:
    p = db.get_product(args.id)
    if not p:
        print(f"\nError: Product with ID #{args.id} does not exist.\n")
        return 1

    candidates = db.get_product_date_candidates(args.id)
    stat = p.current_status()

    print("=" * 65)
    print(f"Product Details — ID #{p.id}")
    print("=" * 65)
    print(f"Product Name       : {p.product_name}")
    print(f"Brand              : {p.brand or '—'}")
    print(f"Category           : {p.food_category or '—'}")
    print(f"Date Type          : {p.date_type}")
    print(f"Recorded Date      : {p.normalized_date or 'None'}")
    print(f"Date Status        : {p.date_status} (Source: {p.date_source})")
    print(f"Current Shelf Life : {_format_status_badge(stat)} ({stat})")
    print(f"Printed Label Text : {p.date_text or '—'}")
    print(f"Analysis Status    : {p.analysis_status or '—'}")
    print(f"Image Reference    : {p.image_path or '—'}")
    print(f"Created At         : {p.created_at}")
    print(f"Updated At         : {p.updated_at}")
    if p.notes:
        print(f"Notes              : {p.notes}")

    if candidates:
        print("-" * 65)
        print(f"Printed Date Candidates ({len(candidates)} recorded):")
        for i, c in enumerate(candidates, 1):
            print(f"  [{i}] Raw: '{c.raw_text}' | Type: {c.date_type} | Norm: {c.normalized_date or 'None'} (Conf: {c.confidence:.2f})")
            if c.evidence:
                print(f"      Evidence: {c.evidence}")
    print("=" * 65 + "\n")
    return 0


def cmd_add(db: InventoryDatabase, args: argparse.Namespace) -> int:
    product_name = args.name or args.name_flag
    if not product_name or not product_name.strip():
        print("\nError: Product name is required (use: python inventory.py add 'Name' or --name 'Name').\n")
        return 1

    try:
        product_id = db.add_product(
            product_name=product_name.strip(),
            brand=args.brand,
            food_category=args.category,
            date_type=args.type,
            normalized_date=args.date,
            date_text=args.text,
            date_status=args.status,
            date_source="manual_entry",
            notes=args.notes,
            force=args.force,
        )
        print(f"\nSuccessfully added product ID #{product_id}: '{product_name.strip()}'\n")
        return 0
    except DuplicateProductError as e:
        print(f"\nWarning: {e}")
        print("To confirm and add anyway, append --force to your command.\n")
        return 1
    except (ValueError, InvalidDateError) as e:
        print(f"\nError: {e}\n")
        return 1


def cmd_add_scan(db: InventoryDatabase, args: argparse.Namespace) -> int:
    scan = db.get_scan(args.scan_id)
    if not scan:
        print(f"\nError: Scan ID #{args.scan_id} not found in scan history.\n")
        return 1

    name = args.name or scan.product_name or "Unknown Item"
    brand = args.brand or scan.brand
    category = args.category or scan.food_category
    date_val = args.date if args.date is not None else scan.selected_expiry_date
    date_type = args.type or ("expiry" if date_val else "unknown")

    # If date was selected or overridden, status is confirmed; otherwise needs review
    date_status = "confirmed" if (args.date or (date_val and not scan.needs_review)) else "needs_review"
    date_source = "user_confirmed" if args.date else "printed"

    print("=" * 65)
    print(f"Confirm Adding Product from Scan #{scan.id}")
    print("=" * 65)
    print(f"Product Name : {name}")
    print(f"Brand        : {brand or '—'}")
    print(f"Category     : {category or '—'}")
    print(f"Date Type    : {date_type}")
    print(f"Date         : {date_val or 'None'}")
    print(f"Date Status  : {date_status}")
    print(f"Image File   : {scan.image_path}")
    if scan.review_reason:
        print(f"Scan Note    : {scan.review_reason}")
    print("-" * 65)

    try:
        product_id = db.add_product(
            product_name=name,
            brand=brand,
            food_category=category,
            date_type=date_type,
            normalized_date=date_val,
            date_status=date_status,
            date_source=date_source,
            analysis_status=scan.analysis_status,
            image_path=scan.image_path,
            notes=f"Created from Scan #{scan.id}. Reason: {scan.review_reason or 'None'}",
            force=args.force,
        )
        print(f"Successfully added to inventory as Product ID #{product_id}!\n")
        return 0
    except DuplicateProductError as e:
        print(f"\nWarning: {e}")
        print("To confirm and add anyway, pass --force.\n")
        return 1
    except (ValueError, InvalidDateError) as e:
        print(f"\nError: {e}\n")
        return 1


def cmd_confirm_date(db: InventoryDatabase, args: argparse.Namespace) -> int:
    date_val = args.date or args.date_flag
    if not date_val:
        print("\nError: Date is required (use: python inventory.py confirm-date <ID> <YYYY-MM-DD> or --date <YYYY-MM-DD>).\n")
        return 1

    try:
        ok = db.confirm_product_date(
            product_id=args.id,
            normalized_date=date_val,
            date_type=args.type,
            notes=args.notes,
        )
        if ok:
            print(f"\nProduct ID #{args.id} date successfully confirmed as {date_val} ({args.type}).\n")
            return 0
        print(f"\nFailed to confirm date for Product ID #{args.id}.\n")
        return 1
    except ProductNotFoundError as e:
        print(f"\nError: {e}\n")
        return 1
    except InvalidDateError as e:
        print(f"\nError: {e}\n")
        return 1


def cmd_edit(db: InventoryDatabase, args: argparse.Namespace) -> int:
    updates = {}
    if args.name is not None:
        updates["product_name"] = args.name
    if args.brand is not None:
        updates["brand"] = args.brand
    if args.category is not None:
        updates["food_category"] = args.category
    if args.notes is not None:
        updates["notes"] = args.notes

    if not updates:
        print("\nNo fields specified to update. Use --name, --brand, --category, or --notes.\n")
        return 1

    try:
        db.update_product(args.id, **updates)
        print(f"\nProduct ID #{args.id} updated successfully.\n")
        return 0
    except ProductNotFoundError as e:
        print(f"\nError: {e}\n")
        return 1
    except ValueError as e:
        print(f"\nError: {e}\n")
        return 1


def cmd_delete(db: InventoryDatabase, args: argparse.Namespace) -> int:
    p = db.get_product(args.id)
    if not p:
        print(f"\nError: Product ID #{args.id} does not exist.\n")
        return 1

    if not args.yes:
        confirm = input(f"Are you sure you want to delete Product #{p.id} ('{p.product_name}')? [y/N]: ")
        if confirm.strip().lower() not in ("y", "yes"):
            print("Deletion cancelled.")
            return 0

    try:
        db.delete_product(args.id)
        print(f"\nProduct ID #{args.id} ('{p.product_name}') deleted.\n")
        return 0
    except ProductNotFoundError as e:
        print(f"\nError: {e}\n")
        return 1


def cmd_scans(db: InventoryDatabase, args: argparse.Namespace) -> int:
    scans = db.get_recent_scans(limit=args.limit)
    if not scans:
        print("\nNo scans found in history. Run 'python auto_scan.py' to capture items.\n")
        return 0

    print("=" * 95)
    print(f"AnnaRakshak — Recent Camera Scan History (last {len(scans)})")
    print("=" * 95)
    print(f"{'ID':<4} | {'Timestamp':<20} | {'Identified Item':<26} | {'Status':<12} | {'Expiry Date':<12} | {'Review':<8}")
    print("-" * 95)

    for s in scans:
        ts = s.timestamp[:19].replace("T", " ")
        item = (s.product_name or s.brand or "Unknown")[:24]
        status = s.analysis_status[:12]
        exp = s.selected_expiry_date or "—"
        rev = "YES" if s.needs_review else "NO"
        print(f"{s.id:<4} | {ts:<20} | {item:<26} | {status:<12} | {exp:<12} | {rev:<8}")

    print("-" * 95)
    print("To add any scan to inventory, run: python inventory.py add-scan <ID>\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AnnaRakshak — Household Food Inventory CLI",
    )
    parser.add_argument(
        "--db", type=str, default=None,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH}).",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List inventory products.")
    p_list.add_argument("--status", type=str, default=None, help="Filter by date_status (confirmed, needs_review, unverified).")

    # search
    p_search = subparsers.add_parser("search", help="Search products by name, brand, or category.")
    p_search.add_argument("query", type=str, help="Search string.")

    # show
    p_show = subparsers.add_parser("show", help="Show full product details and candidate dates.")
    p_show.add_argument("id", type=int, help="Product ID.")

    # add
    p_add = subparsers.add_parser("add", help="Manually add a product to inventory.")
    p_add.add_argument("name", nargs="?", default=None, help="Product name (positional).")
    p_add.add_argument("--name", dest="name_flag", default=None, help="Product name (--name flag).")
    p_add.add_argument("--brand", type=str, default=None, help="Brand name.")
    p_add.add_argument("--category", type=str, default=None, help="Food category.")
    p_add.add_argument("--date", type=str, default=None, help="ISO date YYYY-MM-DD.")
    p_add.add_argument("--type", type=str, default="expiry", help="Date type (expiry, use_by, best_before, etc.).")
    p_add.add_argument("--text", type=str, default=None, help="Raw printed date text.")
    p_add.add_argument("--status", type=str, default="confirmed", help="Date verification status.")
    p_add.add_argument("--notes", type=str, default=None, help="Optional notes.")
    p_add.add_argument("--force", action="store_true", help="Confirm duplicate addition.")

    # add-scan
    p_add_scan = subparsers.add_parser("add-scan", help="Add a product from camera scan history.")
    p_add_scan.add_argument("scan_id", type=int, help="Scan history ID.")
    p_add_scan.add_argument("--name", type=str, default=None, help="Override product name.")
    p_add_scan.add_argument("--brand", type=str, default=None, help="Override brand.")
    p_add_scan.add_argument("--category", type=str, default=None, help="Override category.")
    p_add_scan.add_argument("--date", type=str, default=None, help="Confirmed ISO date YYYY-MM-DD.")
    p_add_scan.add_argument("--type", type=str, default=None, help="Date type (expiry, use_by, best_before).")
    p_add_scan.add_argument("--force", action="store_true", help="Confirm duplicate addition.")

    # confirm-date
    p_confirm = subparsers.add_parser("confirm-date", help="Confirm or correct product date after manual review.")
    p_confirm.add_argument("id", type=int, help="Product ID.")
    p_confirm.add_argument("date", nargs="?", default=None, help="Confirmed ISO date YYYY-MM-DD (positional).")
    p_confirm.add_argument("--date", dest="date_flag", default=None, help="Confirmed ISO date YYYY-MM-DD (--date flag).")
    p_confirm.add_argument("--type", type=str, default="expiry", help="Date type (expiry, use_by, best_before).")
    p_confirm.add_argument("--notes", type=str, default=None, help="Verification notes.")

    # edit
    p_edit = subparsers.add_parser("edit", help="Edit product details.")
    p_edit.add_argument("id", type=int, help="Product ID.")
    p_edit.add_argument("--name", type=str, default=None, help="New product name.")
    p_edit.add_argument("--brand", type=str, default=None, help="New brand.")
    p_edit.add_argument("--category", type=str, default=None, help="New category.")
    p_edit.add_argument("--notes", type=str, default=None, help="New notes.")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a product from inventory.")
    p_delete.add_argument("id", type=int, help="Product ID.")
    p_delete.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt.")

    # scans
    p_scans = subparsers.add_parser("scans", help="Show recent camera scan history.")
    p_scans.add_argument("--limit", type=int, default=15, help="Number of scans to show.")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    db = InventoryDatabase(db_path=args.db)

    handlers = {
        "list": cmd_list,
        "search": cmd_search,
        "show": cmd_show,
        "add": cmd_add,
        "add-scan": cmd_add_scan,
        "confirm-date": cmd_confirm_date,
        "edit": cmd_edit,
        "delete": cmd_delete,
        "scans": cmd_scans,
    }

    handler = handlers.get(args.subcommand)
    if not handler:
        parser.print_help()
        return 1

    return handler(db, args)


if __name__ == "__main__":
    sys.exit(main())
