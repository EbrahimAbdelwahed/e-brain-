Changelog

2025-09-04 — MVP Finalization
- Ingest/extract/cluster via MinHash-LSH with embeddings cache.
- OpenRouter-backed LLM summarization with response caching.
- Summaries persisted in DB; publish reads from DB.
- Ranking polish: time-decay (half-life) and content cues.
- Robots compliance respected during extraction.
- Evaluation harness to compare multiple models with fixed seed.
- CI: pytest and coverage reporting wired.
- Observability: Langfuse hooks (opt-in via env).

