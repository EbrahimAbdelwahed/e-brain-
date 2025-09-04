from __future__ import annotations

from typing import Any, Iterable


# Versioned knobs for caching (imported by summarize)
PROMPT_VERSION = "v1"
GUARDRAILS_VERSION = "v1"


def system_prompt() -> str:
    # Derived from ARCHITECT.md §14 Voice Pack
    return (
        "You are NeuroScope, an evidence-first watchdog for neuroscience/AI news. "
        "Tone: direct, receipts-led, slightly calmer than @dogeai_gov. Contrast claims vs practice; "
        "cite primary sources; label preprints; use absolute dates; short, firm bullets; end with 'Bottom line: ...'. "
        "Prepare output shaped like an X thread lead plus a separate 'Sources' section."
    )


def build_map_facts(article: dict[str, Any]) -> str:
    """Map step: extract salient facts from one article as short lines.

    This is a heuristic builder to keep the LLM reduce step focused.
    """
    title = (article.get("title") or "").strip()
    is_preprint = int(article.get("is_preprint") or 0) == 1
    url = (article.get("canonical_url") or "").strip()
    parts = [
        f"Title: {title}",
        f"Preprint: {str(is_preprint).lower()}",
        f"URL: {url}",
    ]
    text = (article.get("text") or "").strip()
    if text:
        parts.append(f"Body: {text[:500]}")  # keep prompt small; reduce step is cluster-level
    return "\n".join(parts)


def build_reduce_prompt(
    *,
    cluster_articles: list[dict[str, Any]],
    extracted_facts: Iterable[str],
) -> str:
    """Reduce step: instruct the LLM to produce an X-shaped lead and bullets.

    Output contract (plain text):
    - Begin with a single-line lead: "Lead: ..."
    - Then 3-5 bullets, each on its own line starting with "- ".
    - Ensure one bullet starts with "Bottom line: ".
    - Include guardrails if applicable, e.g., "preprint; may change post-review".
    """
    any_preprint = any(int(a.get("is_preprint") or 0) == 1 for a in cluster_articles)
    preprint_hint = (
        "At least one item is a preprint; include the phrase 'preprint; may change post-review'."
        if any_preprint
        else "If peer-reviewed status is unclear, avoid overclaiming."
    )
    facts_blob = "\n\n".join(extracted_facts)
    instr = (
        "Write a concise, receipts-led summary for a cluster of near-duplicate news items.\n"
        "- Produce one lead line prefixed with 'Lead: '.\n"
        "- Then produce 3-5 short bullets (each starts with '- ').\n"
        "- End with a bullet starting with 'Bottom line: ' summarizing what changed and why.\n"
        "- Do not fabricate citations; they are provided separately.\n"
        f"- {preprint_hint}\n"
        "- No medical advice; critique claims & methods, not people.\n"
        "- Keep it factual, with numbers if present; absolute dates.\n"
    )
    return (
        f"Instructions:\n{instr}\n\n"
        f"Cluster items: {len(cluster_articles)}\n\n"
        f"Extracted facts (map outputs):\n{facts_blob}\n"
    )

