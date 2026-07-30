ALTER TABLE named_book_gap_decisions ADD COLUMN pure_model_probability REAL;
ALTER TABLE named_book_gap_decisions ADD COLUMN residual_probability REAL;
ALTER TABLE named_book_gap_decisions ADD COLUMN conservative_probability REAL;
ALTER TABLE named_book_gap_decisions ADD COLUMN conservative_ev REAL;
ALTER TABLE named_book_gap_decisions ADD COLUMN slippage_rate REAL;
