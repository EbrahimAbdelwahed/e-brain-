from __future__ import annotations

from typing import Iterable, List, Tuple

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


def embed_new_items(batch_size: int = 64) -> int:
    items = select_items_without_embedding(limit=batch_size)
    if not items:
        return 0
    texts = [it.text for it in items]
    embs = embed_texts(texts)
    pairs: List[Tuple[int, List[float]]] = [(it.id, emb) for it, emb in zip(items, embs)]
    count = insert_embeddings(pairs)
    logger.info("embedded_items", extra={"count": count})
    return count

