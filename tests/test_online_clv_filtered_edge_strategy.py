import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from online_clv_filtered_edge_strategy import _clv_bucket_report  # noqa: E402


def test_clv_bucket_report_requires_prior_positive_clv_and_profit():
    empty_allowed, empty_rows = _clv_bucket_report(
        pd.DataFrame(),
        min_samples=1,
        min_avg_clv=0.0,
        min_avg_closing_edge=0.0,
        require_positive_profit=True,
    )
    assert empty_allowed == set()
    assert empty_rows == []

    history = pd.DataFrame([
        {"bucket_id": "A", "unit_profit": 1.0, "clv": 0.02, "closing_edge": 0.01},
        {"bucket_id": "B", "unit_profit": 1.0, "clv": -0.02, "closing_edge": 0.01},
        {"bucket_id": "C", "unit_profit": -1.0, "clv": 0.02, "closing_edge": 0.01},
    ])
    allowed, rows = _clv_bucket_report(
        history,
        min_samples=1,
        min_avg_clv=0.0,
        min_avg_closing_edge=0.0,
        require_positive_profit=True,
    )

    assert allowed == {"A"}
    assert rows[0]["bucket_id"] == "A"
