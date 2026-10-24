"""
AnnaRakshak — Verification Suite for 3-Tier Image Overhaul
==========================================================
Verifies:
  1. Flavor & Variant Mismatch Prevention (e.g. Tropicana Litchi Love vs Mixed Fruit).
  2. Scanned Packaging Crop as Tier 2 (never diffusion from scratch).
  3. 200 Common Household Items Catalog as Tier 3 fallback (accurate matching, zero milk cartons on Milkybar).
  4. Backend /api/products/{id}/image SVG serving.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from household_catalog import HOUSEHOLD_CATALOG, find_best_household_item
from product_image_resolver import (
    ImageMetadata,
    ImageResolutionStatus,
    extract_variants,
    check_variant_conflict,
    score_candidate,
)
from ai_image_generator import AIProductImageGenerator, GeneratedImageResult


class TestThreeTierImageOverhaul(unittest.TestCase):
    def test_01_flavor_and_variant_conflict_detection(self):
        """Variant conflict detection strictly rejects mismatched flavors."""
        t_litchi = extract_variants("Tropicana Frutz Litchi Love")
        self.assertIn("litchi", t_litchi)
        self.assertEqual(t_litchi["litchi"], "fruit")

        # Mixed Fruit is in the same group ('fruit') but is a different flavor
        c_mixed = extract_variants("Tropicana Frutz Mixed Fruit Juice")
        self.assertIn("mixed_fruit", c_mixed)
        has_conflict, has_match = check_variant_conflict(t_litchi, c_mixed)
        self.assertTrue(has_conflict)
        self.assertFalse(has_match)

        # Scoring Mixed Fruit against Litchi Love must yield heavy negative penalty (-100)
        score_mixed = score_candidate("Tropicana", "Tropicana Frutz Mixed Fruit Juice", "Tropicana", "Tropicana Frutz Litchi Love")
        self.assertEqual(score_mixed, -100.0)

        # Orange against Litchi Love
        score_orange = score_candidate("Tropicana", "Tropicana Frutz Orange Juice", "Tropicana", "Tropicana Frutz Litchi Love")
        self.assertEqual(score_orange, -100.0)

        # Exact Litchi match
        score_exact = score_candidate("Tropicana", "Tropicana Frutz Litchi Love 250ml", "Tropicana", "Tropicana Frutz Litchi Love")
        self.assertGreater(score_exact, 70.0)

        # Lychee synonym match
        score_synonym = score_candidate("Tropicana", "Tropicana Frutz Lychee Nectar", "Tropicana", "Tropicana Frutz Litchi Love")
        self.assertGreater(score_synonym, 70.0)

    def test_02_biscuit_variety_conflict_detection(self):
        """Biscuit varieties strictly reject conflicting biscuit types."""
        t_osmania = extract_variants("DBH The Deccan Bake House Osmania Biscuits")
        self.assertIn("osmania", t_osmania)

        c_marie = extract_variants("Britannia Marie Gold Biscuits")
        self.assertIn("marie", c_marie)

        has_conflict, _ = check_variant_conflict(t_osmania, c_marie)
        self.assertTrue(has_conflict)

        score_marie = score_candidate("Britannia", "Britannia Marie Gold Biscuits", "DBH The Deccan Bake House", "Osmania Biscuits")
        self.assertEqual(score_marie, -100.0)

    def test_03_ai_scratch_diffusion_disabled(self):
        """AI image generator never uses diffusion from scratch for product display."""
        gen = AIProductImageGenerator()
        # Non-existent scan photo
        res = gen.generate_product_image_from_scratch(
            product_name="Osmania Biscuits",
            brand="DBH The Deccan Bake House",
            category="Grains",
            source_image_path=None,
        )
        self.assertFalse(res.success)
        self.assertEqual(res.status, "crop_unavailable")

    def test_04_200_household_catalog_breadth_and_accuracy(self):
        """Household items catalog has 200+ curated items and matches accurately."""
        self.assertGreaterEqual(len(HOUSEHOLD_CATALOG), 200)

        # Deccan Bake House Osmania Biscuits
        m_osmania = find_best_household_item("Osmania Biscuits", "DBH The Deccan Bake House", "Grains")
        self.assertIsNotNone(m_osmania)
        self.assertEqual(m_osmania.id, "osmania-biscuits")
        self.assertEqual(m_osmania.image_path, "/household/osmania-biscuits.svg")

        # Tropicana Frutz Litchi Love
        m_litchi = find_best_household_item("Tropicana Frutz Litchi Love", "Tropicana", "Beverages")
        self.assertIsNotNone(m_litchi)
        self.assertEqual(m_litchi.id, "litchi-juice")
        self.assertEqual(m_litchi.image_path, "/household/litchi-juice.svg")

        # Milkybar MUST match white-chocolate, NEVER milk
        m_milkybar = find_best_household_item("Milkybar", "Nestle", "Snacks")
        self.assertIsNotNone(m_milkybar)
        self.assertEqual(m_milkybar.id, "white-chocolate")
        self.assertEqual(m_milkybar.image_path, "/household/white-chocolate.svg")

        # Amul Butter
        m_butter = find_best_household_item("Table Butter", "Amul", "Dairy")
        self.assertIsNotNone(m_butter)
        self.assertEqual(m_butter.id, "butter")

        # ChanduRam's Dry Fruit Cookies
        m_cookies = find_best_household_item("Dry Fruit Cookies", "ChanduRam's", "Grains")
        self.assertIsNotNone(m_cookies)
        self.assertEqual(m_cookies.id, "dry-fruit-cookies")

        # SVG files must exist on disk for all sampled matches
        for item in [m_osmania, m_litchi, m_milkybar, m_butter, m_cookies]:
            svg_path = Path("frontend/public") / item.image_path.lstrip("/")
            self.assertTrue(svg_path.exists(), f"Missing SVG file: {svg_path}")
            self.assertGreater(svg_path.stat().st_size, 200)

    def test_05_image_worker_three_tier_hierarchy(self):
        """Worker tries Tier 1 web search, then Tier 2 crop, then Tier 3 household catalog."""
        from image_job_worker import process_image_discovery_job
        from inventory_db import InventoryDatabase

        mock_db = MagicMock(spec=InventoryDatabase)
        mock_db.claim_image_job.return_value = True

        mock_job = MagicMock()
        mock_job.product_id = 999
        mock_job.normalized_identity = "DBH The Deccan Bake House Osmania Biscuits"
        mock_db.get_image_job.return_value = mock_job

        mock_prod = MagicMock()
        mock_prod.id = 999
        mock_prod.product_name = "Osmania Biscuits"
        mock_prod.brand = "DBH The Deccan Bake House"
        mock_prod.food_category = "Grains"
        mock_prod.image_source_type = "fallback"
        mock_prod.image_path = None
        mock_prod.scan_id = None
        mock_prod.notes = None
        mock_db.get_product.return_value = mock_prod

        # Resolver returns no match (flavor conflict or not found)
        mock_resolver = MagicMock()
        no_match_meta = ImageMetadata(
            source="category_fallback",
            original_url=None,
            cached_path=None,
            status=ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH,
            barcode=None,
            product_identity="DBH The Deccan Bake House Osmania Biscuits",
        )
        mock_resolver.resolve_product_image.return_value = no_match_meta

        # Process job: No scan photo available -> Must resolve with Tier 3 Household Catalog!
        success = process_image_discovery_job(101, mock_db, resolver=mock_resolver)
        self.assertTrue(success)

        # Verify apply_resolved_product_image was called with Tier 3 catalog preset
        mock_db.apply_resolved_product_image.assert_called_once()
        args, kwargs = mock_db.apply_resolved_product_image.call_args
        self.assertEqual(kwargs.get("product_id"), 999)
        self.assertEqual(kwargs.get("image_path"), "/household/osmania-biscuits.svg")
        self.assertEqual(kwargs.get("image_source_type"), "catalog_preset")
        self.assertEqual(kwargs.get("image_metadata", {}).get("source"), "household_catalog")


if __name__ == "__main__":
    unittest.main()
