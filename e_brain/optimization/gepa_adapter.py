from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, TypedDict

from gepa.core.adapter import EvaluationBatch, GEPAAdapter

from ..config import get_settings
from ..embedding.embedding import embed_texts
from ..db import semantic_search
from ..moderation.moderation import moderate_text
from ..util.logging import get_logger


logger = get_logger(__name__)


class EBrainDataInst(TypedDict, total=False):
    query: str
    # Optional precomputed retrieval context to speed up evaluation
    context: str


class EBrainTrajectory(TypedDict):
    query: str
    context: str
    system_prompt: str
    assistant_response: str
    length: int
    moderation_ok: bool
    missing_keywords: list[str]


class EBrainRollout(TypedDict):
    text: str


_STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "or",
    "of",
    "in",
    "on",
    "for",
    "to",
    "with",
    "about",
    "is",
    "are",
    "be",
    "how",
    "what",
    "why",
}


def _extract_keywords(text: str, k: int = 6) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", text.lower())
    uniq: list[str] = []
    for w in words:
        if w in _STOPWORDS:
            continue
        if w not in uniq:
            uniq.append(w)
    return uniq[:k]


def _length_score(n: int, max_len: int = 280, ideal: int = 200) -> float:
    if n > max_len:
        return 0.0
    # Piecewise triangular: peak at ideal, 0 at 0 and max_len
    left = n / ideal if n <= ideal else 1.0
    right = (max_len - n) / (max_len - ideal) if n > ideal else 1.0
    return max(0.0, min(left, right))


def _keyword_coverage_score(keywords: list[str], text: str) -> float:
    tl = text.lower()
    hits = sum(1 for kw in keywords if kw in tl)
    if not keywords:
        return 0.7  # neutral if no keywords found
    return hits / len(keywords)


def _emoji_penalty(text: str) -> float:
    # discourage emoji spam; allow up to 2 without penalty
    count = len(re.findall(r"[\U0001F300-\U0001FAFF]", text))
    if count <= 2:
        return 1.0
    # Each extra emoji reduces by 10%, floor at 0.6
    return max(0.6, 1.0 - 0.1 * (count - 2))


def _build_context_from_query(query: str, max_sources: int = 5) -> str:
    # Embed query and retrieve top matches
    q_emb = embed_texts([query])[0]
    matches = semantic_search(q_emb, limit=max_sources)
    bullets = [f"- {m['text']}" for m in matches]
    return "\n".join(bullets)


class EBrainGEPAAdapter(GEPAAdapter[EBrainDataInst, EBrainTrajectory, EBrainRollout]):
    """Adapter that optimizes the system prompt for post generation.

    Candidate schema: {"system": <system_prompt_text>}
    """

    def __init__(self, model: str | None = None) -> None:
        self.model_name = model or get_settings().chat_model
        # lazy import to avoid import cost if unused
        import litellm  # type: ignore

        self._litellm = litellm

    def _generate(self, system_prompt: str, user_content: str) -> str:
        resp = self._litellm.completion(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.7,
            max_tokens=120,
        )
        return resp.choices[0].message.content.strip()

    def evaluate(
        self,
        batch: list[EBrainDataInst],
        candidate: dict[str, str],
        capture_traces: bool = False,
    ) -> EvaluationBatch[EBrainTrajectory, EBrainRollout]:
        system_prompt = candidate.get("system") or ""
        outputs: list[EBrainRollout] = []
        scores: list[float] = []
        trajectories: list[EBrainTrajectory] | None = [] if capture_traces else None

        for item in batch:
            query = item.get("query", "").strip()
            context = item.get("context") or _build_context_from_query(query)

            user_prompt = (
                "Context (curated snippets):\n"
                + context
                + "\n\nWrite an audience-ready X post about: '"
                + query
                + "'. Prefer factual clarity, avoid hype, keep it short. If complex, offer an example."
            )

            try:
                text = self._generate(system_prompt, user_prompt)
            except Exception as e:
                logger.info("gepa_eval_generation_error", extra={"error": str(e)})
                text = ""

            ok, _ = moderate_text(text)
            length = len(text)
            kws = _extract_keywords(query)
            kw_score = _keyword_coverage_score(kws, text)
            len_score = _length_score(length)
            mod_score = 1.0 if ok else 0.0
            style_mult = _emoji_penalty(text)

            # Weighted aggregate; rescale to [0,1]
            base = 0.4 * mod_score + 0.3 * len_score + 0.3 * kw_score
            score = base * style_mult

            outputs.append({"text": text})
            scores.append(float(score))

            if capture_traces and trajectories is not None:
                missing = [kw for kw in kws if kw not in text.lower()]
                trajectories.append(
                    {
                        "query": query,
                        "context": context,
                        "system_prompt": system_prompt,
                        "assistant_response": text,
                        "length": length,
                        "moderation_ok": ok,
                        "missing_keywords": missing,
                    }
                )

        return EvaluationBatch(outputs=outputs, scores=scores, trajectories=trajectories)

    def make_reflective_dataset(
        self,
        candidate: dict[str, str],
        eval_batch: EvaluationBatch[EBrainTrajectory, EBrainRollout],
        components_to_update: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        # Only optimizing the 'system' component
        items: list[dict[str, Any]] = []
        if not eval_batch.trajectories:
            raise ValueError("Trajectories required for reflection")

        for traj, score, out in zip(
            eval_batch.trajectories, eval_batch.scores, eval_batch.outputs, strict=False
        ):
            feedback_bits: list[str] = []
            if not traj["moderation_ok"]:
                feedback_bits.append("The output violates moderation/length constraints. Keep <= 280 chars, avoid risky claims.")
            if traj["missing_keywords"]:
                feedback_bits.append(
                    "Include relevant keywords from the user query when natural: "
                    + ", ".join(traj["missing_keywords"])
                )
            if traj["length"] > 260:
                feedback_bits.append("Tighten phrasing to reduce characters while keeping clarity.")
            if traj["length"] < 120:
                feedback_bits.append("Add a concrete detail or example to increase informativeness.")

            if not feedback_bits:
                feedback_bits.append("Good output. Consider minor clarity and specificity improvements.")

            items.append(
                {
                    "Inputs": {
                        "query": traj["query"],
                        "context_excerpt": "\n".join(traj["context"].splitlines()[:3]),
                    },
                    "Generated Outputs": out["text"],
                    "Feedback": " ".join(feedback_bits),
                    "score": float(score),
                }
            )

        return {"system": items}

