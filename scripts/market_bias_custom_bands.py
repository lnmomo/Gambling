from __future__ import annotations

import pandas as pd


def band_label(low: float, high: float) -> str:
    return f"[{low:.2f},{high:.2f})"


def i2_draw_band_rule(low: float, high: float) -> str:
    return f"league|outcome|custom_i2_draw_band=I2|draw|{band_label(low, high)}"


def add_i2_draw_band(frame: pd.DataFrame, low: float, high: float) -> pd.DataFrame:
    labeled = frame.copy()
    label = band_label(low, high)
    in_band = (
        (labeled["league"].astype(str) == "I2")
        & (labeled["outcome"].astype(str) == "draw")
        & (labeled["odds"].astype(float) >= low)
        & (labeled["odds"].astype(float) < high)
    )
    labeled["custom_i2_draw_band"] = "__out_of_band__"
    labeled.loc[in_band, "custom_i2_draw_band"] = label
    return labeled
