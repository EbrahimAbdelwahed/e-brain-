from __future__ import annotations

from typing import List, Optional

from openai import OpenAI

from ..config import get_settings
from ..db import insert_candidate_post, semantic_search
from ..util.logging import get_logger
from ..moderation.moderation import moderate_text


logger = get_logger(__name__)


SYSTEM_PROMPT = (
    "You are a concise, factual neuroscience communicator crafting engaging X posts. "
    "Prefer clear, accurate statements. Use occasional emoji sparingly. Keep to 1-2 sentences."
)


def _client() -> OpenAI:
    s = get_settings()
    if not s.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY missing")
    return OpenAI(api_key=s.openai_api_key)


def generate_post_from_query(query: str, max_sources: int = 5) -> Optional[str]:
    # Get embedding for query via embedding endpoint for semantic retrieval
    from ..embedding.embedding import embed_texts

    q_emb = embed_texts([query])[0]
    matches = semantic_search(q_emb, limit=max_sources)
    bullets = [f"- {m['text']}" for m in matches]
    context = "\n".join(bullets)

    s = get_settings()
    client = _client()
    prompt = (
        "Context (curated snippets):\n" + context + "\n\n"
        f"Write an audience-ready X post about: '{query}'."
        " Prefer factual clarity, avoid hype, keep it short."
        " If concept is complex, offer a concrete example."
    )
    resp = client.chat.completions.create(
        model=s.chat_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=120,
    )
    text = resp.choices[0].message.content.strip()
    ok, reason = moderate_text(text)
    if not ok:
        logger.info("moderation_rejected", extra={"reason": reason})
        return None
    return text


def generate_and_store(query: str, max_sources: int = 5) -> Optional[int]:
    text = generate_post_from_query(query, max_sources=max_sources)
    if not text:
        return None
    return insert_candidate_post(text)

