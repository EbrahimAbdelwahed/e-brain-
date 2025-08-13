from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from ..config import get_settings


def _parse_windows(s: str) -> list[tuple[time, time]]:
    windows: list[tuple[time, time]] = []
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        start_s, end_s = part.split('-')
        sh, sm = [int(x) for x in start_s.split(':')]
        eh, em = [int(x) for x in end_s.split(':')]
        windows.append((time(sh, sm), time(eh, em)))
    return windows


def within_post_window(tz: str = "US/Eastern") -> bool:
    s = get_settings()
    now = datetime.now(ZoneInfo(tz))
    windows_s = s.post_windows_us if tz in ("US/Eastern", "US/Central", "US/Pacific") else s.post_windows_eu
    for start, end in _parse_windows(windows_s):
        if start <= now.time() <= end:
            return True
    return False

