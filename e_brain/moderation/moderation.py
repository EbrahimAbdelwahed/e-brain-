from __future__ import annotations

from pathlib import Path
from typing import Tuple


MAX_TWEET_LENGTH = 280
BLOCKLIST_PATH = Path(__file__).parent / "blocklist.txt"


def _load_blocklist() -> set[str]:
    words: set[str] = set()
    if BLOCKLIST_PATH.exists():
        for line in BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                words.add(s.lower())
    return words


_BLOCKLIST = _load_blocklist()


def moderate_text(text: str) -> Tuple[bool, str | None]:
    # Length check (single post default)
    if len(text) > MAX_TWEET_LENGTH:
        return False, "too_long"
    # Blocklist
    tl = text.lower()
    for word in _BLOCKLIST:
        if word in tl:
            return False, f"blocked:{word}"
    # Simple unverifiable claim heuristic
    risky = ["cure", "guarantee", "proves", "always", "never"]
    if any(w in tl for w in risky):
        return False, "unverifiable_claim"
    return True, None

