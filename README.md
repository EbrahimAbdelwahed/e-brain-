Eâ€‘Brain Bot: Neuroscience/AI News Pipeline

This is a minimal, endâ€‘toâ€‘end terminal pipeline that ingests neuroscience/AI news from RSS, extracts articles, clusters nearâ€‘duplicates, computes embeddings with OpenAI text-embedding-3-small, summarizes clusters with citations in an evidence-first watchdog tone, and publishes ranked outputs to a timestamped folder. No web UI.

Quickstart

- Prereqs: Python 3.11+, `pip` or `uv`, and an OpenAI API key.
- Create venv and install:
  - Using uv: `uv venv && uv pip install -e .`
  - Using pip: `python -m venv .venv && .\.venv\Scripts\activate && pip install -e .`
- Copy `.env.example` to `.env` and set `OPENAI_API_KEY`.
- Run: `python -m pipeline all --out ./pipeline_runs --since 2025-09-01T00:00:00Z`

Notes

- Output folder is timestamped in ISO 8601 UTC with `:` replaced by `-` for Windows compatibility (e.g., `2025-09-01T00-00-00Z`).
- The pipeline respects robots and uses throttled requests (2 req/s per host), timeouts, retries, and HTTP caching via ETag/Last-Modified.
- Idempotent: re-running will not re-embed identical content (embedding cache by content hash in SQLite).
- Offline/development: if `OPENAI_API_KEY` is not set or `EMBED_OFFLINE=1`, embeddings fall back to a deterministic local stub so tests pass without network.

CLI

- Commands: `fetch`, `extract`, `cluster`, `summarize`, `publish`, `all`
- Flags: `--out`, `--since`, `--max-items`, `--dry-run`, `--log-level`, `--parallel`
- Cluster flags: `--jaccard-threshold` (default 0.85), `--num-perm` (default 128)
- Example: `python -m pipeline all --out ./pipeline_runs --since 2025-09-01T00:00:00Z --parallel 8`

Outputs (under the run folder)

- `summaries.md`: ranked clusters with bullets and citations
- `clusters.json`: full objects
- `run_report.json`: counts, durations, failures, rate-limit stats
- `logs/run.log`: pipeline logs

Summaries Persistence

- Summaries are persisted in SQLite table `summaries` with columns: `cluster_id` (PK), `tl_dr`, `bullets_json`, `citations_json`, `score`, `created_at`, `published_at`, `version_hash`.
- Summarization computes a deterministic `version_hash = sha256(PROMPT_VERSION + GUARDRAILS_VERSION + sorted(article_ids) + joined_extracted_facts)` and upserts one row per cluster. Re-running with unchanged inputs is idempotent (no updates).
- Publish reads persisted summaries from the DB (no recomputation) and writes `summaries.md` and `clusters.json` with unchanged shapes; ranking/ordering uses `rank.score_clusters()`.

Environment (.env)

- `OPENAI_API_KEY=...` (required for real embeddings)
- Optional: `EMBED_OFFLINE=1` to force offline embedding stub

Runbook

1) `python -m pipeline fetch --since <ISO8601>`: fetch RSS into SQLite with ETag caching.
2) `python -m pipeline extract`: extract canonical URLs and article text via trafilatura.
3) `python -m pipeline cluster`: cluster near-duplicates via MinHash/LSH over 5-gram shingles (default Jaccard 0.85); compute centroids.
4) `python -m pipeline summarize`: produce map/reduce summaries with watchdog tone.
5) `python -m pipeline publish --out ./pipeline_runs`: write summaries and artifacts.
6) `python -m pipeline all` runs the above in sequence.

Testing

- `pytest -q`

TODOs (next iteration)

- Optional publishing to social platforms (X), and light web UI.
- Additional sources and smarter summarization heuristics.


Environment (.env) additions

- Optional (DB): DATABASE_URL=postgresql://... (Neon with pgvector)
- Optional (Observability): LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

