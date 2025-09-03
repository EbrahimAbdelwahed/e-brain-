import os

from pipeline.io import Article, db, init_db, upsert_article
from pipeline.config import DB_PATH
from pipeline.cluster import cluster as do_cluster


def test_similar_texts_cluster_together(tmp_path):
    os.environ["EMBED_OFFLINE"] = "1"
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    # Near-duplicates with only punctuation difference; identical 5-gram shingles
    text1 = "Neural network achieves new accuracy on benchmark using simple method."
    text2 = "Neural network achieves new accuracy on benchmark using simple method!"
    text3 = "Mice study reveals new circuit in hippocampus."
    a1 = Article(
        article_id="a1",
        canonical_url="https://example.com/a1",
        title="NN hits new accuracy",
        byline=None,
        published_at="2025-09-01T00:00:00Z",
        source_id="mit-techreview-ai",
        is_preprint=0,
        text=text1,
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h1",
    )
    a2 = Article(
        article_id="a2",
        canonical_url="https://example.com/a2",
        title="Simple method boosts NN accuracy",
        byline=None,
        published_at="2025-09-01T01:00:00Z",
        source_id="mit-techreview-ai",
        is_preprint=0,
        text=text2,
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h2",
    )
    a3 = Article(
        article_id="a3",
        canonical_url="https://example.com/a3",
        title="Hippocampus circuit study",
        byline=None,
        published_at="2025-09-01T02:00:00Z",
        source_id="nature-neuroscience",
        is_preprint=0,
        text=text3,
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h3",
    )
    with db() as conn:
        upsert_article(conn, a1)
        upsert_article(conn, a2)
        upsert_article(conn, a3)
    clusters = do_cluster()
    sizes = sorted(len(c["members"]) for c in clusters)
    assert sizes == [1, 2]


def test_dissimilar_texts_do_not_cluster_and_deterministic(tmp_path):
    os.environ["EMBED_OFFLINE"] = "1"
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    # Two different stories should not co-cluster at default 0.85
    text1 = "Study shows dopamine neurons encode reward prediction error."
    text2 = "OpenAI releases new embedding model improving performance on MTEB tasks."
    a1 = Article(
        article_id="b1",
        canonical_url="https://example.com/b1",
        title="Dopamine neurons and RPE",
        byline=None,
        published_at="2025-09-01T00:00:00Z",
        source_id="nature",
        is_preprint=0,
        text=text1,
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="bh1",
    )
    a2 = Article(
        article_id="b2",
        canonical_url="https://example.com/b2",
        title="New embedding model",
        byline=None,
        published_at="2025-09-01T01:00:00Z",
        source_id="openai",
        is_preprint=0,
        text=text2,
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="bh2",
    )
    with db() as conn:
        upsert_article(conn, a1)
        upsert_article(conn, a2)
    clusters1 = do_cluster()
    clusters2 = do_cluster()
    # Both runs produce the same memberships and sizes
    def shape(cs):
        return sorted(sorted(c["members"]) for c in cs)
    assert shape(clusters1) == shape(clusters2)
    assert all(len(c["members"]) == 1 for c in clusters1)
