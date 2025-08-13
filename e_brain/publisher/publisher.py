from __future__ import annotations

import json
import time
from typing import Optional

import http.client

from ..config import get_settings
from ..db import mark_posted, select_pending_posts
from ..util.logging import get_logger
from ..scheduler.windows import within_post_window


logger = get_logger(__name__)


def _post_to_x(text: str) -> bool:
    s = get_settings()
    if s.dry_run:
        logger.info("dry_run_post", extra={"text": text})
        return True

    # This is a placeholder using OAuth 2.0 Bearer if available; real posting typically needs user-context tokens.
    # For actual posting we would need to sign requests with OAuth 1.0a or use OAuth2 user-context.
    if not (s.x_api_key and s.x_api_secret and s.x_access_token and s.x_access_token_secret):
        logger.error("x_user_context_missing")
        return False

    # Placeholder: without third-party OAuth lib, we cannot sign; so we log and return False.
    logger.error("x_posting_not_implemented_oauth_signature")
    return False


def publish_pending(limit: int = 3, tz: str = "US/Eastern") -> int:
    if not within_post_window(tz):
        logger.info("outside_post_window", extra={"tz": tz})
        return 0
    posts = select_pending_posts(limit=limit)
    posted = 0
    for p in posts:
        ok = _post_to_x(p["text"])
        if ok:
            mark_posted(p["id"])
            posted += 1
            time.sleep(2)
    logger.info("publish_done", extra={"count": posted})
    return posted

