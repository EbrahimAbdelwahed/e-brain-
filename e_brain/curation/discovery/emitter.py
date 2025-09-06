from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Iterable, Dict, Any, Tuple


def _weekly_artifact_path(out_dir: str) -> Path:
    now = dt.datetime.utcnow().date()
    iso_year, iso_week, _ = now.isocalendar()
    fn = f"discovery_results_{iso_year}-{iso_week:02d}.ndjson"
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / fn


def write_ndjson(records: Iterable[Dict[str, Any]], out_dir: str) -> Tuple[str, int]:
    path = _weekly_artifact_path(out_dir)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
    return str(path), count


def write_metrics(metrics: Dict[str, Any], out_dir: str) -> str:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    path = p / "metrics.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    return str(path)

