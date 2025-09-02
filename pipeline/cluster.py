from __future__ import annotations

import itertools
import logging
import math
import uuid
from collections import defaultdict
from typing import Any
import re

from .embed import ensure_embeddings_for_hashes, get_embedding_vector
import hashlib
from .io import db, fetch_articles, put_cluster, put_cluster_members


def _shingles(text: str, k: int = 3) -> list[str]:
    words = [w for w in text.lower().split() if w]
    if len(words) <= k:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + k]) for i in range(len(words) - k + 1)]


def simhash64(text: str) -> int:
    # 64-bit simhash on shingles using stable md5 hashing for determinism
    bits = [0] * 64
    for sh in _shingles(text):
        h = int.from_bytes(hashlib.md5(sh.encode("utf-8")).digest()[:8], "big")
        for i in range(64):
            bits[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, b in enumerate(bits):
        if b > 0:
            out |= 1 << i
    return out


def hamming64(a: int, b: int) -> int:
    return ((a ^ b).bit_count())


def _representative(article_list: list[dict[str, Any]]) -> dict[str, Any]:
    # Choose the article with the longest text as representative
    return max(article_list, key=lambda x: len(x.get("text") or ""))


def cluster(threshold: int = 8, logger: logging.Logger | None = None) -> list[dict[str, Any]]:
    with db() as conn:
        arts = fetch_articles(conn)
    if not arts:
        if logger:
            logger.info("No articles to cluster.")
        return []

    # Precompute simhash for each article
    sims: dict[str, int] = {}
    for a in arts:
        sims[a["article_id"]] = simhash64(a.get("text") or "")

    # Greedy clustering by hamming distance and canonical URL equality
    unassigned = set(a["article_id"] for a in arts)
    clusters: list[list[str]] = []
    by_id = {a["article_id"]: a for a in arts}
    # Precompute token sets for quick Jaccard check
    def tokens(t: str) -> set[str]:
        return set(re.findall(r"\w+", (t or "").lower()))
    tok_sets = {a["article_id"]: tokens(a.get("text") or "") for a in arts}

    while unassigned:
        seed = unassigned.pop()
        group = [seed]
        seed_sim = sims[seed]
        seed_url = by_id[seed].get("canonical_url")
        to_check = list(unassigned)
        for aid in to_check:
            if by_id[aid].get("canonical_url") == seed_url:
                group.append(aid)
                unassigned.remove(aid)
                continue
            # Jaccard similarity on word sets as a robust fallback
            s1, s2 = tok_sets[seed], tok_sets[aid]
            if s1 and s2:
                inter = len(s1 & s2)
                union = len(s1 | s2)
                if union > 0 and (inter / union) >= 0.5:
                    group.append(aid)
                    unassigned.remove(aid)
                    continue
            dist = hamming64(seed_sim, sims[aid])
            if dist <= threshold:
                group.append(aid)
                unassigned.remove(aid)
        clusters.append(group)

    # Compute embeddings centroid (ensure cached first)
    content_hashes = [a.get("content_hash") for a in arts if a.get("content_hash")]
    ensure_embeddings_for_hashes(content_hashes, logger=logger)

    # Persist clusters
    saved = []
    with db() as conn:
        for members in clusters:
            articles = [by_id[m] for m in members]
            rep = _representative(articles)
            cluster_id = uuid.uuid5(uuid.NAMESPACE_URL, rep.get("canonical_url") or rep.get("article_id")).hex[:16]
            # centroid: average of vectors for members with embeddings
            vecs = []
            for a in articles:
                v = get_embedding_vector(conn, a.get("content_hash"))
                if v:
                    vecs.append(v)
            centroid = None
            if vecs:
                # average pool
                dims = len(vecs[0])
                centroid = [sum(v[i] for v in vecs) / len(vecs) for i in range(dims)]
            put_cluster(conn, cluster_id, method="simhash+embed", centroid_embed=centroid, representative_article_id=rep["article_id"])
            put_cluster_members(conn, cluster_id, members)
            saved.append({"cluster_id": cluster_id, "members": members, "representative_article_id": rep["article_id"]})
    if logger:
        logger.info("Created %d clusters", len(saved))
    return saved
