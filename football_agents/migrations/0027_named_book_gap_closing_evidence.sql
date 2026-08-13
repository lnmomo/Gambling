ALTER TABLE prospective_external_odds_snapshots
RENAME TO prospective_external_odds_snapshots_legacy_0027;

CREATE TABLE prospective_external_odds_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    bookmaker_key TEXT NOT NULL,
    market TEXT NOT NULL CHECK(market='H2H'),
    home_odds REAL NOT NULL CHECK(home_odds>1),
    draw_odds REAL NOT NULL CHECK(draw_odds>1),
    away_odds REAL NOT NULL CHECK(away_odds>1),
    bookmaker_last_update TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    minutes_to_kickoff REAL NOT NULL CHECK(minutes_to_kickoff>0),
    capture_window TEXT NOT NULL CHECK(capture_window IN (
        'T_MINUS_24H','T_MINUS_6H','T_MINUS_1H','CLOSING','OTHER_PRE_MATCH'
    )),
    source TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    raw_event_json TEXT NOT NULL,
    UNIQUE(match_id,event_id,bookmaker_key,capture_window)
);

INSERT INTO prospective_external_odds_snapshots
SELECT * FROM prospective_external_odds_snapshots_legacy_0027;

DROP TABLE prospective_external_odds_snapshots_legacy_0027;

CREATE INDEX idx_prospective_external_odds_match_time
ON prospective_external_odds_snapshots(match_id,captured_at);

CREATE TRIGGER prospective_external_odds_no_update
BEFORE UPDATE ON prospective_external_odds_snapshots BEGIN
    SELECT RAISE(ABORT, 'prospective external odds snapshots are immutable');
END;

CREATE TRIGGER prospective_external_odds_no_delete
BEFORE DELETE ON prospective_external_odds_snapshots BEGIN
    SELECT RAISE(ABORT, 'prospective external odds snapshots are immutable');
END;

CREATE TABLE IF NOT EXISTS named_book_gap_closing_observations (
    observation_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE REFERENCES named_book_gap_decisions(decision_id),
    policy_id TEXT NOT NULL REFERENCES named_book_gap_policies(policy_id),
    match_id INTEGER NOT NULL REFERENCES matches(id),
    selected_outcome TEXT NOT NULL CHECK(selected_outcome IN ('home','draw','away')),
    captured_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    minutes_to_kickoff REAL NOT NULL CHECK(minutes_to_kickoff >= 0),
    execution_odds REAL NOT NULL,
    closing_reference_probability REAL NOT NULL,
    closing_fair_odds REAL NOT NULL,
    closing_edge_pct REAL NOT NULL,
    positive_clv INTEGER NOT NULL CHECK(positive_clv IN (0,1)),
    reference_bookmakers_json TEXT NOT NULL,
    reference_method TEXT NOT NULL,
    source_snapshot_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_named_book_gap_closing_policy_time
ON named_book_gap_closing_observations(policy_id,captured_at);

CREATE TRIGGER IF NOT EXISTS named_book_gap_closing_observations_no_update
BEFORE UPDATE ON named_book_gap_closing_observations BEGIN
    SELECT RAISE(ABORT, 'named book gap closing observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS named_book_gap_closing_observations_no_delete
BEFORE DELETE ON named_book_gap_closing_observations BEGIN
    SELECT RAISE(ABORT, 'named book gap closing observations are immutable');
END;
