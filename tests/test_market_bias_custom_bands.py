import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_custom_bands import add_i2_draw_band, band_label, i2_draw_band_rule  # noqa: E402


def test_custom_band_helpers_use_consistent_labels_and_rules():
    assert band_label(2.8, 3.3) == "[2.80,3.30)"
    assert i2_draw_band_rule(2.8, 3.3) == "league|outcome|custom_i2_draw_band=I2|draw|[2.80,3.30)"


def test_add_i2_draw_band_only_marks_matching_rows():
    frame = pd.DataFrame([
        {"league": "I2", "outcome": "draw", "odds": 3.2},
        {"league": "I2", "outcome": "draw", "odds": 3.3},
        {"league": "I2", "outcome": "away", "odds": 3.2},
    ])

    result = add_i2_draw_band(frame, 2.8, 3.3)

    assert result["custom_i2_draw_band"].tolist() == [
        "[2.80,3.30)",
        "__out_of_band__",
        "__out_of_band__",
    ]
