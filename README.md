e-brain: Neuroscience Content Pipeline

Overview
- Terminal-first pipeline that fetches sources, extracts content, clusters near-duplicates, summarizes with an LLM (via OpenRouter), ranks with time-decay and cues, and publishes summaries. Summaries persist in DB; robots compliance is respected during extraction. Observability is available via Langfuse.

Quick Start
- Copy `.env.example` to `.env` and set the variables listed below.
- Ensure PostgreSQL with `pgvector` is available via `DATABASE_URL` (optional).
- Run the pipeline via the Typer CLI described in Runbook.

Environment
- `OPENAI_API_KEY` (optional): for embeddings if used
- `OPENROUTER_API_KEY`: OpenRouter API key
- `OPENROUTER_BASE_URL`: defaults to `https://openrouter.ai/api/v1`
- `SUMMARIZE_USE_LLM`: enable LLM-based summarization (`true`/`false`)
- `SUMMARIZE_MODEL`: model used when summarizing via LLM
- `SUMMARIZE_TEMPERATURE`: sampling temperature
- `SUMMARIZE_TOP_P`: nucleus sampling top-p
- `SUMMARIZE_SEED`: randomness seed if supported
- `EMBED_OFFLINE`: embed without external calls (`true`/`false`)
- `RANK_HALF_LIFE_HOURS`: score decay half-life for ranking
- `LANGFUSE_HOST` (optional): Langfuse host
- `LANGFUSE_PUBLIC_KEY` (optional)
- `LANGFUSE_SECRET_KEY` (optional)
- `DATABASE_URL` (optional): Postgres connection for summaries persistence

Runbook (CLI)
- Preferred: use the `e_brain` module
  - Init DB: `python -m e_brain init-db`
  - Ingest RSS: `python -m e_brain ingest-rss [--feeds-file feeds.txt] [--max 20] [--filter \\b(neuro|ai)\\b]`
  - Embed new items: `python -m e_brain embed [--batch 64]`
  - Generate candidate post: `python -m e_brain generate [--theme "neuroscience general facts"] [--max-sources 5]`
  - Publish (respects DRY_RUN and windows): `python -m e_brain publish [--limit 3] [--tz US/Eastern]`

- Compatibility alias: `python -m pipeline` (maps to the above)
  - Fetch sources: `python -m pipeline fetch`
  - Extract content: `python -m pipeline extract` (no-op; handled during fetch)
  - Cluster: `python -m pipeline cluster` (no-op; not implemented in this MVP)
  - Summarize: `python -m pipeline summarize [--theme ...] [--max-sources 5]`
  - Publish summaries: `python -m pipeline publish [--limit 3] [--tz US/Eastern]`
  - Full pipeline: `python -m pipeline all`
  - Evaluate models: `python -m pipeline eval-models` (no-op)

LLM Summarization (OpenRouter)
- Uses OpenRouter for LLM access. Control behavior via `SUMMARIZE_USE_LLM`, `SUMMARIZE_MODEL`, `SUMMARIZE_TEMPERATURE`, `SUMMARIZE_TOP_P`, and `SUMMARIZE_SEED`. Set `OPENROUTER_API_KEY` and optionally `OPENROUTER_BASE_URL`.

Model Evaluation
- Compare candidate models with `python -m pipeline eval-models --models <m1,m2,...> --seed 42` to assess summarization quality deterministically (seeded where supported).

Observability
- If `LANGFUSE_*` variables are set, LLM calls and pipeline steps emit traces/metrics to Langfuse.

Ranking
- Recency-aware ranking decays scores using `RANK_HALF_LIFE_HOURS`. Content cues (e.g., source quality, engagement) may bias selection.

Summaries Persistence
- Summaries are stored in the database when `DATABASE_URL` is configured (pgvector recommended). Without it, summaries may be ephemeral or stored locally depending on setup.

Robots Compliance
- The extractor respects site robots and rate limits to avoid abusive fetching.

Notes
- X posting, OAuth tokens, and post scheduling are not part of this pipeline and have been removed from documentation.
