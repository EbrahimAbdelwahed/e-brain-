from __future__ import annotations

import os
from typing import List, Optional

from openai import OpenAI

from ..config import get_settings
from ..db import insert_candidate_post, semantic_search
from ..util.logging import get_logger
from ..moderation.moderation import moderate_text, MAX_TWEET_LENGTH


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
    # Keep context concise to control prompt size and focus
    bullets = [f"- {m['text'][:400].rstrip()}{'…' if len(m['text']) > 400 else ''}" for m in matches]
    context = "\n".join(bullets)

    # Optional DSPy path (toggle via USE_DSPY=true)
    use_dspy = os.getenv("USE_DSPY", "false").lower() == "true"
    if use_dspy:
        try:
            from ..llm.dspy_module import generate_post as dspy_generate

            text = dspy_generate(query=query, context=context)
        except Exception as e:
            logger.info("dspy_generate_error_fallback", extra={"error": str(e)})
            use_dspy = False

    if not use_dspy:
        s = get_settings()
        client = _client()
        prompt = (
            "Context (curated snippets):\n" + context + "\n\n"
            f"Write an audience-ready X post about: '{query}'."
            " Prefer factual clarity, avoid hype, keep it short."
            " If concept is complex, offer a concrete example."
            " Keep the final output under 260 characters, no hashtags, no links."
        )
        resp = client.chat.completions.create(
            model=s.chat_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=80,
        )
        text = resp.choices[0].message.content.strip()
    # Final clamp to ensure moderation length pass
    text = _clamp_to_limit(text, MAX_TWEET_LENGTH)
    ok, reason = moderate_text(text)
    if not ok:
        logger.info("moderation_rejected", extra={"reason": reason})
        return None
    return text


def _clamp_to_limit(text: str, limit: int) -> str:
    # Normalize whitespace
    t = " ".join((text or "").strip().split())
    if len(t) <= limit:
        return t
    # Try to end at sentence boundary
    cut = t[:limit]
    last_stop = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if last_stop >= 0 and last_stop >= limit // 2:
        return cut[: last_stop + 1]
    # Else cut at last space and add ellipsis
    last_space = cut.rfind(" ")
    if last_space >= 0 and last_space >= limit // 2:
        out = cut[:last_space].rstrip()
        return out if len(out) <= limit else out[:limit]
    # Hard cut with ellipsis if possible
    return (t[: max(0, limit - 1)] + "…") if limit > 1 else ""


def generate_and_store(query: str, max_sources: int = 5) -> Optional[int]:
    text = generate_post_from_query(query, max_sources=max_sources)
    if not text:
        return None
    return insert_candidate_post(text)

