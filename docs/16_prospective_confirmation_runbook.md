# Prospective Confirmation Runbook

## Registered Primary Analysis

- Frozen model: deterministic production `ensemble` only.
- Probability effects from Qwen are excluded from the primary endpoint.
- Primary snapshot window: 60 to 120 minutes before kickoff.
- If several snapshots exist in the window, use the one closest to 60 minutes.
- Primary endpoint: paired multiclass Log Loss difference against de-vigged official odds.
- Readiness: at least 5,000 settled eligible matches and 365 calendar days.
- Confirmation analysis may be inserted only once.

The database rejects updates and deletes for model freezes, study registrations,
prospective predictions, and confirmation runs.

## Automatic Collection

When `ENABLE_PROSPECTIVE_RESEARCH=true`, the backend runs
`prospective_research_capture` once after startup and every
`BACKGROUND_AGENT_INTERVAL_SECONDS` seconds. The normal value is 3600 seconds.

Every capture stores the exact official odds observation ID, model prediction ID,
kickoff time, model probabilities, market probabilities, and frozen algorithm hash.
Duplicate study/match/snapshot combinations are ignored.

The external-market confirmation path has a separate lightweight collector named
`external_odds_primary_horizon_capture`. It checks every
`LIVE_FAST_REFRESH_MINUTES` minutes, fetches The Odds API only when an uncaptured match
is 60 to 120 minutes from kickoff, and runs independently of news and weather. After a
successful market capture it immediately runs the downstream feature, prospective,
external-consensus challenger, and readiness tasks. This collector must run before
kickoff; later results are never used to reconstruct a missing pre-match snapshot.

## Monitoring

```text
GET /api/research/prospective/status
GET /health
```

The Agent / Workflow Monitor displays the capture task, immutable prediction count,
eligible settled count, remaining sample requirement, remaining days, and final decision.

## Manual Capture

```text
POST /api/research/prospective/capture?limit=100
```

## Confirmation

```text
POST /api/research/prospective/confirm
```

Before both registered thresholds are met, the endpoint returns HTTP 409. After a run is
stored, every later call returns that same immutable run and does not resample or recompute
the result.
