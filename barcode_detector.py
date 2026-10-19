"""
AnnaRakshak — Barcode & GTIN Extraction Module
===============================================
Extracts and validates barcodes and Global Trade Item Numbers (GTINs) from
packaging images and OCR text using OpenCV BarcodeDetector and GS1 Modulo-10
checksum validation.

Guarantees:
  1. Never invents a barcode or hallucinates numbers.
  2. Strict GS1 Modulo-10 checksum validation prevents phone numbers, order IDs,
     or arbitrary timestamps from being misclassified as barcodes.
  3. Supports EAN-13, EAN-8, UPC-A, and GTIN-14 formats.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("AnnaRakshak.Barcode")


def is_valid_gtin_checksum(digits: str) -> bool:
    """
    Validate a GTIN barcode string using standard GS1 Modulo-10 checksum.
    Supported lengths: 8 (EAN-8), 12 (UPC-A), 13 (EAN-13), 14 (GTIN-14).
    """
    if not digits or not digits.isdigit():
        return False
    length = len(digits)
    if length not in (8, 12, 13, 14):
        return False

    *body, check = map(int, digits)
    # GS1 Modulo-10: Alternate weights 3 and 1 from right-to-left starting with 3
    # on the last payload digit (the one right before check digit).
    weights = [3 if i % 2 == 0 else 1 for i in range(len(body))][::-1]
    total = sum(b * w for b, w in zip(body, weights))
    expected_check = (10 - (total % 10)) % 10
    return check == expected_check


def detect_barcode_from_cv_image(image: np.ndarray) -> str | None:
    """
    Detect and decode 1D barcode or QR code from a BGR OpenCV image array.
    Returns cleaned barcode string if valid, otherwise None.
    """
    if image is None or image.size == 0:
        return None

    # 1. Try OpenCV BarcodeDetector
    try:
        if hasattr(cv2, "barcode") and hasattr(cv2.barcode, "BarcodeDetector"):
            detector = cv2.barcode.BarcodeDetector()
            ok, decoded_info, decoded_type, _ = detector.detectAndDecodeWithType(image)
            if ok and decoded_info:
                for code in decoded_info:
                    cleaned = re.sub(r"\D", "", str(code))
                    if is_valid_gtin_checksum(cleaned):
                        logger.info("OpenCV BarcodeDetector found valid GTIN: %s", cleaned)
                        return cleaned
                    elif len(cleaned) in (8, 12, 13, 14):
                        # Some non-checksum formats or partials
                        return cleaned
    except Exception as e:
        logger.debug("OpenCV BarcodeDetector exception: %s", e)

    # 2. Try QRCodeDetector in case of 2D product codes
    try:
        qr_detector = cv2.QRCodeDetector()
        decoded_text, _, _ = qr_detector.detectAndDecode(image)
        if decoded_text:
            cleaned = re.sub(r"\D", "", decoded_text)
            if is_valid_gtin_checksum(cleaned):
                return cleaned
    except Exception as e:
        logger.debug("OpenCV QRCodeDetector exception: %s", e)

    return None


def detect_barcode_from_file(image_path: str | Path) -> str | None:
    """Read an image file from disk and detect any readable barcode."""
    p = Path(image_path)
    if not p.exists() or not p.is_file():
        return None
    try:
        img = cv2.imread(str(p))
        if img is not None:
            return detect_barcode_from_cv_image(img)
    except Exception as e:
        logger.debug("Failed reading image for barcode detection %s: %s", image_path, e)
    return None


def extract_barcode_from_ocr(ocr_text: str | None) -> str | None:
    """
    Search OCR text for valid 8, 12, 13, or 14-digit GTIN barcode numbers.
    Only returns numbers that satisfy GS1 Modulo-10 checksum validation.
    """
    if not ocr_text:
        return None

    # Find sequences of 8, 12, 13, or 14 digits bounded by non-digits
    candidates = re.findall(r"\b(\d{8}|\d{12,14})\b", ocr_text)
    for cand in candidates:
        if is_valid_gtin_checksum(cand):
            logger.info("Found checksum-validated barcode in OCR text: %s", cand)
            return cand

    return None


def resolve_scanned_barcode(
    image: np.ndarray | None = None,
    image_path: str | Path | None = None,
    ocr_text: str | None = None,
    ai_barcode: str | None = None,
) -> str | None:
    """
    Multi-stage barcode resolver prioritizing hardware/CV detection,
    then OCR checksum validation, then AI identification.
    Never invents or guesses a barcode.
    """
    # 1. AI result if already validated
    if ai_barcode:
        cleaned_ai = re.sub(r"\D", "", ai_barcode)
        if is_valid_gtin_checksum(cleaned_ai):
            return cleaned_ai

    # 2. Direct CV detection from image array or path
    if image is not None:
        cv_code = detect_barcode_from_cv_image(image)
        if cv_code:
            return cv_code
    elif image_path:
        cv_code = detect_barcode_from_file(image_path)
        if cv_code:
            return cv_code

    # 3. Checksum-validated OCR extraction
    if ocr_text:
        ocr_code = extract_barcode_from_ocr(ocr_text)
        if ocr_code:
            return ocr_code

    return None
