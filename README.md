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
- Fetch sources: `python -m pipeline fetch`
- Extract content: `python -m pipeline extract`
- Cluster near-duplicates: `python -m pipeline cluster --jaccard-threshold 0.85 --num-perm 64`
- Summarize: `python -m pipeline summarize --use-llm --model <provider/model>`
- Publish summaries: `python -m pipeline publish`
- Full pipeline: `python -m pipeline all`
- Evaluate models: `python -m pipeline eval-models --models <modelA,modelB,...> --seed 42`

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
