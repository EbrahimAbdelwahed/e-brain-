from __future__ import annotations

from typing import Iterable, List, Tuple

import tiktoken

from openai import OpenAI

from ..config import get_settings
from ..db import insert_embeddings, select_items_without_embedding
from ..util.logging import get_logger


logger = get_logger(__name__)


def embed_texts(texts: List[str]) -> List[List[float]]:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY missing")
    client = OpenAI(api_key=s.openai_api_key)
    resp = client.embeddings.create(model=s.embedding_model, input=texts)
    # openai returns floats; ensure Python floats
    return [list(d.embedding) for d in resp.data]


def _chunk_text(text: str, max_tokens: int = 7500) -> List[str]:
    """Chunk a long string into token-limited pieces for embeddings.

    Uses a conservative token limit below the model context to account for
    any overhead. Default assumes an ~8k context model.
    """
    # Heuristic: use cl100k_base which matches text-embedding-3-* tokenization closely
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        # Fallback: simple split by characters if tokenizer unavailable
        approx_chars = max_tokens * 4
        return [text[i : i + approx_chars] for i in range(0, len(text), approx_chars)]

    tokens = enc.encode(text)
    chunks: List[str] = []
    for i in range(0, len(tokens), max_tokens):
        sub = tokens[i : i + max_tokens]
        chunks.append(enc.decode(sub))
    return chunks if chunks else [text]


def _avg_vectors(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    sums = [0.0] * dim
    for v in vectors:
        # guard against inconsistent dims
        if len(v) != dim:
            raise ValueError("inconsistent embedding dimensions across chunks")
        for j in range(dim):
            sums[j] += v[j]
    return [x / len(vectors) for x in sums]


def embed_new_items(batch_size: int = 64) -> int:
    # Fetch items missing embeddings
    items = select_items_without_embedding(limit=batch_size)
    if not items:
        return 0

    s = get_settings()
    # Process each item independently to avoid cross-item concatenation
    pairs: List[Tuple[int, List[float]]] = []
    for it in items:
        text = it.text or ""
        # Chunk long articles; keep short ones as single chunk
        chunks = _chunk_text(text, max_tokens=7500)
        # Embed per-chunk in mini-batches to respect API shape
        # Here we keep it simple and embed the chunks for a single item at once
        try:
            chunk_embs = embed_texts(chunks)
        except Exception as e:
            logger.error("embed_error", extra={"item_id": it.id, "err": str(e)})
            continue

        # Aggregate chunk embeddings; average is a common/simple choice
        item_emb = _avg_vectors(chunk_embs)
        if not item_emb:
            logger.error("empty_embedding", extra={"item_id": it.id})
            continue
        pairs.append((it.id, item_emb))

    count = insert_embeddings(pairs)
    logger.info("embedded_items", extra={"count": count})
    return count

