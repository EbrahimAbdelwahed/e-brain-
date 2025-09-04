from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from gepa import optimize

from e_brain.config import get_settings
from e_brain.generation.generator import SYSTEM_PROMPT
from e_brain.optimization.gepa_adapter import EBrainGEPAAdapter
from e_brain.util.logging import get_logger


logger = get_logger(__name__)


def _load_queries(path: Path | None) -> list[str]:
    if path and path.exists():
        return [s.strip() for s in path.read_text(encoding="utf-8").splitlines() if s.strip() and not s.startswith("#")]
    # Fallback starter set (neuroscience-centric)
    return [
        "What does synaptic pruning do in adolescence?",
        "Explain neuroplasticity in adult brains with an example.",
        "How do glial cells support neurons?",
        "What's the blood-brain barrier and why it matters?",
        "What are place cells in the hippocampus?",
        "How does myelin affect signal speed?",
        "What is predictive coding in the brain?",
        "How do fMRI and EEG differ in what they measure?",
        "What is long-term potentiation (LTP)?",
        "How does sleep impact memory consolidation?",
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Optimize the system prompt for post generation using GEPA")
    ap.add_argument("--queries-file", type=Path, default=None, help="Text file with one query per line")
    ap.add_argument("--max-metric-calls", type=int, default=40, help="Budget for evaluation calls")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("pipeline/out/system_prompt.optimized.txt"))
    args = ap.parse_args()

    s = get_settings()
    queries = _load_queries(args.queries_file)
    trainset = [{"query": q} for q in queries]

    adapter = EBrainGEPAAdapter(model=s.chat_model)

    seed_cand = {"system": SYSTEM_PROMPT}
    logger.info("gepa_optimize_start", extra={"n_queries": len(queries), "budget": args.max_metric_calls, "model": s.chat_model})

    result = optimize(
        seed_candidate=seed_cand,
        trainset=trainset,
        adapter=adapter,
        task_lm=s.chat_model,
        reflection_lm=s.chat_model,
        max_metric_calls=args.max_metric_calls,
        display_progress_bar=True,
        seed=args.seed,
    )

    best = result.best_candidate
    optimized_system = best.get("system") or SYSTEM_PROMPT

    out_path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(optimized_system, encoding="utf-8")
    logger.info("gepa_optimize_done", extra={"out": str(out_path), "score": result.val_aggregate_scores[result.best_idx]})
    print("\nOptimized system prompt saved to:", out_path)


if __name__ == "__main__":
    main()

