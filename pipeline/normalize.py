from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from url_normalize import url_normalize


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


def canonicalize_url(url: str) -> str:
    # Normalize and strip tracking params and fragments
    normalized = url_normalize(url, default_scheme="https")
    # Drop fragment if present
    if "#" in normalized:
        normalized = normalized.split("#", 1)[0]
    # Remove tracking params via regex; url_normalize keeps query order
    # Strategy: split query string and filter keys
    if "?" not in normalized:
        return normalized.rstrip("/")
    base, qs = normalized.split("?", 1)
    parts = []
    for kv in qs.split("&"):
        if not kv:
            continue
        key = kv.split("=", 1)[0].lower()
        if key in TRACKING_PARAMS:
            continue
        parts.append(kv)
    canonical = base + ("?" + "&".join(parts) if parts else "")
    return canonical.rstrip("/")


def clean_text(text: str) -> str:
    # Collapse whitespace and strip
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def parse_date(dt: Any) -> str | None:
    if not dt:
        return None
    if isinstance(dt, datetime):
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Try common formats
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(str(dt), fmt)
            return d.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
    return None


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def is_preprint_source(source_id: str, url: str | None) -> bool:
    s = (source_id or "").lower()
    u = (url or "").lower()
    return any(x in s or x in u for x in ("arxiv", "biorxiv", "medrxiv"))
