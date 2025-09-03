from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Tuple

import requests
import certifi
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, RetryError

from .config import DB_PATH, ensure_dirs, DEFAULT_RPS_PER_HOST, ROOT


_lock = threading.Lock()


def _dict_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = _dict_factory
    return conn


@contextmanager
def db() -> Iterable[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn, _lock:
        c = conn.cursor()
        c.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS http_cache (
                url TEXT PRIMARY KEY,
                etag TEXT,
                last_modified TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS feeds (
                feed_url TEXT PRIMARY KEY,
                source_id TEXT,
                etag TEXT,
                last_modified TEXT
            );

            CREATE TABLE IF NOT EXISTS raw_articles (
                entry_id TEXT,
                feed_url TEXT,
                source_id TEXT,
                link TEXT,
                title TEXT,
                summary TEXT,
                published_at TEXT,
                fetched_at TEXT,
                etag TEXT,
                last_modified TEXT,
                PRIMARY KEY (entry_id, feed_url)
            );

            CREATE TABLE IF NOT EXISTS articles (
                article_id TEXT PRIMARY KEY,
                canonical_url TEXT,
                title TEXT,
                byline TEXT,
                published_at TEXT,
                source_id TEXT,
                is_preprint INTEGER,
                text TEXT,
                lang TEXT,
                tags TEXT,
                extraction_quality REAL,
                content_hash TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS embeddings (
                content_hash TEXT PRIMARY KEY,
                model TEXT,
                dims INTEGER,
                vector TEXT
            );

            CREATE TABLE IF NOT EXISTS clusters (
                cluster_id TEXT PRIMARY KEY,
                method TEXT,
                centroid_embed TEXT,
                representative_article_id TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS cluster_members (
                cluster_id TEXT,
                article_id TEXT,
                PRIMARY KEY (cluster_id, article_id)
            );

            CREATE TABLE IF NOT EXISTS summaries (
                cluster_id TEXT PRIMARY KEY,
                tl_dr TEXT,
                bullets_json TEXT,
                citations_json TEXT,
                score REAL,
                created_at TEXT,
                published_at TEXT,
                version_hash TEXT
            );
            """
        )


# HTTP cache helpers
def get_http_cache(conn: sqlite3.Connection, url: str) -> tuple[str | None, str | None]:
    cur = conn.execute("SELECT etag, last_modified FROM http_cache WHERE url=?", (url,))
    row = cur.fetchone()
    if not row:
        return None, None
    return row.get("etag"), row.get("last_modified")


def upsert_http_cache(conn: sqlite3.Connection, url: str, etag: str | None, last_modified: str | None) -> None:
    with _lock:
        conn.execute(
            """
            INSERT INTO http_cache(url, etag, last_modified, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET etag=excluded.etag, last_modified=excluded.last_modified, updated_at=excluded.updated_at
            """,
            (url, etag, last_modified, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )


_session_lock = threading.Lock()
_session: requests.Session | None = None
_last_req_ts: dict[str, float] = {}
_min_interval = 1.0 / max(0.1, DEFAULT_RPS_PER_HOST)


def _rate_limit(url: str) -> None:
    host = requests.utils.urlparse(url).hostname or ""
    now = time.monotonic()
    last = _last_req_ts.get(host, 0.0)
    delta = now - last
    if delta < _min_interval:
        time.sleep(_min_interval - delta)
    _last_req_ts[host] = time.monotonic()


def get_http_session() -> requests.Session:
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is None:
            s = requests.Session()
            s.headers.update(
                {
                    "User-Agent": "e-brain-bot/0.1 (+https://github.com/EbrahimAbdelwahed/e-brain-bot)",
                    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
                }
            )
            _session = s
    return _session  # type: ignore[return-value]


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(1, 4))
def http_get_bytes(url: str, logger=None) -> Tuple[int, bytes | None, dict[str, str]]:
    """GET a URL with conditional headers + caching.

    Returns: (status_code, content or None, response_headers)
    On 304 Not Modified, returns (304, None, headers).
    """
    # Fixtures/local files support
    if url.startswith("file://"):
        parsed = requests.utils.urlparse(url)
        # file://<netloc>/<path>
        if parsed.netloc and parsed.netloc not in {"localhost"}:
            # Treat netloc as first path component (fixture-like)
            p = ROOT / parsed.netloc / parsed.path.lstrip("/")
        else:
            p = Path(parsed.path)
            # On Windows, a leading '/C:/' may appear; normalize
            if p.drive and parsed.path.startswith("/"):
                p = Path(parsed.path[1:])
            if not p.is_absolute():
                p = ROOT / parsed.path.lstrip("/")
        data = p.read_bytes()
        return 200, data, {}

    s = get_http_session()
    _rate_limit(url)
    headers: dict[str, str] = {}
    with db() as conn:
        etag, last_mod = get_http_cache(conn, url)
    if etag:
        headers["If-None-Match"] = etag
    if last_mod:
        headers["If-Modified-Since"] = last_mod
    try:
        resp = s.get(url, headers=headers, timeout=10, allow_redirects=True, verify=certifi.where())
    except requests.RequestException as e:  # network or TLS errors
        if logger:
            logger.error("HTTP request failed: %s", e)
        raise
    # 304 short-circuit
    if resp.status_code == 304:
        if logger:
            logger.info("HTTP 304 Not Modified: %s", resp.url)
        return 304, None, dict(resp.headers)
    # Raise for other non-OK
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        if logger:
            logger.error(
                "HTTP error: %s %s url=%s final=%s",
                resp.status_code,
                resp.reason,
                url,
                resp.url,
            )
        raise

    # Update cache on 200
    with db() as conn:
        upsert_http_cache(conn, url, resp.headers.get("ETag"), resp.headers.get("Last-Modified"))
    return resp.status_code, resp.content, dict(resp.headers)


# Feed cache
def get_feed_cache(conn: sqlite3.Connection, feed_url: str) -> tuple[str | None, str | None]:
    cur = conn.execute("SELECT etag, last_modified FROM feeds WHERE feed_url=?", (feed_url,))
    row = cur.fetchone()
    if not row:
        return None, None
    return row.get("etag"), row.get("last_modified")


def upsert_feed_cache(conn: sqlite3.Connection, feed_url: str, source_id: str, etag: str | None, last_modified: str | None) -> None:
    with _lock:
        conn.execute(
            """
            INSERT INTO feeds(feed_url, source_id, etag, last_modified)
            VALUES(?,?,?,?)
            ON CONFLICT(feed_url) DO UPDATE SET etag=excluded.etag, last_modified=excluded.last_modified, source_id=excluded.source_id
            """,
            (feed_url, source_id, etag, last_modified),
        )


# Raw articles
@dataclass
class ArticleRaw:
    source_id: str
    feed_url: str
    entry_id: str
    link: str
    title: str | None
    summary: str | None
    published_at: str | None
    fetched_at: str
    etag: str | None
    last_modified: str | None


def insert_raw_articles(conn: sqlite3.Connection, raws: list[ArticleRaw]) -> int:
    with _lock:
        cur = conn.executemany(
            """
            INSERT OR IGNORE INTO raw_articles(entry_id, feed_url, source_id, link, title, summary, published_at, fetched_at, etag, last_modified)
            VALUES(:entry_id,:feed_url,:source_id,:link,:title,:summary,:published_at,:fetched_at,:etag,:last_modified)
            """,
            [asdict(r) for r in raws],
        )
        return cur.rowcount or 0


def fetch_unextracted_raws(conn: sqlite3.Connection, limit: int | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT ra.* FROM raw_articles ra "
        "LEFT JOIN articles a ON a.source_id = ra.source_id AND a.title = ra.title AND a.published_at = ra.published_at "
        "WHERE a.article_id IS NULL"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    cur = conn.execute(sql)
    return list(cur.fetchall())


# Articles
@dataclass
class Article:
    article_id: str
    canonical_url: str
    title: str
    byline: str | None
    published_at: str | None
    source_id: str
    is_preprint: int
    text: str
    lang: str | None
    tags: str | None
    extraction_quality: float | None
    content_hash: str


def upsert_article(conn: sqlite3.Connection, article: Article) -> None:
    with _lock:
        conn.execute(
            """
            INSERT INTO articles(article_id, canonical_url, title, byline, published_at, source_id, is_preprint, text, lang, tags, extraction_quality, content_hash)
            VALUES(:article_id,:canonical_url,:title,:byline,:published_at,:source_id,:is_preprint,:text,:lang,:tags,:extraction_quality,:content_hash)
            ON CONFLICT(article_id) DO UPDATE SET
                canonical_url=excluded.canonical_url,
                title=excluded.title,
                byline=excluded.byline,
                published_at=excluded.published_at,
                source_id=excluded.source_id,
                is_preprint=excluded.is_preprint,
                text=excluded.text,
                lang=excluded.lang,
                tags=excluded.tags,
                extraction_quality=excluded.extraction_quality,
                content_hash=excluded.content_hash
            """,
            asdict(article),
        )


def fetch_articles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT * FROM articles")
    return list(cur.fetchall())


def fetch_articles_by_ids(conn: sqlite3.Connection, ids: list[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = ",".join(["?"] * len(ids))
    cur = conn.execute(f"SELECT * FROM articles WHERE article_id IN ({placeholders})", ids)
    return list(cur.fetchall())


# Embeddings
def get_embedding(conn: sqlite3.Connection, content_hash: str) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM embeddings WHERE content_hash=?", (content_hash,))
    row = cur.fetchone()
    return row


def put_embedding(conn: sqlite3.Connection, content_hash: str, model: str, dims: int, vector: list[float]) -> None:
    with _lock:
        conn.execute(
            """
            INSERT INTO embeddings(content_hash, model, dims, vector)
            VALUES(?,?,?,?)
            ON CONFLICT(content_hash) DO UPDATE SET model=excluded.model, dims=excluded.dims, vector=excluded.vector
            """,
            (content_hash, model, dims, json.dumps(vector)),
        )


# Clusters
def put_cluster(conn: sqlite3.Connection, cluster_id: str, method: str, centroid_embed: list[float] | None, representative_article_id: str) -> None:
    with _lock:
        conn.execute(
            """
            INSERT INTO clusters(cluster_id, method, centroid_embed, representative_article_id, created_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(cluster_id) DO UPDATE SET method=excluded.method, centroid_embed=excluded.centroid_embed, representative_article_id=excluded.representative_article_id
            """,
            (cluster_id, method, json.dumps(centroid_embed) if centroid_embed else None, representative_article_id, datetime.utcnow().isoformat() + "Z"),
        )


def put_cluster_members(conn: sqlite3.Connection, cluster_id: str, article_ids: list[str]) -> None:
    with _lock:
        conn.executemany(
            "INSERT OR IGNORE INTO cluster_members(cluster_id, article_id) VALUES(?,?)",
            [(cluster_id, a) for a in article_ids],
        )


def fetch_clusters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT * FROM clusters")
    return list(cur.fetchall())


def fetch_cluster_members(conn: sqlite3.Connection, cluster_id: str) -> list[str]:
    cur = conn.execute("SELECT article_id FROM cluster_members WHERE cluster_id=?", (cluster_id,))
    return [r["article_id"] for r in cur.fetchall()]


# Summaries persistence
def get_summary(conn: sqlite3.Connection, cluster_id: str) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM summaries WHERE cluster_id=?", (cluster_id,))
    return cur.fetchone()


def upsert_summary(
    conn: sqlite3.Connection,
    *,
    cluster_id: str,
    tl_dr: str,
    bullets: list[str],
    citations: list[dict[str, Any]],
    version_hash: str,
    score: float | None = None,
) -> None:
    existing = get_summary(conn, cluster_id)
    now = datetime.utcnow().isoformat() + "Z"
    if existing and existing.get("version_hash") == version_hash:
        # Idempotent: no-op if content unchanged
        return
    with _lock:
        if existing is None:
            conn.execute(
                """
                INSERT INTO summaries(cluster_id, tl_dr, bullets_json, citations_json, score, created_at, published_at, version_hash)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    cluster_id,
                    tl_dr,
                    json.dumps(bullets, ensure_ascii=False),
                    json.dumps(citations, ensure_ascii=False),
                    score if score is not None else 0.0,
                    now,
                    None,
                    version_hash,
                ),
            )
        else:
            # Preserve created_at; update content and version
            conn.execute(
                """
                UPDATE summaries
                SET tl_dr=?, bullets_json=?, citations_json=?, version_hash=?, score=COALESCE(?, score)
                WHERE cluster_id=?
                """,
                (
                    tl_dr,
                    json.dumps(bullets, ensure_ascii=False),
                    json.dumps(citations, ensure_ascii=False),
                    version_hash,
                    score,
                    cluster_id,
                ),
            )


def fetch_summaries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT * FROM summaries")
    return list(cur.fetchall())


def mark_published(conn: sqlite3.Connection, cluster_ids: list[str]) -> None:
    if not cluster_ids:
        return
    ts = datetime.utcnow().isoformat() + "Z"
    with _lock:
        conn.executemany(
            "UPDATE summaries SET published_at=? WHERE cluster_id=?",
            [(ts, cid) for cid in cluster_ids],
        )
