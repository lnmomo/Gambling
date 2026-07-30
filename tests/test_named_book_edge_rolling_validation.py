import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.named_book_edge_rolling_validation import _eligible_train_candidates  # noqa: E402


def _row(*, bets: int, staked: float, profit: float) -> dict:
    return {"config_name": "candidate", "bets": bets, "staked": staked, "profit": profit}


def test_nested_selection_requires_material_positive_train_evidence() -> None:
    rows = [
        _row(bets=29, staked=20.0, profit=2.0),
        _row(bets=30, staked=9.99, profit=2.0),
        _row(bets=30, staked=10.0, profit=0.0),
        _row(bets=30, staked=10.0, profit=2.0),
    ]

    assert _eligible_train_candidates(rows) == [rows[-1]]


def test_persistent_train_requires_each_recent_segment_to_be_positive() -> None:
    row = _row(bets=40, staked=20.0, profit=3.0)
    segments = {"candidate": [
        _row(bets=15, staked=5.0, profit=1.0),
        _row(bets=15, staked=5.0, profit=-0.1),
    ]}

    assert _eligible_train_candidates([row], segments) == []
