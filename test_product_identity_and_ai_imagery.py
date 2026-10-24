"""
Tests for Product Identity and Asynchronous AI Image Generation
"""

import os
import tempfile
import unittest
import numpy as np
import cv2

from product_identity import (
    derive_display_name,
    clean_raw_name_string,
    title_case_name,
)
from ai_image_generator import (
    AIProductImageGenerator,
    build_product_image_prompt,
    overlay_product_label_pill,
    GeneratedImageResult,
)
from inventory_db import InventoryDatabase, ProductRecord


class TestProductIdentity(unittest.TestCase):
    def test_derived_display_name_known_brands(self):
        # Amul Taaza
        name = derive_display_name("Amul Taaza 1L", brand="Amul", category="Dairy & Eggs")
        self.assertIn("Amul", name)
        self.assertIn("Taaza", name)
        self.assertIn("Milk", name)

        # Parle Products
        name = derive_display_name("Parle Products", brand="Parle", category="Pantry Staples")
        self.assertIn("Parle", name)
        self.assertIn("Biscuit", name)

        # Maggi
        name = derive_display_name("Maggi", brand="Nestle", category="Pantry Staples")
        self.assertIn("Maggi", name)
        self.assertIn("Noodles", name)

        # Fortune
        name = derive_display_name("Fortune 1L", brand="Fortune", category="Pantry Staples")
        self.assertIn("Fortune", name)
        self.assertIn("Oil", name)

    def test_derived_display_name_regional_protection(self):
        # Regional foods must keep their authentic identity
        poha = derive_display_name("Poha Thick", brand="", category="Grains & Cereals")
        self.assertIn("Poha", poha)

        khakhra = derive_display_name("Methi Khakhra Crispy", brand="", category="Pantry Staples")
        self.assertIn("Khakhra", khakhra)

        sattu = derive_display_name("Chana Sattu Pure", brand="", category="Grains & Cereals")
        self.assertIn("Sattu", sattu)

    def test_clean_raw_name_removes_noise_and_duplicates(self):
        # Repeated brand
        cleaned = clean_raw_name_string("Amul Amul Milk")
        self.assertEqual(cleaned, "Amul Milk")

        # Strip dates / batch noise
        noisy = clean_raw_name_string("Tata Salt 1kg B.No. 402 MFG 10/25")
        self.assertNotIn("MFG", noisy)
        self.assertNotIn("B.No", noisy)
        self.assertIn("Tata Salt", noisy)

    def test_title_casing_preserves_known_acronyms(self):
        titled = title_case_name("amul uht toned milk 500ml")
        self.assertIn("UHT", titled)
        self.assertIn("Amul", titled)


class TestAIProductImageGenerator(unittest.TestCase):
    def test_prompt_construction(self):
        prompt = build_product_image_prompt("Amul Taaza", brand="Amul", category="Dairy & Eggs")
        self.assertIn("#FAF7F2", prompt)
        self.assertIn("Amul", prompt)
        self.assertIn("catalog photograph", prompt)

    def test_pill_label_overlay(self):
        # Create a test blank image
        test_img = np.full((300, 300, 3), 245, dtype=np.uint8)
        labeled = overlay_product_label_pill(test_img, "Amul Milk")
        self.assertEqual(labeled.shape, test_img.shape)
        # Verify image was modified
        self.assertFalse(np.array_equal(test_img, labeled))

    def test_validation_rejects_corrupt_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = AIProductImageGenerator(api_key="", output_dir=tmpdir)
            result = gen.generate_product_image("")
            self.assertFalse(result.success)
            self.assertEqual(result.status, "validation_failed")

    def test_caching_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = AIProductImageGenerator(api_key="", output_dir=tmpdir)
            # Create a valid pre-existing source and cropped image file
            dummy_img = np.full((200, 200, 3), 200, dtype=np.uint8)
            source_img_path = os.path.join(tmpdir, "source_scan.jpg")
            cv2.imwrite(source_img_path, dummy_img)

            import hashlib
            from product_identity import derive_display_name
            identity = derive_display_name("Test Product", None, None)
            id_hash = hashlib.sha256(identity.lower().encode("utf-8")).hexdigest()[:10]
            existing_path = os.path.join(tmpdir, f"crop_999_{id_hash}.jpg")
            cv2.imwrite(existing_path, dummy_img)

            # Request crop generation for product_id=999
            result = gen.generate_product_image("Test Product", product_id=999, source_image_path=source_img_path)
            self.assertTrue(result.success)
            self.assertEqual(result.status, "generated")
            self.assertEqual(result.image_path, existing_path)


class TestImagePrecedenceAndDatabase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        self.db = InventoryDatabase(self.db_path)

    def tearDown(self):
        try:
            os.close(self.db_fd)
            if os.path.exists(self.db_path):
                os.unlink(self.db_path)
        except Exception:
            pass

    def test_image_precedence_rules(self):
        # Insert a product
        prod_id = self.db.add_product(
            product_name="Amul Butter",
            brand="Amul",
            food_category="Dairy & Eggs",
            normalized_date="2026-11-01",
            date_type="Expiry",
            date_status="verified",
        )

        # 1. Apply AI generated image -> should succeed
        applied = self.db.apply_resolved_product_image(
            product_id=prod_id,
            job_id=None,
            image_path="/captures/generated/prod_1.jpg",
            image_metadata={"source": "ai_generated"},
            image_source_type="generated",
        )
        self.assertTrue(applied)
        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_source_type, "generated")
        self.assertEqual(prod.image_path, "/captures/generated/prod_1.jpg")

        # 2. Apply verified catalog image -> should overwrite generated image
        applied_catalog = self.db.apply_resolved_product_image(
            product_id=prod_id,
            job_id=None,
            image_path="https://images.openfoodfacts.org/butter.jpg",
            image_metadata={"source": "openfoodfacts"},
            image_source_type="catalog",
        )
        self.assertTrue(applied_catalog)
        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_source_type, "catalog")
        self.assertEqual(prod.image_path, "https://images.openfoodfacts.org/butter.jpg")

        # 3. Apply another AI generated image -> should NOT overwrite catalog image
        applied_gen_again = self.db.apply_resolved_product_image(
            product_id=prod_id,
            job_id=None,
            image_path="/captures/generated/prod_1_new.jpg",
            image_metadata={"source": "ai_generated"},
            image_source_type="generated",
        )
        self.assertFalse(applied_gen_again)
        prod = self.db.get_product(prod_id)
        self.assertEqual(prod.image_source_type, "catalog")
        self.assertEqual(prod.image_path, "https://images.openfoodfacts.org/butter.jpg")

    def test_product_record_display_name_property(self):
        prod = ProductRecord(
            id=1,
            product_name="Amul Taaza 1L",
            brand="Amul",
            food_category="Dairy & Eggs",
            date_type="Expiry",
            date_text="01/11/2026",
            normalized_date="2026-11-01",
            date_status="verified",
            date_source="printed",
            analysis_status="success",
            image_path=None,
            notes=None,
            created_at="2026-10-22",
            updated_at="2026-10-22",
        )
        self.assertIn("Amul Taaza Toned Milk", prod.display_name)
        d = prod.to_dict()
        self.assertIn("display_name", d)
        self.assertEqual(d["display_name"], prod.display_name)


if __name__ == "__main__":
    unittest.main()
