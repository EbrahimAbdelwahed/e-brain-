from __future__ import annotations

import logging
import uuid
from typing import Any

from .embed import ensure_embeddings_for_hashes, get_embedding_vector
from .io import db, fetch_articles, put_cluster, put_cluster_members


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

    # Greedy clustering by Jaccard similarity and canonical URL equality
    word_sets = {a["article_id"]: set((a.get("text") or "").lower().split()) for a in arts}
    unassigned = set(a["article_id"] for a in arts)
    clusters: list[list[str]] = []
    by_id = {a["article_id"]: a for a in arts}
    jaccard_threshold = 1.0 / max(threshold, 1)

    while unassigned:
        seed = unassigned.pop()
        group = [seed]
        seed_words = word_sets.get(seed, set())
        seed_url = by_id[seed].get("canonical_url")
        to_check = list(unassigned)
        for aid in to_check:
            if by_id[aid].get("canonical_url") == seed_url:
                group.append(aid)
                unassigned.remove(aid)
                continue
            words = word_sets.get(aid, set())
            if not seed_words or not words:
                continue
            inter = len(seed_words & words)
            union = len(seed_words | words)
            if union and inter / union >= jaccard_threshold:
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

