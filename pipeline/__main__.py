from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer

from .cluster import cluster as cluster_step
from .config import CLISettings, make_run_dir, parse_since
from .context import RunContext
from .extract import extract as extract_step
from .ingest import fetch_feeds
from .io import init_db
from .logging import setup_logging
from .rank import score_clusters
from .summarize import summarize
from .main import publish as publish_from_db


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
    return CLISettings(
        out_dir=run_dir,
        since=parse_since(since),
        max_items=max_items,
        dry_run=dry_run,
        log_level=log_level,
        parallel=parallel,
    )


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
    jaccard_threshold: float = typer.Option(0.85, help="Jaccard threshold for MinHash/LSH grouping"),
    num_perm: int = typer.Option(128, help="Number of permutations for MinHash"),
):
    """Cluster near-duplicate articles via MinHash/LSH (5-gram shingles)."""
    settings = _common_settings(out, since, max_items, dry_run, log_level, parallel)
    logger = setup_logging(settings.out_dir, settings.log_level)
    init_db()
    t0 = time.time()
    cs = cluster_step(jaccard_threshold=jaccard_threshold, num_perm=num_perm, logger=logger)
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
    ctx = RunContext(out_dir=settings.out_dir, logger=logger)
    t0 = time.time()
    rows = publish_from_db(ctx.out_dir, dry_run=settings.dry_run, logger=ctx.logger)
    # minimal report (clusters count + duration)
    report = {"counts": {"clusters": len(rows)}, "durations": {"publish_sec": time.time() - t0}}
    if not settings.dry_run:
        (ctx.out_dir / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Publish: %d clusters -> %s", len(rows), ctx.out_dir)


@app.command("all")
def run_all(
    out: Optional[Path] = typer.Option(None),
    since: Optional[str] = typer.Option(None),
    max_items: Optional[int] = typer.Option(None),
    dry_run: bool = typer.Option(False),
    log_level: str = typer.Option("INFO"),
    parallel: int = typer.Option(6),
):
    """Run fetch – extract – cluster – summarize – publish."""
    # One run dir + one logger for the whole run
    run_dir = make_run_dir(out)
    logger = setup_logging(run_dir, log_level)
    logger.info("Run directory: %s", run_dir)
    ctx = RunContext(out_dir=run_dir, logger=logger)
    init_db()
    report_path = ctx.out_dir / "run_report.json"
    report = {"counts": {}, "durations": {}}
    t0 = time.time()

    # Fetch
    t = time.time()
    totals = fetch_feeds(since=parse_since(since), max_items=max_items, logger=ctx.logger)
    report["counts"].update({
        "feeds": totals.get("feeds", 0),
        "raw_entries": totals.get("entries", 0),
        "raw_inserted": totals.get("inserted", 0),
    })
    report["durations"]["fetch_sec"] = time.time() - t
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Fetch: %d feeds, %d new entries", totals.get("feeds", 0), totals.get("inserted", 0))

    # Extract
    t = time.time()
    n_ext = extract_step(limit=max_items, parallel=parallel, logger=ctx.logger)
    report["counts"]["articles_extracted"] = n_ext
    report["durations"]["extract_sec"] = time.time() - t
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Extract: %d articles", n_ext)

    # Cluster
    t = time.time()
    clusters = cluster_step(logger=ctx.logger)
    report["counts"]["clusters"] = len(clusters)
    report["durations"]["cluster_sec"] = time.time() - t
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Cluster: %d clusters", len(clusters))

    # Summarize (persist to DB)
    t = time.time()
    _ = summarize(logger=ctx.logger)
    report["durations"]["summarize_sec"] = time.time() - t
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Summarize: done")

    # Publish from DB (no re-summarize)
    t = time.time()
    _ = publish_from_db(ctx.out_dir, logger=ctx.logger)
    report["durations"]["publish_sec"] = time.time() - t
    total = time.time() - t0
    report["durations"]["total_sec"] = total
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("All done in %.2fs", total)


if __name__ == "__main__":
    app()
