from __future__ import annotations

import argparse

from .config import get_settings
from .db import init_db, create_vector_index
from .curation.x_client import ingest_from_accounts
from .embedding.embedding import embed_new_items
from .generation.generator import generate_and_store
from .publisher.publisher import publish_pending
from .util.logging import get_logger


logger = get_logger(__name__)


def cmd_init_db(args: argparse.Namespace) -> None:
    init_db()
    logger.info("init_db_done")


def cmd_ingest_x(args: argparse.Namespace) -> None:
    count = ingest_from_accounts(accounts_md_path=args.accounts, max_per_account=args.max)
    logger.info("ingested", extra={"count": count})


def cmd_embed(args: argparse.Namespace) -> None:
    count = embed_new_items(batch_size=args.batch)
    logger.info("embedded", extra={"count": count})


def cmd_generate(args: argparse.Namespace) -> None:
    post_id = generate_and_store(args.theme, max_sources=args.max_sources)
    logger.info("generated", extra={"post_id": post_id})


def cmd_publish(args: argparse.Namespace) -> None:
    count = publish_pending(limit=args.limit, tz=args.tz)
    logger.info("published", extra={"count": count})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="e_brain")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-db", help="Create tables and extensions")
    s.set_defaults(func=cmd_init_db)

    s = sub.add_parser("ingest-x", help="Ingest recent posts from accounts-to-follow.md")
    s.add_argument("--accounts", default="accounts-to-follow.md")
    s.add_argument("--max", type=int, default=5)
    s.set_defaults(func=cmd_ingest_x)

    s = sub.add_parser("embed", help="Embed unembedded items")
    s.add_argument("--batch", type=int, default=64)
    s.set_defaults(func=cmd_embed)

    s = sub.add_parser("generate", help="Generate a candidate post from a theme/query")
    s.add_argument("--theme", default="neuroscience general facts")
    s.add_argument("--max-sources", type=int, default=5)
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("publish", help="Publish pending posts if within time window")
    s.add_argument("--limit", type=int, default=3)
    s.add_argument("--tz", default="US/Eastern")
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("ingest-rss", help="Ingest recent articles from curated RSS feeds")
    s.add_argument("--feeds-file", default=None, help="Optional path to a newline-delimited list of feed URLs")
    s.add_argument("--max", type=int, default=20, help="Max entries per feed")
    s.add_argument(
        "--interval-mins",
        type=int,
        default=60,
        help="Update interval hint (stored in source meta; does not enforce scheduling)",
    )
    s.add_argument(
        "--filter",
        default=None,
        help="Regex to include items (default targets neuro/brain/AI terms)",
    )
    def _cmd_ingest_rss(args: argparse.Namespace) -> None:
        # Lazy import to avoid requiring RSS deps unless used
        from .curation.rss_client import ingest_rss
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
        logger.info("rss_ingested", extra={"count": count})
    s.set_defaults(func=_cmd_ingest_rss)

    s = sub.add_parser("create-index", help="Create vector index on embeddings (hnsw/ivfflat)")
    s.add_argument("--type", choices=["hnsw", "ivfflat"], default="hnsw")
    def _cmd_create_index(args: argparse.Namespace) -> None:
        create_vector_index(args.type)
        logger.info("index_created", extra={"type": args.type})
    s.set_defaults(func=_cmd_create_index)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
