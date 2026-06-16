# data/ Directory Policy

`data/` separates source code from local runtime state. Commit only small, sanitized sample data and documentation.

```text
data/
  sample/       Sanitized demo/test data that may be committed.
  runtime/      Local runtime databases and state. Do not commit.
  cache/        API response caches. Do not commit.
  logs/         Runtime logs. Do not commit.
  snapshots/    Temporary snapshot exports. Do not commit.
  raw/          Raw collected data. Do not commit.
  private/      Private historical CSV/data. Do not commit.
```

Rules:

- Real `football_agents.db` files must not be committed.
- Real historical CSV files are treated as private collected data by default.
- Migration SQL under `football_agents/migrations/` should be committed.
- Sample data must be small, sanitized, and reproducible.
- Never store API keys, cookies, tokens, or personal data in this directory.
