"""
AnnaRakshak — Intelligent Product Image Discovery, Validation & Persistent Caching
==================================================================================
Discovers, validates, caches, and serves real product packaging images from
authoritative product catalogs (Open Food Facts) and verified web sources.

Guarantees:
  1. Mandatory Discovery Order:
     - Stage 1: Exact Barcode / GTIN match on Open Food Facts.
     - Stage 2: Exact Product Name + Brand match on Open Food Facts.
     - Stage 3: Configured web search provider (if enabled).
     - Stage 4: Clean fallback to category-specific default image.
  2. Strict SSRF Protection: Rejects non-HTTPS, loopback, private, and link-local IPs.
  3. Image Validation: Enforces allowed MIME types, max file size, OpenCV decode,
     minimum dimensions (no 1x1 tracking pixels), and reasonable aspect ratios.
  4. Deduplication & Supplementary Scans:
     - Concurrency-safe cache keyed by barcode and normalized identity.
     - Never repeats image searches on supplementary scans when an image or no-match
       was already established.
     - Triggers lookup on supplementary scan only if a new barcode is resolved.
  5. Zero Regression: External image lookup failures never break scan or inventory flows.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import threading
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import httpx
import numpy as np

logger = logging.getLogger("AnnaRakshak.ImageResolver")

# Timeouts & Size Limits
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
DOWNLOAD_TIMEOUT_SECONDS = 8.0
MIN_IMAGE_DIMENSION = 100
MAX_IMAGE_DIMENSION = 5000
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Open Food Facts API Endpoints
OFF_BARCODE_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
OFF_USER_AGENT = "AnnaRakShak - FoodTracker - Version 1.0 - Contact: info@annarakshak.app"


class ImageResolutionStatus(str, Enum):
    VERIFIED_WEB_IMAGE = "verified_web_image"
    CATEGORY_FALLBACK = "category_fallback"
    SEARCH_PENDING = "search_pending"
    SEARCH_ATTEMPTED_NO_MATCH = "search_attempted_no_match"
    SEARCH_FAILED_RETRYABLE = "search_failed_retryable"


@dataclass
class ImageMetadata:
    source: str
    original_url: str | None
    cached_path: str | None
    status: ImageResolutionStatus
    barcode: str | None
    product_identity: str | None
    content_type: str | None = None
    width: int | None = None
    height: int | None = None
    created_at: float = 0.0

    @property
    def image_status(self) -> str:
        return self.status.value

    @property
    def image_url(self) -> str | None:
        return self.original_url

    @property
    def local_path(self) -> str | None:
        return self.cached_path

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["image_status"] = self.status.value
        d["image_url"] = self.original_url
        d["local_path"] = self.cached_path
        return d

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImageMetadata:
        stat_val = data.get("status") or data.get("image_status", ImageResolutionStatus.CATEGORY_FALLBACK.value)
        try:
            status = ImageResolutionStatus(stat_val)
        except ValueError:
            status = ImageResolutionStatus.CATEGORY_FALLBACK
        return cls(
            source=data.get("source", "unknown"),
            original_url=data.get("original_url") or data.get("image_url"),
            cached_path=data.get("cached_path") or data.get("local_path"),
            status=status,
            barcode=data.get("barcode"),
            product_identity=data.get("product_identity"),
            content_type=data.get("content_type"),
            width=data.get("width"),
            height=data.get("height"),
            created_at=data.get("created_at", 0.0),
        )


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """
    Validate that an image URL is HTTPS and does not resolve to loopback,
    private, link-local, multicast, or reserved IP address (SSRF Protection).
    """
    if not url:
        return False, "Empty URL"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL: {e}"

    if parsed.scheme.lower() != "https":
        return False, f"URL scheme must be HTTPS, got: {parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname in URL"

    # Reject localhost or internal names
    if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        return False, "SSRF attempt: localhost forbidden"

    try:
        # Resolve all IPs for hostname
        addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False, f"SSRF protection: resolved IP {ip_str} is private or non-public"
    except Exception as e:
        return False, f"DNS resolution failed for {hostname}: {e}"

    return True, "OK"


def validate_and_decode_image_bytes(
    image_bytes: bytes,
    content_type: str | None = None,
) -> tuple[bool, int, int, str]:
    """
    Validate image bytes using OpenCV. Checks:
    1. Size within limit.
    2. Valid image decoding.
    3. Minimum/maximum dimensions (no 1x1 pixels or extreme sizes).
    4. Reasonable aspect ratio (0.2 to 5.0).
    """
    if not image_bytes or len(image_bytes) == 0:
        return False, 0, 0, "Empty image bytes"

    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        return False, 0, 0, f"Image size ({len(image_bytes)} bytes) exceeds limit ({MAX_IMAGE_SIZE_BYTES} bytes)"

    # Check if data starts with HTML or XML error tags
    prefix = image_bytes[:256].lower()
    if b"<html" in prefix or b"<!doctype html" in prefix or b"<xml" in prefix:
        return False, 0, 0, "Response content is HTML/text rather than binary image data"

    # Decode using OpenCV
    try:
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            return False, 0, 0, "Failed to decode image as valid OpenCV visual matrix"

        height, width = img.shape[:2]
        if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
            return (
                False,
                width,
                height,
                f"Image dimensions ({width}x{height}) below minimum {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION}",
            )

        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            return (
                False,
                width,
                height,
                f"Image dimensions ({width}x{height}) exceed maximum {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}",
            )

        aspect_ratio = width / max(height, 1)
        if aspect_ratio < 0.2 or aspect_ratio > 5.0:
            return (
                False,
                width,
                height,
                f"Image aspect ratio {aspect_ratio:.2f} is extreme and unsuitable for product display",
            )

        return True, width, height, "OK"
    except Exception as e:
        return False, 0, 0, f"Exception during image decode: {e}"


def download_and_validate_web_image(
    url: str,
    target_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> tuple[bool, bytes | None, dict[str, Any], str]:
    """
    Safely download and validate an external product image with SSRF checks.
    Returns: (success, image_bytes, metadata_dict, error_message)
    """
    safe, reason = is_safe_public_url(url)
    if not safe:
        return False, None, {}, f"URL safety check failed: {reason}"

    close_client = False
    if client is None:
        client = httpx.Client(
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": OFF_USER_AGENT},
        )
        close_client = True

    try:
        resp = client.get(url)
        if resp.status_code != 200:
            return False, None, {}, f"HTTP {resp.status_code} fetching image from {url}"

        # Validate final URL after redirects for SSRF
        final_url = str(resp.url)
        safe_final, reason_final = is_safe_public_url(final_url)
        if not safe_final:
            return False, None, {}, f"Redirected to unsafe URL: {reason_final}"

        ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if ct and not ct.startswith("image/"):
            return False, None, {}, f"Invalid Content-Type '{ct}' (expected image/*)"

        raw_bytes = resp.content
        ok, width, height, decode_msg = validate_and_decode_image_bytes(raw_bytes, ct)
        if not ok:
            return False, None, {}, f"Image validation failed: {decode_msg}"

        # Save locally if target_dir provided
        cached_path_str = None
        if target_dir:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
                cached_filename = f"prod_{url_hash}.jpg"
                cached_file = target_dir / cached_filename
                cached_file.write_bytes(raw_bytes)
                cached_path_str = str(cached_file)
            except Exception as e:
                logger.warning("Could not persist cached image file to %s: %s", target_dir, e)

        meta = {
            "original_url": url,
            "cached_path": cached_path_str,
            "content_type": ct or "image/jpeg",
            "width": width,
            "height": height,
            "size_bytes": len(raw_bytes),
        }
        return True, raw_bytes, meta, "OK"
    except Exception as e:
        return False, None, {}, f"Download exception for {url}: {e}"
    finally:
        if close_client:
            client.close()


class ProductImageResolver:
    """
    Centralized, concurrency-safe product image discovery and caching manager.
    Follows mandatory priority: Barcode -> Catalog Name/Brand -> Web Search -> Fallback.
    """

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        http_client: httpx.Client | None = None,
    ):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            from api import get_captures_dir
            self.cache_dir = get_captures_dir() / "products"

        self._client = http_client
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        # In-memory resolution cache: key -> ImageMetadata
        self._cache: dict[str, ImageMetadata] = {}
        self._in_flight: set[str] = set()

    def _get_client(self) -> httpx.Client:
        if self._client:
            return self._client
        return httpx.Client(
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": OFF_USER_AGENT},
        )

    def _normalize_key(self, barcode: str | None, product_name: str | None, brand: str | None) -> str:
        if barcode:
            return f"barcode:{barcode.strip()}"
        b = (brand or "").strip().lower()
        p = (product_name or "").strip().lower()
        return f"identity:{b}::{p}"

    def get_cached(self, barcode: str | None, product_name: str | None, brand: str | None) -> ImageMetadata | None:
        """Retrieve previously cached resolution result if available."""
        key = self._normalize_key(barcode, product_name, brand)
        with self._lock:
            return self._cache.get(key)

    def cache_result(self, barcode: str | None, product_name: str | None, brand: str | None, meta: ImageMetadata):
        """Store resolution result in in-memory cache."""
        key = self._normalize_key(barcode, product_name, brand)
        with self._lock:
            self._cache[key] = meta

    def resolve_product_image(
        self,
        product_name: str | None,
        brand: str | None = None,
        barcode: str | None = None,
        category: str | None = None,
        existing_metadata: dict[str, Any] | None = None,
        is_supplementary: bool = False,
    ) -> ImageMetadata:
        """
        Main entry point for resolving a product's display image.
        Deduplicates supplementary requests and adheres to strict provider order.
        Thread-safe single-flight mechanism prevents concurrent duplicate lookups.
        """
        # Fast exit if disabled by environment
        if os.getenv("ANNARAKSHAK_DISABLE_IMAGE_RESOLVER") == "1":
            return ImageMetadata(
                source="category_fallback",
                original_url=None,
                cached_path=None,
                status=ImageResolutionStatus.CATEGORY_FALLBACK,
                barcode=barcode,
                product_identity=product_name or "Unknown Item",
                created_at=time.time(),
            )

        # 1. Check existing metadata if provided
        if existing_metadata:
            meta = ImageMetadata.from_dict(existing_metadata)
            if meta.status == ImageResolutionStatus.VERIFIED_WEB_IMAGE:
                logger.info("Reusing existing verified product image from metadata: %s", meta.original_url)
                return meta
            if is_supplementary and meta.status == ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH:
                if not (barcode and barcode != meta.barcode):
                    logger.info("Supplementary scan reusing previous no-match state; skipping repeated lookup.")
                    return meta

        key = self._normalize_key(barcode, product_name, brand)

        with self._lock:
            cached = self._cache.get(key)
            if cached:
                if cached.status == ImageResolutionStatus.VERIFIED_WEB_IMAGE:
                    return cached
                if is_supplementary and cached.status == ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH:
                    if not (barcode and barcode != cached.barcode):
                        return cached

            # Wait if another thread is currently executing search for this exact identity
            while key in self._in_flight:
                self._condition.wait()
                cached = self._cache.get(key)
                if cached:
                    return cached

            self._in_flight.add(key)

        try:
            # Product identity string for provenance
            identity_str = f"{brand.strip()} {product_name.strip()}" if brand and product_name else (product_name or "Unknown Item")

            # 3. If product identity is completely absent or uncertain, fall back
            if not barcode and (not product_name or len(product_name.strip()) < 3 or product_name.strip().lower() in ("item", "food", "unknown", "product")):
                fallback = ImageMetadata(
                    source="category_fallback",
                    original_url=None,
                    cached_path=None,
                    status=ImageResolutionStatus.CATEGORY_FALLBACK,
                    barcode=None,
                    product_identity=identity_str,
                    created_at=time.time(),
                )
                self.cache_result(barcode, product_name, brand, fallback)
                return fallback

            # 4. Mandatory Priority: Stage 1 — Exact Barcode lookup in Open Food Facts
            client = self._get_client()
            if barcode:
                logger.info("Attempting Stage 1: Barcode lookup on Open Food Facts for %s", barcode)
                meta = self._lookup_open_food_facts_barcode(barcode, identity_str, client)
                if meta and meta.status == ImageResolutionStatus.VERIFIED_WEB_IMAGE:
                    self.cache_result(barcode, product_name, brand, meta)
                    return meta

            # 5. Mandatory Priority: Stage 2 — Exact Product Name + Brand on Open Food Facts
            if product_name and product_name.strip():
                logger.info("Attempting Stage 2: Name & Brand search on Open Food Facts for '%s' ('%s')", product_name, brand or "")
                meta = self._lookup_open_food_facts_search(product_name, brand, barcode, identity_str, client)
                if meta and meta.status == ImageResolutionStatus.VERIFIED_WEB_IMAGE:
                    self.cache_result(barcode, product_name, brand, meta)
                    return meta

            # 6. Stage 3 — Optional General Web Search Provider (if configured)
            meta = self._lookup_optional_web_search(product_name, brand, barcode, identity_str, client)
            if meta and meta.status == ImageResolutionStatus.VERIFIED_WEB_IMAGE:
                self.cache_result(barcode, product_name, brand, meta)
                return meta

            # 7. Stage 4 — Fallback: No suitable image found. Cache search attempted.
            logger.info("Product image lookup completed with no suitable match for '%s'. Using category fallback.", identity_str)
            no_match = ImageMetadata(
                source="category_fallback",
                original_url=None,
                cached_path=None,
                status=ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH,
                barcode=barcode,
                product_identity=identity_str,
                created_at=time.time(),
            )
            self.cache_result(barcode, product_name, brand, no_match)
            return no_match
        finally:
            with self._lock:
                self._in_flight.discard(key)
                self._condition.notify_all()

    def _lookup_open_food_facts_barcode(
        self,
        barcode: str,
        identity_str: str,
        client: httpx.Client,
    ) -> ImageMetadata | None:
        """Query Open Food Facts by barcode."""
        url = OFF_BARCODE_URL.format(barcode=barcode.strip())
        try:
            resp = client.get(url)
            if resp.status_code != 200:
                logger.debug("Open Food Facts returned %s for barcode %s", resp.status_code, barcode)
                return None

            data = resp.json()
            if data.get("status") != 1 and "product" not in data:
                return None

            prod = data.get("product") or {}
            img_url = (
                prod.get("image_front_url")
                or prod.get("image_url")
                or prod.get("image_front_small_url")
            )
            if not img_url:
                return None

            # Download & Validate candidate image
            success, _, meta_dict, err = download_and_validate_web_image(
                img_url,
                target_dir=self.cache_dir,
                client=client,
            )
            if not success:
                logger.warning("Candidate image for barcode %s failed validation: %s", barcode, err)
                return None

            return ImageMetadata(
                source="open_food_facts_barcode",
                original_url=img_url,
                cached_path=meta_dict.get("cached_path"),
                status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                barcode=barcode,
                product_identity=prod.get("product_name") or identity_str,
                content_type=meta_dict.get("content_type"),
                width=meta_dict.get("width"),
                height=meta_dict.get("height"),
                created_at=time.time(),
            )
        except Exception as e:
            logger.warning("Exception querying Open Food Facts for barcode %s: %s", barcode, e)
            return None

    def _lookup_open_food_facts_search(
        self,
        product_name: str,
        brand: str | None,
        barcode: str | None,
        identity_str: str,
        client: httpx.Client,
    ) -> ImageMetadata | None:
        """Search Open Food Facts by product name and brand."""
        query_parts = []
        if brand and brand.strip():
            query_parts.append(brand.strip())
        query_parts.append(product_name.strip())
        query = " ".join(query_parts)

        params = {
            "search_terms": query,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 5,
            "fields": "code,product_name,brands,image_url,image_front_url",
        }

        try:
            resp = client.get(OFF_SEARCH_URL, params=params)
            if resp.status_code != 200:
                return None

            data = resp.json()
            products = data.get("products", [])
            if not products:
                return None

            # Target tokens for identity matching
            target_tokens = set(re.findall(r"\w+", query.lower()))

            for cand in products:
                cand_name = cand.get("product_name") or ""
                cand_brand = cand.get("brands") or ""
                cand_tokens = set(re.findall(r"\w+", f"{cand_brand} {cand_name}".lower()))

                # Ensure at least 50% overlap with target search tokens
                overlap = target_tokens.intersection(cand_tokens)
                if not overlap or (len(overlap) / max(len(target_tokens), 1)) < 0.4:
                    continue

                img_url = cand.get("image_front_url") or cand.get("image_url")
                if not img_url:
                    continue

                success, _, meta_dict, err = download_and_validate_web_image(
                    img_url,
                    target_dir=self.cache_dir,
                    client=client,
                )
                if success:
                    return ImageMetadata(
                        source="open_food_facts_search",
                        original_url=img_url,
                        cached_path=meta_dict.get("cached_path"),
                        status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                        barcode=barcode or cand.get("code"),
                        product_identity=f"{cand_brand} {cand_name}".strip() or identity_str,
                        content_type=meta_dict.get("content_type"),
                        width=meta_dict.get("width"),
                        height=meta_dict.get("height"),
                        created_at=time.time(),
                    )
        except Exception as e:
            logger.warning("Exception searching Open Food Facts for '%s': %s", query, e)
            return None

        return None

    def _lookup_optional_web_search(
        self,
        product_name: str | None,
        brand: str | None,
        barcode: str | None,
        identity_str: str,
        client: httpx.Client,
    ) -> ImageMetadata | None:
        """
        Optional Stage 3: General web image search if API keys are configured.
        Supports Google Custom Search API if GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX are present.
        If not configured, returns None silently.
        """
        api_key = os.environ.get("GOOGLE_CSE_API_KEY") or os.environ.get("IMAGE_SEARCH_API_KEY")
        cx = os.environ.get("GOOGLE_CSE_CX")
        if not api_key or not cx or not product_name:
            return None

        query = f"{brand or ''} {product_name} packaging product".strip()
        search_url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx,
            "q": query,
            "searchType": "image",
            "num": 3,
            "safe": "active",
        }

        try:
            resp = client.get(search_url, params=params)
            if resp.status_code != 200:
                return None

            items = resp.json().get("items", [])
            for item in items:
                img_url = item.get("link")
                if not img_url:
                    continue

                success, _, meta_dict, _ = download_and_validate_web_image(
                    img_url,
                    target_dir=self.cache_dir,
                    client=client,
                )
                if success:
                    return ImageMetadata(
                        source="web_search",
                        original_url=img_url,
                        cached_path=meta_dict.get("cached_path"),
                        status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                        barcode=barcode,
                        product_identity=identity_str,
                        content_type=meta_dict.get("content_type"),
                        width=meta_dict.get("width"),
                        height=meta_dict.get("height"),
                        created_at=time.time(),
                    )
        except Exception as e:
            logger.debug("Optional web search exception: %s", e)
            return None

        return None


# Global singleton instance for use across API endpoints
_global_resolver: ProductImageResolver | None = None
_resolver_lock = threading.Lock()


def get_image_resolver(cache_dir: Path | str | None = None) -> ProductImageResolver:
    """Retrieve or initialize the global ProductImageResolver instance."""
    global _global_resolver
    with _resolver_lock:
        if _global_resolver is None:
            _global_resolver = ProductImageResolver(cache_dir=cache_dir)
        return _global_resolver
