# OpenAlex API key — holder file

The live key lives in `.env` (`OPENALEX_API_KEY=...`) inside this folder.
This sanitized copy documents the mechanism without embedding the secret:

- Worker: `app/openalex_worker.py` (`_key_sources()`)
- Resolution order: environment variable → this file's notes → legacy
  parent-folder `.env` (belt and braces for pre-§46 setups)
- Key format note: OpenAlex keys are carried either as a bare token or
  URL-embedded after `https://api.openalex.org/<token>` — the worker parses
  both shapes.

Never commit a live key. If one ever lands in the history, rotate it at
OpenAlex and re-seed `.env`.
