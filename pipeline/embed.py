from __future__ import annotations

import math
import os
import random
from typing import Any, Iterable

from .config import EMBED_DIMS, EMBED_MODEL, EMBED_OFFLINE
from .io import db, get_embedding, put_embedding


def _norm(vec: list[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / s for x in vec]


def _offline_embed_stub(text: str, dims: int = EMBED_DIMS) -> list[float]:
    # Deterministic pseudo-embedding based on text hash; good for tests/offline
    seed = abs(hash(text)) % (2**32)
    rng = random.Random(seed)
    vec = [rng.uniform(-1.0, 1.0) for _ in range(dims)]
    return _norm(vec)


def _embed_openai_chunks(chunks: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    # Lazy import to avoid dependency at import time
    from openai import OpenAI  # type: ignore

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=api_key)
    res = client.embeddings.create(model=model, input=chunks)
    return [d.embedding for d in res.data]


def embed_text(text: str, model: str = EMBED_MODEL, dims: int = EMBED_DIMS) -> list[float]:
    # Split into ~4000 token chunks (approx by chars)
    if not text:
        return [0.0] * dims
    approx_chunk_chars = 4000  # crude proxy
    chunks = [text[i : i + approx_chunk_chars] for i in range(0, len(text), approx_chunk_chars)]
    if EMBED_OFFLINE or not os.getenv("OPENAI_API_KEY"):
        vecs = [_offline_embed_stub(c, dims=dims) for c in chunks]
    else:
        vecs = _embed_openai_chunks(chunks, model=model)
    if not vecs:
        return [0.0] * dims
    # Average pool to single vector
    dims0 = len(vecs[0])
    out = [sum(v[i] for v in vecs) / len(vecs) for i in range(dims0)]
    return _norm(out)


def ensure_embeddings_for_hashes(content_hashes: Iterable[str], logger=None) -> int:
    ch_list = list(dict.fromkeys(content_hashes))
    if not ch_list:
        return 0

    placeholders = ",".join(["?"] * len(ch_list))
    with db() as conn:
        cur = conn.execute(
            f"SELECT content_hash, text FROM articles WHERE content_hash IN ({placeholders})",
            ch_list,
        )
        text_by_hash = {r["content_hash"]: r["text"] for r in cur.fetchall()}
        cur = conn.execute(
            f"SELECT content_hash FROM embeddings WHERE content_hash IN ({placeholders})",
            ch_list,
        )
        existing = {r["content_hash"] for r in cur.fetchall()}

    to_embed = [ch for ch in ch_list if ch not in existing and text_by_hash.get(ch)]
    if not to_embed:
        return 0

    done = 0
    with db() as conn:
        for ch in to_embed:
            vec = embed_text(text_by_hash[ch])
            put_embedding(conn, ch, EMBED_MODEL, len(vec), vec)
            done += 1
            if logger:
                logger.debug("Embedded %s", ch[:8])
    return done


def get_embedding_vector(conn, content_hash: str | None) -> list[float] | None:
    if not content_hash:
        return None
    row = get_embedding(conn, content_hash)
    if not row:
        return None
    try:
        return [float(x) for x in (row["vector"] and __import__("json").loads(row["vector"]))]
    except Exception:  # noqa: BLE001
        return None

