e-brain: Neuroscience Content Pipeline

Overview
- Curates neuroscience content from X, embeds with OpenAI (or OpenRouter), stores in PostgreSQL + pgvector, generates posts, moderates, and publishes on a schedule.

Quick Start
- Copy `.env.example` to `.env` and set required variables (see Environment below).
- Ensure PostgreSQL with `pgvector` is available via `DATABASE_URL`.
- Initialize database: `python -m e_brain.cli init-db`
- Ingest recent posts: `python -m e_brain.cli ingest-x`
- Embed new items: `python -m e_brain.cli embed`
- Generate candidate posts: `python -m e_brain.cli generate --theme "neuroscience general facts"`
- Publish pending (respects time windows and `DRY_RUN`): `python -m e_brain.cli publish`

Environment
- `ENV`: deployment env name (e.g., development)
- `DRY_RUN`: when `true`, no external side effects
- `DATABASE_URL` (optional): Postgres connection (pgvector recommended)
- `EMBEDDING_DIM`: vector dimension (e.g., 1536)
- `OPENAI_API_KEY` (optional): OpenAI API key
- `OPENROUTER_API_KEY` (optional): OpenRouter API key
- `OPENROUTER_BASE_URL` (optional): defaults to `https://openrouter.ai/api/v1`
- `EMBEDDING_MODEL`: default embedding model (e.g., text-embedding-3-small)
- `CHAT_MODEL`: default chat/generation model (e.g., gpt-4o-mini)
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

See also: `docs/env-setup.md` for DB and X API setup.

Runbook (CLI)
- Init DB: `python -m e_brain.cli init-db`
- Create vector index (optional): `python -m e_brain.cli create-index --type hnsw`
- Ingest X accounts: `python -m e_brain.cli ingest-x --accounts accounts-to-follow.md --max 5`
- Ingest curated RSS (optional): `python -m e_brain.cli ingest-rss --feeds-file feeds.txt --max 20`
- Embed: `python -m e_brain.cli embed --batch 64`
- Generate: `python -m e_brain.cli generate --theme "neuroscience general facts" --max-sources 5`
- Publish: `python -m e_brain.cli publish --limit 3 --tz US/Eastern`

Evaluation (models) — optional
- When the evaluation harness is enabled, compare LLMs with: `eval-models --models <modelA,modelB,...> --seed 42`.
- Summarization flags (if supported): `--use-llm true --model <model-name>` to override env defaults.

Observability
- If `LANGFUSE_*` variables are set, LLM calls may be traced and measured via Langfuse. Without them, observability is a no-op.

Ranking
- Recency-aware ranking decays scores using `RANK_HALF_LIFE_HOURS`. Content cues (e.g., engagement, source quality) can bias ranking during selection.

Scheduling
- Use cron (or Task Scheduler on Windows) to run `python -m e_brain.cli publish` periodically. Posting occurs only within configured US/EU windows.

Notes
- `DRY_RUN` defaults to `true`. Set `DRY_RUN=false` to enable posting.
- Mentions/DM polling remains disabled by default.
