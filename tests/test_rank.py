import os
from datetime import datetime, timedelta, timezone

from pipeline.io import (
    Article,
    db,
    init_db,
    upsert_article,
    put_cluster,
    put_cluster_members,
    upsert_summary,
)
from pipeline.config import DB_PATH
from pipeline.rank import _freshness_decay, score_clusters
from pipeline.main import publish as publish_from_db


def _iso_utc(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def test_freshness_exponential_half_life_and_monotonicity(monkeypatch):
    monkeypatch.setenv("RANK_HALF_LIFE_HOURS", "24")
    now = datetime.now(timezone.utc)
    # Exactly one half-life old -> ~0.5
    p1 = _iso_utc(now - timedelta(hours=24))
    f1 = _freshness_decay([p1])
    assert 0.45 <= f1 <= 0.55

    # Newer should be higher than older
    p_new = _iso_utc(now - timedelta(hours=1))
    p_old = _iso_utc(now - timedelta(hours=5))
    f_new = _freshness_decay([p_new])
    f_old = _freshness_decay([p_old])
    assert f_new > f_old


def test_heuristics_boosts_affect_ordering(monkeypatch):
    monkeypatch.setenv("RANK_HALF_LIFE_HOURS", "24")
    _reset_db()
    now = datetime.utcnow()

    # Baseline cluster (no special cues, but has method cue to avoid penalty)
    a1 = Article(
        article_id="a1",
        canonical_url="https://example.com/a1",
        title="Study on synaptic plasticity",
        byline=None,
        published_at=_iso_utc(now - timedelta(hours=72)),
        source_id="test-src",
        is_preprint=0,
        text="Methods include randomized assignment.",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h1",
    )
    # Cluster with replication + GitHub cues
    a2 = Article(
        article_id="a2",
        canonical_url="https://example.com/a2",
        title="Replication study releases code on GitHub",
        byline=None,
        published_at=_iso_utc(now - timedelta(hours=72)),
        source_id="test-src",
        is_preprint=0,
        text="This replication shares code at github.com/org/repo; randomized.",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h2",
    )

    with db() as conn:
        upsert_article(conn, a1)
        upsert_article(conn, a2)
        put_cluster(conn, "c1", method="test", centroid_embed=None, representative_article_id="a1")
        put_cluster_members(conn, "c1", ["a1"])
        put_cluster(conn, "c2", method="test", centroid_embed=None, representative_article_id="a2")
        put_cluster_members(conn, "c2", ["a2"])

    scores = score_clusters()
    s_map = {s["cluster_id"]: s["score"] for s in scores}
    assert s_map["c2"] > s_map["c1"]  # replication+github outranks baseline


def test_penalty_for_missing_methods(monkeypatch):
    monkeypatch.setenv("RANK_HALF_LIFE_HOURS", "24")
    _reset_db()
    now = datetime.utcnow()

    a3 = Article(
        article_id="a3",
        canonical_url="https://example.com/a3",
        title="Exploratory analysis",
        byline=None,
        published_at=_iso_utc(now - timedelta(hours=72)),
        source_id="test-src",
        is_preprint=0,
        text="No specific methods mentioned.",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h3",
    )
    a4 = Article(
        article_id="a4",
        canonical_url="https://example.com/a4",
        title="Controlled trial",
        byline=None,
        published_at=_iso_utc(now - timedelta(hours=72)),
        source_id="test-src",
        is_preprint=0,
        text="double-blind, n=120 participants",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h4",
    )

    with db() as conn:
        upsert_article(conn, a3)
        upsert_article(conn, a4)
        put_cluster(conn, "c3", method="test", centroid_embed=None, representative_article_id="a3")
        put_cluster_members(conn, "c3", ["a3"])
        put_cluster(conn, "c4", method="test", centroid_embed=None, representative_article_id="a4")
        put_cluster_members(conn, "c4", ["a4"])

    scores = score_clusters()
    s_map = {s["cluster_id"]: s["score"] for s in scores}
    assert s_map["c4"] >= s_map["c3"] + 0.099  # ~0.1 higher due to method cues


def test_score_clamped_and_present_in_publish(tmp_path, monkeypatch):
    # Ensure clamp: create a cluster with large base & boosts
    monkeypatch.setenv("RANK_HALF_LIFE_HOURS", "24")
    _reset_db()
    now = datetime.utcnow()

    arts = []
    for i in range(5):  # size -> 1.0
        arts.append(
            Article(
                article_id=f"n{i}",
                canonical_url=f"https://example.com/n{i}",
                title="Policy replication with prereg (registered report)",
                byline=None,
                published_at=_iso_utc(now - timedelta(hours=6)),
                source_id="nature-neuroscience",  # weight=3
                is_preprint=0,
                text="random assignment; open data on GitHub; regulator notes",
                lang="en",
                tags=None,
                extraction_quality=0.9,
                content_hash=f"nh{i}",
            )
        )

    with db() as conn:
        for a in arts:
            upsert_article(conn, a)
        put_cluster(conn, "cx", method="test", centroid_embed=None, representative_article_id=arts[0].article_id)
        put_cluster_members(conn, "cx", [a.article_id for a in arts])

    # Provide a persisted summary row so publish can include the cluster
    with db() as conn:
        upsert_summary(
            conn,
            cluster_id="cx",
            tl_dr="Test",
            bullets=["Bottom line: test"],
            citations=[{"title": "T", "url": "https://x", "outlet": "O", "date": "2025-09-01"}],
            version_hash="v1",
            score=None,
        )

    rows = publish_from_db(out_dir=tmp_path, dry_run=True)
    assert any(r.get("cluster_id") == "cx" for r in rows)
    for r in rows:
        assert 0.0 <= r.get("score", 0.0) <= 1.0
