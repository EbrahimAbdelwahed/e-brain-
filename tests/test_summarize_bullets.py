import os

from pipeline.io import Article, db, init_db, upsert_article
from pipeline.cluster import cluster as do_cluster
from pipeline.summarize import summarize
from pipeline.config import DB_PATH


def test_summarize_includes_map_bullets(tmp_path):
    os.environ["EMBED_OFFLINE"] = "1"
    # Ensure clean database
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    text1 = "Neural network achieves new accuracy on benchmark using simple method."
    text2 = "A simple method lets a neural network hit new accuracy on the benchmark."

    a1 = Article(
        article_id="s1",
        canonical_url="https://example.com/shared",
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
        article_id="s2",
        canonical_url="https://example.com/shared",
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
    with db() as conn:
        upsert_article(conn, a1)
        upsert_article(conn, a2)

    do_cluster(threshold=10)

    summaries = summarize()
    summary = next(r for r in summaries if r["delta"]["articles"] == 2)
    bullets = summary["bullets"]

    assert bullets[0].startswith("What changed:")
    bottom_idx = next(i for i, b in enumerate(bullets) if b.startswith("Bottom line:"))
    claim_idxs = [i for i, b in enumerate(bullets) if b.startswith("Claim/result:")]
    method_count = sum(1 for b in bullets if b.startswith("Method/limit:"))

    assert bottom_idx < claim_idxs[0]
    assert len(claim_idxs) == 2
    assert method_count == 2

    # Clean up
    if DB_PATH.exists():
        DB_PATH.unlink()
