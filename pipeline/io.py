from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH, ensure_dirs


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
            """
        )


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

