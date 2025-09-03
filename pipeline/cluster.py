from __future__ import annotations

import logging
import uuid
from typing import Any
import re

from datasketch import MinHash, MinHashLSH

from .embed import ensure_embeddings_for_hashes, get_embedding_vector
from .io import db, fetch_articles, put_cluster, put_cluster_members


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", (text or "").lower())


def _shingles_words(tokens: list[str], k: int = 5) -> list[str]:
    if not tokens:
        return []
    if len(tokens) <= k:
        return [" ".join(tokens)]
    return [" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)]


def _representative(article_list: list[dict[str, Any]]) -> dict[str, Any]:
    # Choose the article with the longest text as representative
    return max(article_list, key=lambda x: len(x.get("text") or ""))


def _build_minhash(shingles: list[str], num_perm: int, seed: int = 1) -> MinHash:
    mh = MinHash(num_perm=num_perm, seed=seed)
    for sh in shingles:
        mh.update(sh.encode("utf-8"))
    return mh


def cluster(
    jaccard_threshold: float = 0.85,
    num_perm: int = 128,
    logger: logging.Logger | None = None,
    threshold: int | None = None,  # backward-compat: ignored
) -> list[dict[str, Any]]:
    with db() as conn:
        arts = fetch_articles(conn)
    if not arts:
        if logger:
            logger.info("No articles to cluster.")
        return []

    by_id = {a["article_id"]: a for a in arts}

    # Precompute tokens, shingles, and MinHash signatures deterministically
    tok_map: dict[str, list[str]] = {}
    shingle_map: dict[str, list[str]] = {}
    mh_map: dict[str, MinHash] = {}
    for a in arts:
        aid = a["article_id"]
        toks = _tokens(a.get("text") or "")
        tok_map[aid] = toks
        shingles = _shingles_words(toks, k=5)
        shingle_map[aid] = shingles
        mh_map[aid] = _build_minhash(shingles, num_perm=num_perm, seed=1)

    # LSH index
    lsh = MinHashLSH(threshold=jaccard_threshold, num_perm=num_perm)
    for aid in sorted(mh_map.keys()):  # deterministic insertion order
        lsh.insert(aid, mh_map[aid])

    # Build similarity graph using LSH candidates + exact Jaccard on shingles
    neighbors: dict[str, set[str]] = {aid: set() for aid in mh_map.keys()}
    ids_sorted = sorted(mh_map.keys())
    for i, aid in enumerate(ids_sorted):
        cands = set(lsh.query(mh_map[aid]))
        cands.discard(aid)
        for bid in cands:
            # Exact Jaccard on 5-gram shingles for precision
            s1 = set(shingle_map[aid])
            s2 = set(shingle_map[bid])
            if not s1 or not s2:
                continue
            inter = len(s1 & s2)
            union = len(s1 | s2)
            jac = (inter / union) if union else 0.0
            if jac >= jaccard_threshold:
                neighbors[aid].add(bid)
                neighbors[bid].add(aid)

    # Strong tie: identical canonical_url => same cluster
    url_groups: dict[str | None, list[str]] = {}
    for aid, a in by_id.items():
        url_groups.setdefault(a.get("canonical_url"), []).append(aid)
    for group_ids in url_groups.values():
        if len(group_ids) > 1:
            for x in group_ids:
                neighbors.setdefault(x, set())
            base = group_ids[0]
            for y in group_ids[1:]:
                neighbors[base].add(y)
                neighbors[y].add(base)

    # Connected components as clusters (deterministic traversal)
    seen: set[str] = set()
    clusters_ids: list[list[str]] = []
    for aid in ids_sorted:
        if aid in seen:
            continue
        comp = []
        stack = [aid]
        seen.add(aid)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nb in sorted(neighbors.get(cur, set())):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        clusters_ids.append(sorted(comp))

    # Compute embeddings centroid (ensure cached first)
    content_hashes = [a.get("content_hash") for a in arts if a.get("content_hash")]
    ensure_embeddings_for_hashes(content_hashes, logger=logger)

    # Persist clusters
    saved = []
    with db() as conn:
        for members in clusters_ids:
            articles = [by_id[m] for m in members]
            rep = _representative(articles)
            cluster_id = uuid.uuid5(
                uuid.NAMESPACE_URL, rep.get("canonical_url") or rep.get("article_id")
            ).hex[:16]
            # centroid: average of vectors for members with embeddings
            vecs = []
            for a in articles:
                v = get_embedding_vector(conn, a.get("content_hash"))
                if v:
                    vecs.append(v)
            centroid = None
            if vecs:
                dims = len(vecs[0])
                centroid = [sum(v[i] for v in vecs) / len(vecs) for i in range(dims)]
            put_cluster(
                conn,
                cluster_id,
                method="minhash-lsh",
                centroid_embed=centroid,
                representative_article_id=rep["article_id"],
            )
            put_cluster_members(conn, cluster_id, members)
            saved.append(
                {
                    "cluster_id": cluster_id,
                    "members": members,
                    "representative_article_id": rep["article_id"],
                }
            )
    if logger:
        logger.info("Created %d clusters", len(saved))
    return saved
