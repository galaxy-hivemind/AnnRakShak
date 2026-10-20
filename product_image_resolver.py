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
import urllib.parse
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import cv2
import httpcore
import httpx
import numpy as np
from httpcore._backends.sync import SyncBackend, SyncStream
from httpcore._exceptions import ConnectError, ConnectTimeout, ExceptionMapping, map_exceptions

from barcode_detector import is_valid_gtin_checksum

logger = logging.getLogger("AnnaRakshak.ImageResolver")

# Timeouts, Limits & SSRF Controls
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
DOWNLOAD_TIMEOUT_SECONDS = 5.0
MAX_CATALOG_SEARCH_REQUESTS = 6
MIN_IMAGE_DIMENSION = 100
MAX_IMAGE_DIMENSION = 5000
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_REDIRECTS = 3
CHUNK_SIZE = 16 * 1024  # 16 KB chunks for streaming
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}

DISALLOWED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
]


def is_ip_disallowed(ip_str: str) -> bool:
    """Check if an IP string belongs to any private, loopback, link-local, non-global, or reserved network."""
    try:
        ip = ipaddress.ip_address(str(ip_str).strip())
    except (ValueError, TypeError):
        return False

    # 1. Handle IPv4-mapped IPv6 (::ffff:x.x.x.x)
    if ip.version == 6 and ip.ipv4_mapped:
        return is_ip_disallowed(str(ip.ipv4_mapped))

    # 2. Reject RFC 8215 local-use NAT64 prefix (64:ff9b:1::/48) outright
    if ip.version == 6 and ip in ipaddress.ip_network("64:ff9b:1::/48"):
        return True

    # 3. Handle RFC 6052 Well-Known Prefix (64:ff9b::/96)
    if ip.version == 6 and ip in ipaddress.ip_network("64:ff9b::/96"):
        embedded_ipv4 = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
        return is_ip_disallowed(str(embedded_ipv4))

    # 4. Positive global-routability check
    if not ip.is_global:
        return True

    # 4. Strict classification properties
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True

    # 5. Explicit CIDR denylist
    for net in DISALLOWED_NETWORKS:
        if ip in net:
            return True

    return False

# Authoritative Product Catalogs & Public Sources
OFF_BARCODE_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
OBF_BARCODE_URL = "https://world.openbeautyfacts.org/api/v2/product/{barcode}.json"
OBF_SEARCH_URL = "https://world.openbeautyfacts.org/cgi/search.pl"
OPF_BARCODE_URL = "https://world.openproductsfacts.org/api/v2/product/{barcode}.json"
OPF_SEARCH_URL = "https://world.openproductsfacts.org/cgi/search.pl"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
OFF_USER_AGENT = "AnnaRakShak - FoodTracker - Version 1.0 - Contact: info@annarakshak.app"


class ImageResolutionStatus(str, Enum):
    VERIFIED_WEB_IMAGE = "verified_web_image"
    WEB_VERIFIED = "web_verified"
    CATEGORY_FALLBACK = "category_fallback"
    SEARCH_PENDING = "search_pending"
    SEARCH_ATTEMPTED_NO_MATCH = "search_attempted_no_match"
    WEB_UNAVAILABLE = "web_unavailable"
    AI_GENERATED = "ai_generated"
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
    def is_verified(self) -> bool:
        return self.status in (
            ImageResolutionStatus.VERIFIED_WEB_IMAGE,
            ImageResolutionStatus.WEB_VERIFIED,
        )

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
        d["is_verified"] = self.is_verified
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
            if stat_val == "web_verified":
                status = ImageResolutionStatus.WEB_VERIFIED
            elif stat_val == "web_unavailable":
                status = ImageResolutionStatus.WEB_UNAVAILABLE
            elif stat_val == "ai_generated":
                status = ImageResolutionStatus.AI_GENERATED
            else:
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


def generate_search_queries(product_name: str | None, brand: str | None) -> list[str]:
    """Generate ordered progressive queries from specific to broader."""
    queries = []
    clean_p = re.sub(r"['’]s\b", "", product_name or "")
    clean_p = re.sub(r"['\"’]", "", clean_p).strip()
    clean_b = re.sub(r"['’]s\b", "", brand or "")
    clean_b = re.sub(r"['\"’]", "", clean_b).strip()

    if not clean_p and not clean_b:
        return []

    p_lower = clean_p.lower()
    b_lower = clean_b.lower()
    p_without_brand = clean_p
    if b_lower and p_lower.startswith(b_lower):
        p_without_brand = clean_p[len(clean_b):].strip()
    elif b_lower and b_lower in p_lower:
        p_without_brand = re.sub(re.escape(clean_b), "", clean_p, flags=re.IGNORECASE).strip()

    # 1. Full clean query
    if clean_b and p_without_brand:
        queries.append(f"{clean_b} {p_without_brand}".strip())
    elif clean_p:
        queries.append(clean_p)
    elif clean_b:
        queries.append(clean_b)

    tokens = [t for t in re.findall(r"\w+", p_without_brand or clean_p) if len(t) > 2]
    if clean_b and tokens:
        # First 2 tokens with brand (e.g. 'Listerine Cool Mint', 'Paper Boat Swing Lively')
        if len(tokens) >= 2:
            queries.append(f"{clean_b} {tokens[0]} {tokens[1]}".strip())
        # Last 2 tokens with brand (e.g. 'Cadbury Silk Brownie')
        if len(tokens) >= 3:
            queries.append(f"{clean_b} {tokens[-2]} {tokens[-1]}".strip())
        # Flavor keyword with brand (e.g. 'Paper Boat Orange', 'Cadbury Brownie')
        flavor_words = {
            "orange", "brownie", "mint", "almond", "chocolate", "cookies",
            "mango", "lemon", "apple", "berry", "butter", "masala", "lychee", "guava",
        }
        flavors = [t for t in tokens if t.lower() in flavor_words]
        if flavors:
            queries.append(f"{clean_b} {flavors[0]}".strip())
        # Brand + first token (e.g. 'Paper Boat Swing', 'Cadbury Dairy', 'Listerine Cool')
        if len(tokens) >= 1:
            queries.append(f"{clean_b} {tokens[0]}".strip())
        # Brand + last token (e.g. 'ChanduRam Cookies', 'Listerine Mouthwash')
        if len(tokens) >= 2:
            queries.append(f"{clean_b} {tokens[-1]}".strip())

    # Product name alone (for brandless items like 'Bhajani Chakli')
    if clean_p and clean_p not in queries:
        queries.append(clean_p)

    seen = set()
    deduped = []
    for q in queries:
        q_norm = " ".join(q.split()).lower()
        if q_norm and q_norm not in seen:
            seen.add(q_norm)
            deduped.append(q)
    return deduped[:5]


def score_candidate(
    cand_brand: str | None,
    cand_name: str | None,
    target_brand: str | None,
    target_name: str | None,
    has_front_img: bool = False,
) -> float:
    """Score relevance of candidate product against target brand and product name."""
    score = 0.0
    c_brand = (cand_brand or "").lower().strip()
    c_name = (cand_name or "").lower().strip()
    t_brand = (target_brand or "").lower().strip()
    t_name = (target_name or "").lower().strip()

    c_brand = re.sub(r"['’]s\b", "", c_brand)
    c_name = re.sub(r"['’]s\b", "", c_name)
    t_brand = re.sub(r"['’]s\b", "", t_brand)
    t_name = re.sub(r"['’]s\b", "", t_name)

    # 1. Brand matching
    if t_brand:
        if t_brand in c_brand or c_brand in t_brand or t_brand in c_name:
            score += 50.0
        elif c_brand:
            t_b_tokens = set(re.findall(r"\w+", t_brand))
            c_b_tokens = set(re.findall(r"\w+", c_brand))
            if not t_b_tokens.intersection(c_b_tokens):
                score -= 60.0  # Penalize mismatched brand heavily
    else:
        score += 10.0

    # 2. Token overlap
    t_tokens = set(t for t in re.findall(r"\w+", t_name) if len(t) > 2)
    if t_brand:
        t_tokens -= set(re.findall(r"\w+", t_brand))
    c_all_tokens = set(re.findall(r"\w+", f"{c_brand} {c_name}"))

    if t_tokens:
        overlap = t_tokens.intersection(c_all_tokens)
        ratio = len(overlap) / len(t_tokens)
        score += 40.0 * ratio
    else:
        score += 15.0

    # 3. Flavor / variant match
    flavor_words = {
        "orange", "brownie", "mint", "almond", "chocolate", "cookies",
        "mango", "lemon", "apple", "berry", "butter", "masala", "lychee", "guava",
    }
    t_flavors = t_tokens.intersection(flavor_words)
    c_flavors = c_all_tokens.intersection(flavor_words)

    if t_flavors:
        if t_flavors.intersection(c_flavors):
            score += 25.0
        elif c_flavors:
            score -= 15.0

    # 4. Front image preference
    if has_front_img:
        score += 10.0

    return score


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """
    Validate that an image URL is HTTPS and does not resolve to loopback,
    private, link-local, multicast, carrier-grade NAT, or reserved IP address (SSRF Protection).
    Rejects embedded credentials, non-HTTPS schemes, and internal hostnames.
    """
    if not url:
        return False, "Empty URL"

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL: {e}"

    if parsed.scheme.lower() != "https":
        return False, f"URL scheme must be HTTPS, got: {parsed.scheme}"

    # Reject credentials embedded in URL (e.g. https://user:pass@evil.com)
    if parsed.username or parsed.password:
        return False, "SSRF protection: credentials embedded in URL forbidden"

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname in URL"

    lower_host = hostname.lower()
    # Reject localhost, loopback, or internal domain names
    if (
        lower_host in ("localhost", "127.0.0.1", "::1")
        or lower_host.endswith((".localhost", ".local", ".internal"))
    ):
        return False, "SSRF attempt: localhost or internal domain forbidden"

    # Check if hostname itself is directly a disallowed numeric IP
    try:
        if is_ip_disallowed(lower_host):
            return False, f"SSRF protection: destination IP {lower_host} is private or non-public"
    except Exception:
        pass

    try:
        # Resolve all IPs for hostname and verify each against disallowed networks
        addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
        if not addr_info:
            return False, f"DNS resolution returned no addresses for {hostname}"
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if is_ip_disallowed(ip_str):
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


class PinnedSyncBackend(SyncBackend):
    """
    Synchronous network backend that resolves and validates host IP addresses
    before TCP socket connection, pinning the socket directly to the validated IP.
    This guarantees that no HTTP or TLS request bytes can ever be sent to an
    unvalidated or rebound private / metadata IP address.
    """

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.NetworkStream:
        try:
            addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            if not addr_info:
                raise ConnectError(f"DNS resolution returned no addresses for host {host}")

            verified_ips: list[str] = []
            for _, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                if is_ip_disallowed(ip_str):
                    raise ConnectError(
                        f"SSRF / DNS rebinding protection: destination IP {ip_str} for host {host} is disallowed"
                    )
                if ip_str not in verified_ips:
                    verified_ips.append(ip_str)

            if not verified_ips:
                raise ConnectError(f"No permitted IP addresses found for host {host}")
        except ConnectError:
            raise
        except Exception as e:
            raise ConnectError(f"DNS resolution failure during connect for {host}: {e}") from e

        # Connect directly to the verified public IP(s) so the OS cannot re-resolve
        last_err: Exception | None = None
        sock: socket.socket | None = None
        source_address = None if local_address is None else (local_address, 0)
        exc_map: ExceptionMapping = {
            socket.timeout: ConnectTimeout,
            OSError: ConnectError,
        }

        with map_exceptions(exc_map):
            for ip in verified_ips:
                try:
                    sock = socket.create_connection(
                        (ip, port),
                        timeout,
                        source_address=source_address,
                    )
                    break
                except OSError as e:
                    last_err = e

            if sock is None:
                raise last_err or OSError(f"Could not connect to {host} on any verified IP")

            if socket_options:
                for option in socket_options:
                    sock.setsockopt(*option)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        return SyncStream(sock)


class SafeSSRFTransport(httpx.HTTPTransport):
    """
    HTTPTransport that forces all outbound HTTP/HTTPS connections through PinnedSyncBackend,
    enforcing pre-connect IP validation and DNS pinning while preserving TLS SNI and certificate
    verification against the original hostname.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pool = httpcore.ConnectionPool(
            ssl_context=self._pool._ssl_context,
            max_connections=self._pool._max_connections,
            max_keepalive_connections=self._pool._max_keepalive_connections,
            keepalive_expiry=self._pool._keepalive_expiry,
            http1=self._pool._http1,
            http2=self._pool._http2,
            network_backend=PinnedSyncBackend(),
            retries=self._pool._retries,
        )


def create_safe_image_client() -> httpx.Client:
    """Create an httpx client configured with SafeSSRFTransport, trust_env=False, and non-redirecting policy."""
    return httpx.Client(
        transport=SafeSSRFTransport(trust_env=False),
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": OFF_USER_AGENT},
    )


def download_and_validate_web_image(
    url: str,
    target_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> tuple[bool, bytes | None, dict[str, Any], str]:
    """
    Safely download and validate an external product image with SSRF checks,
    connection-time DNS pinning, incremental streaming size limits, and explicit manual redirect validation.
    Returns: (success, image_bytes, metadata_dict, error_message)
    """
    current_url = url
    visited_urls: set[str] = set()
    redirect_count = 0

    close_client = False
    if client is None:
        client = create_safe_image_client()
        close_client = True

    try:
        raw_bytes: bytes = b""
        final_ct: str = "image/jpeg"

        while True:
            # 1. SSRF pre-request validation on initial and every redirected URL
            safe, reason = is_safe_public_url(current_url)
            if not safe:
                return False, None, {}, f"URL safety check failed for {current_url}: {reason}"

            if current_url in visited_urls:
                return False, None, {}, f"SSRF protection: redirect loop detected at {current_url}"
            visited_urls.add(current_url)

            # 2. Open request stream with follow_redirects=False
            if hasattr(client, "stream"):
                stream_ctx = client.stream("GET", current_url)
            else:
                # Fallback wrapper for test mocks that mock client.get directly
                class _MockStreamCtx:
                    def __init__(self, c, u):
                        self.c = c
                        self.u = u
                        self.resp = None
                    def __enter__(self):
                        self.resp = self.c.get(self.u)
                        return self.resp
                    def __exit__(self, *args):
                        if hasattr(self.resp, "close"):
                            self.resp.close()
                stream_ctx = _MockStreamCtx(client, current_url)

            with stream_ctx as resp:
                # 3. Explicitly handle redirect status codes
                if resp.status_code in REDIRECT_STATUS_CODES:
                    redirect_count += 1
                    if redirect_count > MAX_REDIRECTS:
                        return False, None, {}, f"Too many redirects (exceeded limit of {MAX_REDIRECTS})"

                    location = resp.headers.get("Location") or resp.headers.get("location")
                    if not location:
                        return False, None, {}, f"HTTP {resp.status_code} redirect without Location header"

                    # Resolve relative redirects against current URL
                    next_url = urllib.parse.urljoin(current_url, location)
                    current_url = next_url
                    continue

                if resp.status_code != 200:
                    return False, None, {}, f"HTTP {resp.status_code} fetching image from {current_url}"

                # 4. Check Content-Type header before reading stream
                ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ct and not ct.startswith("image/"):
                    return False, None, {}, f"Invalid Content-Type '{ct}' (expected image/*)"
                final_ct = ct or "image/jpeg"

                # 5. Check declared Content-Length upfront if present
                content_length_str = resp.headers.get("content-length")
                if content_length_str and content_length_str.isdigit():
                    declared_len = int(content_length_str)
                    if declared_len > MAX_IMAGE_SIZE_BYTES:
                        return (
                            False,
                            None,
                            {},
                            f"Declared Content-Length ({declared_len} bytes) exceeds limit ({MAX_IMAGE_SIZE_BYTES} bytes)",
                        )

                # 6. Post-connect socket check for DNS rebinding mitigation (inspect actual connected peer IP)
                ns = getattr(resp, "extensions", {}).get("network_stream") if hasattr(resp, "extensions") and resp.extensions else None
                if ns and hasattr(ns, "get_extra_info"):
                    server_addr = ns.get_extra_info("server_addr")
                    if server_addr and len(server_addr) >= 1:
                        connected_ip = str(server_addr[0])
                        if is_ip_disallowed(connected_ip):
                            return (
                                False,
                                None,
                                {},
                                f"SSRF / DNS rebinding protection: connected IP {connected_ip} is disallowed",
                            )

                # 7. Incremental stream consumption with hard byte counter
                chunks = []
                total_bytes = 0
                if hasattr(resp, "iter_bytes"):
                    for chunk in resp.iter_bytes(chunk_size=CHUNK_SIZE):
                        total_bytes += len(chunk)
                        if total_bytes > MAX_IMAGE_SIZE_BYTES:
                            return (
                                False,
                                None,
                                {},
                                f"Image size exceeds limit ({MAX_IMAGE_SIZE_BYTES} bytes) while streaming",
                            )
                        chunks.append(chunk)
                    raw_bytes = b"".join(chunks)
                else:
                    raw_bytes = getattr(resp, "content", b"")
                    if len(raw_bytes) > MAX_IMAGE_SIZE_BYTES:
                        return (
                            False,
                            None,
                            {},
                            f"Image size exceeds limit ({MAX_IMAGE_SIZE_BYTES} bytes)",
                        )

            # Successfully streamed response without redirect
            break

        # 8. Decode and visually validate image using OpenCV
        ok, width, height, decode_msg = validate_and_decode_image_bytes(raw_bytes, final_ct)
        if not ok:
            return False, None, {}, f"Image validation failed: {decode_msg}"

        # 9. Local disk caching if requested
        cached_path_str = None
        if target_dir:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                url_hash = hashlib.sha256(current_url.encode()).hexdigest()[:16]
                cached_filename = f"prod_{url_hash}.jpg"
                cached_file = target_dir / cached_filename
                cached_file.write_bytes(raw_bytes)
                cached_path_str = str(cached_file)
            except Exception as e:
                logger.warning("Could not persist cached image file to %s: %s", target_dir, e)

        meta = {
            "original_url": current_url,
            "cached_path": cached_path_str,
            "content_type": final_ct,
            "width": width,
            "height": height,
            "size_bytes": len(raw_bytes),
        }
        return True, raw_bytes, meta, "OK"

    except Exception as e:
        return False, None, {}, f"Download exception for {current_url}: {e}"
    finally:
        if close_client and client is not None:
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
        if self._client and not self._client.is_closed:
            return self._client
        return create_safe_image_client()

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
        deadline: float | None = None,
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
            if meta.is_verified:
                logger.info("Reusing existing verified product image from metadata: %s", meta.original_url)
                return meta
            if is_supplementary and meta.status in (ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH, ImageResolutionStatus.WEB_UNAVAILABLE):
                clean_incoming_bc = re.sub(r"\D", "", str(barcode)) if barcode else None
                clean_prev_bc = re.sub(r"\D", "", str(meta.barcode)) if meta.barcode else None
                has_new_valid_bc = bool(
                    clean_incoming_bc
                    and is_valid_gtin_checksum(clean_incoming_bc)
                    and clean_incoming_bc != clean_prev_bc
                )
                if not has_new_valid_bc:
                    logger.info("Supplementary scan reusing previous no-match state; skipping repeated lookup.")
                    return meta

        key = self._normalize_key(barcode, product_name, brand)

        with self._lock:
            cached = self._cache.get(key)
            if cached:
                if cached.is_verified:
                    return cached
                if is_supplementary and cached.status in (ImageResolutionStatus.SEARCH_ATTEMPTED_NO_MATCH, ImageResolutionStatus.WEB_UNAVAILABLE):
                    clean_incoming_bc = re.sub(r"\D", "", str(barcode)) if barcode else None
                    clean_cached_bc = re.sub(r"\D", "", str(cached.barcode)) if cached.barcode else None
                    has_new_valid_bc = bool(
                        clean_incoming_bc
                        and is_valid_gtin_checksum(clean_incoming_bc)
                        and clean_incoming_bc != clean_cached_bc
                    )
                    if not has_new_valid_bc:
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

            # 4. Mandatory Priority: Stage 1 — Exact Barcode lookup in product catalogs
            client = self._get_client()
            if barcode:
                clean_bc = re.sub(r"\D", "", str(barcode))
                if is_valid_gtin_checksum(clean_bc):
                    logger.info("Attempting Stage 1: Barcode lookup on product catalogs for %s", clean_bc)
                    if deadline is not None:
                        meta = self._lookup_open_food_facts_barcode(clean_bc, identity_str, client, deadline=deadline)
                    else:
                        meta = self._lookup_open_food_facts_barcode(clean_bc, identity_str, client)
                    if meta and meta.is_verified:
                        self.cache_result(clean_bc, product_name, brand, meta)
                        return meta
                else:
                    logger.info("Barcode '%s' failed GTIN checksum validation; skipping exact barcode lookup", barcode)

            # 5. Mandatory Priority: Stage 2 — Name & Brand progressive search across product catalogs and public sources
            if product_name and product_name.strip():
                logger.info("Attempting Stage 2: Name & Brand search across catalogs for '%s' ('%s')", product_name, brand or "")
                if deadline is not None:
                    meta = self._lookup_open_food_facts_search(product_name, brand, barcode, identity_str, client, deadline=deadline)
                else:
                    meta = self._lookup_open_food_facts_search(product_name, brand, barcode, identity_str, client)
                if meta and meta.is_verified:
                    self.cache_result(barcode, product_name, brand, meta)
                    return meta

            # 6. Stage 3 — Optional General Web Search Provider (if configured)
            if deadline is not None:
                meta = self._lookup_optional_web_search(product_name, brand, barcode, identity_str, client, deadline=deadline)
            else:
                meta = self._lookup_optional_web_search(product_name, brand, barcode, identity_str, client)
            if meta and meta.is_verified:
                self.cache_result(barcode, product_name, brand, meta)
                return meta

            # 7. Stage 4 — Fallback: No suitable image found after bounded multi-catalog search
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
        deadline: float | None = None,
    ) -> ImageMetadata | None:
        """Query product catalogs by barcode (OFF, OBF, OPF)."""
        clean_bc = barcode.strip()
        catalog_endpoints = [
            ("open_food_facts_barcode", OFF_BARCODE_URL),
            ("open_beauty_facts_barcode", OBF_BARCODE_URL),
            ("open_products_facts_barcode", OPF_BARCODE_URL),
        ]

        for source_name, url_template in catalog_endpoints:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Execution budget exceeded during barcode lookup")
            url = url_template.format(barcode=clean_bc)
            for attempt in range(2):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Execution budget exceeded during barcode lookup")
                try:
                    resp = client.get(url)
                    if resp.status_code in (502, 503, 504) and attempt == 0:
                        time.sleep(0.25)
                        continue
                    if resp.status_code != 200:
                        break

                    data = resp.json()
                    if data.get("status") != 1 and "product" not in data:
                        break

                    prod = data.get("product") or {}
                    img_url = (
                        prod.get("image_front_url")
                        or prod.get("image_url")
                        or prod.get("image_front_small_url")
                    )
                    if not img_url:
                        break

                    # Download & Validate candidate image
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Execution budget exceeded during barcode image download")
                    success, _, meta_dict, err = download_and_validate_web_image(
                        img_url,
                        target_dir=self.cache_dir,
                        client=client,
                    )
                    if not success:
                        logger.warning("Barcode %s candidate image failed validation: %s", clean_bc, err)
                        break

                    return ImageMetadata(
                        source=source_name,
                        original_url=img_url,
                        cached_path=meta_dict.get("cached_path"),
                        status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                        barcode=clean_bc,
                        product_identity=prod.get("product_name") or identity_str,
                        content_type=meta_dict.get("content_type"),
                        width=meta_dict.get("width"),
                        height=meta_dict.get("height"),
                        created_at=time.time(),
                    )
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == 0:
                        time.sleep(0.25)
                        continue
                    break
                except Exception as e:
                    logger.debug("Exception querying %s for barcode %s: %s", source_name, clean_bc, e)
                    break

        return None

    def _lookup_open_food_facts_search(
        self,
        product_name: str,
        brand: str | None,
        barcode: str | None,
        identity_str: str,
        client: httpx.Client,
        deadline: float | None = None,
    ) -> ImageMetadata | None:
        """Progressively search product catalogs (OFF, OBF, OPF) with candidate ranking."""
        queries = generate_search_queries(product_name, brand)
        if not queries:
            return None

        # Check for beauty/personal care keywords to prioritize Open Beauty Facts
        combined_text = f"{brand or ''} {product_name}".lower()
        beauty_keywords = (
            "mouthwash", "toothpaste", "shampoo", "soap", "cream", "lotion",
            "cosmetic", "skincare", "listerine", "deodorant", "perfume", "cleanser",
        )
        if any(kw in combined_text for kw in beauty_keywords):
            catalogs = [
                ("open_beauty_facts", OBF_SEARCH_URL),
                ("open_food_facts", OFF_SEARCH_URL),
                ("open_products_facts", OPF_SEARCH_URL),
            ]
        else:
            catalogs = [
                ("open_food_facts", OFF_SEARCH_URL),
                ("open_beauty_facts", OBF_SEARCH_URL),
                ("open_products_facts", OPF_SEARCH_URL),
            ]

        catalog_requests_count = 0

        for query in queries[:4]:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Execution budget exceeded during catalog search")

            params = {
                "search_terms": query,
                "search_simple": 1,
                "action": "process",
                "json": 1,
                "page_size": 10,
                "fields": "code,product_name,brands,image_url,image_front_url,image_front_small_url",
            }

            for cat_name, cat_url in catalogs:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Execution budget exceeded during catalog search")

                if catalog_requests_count >= MAX_CATALOG_SEARCH_REQUESTS:
                    logger.debug("Reached maximum catalog search requests (%d); stopping broader catalog scan.", MAX_CATALOG_SEARCH_REQUESTS)
                    break
                catalog_requests_count += 1

                products = []
                for attempt in range(2):
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Execution budget exceeded during catalog search")
                    try:
                        resp = client.get(cat_url, params=params)
                        if resp.status_code in (502, 503, 504) and attempt == 0:
                            time.sleep(0.25)
                            continue
                        if resp.status_code != 200:
                            break
                        data = resp.json()
                        products = data.get("products", [])
                        break
                    except (httpx.TimeoutException, httpx.NetworkError):
                        if attempt == 0:
                            time.sleep(0.25)
                            continue
                        break
                    except Exception as e:
                        logger.debug("Exception searching %s for '%s': %s", cat_name, query, e)
                        break

                if not products:
                    continue

                # Rank candidates
                ranked_candidates = []
                min_threshold = 45.0 if (brand and brand.strip()) else 25.0
                for cand in products:
                    c_name = cand.get("product_name") or ""
                    c_brand = cand.get("brands") or ""
                    has_front = bool(cand.get("image_front_url"))
                    score = score_candidate(c_brand, c_name, brand, product_name, has_front_img=has_front)
                    if score >= min_threshold:
                        img_url = cand.get("image_front_url") or cand.get("image_url") or cand.get("image_front_small_url")
                        if img_url:
                            ranked_candidates.append((score, cand, img_url))

                ranked_candidates.sort(key=lambda x: x[0], reverse=True)

                # Try downloading and validating in rank order
                for score, cand, img_url in ranked_candidates:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Execution budget exceeded during candidate image download")
                    success, _, meta_dict, err = download_and_validate_web_image(
                        img_url,
                        target_dir=self.cache_dir,
                        client=client,
                    )
                    if success:
                        cand_brand = cand.get("brands") or brand or ""
                        cand_name = cand.get("product_name") or product_name
                        return ImageMetadata(
                            source=f"{cat_name}_search",
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
                    else:
                        logger.info("Candidate image %s failed validation: %s; trying next candidate", img_url, err)

        # Fallback to Wikipedia / Wikimedia image search if catalogs found no suitable image
        wiki_meta = self._lookup_wikipedia_search(product_name, brand, barcode, identity_str, client, deadline=deadline)
        if wiki_meta and wiki_meta.is_verified:
            return wiki_meta

        return None

    def _lookup_wikipedia_search(
        self,
        product_name: str | None,
        brand: str | None,
        barcode: str | None,
        identity_str: str,
        client: httpx.Client,
        deadline: float | None = None,
    ) -> ImageMetadata | None:
        """Search Wikipedia/Wikimedia for authoritative brand or packaging images."""
        queries = generate_search_queries(product_name, brand)
        if not queries:
            return None

        min_threshold = 45.0 if (brand and brand.strip()) else 25.0

        for query in queries[:3]:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Execution budget exceeded during Wikipedia search")
            params = {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrlimit": 3,
                "prop": "pageimages",
                "piprop": "thumbnail|original",
                "pithumbsize": 600,
            }
            try:
                resp = client.get(WIKIPEDIA_API_URL, params=params)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                pages = data.get("query", {}).get("pages", {})
                for page_id, page in pages.items():
                    title = page.get("title") or ""
                    score = score_candidate(title, title, brand, product_name, has_front_img=False)
                    if score < min_threshold:
                        continue
                    thumb = page.get("thumbnail") or {}
                    img_url = thumb.get("source") or (page.get("original") or {}).get("source")
                    if not img_url:
                        continue
                    if deadline is not None and time.monotonic() >= deadline:
                        raise TimeoutError("Execution budget exceeded during candidate image download")
                    success, _, meta_dict, err = download_and_validate_web_image(
                        img_url,
                        target_dir=self.cache_dir,
                        client=client,
                    )
                    if success:
                        return ImageMetadata(
                            source="wikipedia_search",
                            original_url=img_url,
                            cached_path=meta_dict.get("cached_path"),
                            status=ImageResolutionStatus.VERIFIED_WEB_IMAGE,
                            barcode=barcode,
                            product_identity=f"{title} ({identity_str})",
                            content_type=meta_dict.get("content_type"),
                            width=meta_dict.get("width"),
                            height=meta_dict.get("height"),
                            created_at=time.time(),
                        )
            except Exception as e:
                logger.debug("Wikipedia search exception for '%s': %s", query, e)
                continue

        return None

    def _lookup_optional_web_search(
        self,
        product_name: str | None,
        brand: str | None,
        barcode: str | None,
        identity_str: str,
        client: httpx.Client,
        deadline: float | None = None,
    ) -> ImageMetadata | None:
        """
        Optional Stage 3: General web image search if API keys are configured.
        Supports Google Custom Search API if GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX are present.
        If not configured, returns None silently.
        """
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Execution budget exceeded during web search")

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
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Execution budget exceeded during web search")
            resp = client.get(search_url, params=params)
            if resp.status_code != 200:
                return None

            items = resp.json().get("items", [])
            for item in items:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Execution budget exceeded during web image download")
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
