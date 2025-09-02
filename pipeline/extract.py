from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import trafilatura

from .io import Article, db, fetch_unextracted_raws, upsert_article
from .normalize import canonicalize_url, clean_text, content_hash, is_preprint_source, parse_date


def _extract_from_url(url: str) -> tuple[str | None, dict[str, Any] | None]:
    # Support local fixtures: file:// path -> read bytes and pass to trafilatura
    if url.startswith("file://"):
        p = Path(urlparse(url).path)
        if not p.exists():
            return None, None
        downloaded = p.read_text(encoding="utf-8", errors="ignore")
    else:
        downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None, None
    data_json = trafilatura.extract(downloaded, include_links=False, output="json")
    if not data_json:
        # Try plain text
        txt = trafilatura.extract(downloaded, include_links=False, output=None)
        return (txt or None), None
    try:
        data = json.loads(data_json)
    except Exception:  # noqa: BLE001
        return None, None
    txt = data.get("text") or data.get("raw_text")
    return (txt or None), data


def extract(limit: int | None = None, parallel: int = 4, logger: logging.Logger | None = None) -> int:
    count = 0
    with db() as conn:
        raws = fetch_unextracted_raws(conn, limit=limit)
    if not raws:
        if logger:
            logger.info("No new raw articles to extract.")
        return 0

    def worker(raw: dict[str, Any]) -> int:
        url = raw.get("link") or ""
        text, meta = _extract_from_url(url)
        canonical = None
        if meta:
            canonical = meta.get("url") or meta.get("source") or None
        if not canonical:
            canonical = url
        canonical = canonicalize_url(canonical)
        title = raw.get("title") or (meta.get("title") if meta else None) or canonical
        byline = (meta.get("author") if meta else None)
        published = raw.get("published_at")
        if meta and meta.get("date"):
            published = meta["date"]
        published = parse_date(published)
        # Fallback: if no extracted text, build from feed title+summary
        if not text:
            fallback = clean_text(((raw.get("title") or "") + "\n" + (raw.get("summary") or "")).strip())
            if not fallback:
                if logger:
                    logger.info("Skip: no extract and no fallback for %s", url)
                return 0
            text = fallback
            quality = 0.2
        else:
            quality = min(1.0, max(0.0, len(text) / 2000))
        txt = clean_text(text)
        is_preprint = 1 if is_preprint_source(raw.get("source_id"), canonical) else 0
        lang = (meta.get("language") if meta else None)
        # content hash over canonical+title+text for determinism
        chash = content_hash("\n".join([title or "", txt or "", canonical or ""]))
        art = Article(
            article_id=chash[:16],
            canonical_url=canonical,
            title=title or canonical,
            byline=byline,
            published_at=published,
            source_id=raw.get("source_id"),
            is_preprint=is_preprint,
            text=txt,
            lang=lang,
            tags=None,
            extraction_quality=quality,
            content_hash=chash,
        )
        with db() as conn2:
            upsert_article(conn2, art)
        return 1

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        futures = [ex.submit(worker, r) for r in raws]
        for fut in as_completed(futures):
            try:
                count += fut.result()
            except Exception as e:  # noqa: BLE001
                if logger:
                    logger.error("Extraction error: %s", e)
    if logger:
        logger.info("Extracted %d articles", count)
    return count
