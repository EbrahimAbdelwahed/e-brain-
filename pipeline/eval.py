from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .io import db, fetch_clusters


def _safe_filename(name: str) -> str:
    # Replace characters that are problematic for filenames on Windows/Unix
    safe = (
        name.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "-")
        .replace("*", "_")
        .replace("?", "_")
        .replace("\"", "'")
        .replace("<", "(")
        .replace(">", ")")
        .replace("|", "-")
        .strip()
    )
    return safe or "model"


def evaluate_models(
    *,
    out_dir: Path,
    models: list[str],
    seed: int | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Run non-persisting summarization across multiple models and write artifacts.

    Artifacts:
      - out_dir/eval/<model>.md (per model)
      - out_dir/eval/compare.md (per-cluster comparison across models)
      - out_dir/eval_report.json (models, counts, durations, determinism params)
    """
    if not models:
        raise ValueError("No models provided for evaluation")

    eval_dir = Path(out_dir) / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Determinism parameters from env (with defaults), seed may be set via CLI
    temperature = float(os.getenv("SUMMARIZE_TEMPERATURE", "0.2"))
    top_p = float(os.getenv("SUMMARIZE_TOP_P", "0.9"))

    # Persist and restore env seed to respect summarize's internal resolution
    old_seed_env = os.getenv("SUMMARIZE_SEED")
    try:
        if seed is not None:
            os.environ["SUMMARIZE_SEED"] = str(int(seed))

        # How many clusters we have (for reporting)
        with db() as conn:
            clusters = fetch_clusters(conn)
        cluster_count = len(clusters)

        per_model_results: dict[str, list[dict[str, Any]]] = {}
        durations: dict[str, float] = {}
        errors: dict[str, str] = {}

        # Evaluate each model without persisting to DB
        # Import summarize at call-time to respect any active monkeypatching in tests
        from . import summarize as summarize_mod  # local import
        for m in models:
            t0 = time.time()
            try:
                res = summarize_mod.summarize(logger=logger, use_llm=True, model=m, persist=False)
                per_model_results[m] = res
            except Exception as e:  # noqa: BLE001
                # Surface error but continue with other models
                per_model_results[m] = []
                errors[m] = str(e)
                if logger:
                    logger.warning("Eval failed for model %s: %s", m, e)
            durations[m] = time.time() - t0

        # Write per-model markdown files
        for m, res in per_model_results.items():
            lines: list[str] = [f"# Model {m} summaries\n"]
            for r in res:
                cid = r.get("cluster_id")
                lines.append(f"\n## Cluster {cid}")
                for b in (r.get("bullets") or []):
                    lines.append(f"- {b}")
            (eval_dir / f"{_safe_filename(m)}.md").write_text("\n".join(lines), encoding="utf-8")

        # Build compare.md grouped by cluster with per-model sections
        # First, compute the union of cluster_ids across all models
        all_cluster_ids: list[str] = []
        seen: set[str] = set()
        for res in per_model_results.values():
            for r in res:
                cid = r.get("cluster_id")
                if isinstance(cid, str) and cid not in seen:
                    seen.add(cid)
                    all_cluster_ids.append(cid)

        comp_lines: list[str] = ["# Model comparison\n"]
        for cid in all_cluster_ids:
            comp_lines.append(f"\n## Cluster {cid}")
            for m in models:
                comp_lines.append(f"\n### {m}")
                # find this cluster in this model's results
                found = next((r for r in per_model_results.get(m, []) if r.get("cluster_id") == cid), None)
                if not found:
                    comp_lines.append("- (no output)")
                    continue
                for b in (found.get("bullets") or []):
                    comp_lines.append(f"- {b}")
        (eval_dir / "compare.md").write_text("\n".join(comp_lines), encoding="utf-8")

        # Write eval report
        report = {
            "models": models,
            "counts": {"clusters": cluster_count},
            "durations": durations,
            "params": {"temperature": temperature, "top_p": top_p, "seed": seed},
            "errors": errors,
        }
        (Path(out_dir) / "eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if logger:
            logger.info(
                "Eval models done: %d clusters across %d models -> %s",
                cluster_count,
                len(models),
                eval_dir,
            )
        return report
    finally:
        if seed is not None:
            if old_seed_env is None:
                os.environ.pop("SUMMARIZE_SEED", None)
            else:
                os.environ["SUMMARIZE_SEED"] = old_seed_env
