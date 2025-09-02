from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # noqa: BLE001
    def load_dotenv() -> None:  # type: ignore
        return None


load_dotenv()


# Paths
ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
DB_PATH = STATE_DIR / "pipeline.sqlite"
DEFAULT_OUT_DIR = ROOT / "pipeline_runs"


# Networking / performance
DEFAULT_RPS_PER_HOST = float(os.getenv("RPS_PER_HOST", "2.0"))  # 2 req/s per host
CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "10.0"))
READ_TIMEOUT = float(os.getenv("READ_TIMEOUT", "20.0"))
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL", "6"))


# Embeddings
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
EMBED_DIMS = int(os.getenv("EMBED_DIMS", "1536"))
EMBED_OFFLINE = os.getenv("EMBED_OFFLINE", "0") == "1"


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)


def iso8601_now_for_path() -> str:
    # Use ISO8601 UTC and replace ':' with '-' for Windows-safe folder names
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return now


def make_run_dir(base: os.PathLike | str | None = None) -> pathlib.Path:
    base_path = pathlib.Path(base) if base else DEFAULT_OUT_DIR
    run_dir = base_path / iso8601_now_for_path()
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    return run_dir


def parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    # Expect Zulu format 2025-09-01T00:00:00Z
    try:
        if since.endswith("Z"):
            return datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        # Allow dash-separated time for Windows copy/paste
        return datetime.strptime(since, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=timezone.utc)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid --since value: {since}") from e


@dataclass
class CLISettings:
    out_dir: pathlib.Path
    since: datetime | None
    max_items: int | None
    dry_run: bool
    log_level: str
    parallel: int
