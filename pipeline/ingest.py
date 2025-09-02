from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import feedparser
import requests
import yaml
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential_jitter

from .config import CONNECT_TIMEOUT, READ_TIMEOUT, DEFAULT_RPS_PER_HOST
from .io import ArticleRaw, db, get_feed_cache, init_db, insert_raw_articles, upsert_feed_cache


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


class RateLimiter:
    def __init__(self, rps: float = DEFAULT_RPS_PER_HOST):
        self.min_interval = 1.0 / max(0.1, rps)
        self.last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        now = time.monotonic()
        last = self.last.get(host, 0.0)
        delta = now - last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self.last[host] = time.monotonic()


session = requests.Session()
limiter = RateLimiter()


@retry(wait=wait_exponential_jitter(initial=1, max=8), stop=stop_after_attempt(3))
def _get(url: str, headers: dict[str, str]) -> requests.Response:
    host = requests.utils.urlparse(url).hostname or ""
    limiter.wait(host)
    resp = session.get(url, headers=headers, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    resp.raise_for_status()
    return resp


def fetch_feeds(since: datetime | None = None, max_items: int | None = None, logger=None) -> dict[str, Any]:
    init_db()
    sources = load_sources()
    totals = {"feeds": 0, "entries": 0, "inserted": 0}
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db() as conn:
        for src in sources:
            totals["feeds"] += 1
            etag, last_mod = get_feed_cache(conn, src.url)
            headers: dict[str, str] = {}
            if etag:
                headers["If-None-Match"] = etag
            if last_mod:
                headers["If-Modified-Since"] = last_mod
            try:
                resp = _get(src.url, headers=headers)
                etag_new = resp.headers.get("ETag")
                last_mod_new = resp.headers.get("Last-Modified")
                content = resp.content
                upsert_feed_cache(conn, src.url, src.id, etag_new, last_mod_new)
                if logger:
                    logger.info("Fetched %s (%s)", src.id, resp.status_code)
            except RetryError as e:
                if logger:
                    logger.error("Failed to fetch %s: %s", src.id, e)
                continue
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 304:
                    if logger:
                        logger.info("Not modified: %s", src.id)
                    continue
                if logger:
                    logger.error("HTTP error on %s: %s", src.id, e)
                continue

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
                        etag=etag,
                        last_modified=last_mod,
                    )
                )
                if max_items and len(entries) >= max_items:
                    break
            inserted = insert_raw_articles(conn, entries)
            totals["inserted"] += inserted
            if logger:
                logger.info("%s: %d new raw entries", src.id, inserted)
    return totals

