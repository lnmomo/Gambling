CREATE TABLE IF NOT EXISTS named_book_gap_policies (
    policy_id TEXT PRIMARY KEY,
    policy_hash TEXT NOT NULL UNIQUE,
    config_json TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS named_book_gap_decisions (
    decision_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES named_book_gap_policies(policy_id),
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    external_fetched_at TEXT NOT NULL,
    bet365_last_update TEXT NOT NULL,
    pinnacle_last_update TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    minutes_to_kickoff REAL NOT NULL,
    selected_outcome TEXT,
    bet365_odds REAL,
    pinnacle_odds REAL,
    reference_probability REAL,
    expected_ev REAL,
    action TEXT NOT NULL CHECK(action IN ('CANDIDATE','NO_BET')),
    blockers_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(policy_id, match_id)
);

CREATE INDEX IF NOT EXISTS idx_named_book_gap_decisions_policy_time
ON named_book_gap_decisions(policy_id, decided_at);

CREATE TRIGGER IF NOT EXISTS named_book_gap_policies_no_update
BEFORE UPDATE ON named_book_gap_policies BEGIN
    SELECT RAISE(ABORT, 'named book gap policies are immutable');
END;

CREATE TRIGGER IF NOT EXISTS named_book_gap_policies_no_delete
BEFORE DELETE ON named_book_gap_policies BEGIN
    SELECT RAISE(ABORT, 'named book gap policies are immutable');
END;

CREATE TRIGGER IF NOT EXISTS named_book_gap_decisions_no_update
BEFORE UPDATE ON named_book_gap_decisions BEGIN
    SELECT RAISE(ABORT, 'named book gap decisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS named_book_gap_decisions_no_delete
BEFORE DELETE ON named_book_gap_decisions BEGIN
    SELECT RAISE(ABORT, 'named book gap decisions are immutable');
END;
