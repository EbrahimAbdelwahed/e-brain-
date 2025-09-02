from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import feedparser
import yaml

from .io import (
    ArticleRaw,
    db,
    init_db,
    insert_raw_articles,
    upsert_feed_cache,
    http_get_bytes,
)


@dataclass
class Source:
    id: str
    url: str
    weight: int


def load_sources(cfg_path: str | None = None) -> list[Source]:
    path = cfg_path or "config/sources.yml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    out: list[Source] = []
    for s in data.get("sources", []):
        out.append(Source(id=s["id"], url=s["url"], weight=int(s.get("weight", 1))))
    return out


def fetch_feeds(
    since: datetime | None = None,
    max_items: int | None = None,
    logger=None,
    cfg_path: str | None = None,
) -> dict[str, Any]:
    init_db()
    sources = load_sources(cfg_path)
    totals: dict[str, Any] = {"feeds": 0, "entries": 0, "inserted": 0}
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db() as conn:
        for src in sources:
            totals["feeds"] += 1
            try:
                status, content, headers = http_get_bytes(src.url, logger=logger)
            except Exception as e:  # noqa: BLE001
                if logger:
                    logger.error("Failed to fetch %s: %s", src.id, e)
                continue
            if status == 304 or content is None:
                if logger:
                    logger.info("Not modified: %s", src.id)
                continue
            upsert_feed_cache(conn, src.url, src.id, headers.get("ETag"), headers.get("Last-Modified"))
            if logger:
                logger.info("Fetched %s (%s)", src.id, status)

            feed = feedparser.parse(content)
            entries = []
            for ent in feed.entries:
                totals["entries"] += 1
                if since and hasattr(ent, "published_parsed") and ent.published_parsed:
                    pub_dt = datetime(*ent.published_parsed[:6], tzinfo=timezone.utc)
                    if pub_dt < since:
                        continue
                entry_id = getattr(ent, "id", None) or getattr(ent, "guid", None) or getattr(ent, "link", "")
                if not entry_id:
                    continue
                entries.append(
                    ArticleRaw(
                        source_id=src.id,
                        feed_url=src.url,
                        entry_id=str(entry_id),
                        link=getattr(ent, "link", ""),
                        title=getattr(ent, "title", None),
                        summary=getattr(ent, "summary", None),
                        published_at=getattr(ent, "published", None),
                        fetched_at=fetched_at,
                        etag=headers.get("ETag"),
                        last_modified=headers.get("Last-Modified"),
                    )
                )
                if max_items and len(entries) >= max_items:
                    break
            inserted = insert_raw_articles(conn, entries)
            totals["inserted"] += inserted
            if logger:
                logger.info("%s: %d new raw entries", src.id, inserted)
    return totals
