import sys
from argparse import Namespace
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from market_bias_i2_band_grid_search import (  # noqa: E402
    band_label,
    frame_for_band,
    generate_bands,
)


def test_generate_bands_uses_inclusive_low_grid_and_width_grid():
    assert generate_bands(2.8, 2.9, 0.4, 0.5, 0.1) == [
        (2.8, 3.2),
        (2.8, 3.3),
        (2.9, 3.3),
        (2.9, 3.4),
    ]


def test_frame_for_band_labels_only_i2_draw_rows_inside_range():
    frame = pd.DataFrame([
        {"league": "I2", "outcome": "draw", "odds": 3.1},
        {"league": "I2", "outcome": "draw", "odds": 3.5},
        {"league": "I2", "outcome": "home", "odds": 3.1},
        {"league": "SP1", "outcome": "draw", "odds": 3.1},
    ])

    result = frame_for_band(frame, 2.8, 3.5)

    assert result["custom_i2_draw_band"].tolist() == [
        "[2.80,3.50)",
        "__out_of_band__",
        "__out_of_band__",
        "__out_of_band__",
    ]


def test_band_label_uses_stable_two_decimal_format():
    assert band_label(2.8, 3.5) == "[2.80,3.50)"
