from __future__ import annotations

import argparse

from .config import get_settings
from .db import init_db
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

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

