from __future__ import annotations

import datetime as dt
import re
from typing import Iterable, List, Optional

import requests
import feedparser
from bs4 import BeautifulSoup

from ..db import insert_raw_items, upsert_source_rss, update_source_meta
from ..util.logging import get_logger


logger = get_logger(__name__)


DEFAULT_FEEDS: List[str] = [
    "https://www.nature.com/neuro.rss",
    "https://www.frontiersin.org/journals/neuroscience/rss",
    "https://www.jneurosci.org/rss/current.xml",
    "https://news.mit.edu/rss/topic/brain-and-cognitive-sciences",
    "https://neuroscience.stanford.edu/news/rss.xml",
    "https://neuromatch.io/feed.xml",
    "https://www.cogneurosociety.org/feed/",
    "https://export.arxiv.org/rss/cs.AI",
    "https://distill.pub/rss.xml",
    "https://deepmind.com/blog/feed/basic/",
]


def _clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    # Remove scripts/styles
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # Prefer <article> if present
    art = soup.find("article")
    text = (art.get_text(separator=" ") if art else soup.get_text(separator=" "))
    return re.sub(r"\s+", " ", text).strip()


def _fetch_full_text(url: str, timeout: float = 15.0) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "e-brain/rss (+https://github.com/your-org/e-brain)"})
        if resp.status_code != 200:
            logger.error("rss_fetch_error", extra={"status": resp.status_code, "url": url})
            return None
        return _clean_html_to_text(resp.text)
    except Exception as e:
        logger.error("rss_fetch_exception", extra={"error": str(e), "url": url})
        return None


def _should_include(text: str, include_regex: Optional[re.Pattern]) -> bool:
    if not include_regex:
        return True
    return bool(include_regex.search(text or ""))


def ingest_rss(
    feeds: Optional[List[str]] = None,
    max_entries_per_feed: int = 20,
    update_interval_minutes: int = 60,
    include_filter: Optional[str] = None,
) -> int:
    """Fetch, clean, and store items from RSS/Atom feeds.

    - Stores full text in `raw_items.text` and a summary/title/url/tags in `raw_items.meta`.
    - Adds/updates a "last_fetched_at" timestamp in `sources.meta` for pacing.
    """
    urls = feeds or DEFAULT_FEEDS
    include_re = re.compile(include_filter, re.IGNORECASE) if include_filter else re.compile(
        r"\b(neuro|brain|cogn|cortex|synapse|hippocampus|computational neuroscience|artificial intelligence|deep learning|machine learning|ai)\b",
        re.IGNORECASE,
    )

    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    total_inserted = 0

    for url in urls:
        parsed = feedparser.parse(url)
        feed_title = parsed.feed.get("title", "") if getattr(parsed, "feed", None) else ""
        src_id = upsert_source_rss(url, title=feed_title)

        # Pacing: use last_fetched_at in sources.meta if present (best-effort)
        # For simplicity, we process but keep the interval guidance for callers via CLI.

        entries = parsed.entries or []
        items = []
        for entry in entries[: max(0, int(max_entries_per_feed))]:
            title = getattr(entry, "title", "") or ""
            link = getattr(entry, "link", "") or ""
            summary = getattr(entry, "summary", getattr(entry, "description", "")) or ""
            published_parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
            if published_parsed:
                created_at = dt.datetime(*published_parsed[:6], tzinfo=dt.timezone.utc)
            else:
                created_at = now

            blob_for_filter = f"{title}\n{summary}"
            if not _should_include(blob_for_filter, include_re):
                continue

            full_text = _clean_html_to_text(summary)
            if link:
                fetched = _fetch_full_text(link)
                if fetched and len(fetched) > len(full_text):
                    full_text = fetched

            source_ref = getattr(entry, "id", None) or link or title[:120]
            tags = []
            if getattr(entry, "tags", None):
                try:
                    tags = [t.get("term") for t in entry.tags if t.get("term")]
                except Exception:
                    tags = []

            items.append(
                {
                    "source_type": "rss",
                    "source_ref": source_ref,
                    "source_id": src_id,
                    "author": feed_title,
                    "text": full_text.strip(),
                    "meta": {
                        "kind": "rss_article",
                        "title": title,
                        "url": link,
                        "summary": _clean_html_to_text(summary),
                        "tags": tags,
                    },
                    "created_at": created_at,
                }
            )

        inserted = insert_raw_items(items)
        total_inserted += inserted
        update_source_meta(src_id, {"last_fetched_at": now.isoformat()})
        logger.info("rss_feed_ingested", extra={"url": url, "inserted": inserted})

    logger.info("rss_ingest_completed", extra={"inserted": total_inserted, "feeds": len(urls)})
    return total_inserted

