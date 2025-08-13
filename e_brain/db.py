from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Iterable, Optional

import datetime as dt
import os

import psycopg
from psycopg.rows import dict_row

from .config import get_settings
from .util.logging import get_logger


logger = get_logger(__name__)


@dataclass
class RawItem:
    id: int
    source_type: str
    source_id: Optional[str]
    author: Optional[str]
    text: str
    created_at: dt.datetime


def get_conn():
    settings = get_settings()
    return psycopg.connect(settings.database_url, autocommit=True)


def init_db() -> None:
    s = get_settings()
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Ensure extension (single statement)
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Tables (execute as separate statements to avoid multi-command prepare issues)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                  id SERIAL PRIMARY KEY,
                  type TEXT NOT NULL, -- 'x' | 'rss'
                  handle TEXT,        -- for X
                  url TEXT,           -- for RSS
                  meta JSONB DEFAULT '{}'::jsonb
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_items (
                  id BIGSERIAL PRIMARY KEY,
                  source_type TEXT NOT NULL,
                  source_ref TEXT,
                  source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
                  author TEXT,
                  text TEXT NOT NULL,
                  meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                  created_at TIMESTAMPTZ NOT NULL,
                  inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            # Ensure meta column exists for older deployments
            cur.execute(
                "ALTER TABLE raw_items ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;"
            )

            # Note: type modifiers like vector(N) cannot be parameterized; inject validated int literal
            emb_dim = int(s.embedding_dim)
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS embeddings (
                  item_id BIGINT PRIMARY KEY REFERENCES raw_items(id) ON DELETE CASCADE,
                  embedding vector({emb_dim})
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_posts (
                  id BIGSERIAL PRIMARY KEY,
                  text TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  status TEXT NOT NULL DEFAULT 'pending', -- pending|approved|posted|rejected
                  reason TEXT,
                  source_item_ids BIGINT[] DEFAULT '{}'
                )
                """
            )
    logger.info("db_initialized")


def upsert_source_x(handle: str) -> int:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM sources WHERE type='x' AND handle=%s",
            (handle,),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur.execute(
            "INSERT INTO sources(type, handle) VALUES('x', %s) RETURNING id",
            (handle,),
        )
        return int(cur.fetchone()["id"])


def upsert_source_rss(url: str, title: Optional[str] = None) -> int:
    """Create or fetch an RSS source row by URL.

    Stores title in sources.meta if provided.
    """
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM sources WHERE type='rss' AND url=%s",
            (url,),
        )
        row = cur.fetchone()
        if row:
            src_id = int(row["id"])
        else:
            cur.execute(
                "INSERT INTO sources(type, url) VALUES('rss', %s) RETURNING id",
                (url,),
            )
            src_id = int(cur.fetchone()["id"])

        if title:
            # Merge meta with new title
            cur.execute(
                "UPDATE sources SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb WHERE id=%s",
                ({"title": title}, src_id),
            )
        return src_id


def update_source_meta(source_id: int, meta_patch: dict) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE sources SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb WHERE id=%s",
            (meta_patch, source_id),
        )


def insert_raw_items(items: Iterable[dict]) -> int:
    """Insert many raw items, ignoring duplicates by (source_type, source_ref)."""
    count = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS raw_items_unique
                ON raw_items(source_type, source_ref);
                """
            )
            for it in items:
                try:
                    cur.execute(
                        """
                        INSERT INTO raw_items(source_type, source_ref, source_id, author, text, meta, created_at)
                        VALUES(%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (source_type, source_ref) DO NOTHING
                        """,
                        (
                            it.get("source_type"),
                            it.get("source_ref"),
                            it.get("source_id"),
                            it.get("author"),
                            it.get("text"),
                            it.get("meta", {}),
                            it.get("created_at"),
                        ),
                    )
                    count += cur.rowcount
                except Exception as e:
                    logger.error(f"insert_raw_item_error: {e}")
    logger.info("raw_items_inserted", extra={"count": count})
    return count


def select_items_without_embedding(limit: int = 128) -> list[RawItem]:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT ri.id, ri.source_type, ri.source_ref, ri.author, ri.text, ri.created_at
            FROM raw_items ri
            LEFT JOIN embeddings e ON e.item_id = ri.id
            WHERE e.item_id IS NULL
            ORDER BY ri.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall() or []
        return [
            RawItem(
                id=int(r["id"]),
                source_type=str(r["source_type"]),
                source_id=r.get("source_ref"),
                author=r.get("author"),
                text=str(r["text"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]


def insert_embeddings(pairs: list[tuple[int, list[float]]]) -> int:
    if not pairs:
        return 0
    with get_conn() as conn, conn.cursor() as cur:
        for item_id, emb in pairs:
            cur.execute(
                "INSERT INTO embeddings(item_id, embedding) VALUES(%s, %s) ON CONFLICT (item_id) DO NOTHING",
                (item_id, emb),
            )
        return len(pairs)


def semantic_search(query_embedding: list[float], limit: int = 10) -> list[dict]:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT ri.id, ri.text, ri.author, ri.created_at,
                   1 - (e.embedding <=> %s::vector) AS similarity
            FROM embeddings e
            JOIN raw_items ri ON ri.id = e.item_id
            ORDER BY e.embedding <=> %s::vector ASC
            LIMIT %s
            """,
            (query_embedding, query_embedding, limit),
        )
        return cur.fetchall() or []


def insert_candidate_post(text: str, source_item_ids: Optional[list[int]] = None, reason: Optional[str] = None) -> int:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO candidate_posts(text, status, reason, source_item_ids)
            VALUES(%s,'pending',%s,%s)
            RETURNING id
            """,
            (text, reason, source_item_ids or []),
        )
        return int(cur.fetchone()["id"])


def select_pending_posts(limit: int = 5) -> list[dict]:
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, text FROM candidate_posts WHERE status='pending' ORDER BY created_at ASC LIMIT %s",
            (limit,),
        )
        return cur.fetchall() or []


def mark_posted(post_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE candidate_posts SET status='posted' WHERE id=%s",
            (post_id,),
        )


def create_vector_index(index_type: str = "hnsw") -> None:
    """Create a vector index on embeddings.embedding.

    index_type: 'hnsw' (preferred) or 'ivfflat'.
    """
    index_type = (index_type or "").lower()
    with get_conn() as conn, conn.cursor() as cur:
        if index_type == "hnsw":
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS embeddings_hnsw
                ON embeddings
                USING hnsw (embedding vector_l2_ops)
                """
            )
        elif index_type == "ivfflat":
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS embeddings_ivfflat
                ON embeddings
                USING ivfflat (embedding vector_l2_ops)
                WITH (lists = 100)
                """
            )
        else:
            raise ValueError("index_type must be 'hnsw' or 'ivfflat'")
        cur.execute("ANALYZE embeddings;")
        # removed
        # removed
        # removed
        # removed
        # removed
