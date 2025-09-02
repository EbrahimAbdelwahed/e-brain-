from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer

from .cluster import cluster as cluster_step
from .config import CLISettings, make_run_dir, parse_since
from .ingest import fetch_feeds
from .logging import setup_logging
from .io import init_db
from .rank import score_clusters
from .summarize import summarize
from .extract import extract as extract_step


app = typer.Typer(add_completion=False, no_args_is_help=True)


def _common_settings(
    out: Optional[Path] = typer.Option(None, help="Output base directory"),
    since: Optional[str] = typer.Option(None, help="ISO8601 UTC, e.g., 2025-09-01T00:00:00Z"),
    max_items: Optional[int] = typer.Option(None, help="Max items per feed"),
    dry_run: bool = typer.Option(False, help="Do not write outputs"),
    log_level: str = typer.Option("INFO", help="Log level"),
    parallel: int = typer.Option(6, help="Parallel workers"),
) -> CLISettings:
    run_dir = make_run_dir(out)
    logger = setup_logging(run_dir, log_level)
    logger.info("Run directory: %s", run_dir)
    return CLISettings(out_dir=run_dir, since=parse_since(since), max_items=max_items, dry_run=dry_run, log_level=log_level, parallel=parallel)


@app.command()
def fetch(
    out: Optional[Path] = typer.Option(None),
    since: Optional[str] = typer.Option(None),
    max_items: Optional[int] = typer.Option(None),
    dry_run: bool = typer.Option(False),
    log_level: str = typer.Option("INFO"),
    parallel: int = typer.Option(6),
):
    """Fetch RSS feeds with ETag/Last-Modified caching into SQLite."""
    settings = _common_settings(out, since, max_items, dry_run, log_level, parallel)
    logger = setup_logging(settings.out_dir, settings.log_level)
    init_db()
    t0 = time.time()
    totals = fetch_feeds(since=settings.since, max_items=settings.max_items, logger=logger)
    dt = time.time() - t0
    logger.info("Fetch done in %.2fs: %s", dt, totals)


@app.command()
def extract(
    out: Optional[Path] = typer.Option(None),
    since: Optional[str] = typer.Option(None),
    max_items: Optional[int] = typer.Option(None),
    dry_run: bool = typer.Option(False),
    log_level: str = typer.Option("INFO"),
    parallel: int = typer.Option(6),
):
    """Extract article text and canonical URLs via trafilatura."""
    settings = _common_settings(out, since, max_items, dry_run, log_level, parallel)
    logger = setup_logging(settings.out_dir, settings.log_level)
    init_db()
    t0 = time.time()
    n = extract_step(limit=settings.max_items, parallel=settings.parallel, logger=logger)
    dt = time.time() - t0
    logger.info("Extract done in %.2fs: %d articles", dt, n)


@app.command()
def cluster(
    out: Optional[Path] = typer.Option(None),
    since: Optional[str] = typer.Option(None),
    max_items: Optional[int] = typer.Option(None),
    dry_run: bool = typer.Option(False),
    log_level: str = typer.Option("INFO"),
    parallel: int = typer.Option(6),
    threshold: int = typer.Option(8, help="Hamming distance threshold for simhash"),
):
    """Cluster near-duplicate articles via SimHash."""
    settings = _common_settings(out, since, max_items, dry_run, log_level, parallel)
    logger = setup_logging(settings.out_dir, settings.log_level)
    init_db()
    t0 = time.time()
    cs = cluster_step(threshold=threshold, logger=logger)
    dt = time.time() - t0
    logger.info("Cluster done in %.2fs: %d clusters", dt, len(cs))


@app.command()
def summarize_cmd(
    out: Optional[Path] = typer.Option(None),
    since: Optional[str] = typer.Option(None),
    max_items: Optional[int] = typer.Option(None),
    dry_run: bool = typer.Option(False),
    log_level: str = typer.Option("INFO"),
    parallel: int = typer.Option(6),
):
    """Summarize clusters with citations and watchdog tone."""
    settings = _common_settings(out, since, max_items, dry_run, log_level, parallel)
    logger = setup_logging(settings.out_dir, settings.log_level)
    init_db()
    t0 = time.time()
    _ = summarize(logger=logger)
    dt = time.time() - t0
    logger.info("Summarize done in %.2fs", dt)


@app.command()
def publish(
    out: Optional[Path] = typer.Option(None),
    since: Optional[str] = typer.Option(None),
    max_items: Optional[int] = typer.Option(None),
    dry_run: bool = typer.Option(False),
    log_level: str = typer.Option("INFO"),
    parallel: int = typer.Option(6),
):
    """Publish ranked summaries and artifacts to the run folder."""
    settings = _common_settings(out, since, max_items, dry_run, log_level, parallel)
    logger = setup_logging(settings.out_dir, settings.log_level)
    init_db()
    t0 = time.time()
    summaries = summarize(logger=logger)
    scores = score_clusters()
    score_map = {s["cluster_id"]: s for s in scores}
    # Order summaries by score
    summaries_sorted = sorted(summaries, key=lambda x: score_map.get(x["cluster_id"], {}).get("score", 0.0), reverse=True)

    # Write clusters.json (summaries with scores)
    clusters_json = settings.out_dir / "clusters.json"
    data = []
    for s in summaries_sorted:
        sc = score_map.get(s["cluster_id"], {"score": 0.0, "size": 0})
        row = dict(s)
        row.update(sc)
        data.append(row)
    if not settings.dry_run:
        clusters_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Write summaries.md
    md_lines = ["# E‑Brain Bot Summaries\n"]
    for s in summaries_sorted:
        sc = score_map.get(s["cluster_id"], {"score": 0.0, "size": 0})
        md_lines.append(f"\n## Cluster {s['cluster_id']} — score {sc['score']:.3f}, size {sc['size']}")
        for b in s["bullets"]:
            md_lines.append(f"- {b}")
        md_lines.append("\nCitations:")
        for c in s["citations"]:
            md_lines.append(f"- [{c['title']}]({c['url']}) — {c['outlet']} — {c['date']}")
    if not settings.dry_run:
        (settings.out_dir / "summaries.md").write_text("\n".join(md_lines), encoding="utf-8")

    # Run report
    report = {
        "counts": {"clusters": len(summaries_sorted)},
        "durations": {"total_sec": time.time() - t0},
        "failures": [],
        "rate_limit": {"per_host_rps": 2.0},
    }
    if not settings.dry_run:
        (settings.out_dir / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Publish done in %.2fs -> %s", time.time() - t0, settings.out_dir)


@app.command("all")
def run_all(
    out: Optional[Path] = typer.Option(None),
    since: Optional[str] = typer.Option(None),
    max_items: Optional[int] = typer.Option(None),
    dry_run: bool = typer.Option(False),
    log_level: str = typer.Option("INFO"),
    parallel: int = typer.Option(6),
):
    """Run fetch → extract → cluster → summarize → publish."""
    settings = _common_settings(out, since, max_items, dry_run, log_level, parallel)
    logger = setup_logging(settings.out_dir, settings.log_level)
    init_db()
    t0 = time.time()
    fetch_feeds(since=settings.since, max_items=settings.max_items, logger=logger)
    extract_step(limit=settings.max_items, parallel=settings.parallel, logger=logger)
    cluster_step(logger=logger)
    publish(out=settings.out_dir, since=since, max_items=max_items, dry_run=dry_run, log_level=log_level, parallel=parallel)
    logger.info("All done in %.2fs", time.time() - t0)


if __name__ == "__main__":
    app()

