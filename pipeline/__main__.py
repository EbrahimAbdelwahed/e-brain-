from __future__ import annotations

import argparse
from typing import Optional

from e_brain.util.logging import get_logger


logger = get_logger(__name__)


def _cmd_init_db(args: argparse.Namespace) -> None:
    from e_brain.db import init_db

    init_db()
    logger.info("init_db_done")


def _cmd_fetch(args: argparse.Namespace) -> None:
    from e_brain.curation.rss_client import ingest_rss

    feeds = None
    if args.feeds_file:
        try:
            with open(args.feeds_file, "r", encoding="utf-8") as f:
                feeds = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
        except FileNotFoundError:
            logger.error("feeds_file_missing", extra={"path": args.feeds_file})
    count = ingest_rss(
        feeds=feeds,
        max_entries_per_feed=args.max,
        update_interval_minutes=args.interval_mins,
        include_filter=args.filter,
    )
    logger.info("fetch_done", extra={"count": count})


def _cmd_embed(args: argparse.Namespace) -> None:
    from e_brain.embedding.embedding import embed_new_items

    count = embed_new_items(batch_size=args.batch)
    logger.info("embed_done", extra={"count": count})


def _cmd_summarize(args: argparse.Namespace) -> None:
    from e_brain.generation.generator import generate_and_store

    post_id = generate_and_store(args.theme, max_sources=args.max_sources)
    logger.info("summarize_done", extra={"post_id": post_id})


def _cmd_publish(args: argparse.Namespace) -> None:
    from e_brain.publisher.publisher import publish_pending

    count = publish_pending(limit=args.limit, tz=args.tz)
    logger.info("publish_done", extra={"count": count})


def _cmd_all(args: argparse.Namespace) -> None:
    # Initialize DB (idempotent)
    _cmd_init_db(args)

    # Fetch (RSS)
    _cmd_fetch(args)

    # Embed
    _cmd_embed(args)

    # Summarize (generate one candidate post from theme)
    _cmd_summarize(args)

    # Publish (respects DRY_RUN and posting window)
    _cmd_publish(args)


def _cmd_extract(args: argparse.Namespace) -> None:
    # Not a separate stage in current implementation (handled during fetch)
    logger.info("extract_nop", extra={"note": "extraction occurs during fetch"})


def _cmd_cluster(args: argparse.Namespace) -> None:
    # Not implemented in current codebase
    logger.info("cluster_nop", extra={"note": "clustering not implemented in this MVP"})


def _cmd_eval_models(args: argparse.Namespace) -> None:
    logger.info(
        "eval_models_nop",
        extra={"note": "model evaluation harness not implemented in this codebase"},
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline", description="Compatibility wrapper for e_brain pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-db", help="Create tables and extensions")
    s.set_defaults(func=_cmd_init_db)

    s = sub.add_parser("fetch", help="Fetch and extract items from curated RSS feeds")
    s.add_argument("--feeds-file", default=None, help="Optional path to a newline-delimited list of feed URLs")
    s.add_argument("--max", type=int, default=20, help="Max entries per feed")
    s.add_argument("--interval-mins", type=int, default=60, help="Update interval hint (informational)")
    s.add_argument("--filter", default=None, help="Regex to include items (defaults to neuro/AI terms)")
    s.set_defaults(func=_cmd_fetch)

    s = sub.add_parser("extract", help="No-op (extraction handled during fetch)")
    s.set_defaults(func=_cmd_extract)

    s = sub.add_parser("cluster", help="No-op clustering (not implemented in this MVP)")
    s.set_defaults(func=_cmd_cluster)

    s = sub.add_parser("embed", help="Embed unembedded items")
    s.add_argument("--batch", type=int, default=64)
    s.set_defaults(func=_cmd_embed)

    s = sub.add_parser("summarize", help="Generate a candidate post from a theme/query")
    s.add_argument("--theme", default="neuroscience general facts")
    s.add_argument("--max-sources", type=int, default=5)
    s.set_defaults(func=_cmd_summarize)

    s = sub.add_parser("publish", help="Publish pending posts if within time window")
    s.add_argument("--limit", type=int, default=3)
    s.add_argument("--tz", default="US/Eastern")
    s.set_defaults(func=_cmd_publish)

    s = sub.add_parser("eval-models", help="No-op (not implemented in this codebase)")
    s.set_defaults(func=_cmd_eval_models)

    # Discovery scaffold
    def _cmd_discover(args: argparse.Namespace) -> None:
        from e_brain.curation.discovery.runner import run_discovery

        res = run_discovery(
            window_days=args.window_days,
            out_dir=args.out,
            ipfs_fetch=args.ipfs_fetch,
            store_to_db=args.store_to_db,
        )
        logger.info("discover_done", extra=res)

    def _str2bool(v: str) -> bool:
        if isinstance(v, bool):
            return v
        val = str(v).strip().lower()
        if val in ("yes", "true", "t", "1", "y"):  # enable
            return True
        if val in ("no", "false", "f", "0", "n"):  # disable
            return False
        raise argparse.ArgumentTypeError("Boolean value expected.")

    s = sub.add_parser("discover", help="Run DOI discovery scaffold and emit artifacts")
    s.add_argument("--window-days", type=int, default=60)
    s.add_argument("--out", default="artifacts")
    s.add_argument("--ipfs-fetch", nargs='?', const=True, default=False, type=_str2bool)
    s.add_argument("--store-to-db", nargs='?', const=True, default=True, type=_str2bool)
    s.set_defaults(func=_cmd_discover)

    s = sub.add_parser("all", help="Run fetch -> embed -> summarize -> publish")
    s.add_argument("--feeds-file", default=None)
    s.add_argument("--max", type=int, default=20)
    s.add_argument("--interval-mins", type=int, default=60)
    s.add_argument("--filter", default=None)
    s.add_argument("--batch", type=int, default=64)
    s.add_argument("--theme", default="neuroscience general facts")
    s.add_argument("--max-sources", type=int, default=5)
    s.add_argument("--limit", type=int, default=3)
    s.add_argument("--tz", default="US/Eastern")
    s.set_defaults(func=_cmd_all)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
