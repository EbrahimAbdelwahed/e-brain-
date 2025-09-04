from __future__ import annotations

import json
import logging
from collections import Counter
import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from .io import db, fetch_articles_by_ids, fetch_cluster_members, fetch_clusters, upsert_summary, get_summary
from .prompts import PROMPT_VERSION, GUARDRAILS_VERSION, system_prompt, build_map_facts, build_reduce_prompt
from . import llm
from .obs import obs_span


def _hash_version(article_ids: list[str], extracted_facts: list[str], model: str | None) -> str:
    base = "|".join(
        [PROMPT_VERSION, GUARDRAILS_VERSION, (model or "heuristic")]
        + sorted(article_ids)
        + ["||".join(sorted(extracted_facts))]
    )
    h = hashlib.sha256(base.encode("utf-8")).hexdigest()
    return h


def _first_sentence(text: str) -> str:
    for sep in (". ", "? ", "! "):
        if sep in text:
            return text.split(sep, 1)[0].strip() + sep.strip()
    return text.strip()


def _method_limit_signal(text: str) -> str | None:
    t = text.lower()
    cues = [
        ("random", "randomized design"),
        ("double-blind", "double-blind"),
        ("open-label", "open-label"),
        ("retrospective", "retrospective"),
        ("n=", "sample size reported"),
        ("mouse", "in mice"),
        ("mice", "in mice"),
        ("non-human primate", "in non-human primates"),
        ("human", "in humans"),
        ("preprint", "preprint, not peer-reviewed"),
    ]
    for key, label in cues:
        if key in t:
            return label
    return None


def _map_article(article: dict[str, Any]) -> list[str]:
    title = (article.get("title") or "").strip()
    text = (article.get("text") or "").strip()
    claim = _first_sentence(title or text)
    method = _method_limit_signal(text)
    bullets = [f"Claim/result: {claim}"]
    if method:
        bullets.append(f"Method/limit: {method}.")
    else:
        bullets.append("Method/limit: not clearly stated.")
    return bullets[:2]


def _reduce_cluster(cluster_articles: list[dict[str, Any]]) -> list[str]:
    # 3–5 bullets: what changed, note disagreements, label preprints; end with Bottom line
    bullets: list[str] = []
    titles = [a.get("title") or "" for a in cluster_articles]
    preprints = sum(1 for a in cluster_articles if int(a.get("is_preprint") or 0) == 1)
    outlets = [a.get("canonical_url") or "" for a in cluster_articles]
    domains = [o.split("/")[2] if "//" in o else o for o in outlets if o]
    dom_top = ", ".join([d for d, _ in Counter(domains).most_common(2)])

    bullets.append(f"What changed: {titles[0][:160]}".rstrip(".") + ".")
    if preprints:
        bullets.append(f"Preprints: {preprints} in this cluster; interpret cautiously.")
    if dom_top:
        bullets.append(f"Coverage: {dom_top}.")
    # Disagreements heuristic: differing titles length variance
    if len(set(titles)) > 1:
        bullets.append("Disagreements: reports vary; check methods and sample sizes.")
    bullets.append("Bottom line: evidence-first reading over hype; see citations.")
    return bullets[:5]


def _citations(cluster_articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in cluster_articles:
        url = a.get("canonical_url") or ""
        outlet = url.split("/")[2] if "//" in url else url
        out.append({
            "title": a.get("title"),
            "outlet": outlet,
            "url": url,
            "date": a.get("published_at"),
        })
    return out


def summarize(
    logger: logging.Logger | None = None,
    *,
    use_llm: bool | None = None,
    model: str | None = None,
    persist: bool = True,
) -> list[dict[str, Any]]:
    """Summarize clusters and persist to DB.

    If SUMMARIZE_USE_LLM=1 or use_llm is True and OPENROUTER_API_KEY is set, use LLM via OpenRouter.
    Otherwise, fall back to heuristic summarization (unchanged shapes).
    """
    # Resolve flags from env if not explicitly passed
    env_use_llm = os.getenv("SUMMARIZE_USE_LLM", "0") == "1"
    use_llm = bool(use_llm) or env_use_llm
    model = model or os.getenv("SUMMARIZE_MODEL", "moonshotai/kimi-k2")
    temperature = float(os.getenv("SUMMARIZE_TEMPERATURE", "0.2"))
    top_p = float(os.getenv("SUMMARIZE_TOP_P", "0.9"))
    seed_env = os.getenv("SUMMARIZE_SEED")
    seed = int(seed_env) if seed_env is not None and seed_env != "" else None

    with db() as conn:
        clusters = fetch_clusters(conn)
    if not clusters:
        if logger:
            logger.info("No clusters to summarize.")
        return []
    results: list[dict[str, Any]] = []
    for c in clusters:
        with db() as conn:
            members = fetch_cluster_members(conn, c["cluster_id"])  # list of article_ids
            arts = fetch_articles_by_ids(conn, members)
        # Map facts (heuristic) are used both for LLM and heuristic reduce
        map_bullets = [b for a in arts for b in _map_article(a)]

        if use_llm and os.getenv("OPENROUTER_API_KEY"):
            # Version hash includes model and extracted facts
            version_hash = _hash_version(sorted(members), map_bullets, model)
            # Skip provider call if summary is already up to date (cache boundary)
            with db() as conn:
                existing = get_summary(conn, c["cluster_id"])
            if existing and existing.get("version_hash") == version_hash:
                if logger:
                    logger.debug("Cache hit for cluster %s; skipping LLM", c["cluster_id"])
                # Still return a shape for results (inflate from DB on publish usually)
                citations = _citations(arts)
                bullets = json.loads(existing.get("bullets_json") or "[]")
                tl_dr = existing.get("tl_dr") or "X: (no change)"
            else:
                # Build prompts and call provider
                sys = system_prompt()
                facts_texts = [build_map_facts(a) for a in arts]
                user = build_reduce_prompt(cluster_articles=arts, extracted_facts=facts_texts)
                try:
                    with obs_span(
                        "llm.summarize",
                        {
                            "model": (model or "moonshotai/kimi-k2"),
                            "temperature": float(temperature),
                            "top_p": float(top_p),
                            "seed": int(seed) if seed is not None else -1,
                            "prompt_chars": len(user),
                        },
                    ) as _span:
                        content = llm.generate_chat(
                            model=model or "moonshotai/kimi-k2",
                            system=sys,
                            messages=[{"role": "user", "content": user}],
                            temperature=temperature,
                            top_p=top_p,
                            seed=seed,
                        )
                        _span.set({"output_chars": len(content)})
                except llm.LLMError as e:
                    if logger:
                        logger.warning("LLM failed (%s); falling back to heuristic", e)
                    # Fall back to heuristic reduce
                    bullets = _reduce_cluster(arts)
                    citations = _citations(arts)
                    first = bullets[0] if bullets else ""
                    lead = first.replace("What changed: ", "").strip()
                    if lead and not lead.endswith("."):
                        lead += "."
                    tl_dr = f"X: {lead}" if lead else "X: (no change)"
                else:
                    # Parse content into lead + bullets
                    lead = ""
                    bullets_list: list[str] = []
                    for raw_line in content.splitlines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        if line.lower().startswith("lead:") and not lead:
                            lead = line.split(":", 1)[1].strip()
                            continue
                        if line.startswith("- "):
                            bullets_list.append(line[2:].strip())
                    # Ensure Bottom line present
                    if not any(b.lower().startswith("bottom line:") for b in bullets_list):
                        if lead:
                            bullets_list.append(f"Bottom line: {lead}")
                        else:
                            bullets_list.append("Bottom line: evidence-first reading over hype; see citations.")
                    bullets = bullets_list[:5] if bullets_list else _reduce_cluster(arts)
                    citations = _citations(arts)
                    # Derive tl;dr from lead
                    ld = lead.strip()
                    if ld and not ld.endswith("."):
                        ld += "."
                    tl_dr = f"X: {ld}" if ld else "X: (no change)"

                # Persist summary per cluster (idempotent) unless persist=False (eval path)
                if persist:
                    with db() as conn:
                        upsert_summary(
                            conn,
                            cluster_id=c["cluster_id"],
                            tl_dr=tl_dr,
                            bullets=bullets,
                            citations=citations,
                            version_hash=version_hash,
                        )
                # Small in-process boundary is implicit via DB check within the same run
        else:
            # Heuristic path (unchanged behavior)
            red_bullets = _reduce_cluster(arts)
            bullets = red_bullets
            citations = _citations(arts)
            # Derive a short lead from bullets (X-shaped lead)
            first = bullets[0] if bullets else ""
            lead = first.replace("What changed: ", "").strip()
            if lead and not lead.endswith("."):
                lead += "."
            tl_dr = f"X: {lead}" if lead else "X: (no change)"
            # Hash version for idempotent caching
            version_hash = _hash_version(sorted(members), map_bullets + bullets, None)
            # Persist summary per cluster (idempotent) unless persist=False (eval path)
            if persist:
                with db() as conn:
                    upsert_summary(
                        conn,
                        cluster_id=c["cluster_id"],
                        tl_dr=tl_dr,
                        bullets=bullets,
                        citations=citations,
                        version_hash=version_hash,
                    )
        results.append(
            {
                "cluster_id": c["cluster_id"],
                "bullets": bullets,
                "delta": {"articles": len(arts)},
                "citations": citations,
                "labeled_preprint": any(int(a.get("is_preprint") or 0) == 1 for a in arts),
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    if logger:
        logger.info("Summarized %d clusters", len(results))
    return results
