e-brain: Neuroscience Content Pipeline

Overview
- Pipeline to curate neuroscience content from X, embed with OpenAI, store in PostgreSQL + pgvector, generate posts, moderate, and publish on schedule.

Quick Start
- Create a `.env` from `.env.example` and fill credentials.
- Ensure PostgreSQL with `pgvector` is installed and accessible via `DATABASE_URL`.
- Initialize database: `python -m e_brain.cli init-db`
- Ingest recent posts from accounts in `accounts-to-follow.md`: `python -m e_brain.cli ingest-x`
- Embed new items: `python -m e_brain.cli embed`
- Generate candidate posts: `python -m e_brain.cli generate --theme general`
- Publish pending (respects time windows and `DRY_RUN`): `python -m e_brain.cli publish`

Scheduling
- Use cron to run `python -m e_brain.cli publish` periodically. The command will only post within US/EU windows.

Notes
- DRY_RUN defaults to true. Set `DRY_RUN=false` to enable posting.
- Mentions/DM polling is disabled by default.

