from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging


@dataclass
class RunContext:
    out_dir: Path
    logger: logging.Logger

