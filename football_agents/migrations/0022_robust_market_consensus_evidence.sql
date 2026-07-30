ALTER TABLE named_book_gap_decisions ADD COLUMN execution_bookmaker TEXT;
ALTER TABLE named_book_gap_decisions ADD COLUMN execution_bookmaker_key TEXT;
ALTER TABLE named_book_gap_decisions ADD COLUMN reference_method TEXT;
ALTER TABLE named_book_gap_decisions ADD COLUMN reference_bookmakers_json TEXT;
ALTER TABLE named_book_gap_decisions ADD COLUMN reference_dispersion REAL;
ALTER TABLE named_book_gap_decisions ADD COLUMN snapshot_payload_hash TEXT;
