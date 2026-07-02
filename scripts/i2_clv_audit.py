from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cross_league_rule_search import DEFAULT_SEASONS, load_seasons  # noqa: E402
from football_agents.models.ensemble import market_probabilities  # noqa: E402


OPEN_COLUMNS = {
    "home": ("AvgH", "PSH", "B365H", "MaxH"),
    "draw": ("AvgD", "PSD", "B365D", "MaxD"),
    "away": ("AvgA", "PSA", "B365A", "MaxA"),
}
CLOSE_COLUMNS = {
    "home": ("AvgCH", "PSCH", "B365CH", "MaxCH"),
    "draw": ("AvgCD", "PSCD", "B365CD", "MaxCD"),
    "away": ("AvgCA", "PSCA", "B365CA", "MaxCA"),
}


def _first_number(row: pd.Series, columns: tuple[str, ...]) -> float | None:
    for column in columns:
        value = pd.to_numeric(row.get(column), errors="coerce")
        if pd.notna(value) and float(value) > 1:
            return float(value)
    return None


def _odds_snapshot(matches: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in matches.iterrows():
        item = {
            "bet_date": pd.to_datetime(row["match_date"]).strftime("%Y-%m-%d"),
            "league": str(row["league"]),
            "home_team": str(row["HomeTeam"]),
            "away_team": str(row["AwayTeam"]),
        }
        for outcome in ("home", "draw", "away"):
            item[f"open_{outcome}"] = _first_number(row, OPEN_COLUMNS[outcome])
            item[f"close_{outcome}"] = _first_number(row, CLOSE_COLUMNS[outcome])
        rows.append(item)
    return pd.DataFrame(rows)


def _band(odds: float) -> str:
    if odds < 2.8:
        return "[0,2.8)"
    if odds < 3.3:
        return "[2.8,3.3)"
    if odds < 3.5:
        return "[3.3,3.5)"
    return "[3.5,inf)"


def _summary(frame: pd.DataFrame, label: str) -> dict[str, Any]:
    if frame.empty:
        return {
            "label": label,
            "bets": 0,
            "profit": 0.0,
            "roi_pct": 0.0,
            "avg_clv_pct": 0.0,
            "positive_clv_rate": 0.0,
            "avg_raw_closing_price_edge_pct": 0.0,
            "avg_no_vig_closing_edge_pct": 0.0,
        }
    staked = float(frame["stake"].sum())
    profit = float(frame["profit"].sum())
    return {
        "label": label,
        "bets": int(len(frame)),
        "wins": int(frame["won"].sum()),
        "hit_rate": round(float(frame["won"].mean()), 4),
        "staked": round(staked, 2),
        "profit": round(profit, 2),
        "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
        "avg_bet_odds": round(float(frame["odds"].mean()), 4),
        "avg_close_odds": round(float(frame["close_odds"].mean()), 4),
        "avg_clv_pct": round(float(frame["clv"].mean()) * 100, 3),
        "median_clv_pct": round(float(frame["clv"].median()) * 100, 3),
        "positive_clv_rate": round(float((frame["clv"] > 0).mean()), 4),
        "avg_raw_closing_price_edge_pct": round(float(frame["raw_closing_price_edge"].mean()) * 100, 3),
        "avg_no_vig_closing_edge_pct": round(float(frame["no_vig_closing_edge"].mean()) * 100, 3),
    }


def audit_i2_clv(bets_path: Path, seasons: tuple[str, ...] = DEFAULT_SEASONS) -> tuple[dict[str, Any], pd.DataFrame]:
    bets = pd.read_csv(bets_path)
    if bets.empty:
        raise ValueError(f"No bets found: {bets_path}")
    matches = load_seasons(seasons)
    merged = bets.merge(
        _odds_snapshot(matches),
        on=["bet_date", "league", "home_team", "away_team"],
        how="left",
        validate="many_to_one",
    )
    matched = merged[merged["close_draw"].notna() & merged["open_draw"].notna()].copy()
    if not matched.empty:
        matched["close_odds"] = matched["close_draw"].astype(float)
        matched["open_odds_reference"] = matched["open_draw"].astype(float)
        matched["clv"] = matched["odds"].astype(float) / matched["close_odds"] - 1.0
        matched["raw_closing_price_edge"] = matched["clv"]
        closing_probs = []
        for _, row in matched.iterrows():
            close_prices = {
                "home": float(row["close_home"]),
                "draw": float(row["close_draw"]),
                "away": float(row["close_away"]),
            }
            closing_probs.append(market_probabilities(close_prices)["draw"])
        matched["no_vig_closing_market_probability"] = closing_probs
        matched["no_vig_closing_edge"] = matched["no_vig_closing_market_probability"] * matched["odds"].astype(float) - 1.0
        matched["odds_band"] = matched["odds"].astype(float).map(_band)
    missing = merged[merged["close_draw"].isna() | merged["open_draw"].isna()].copy()
    by_season = [_summary(group, str(season)) for season, group in matched.groupby("season")] if not matched.empty else []
    by_band = [_summary(group, str(band)) for band, group in matched.groupby("odds_band")] if not matched.empty else []
    by_month = [_summary(group, str(month)) for month, group in matched.groupby("month")] if not matched.empty else []
    positive_clv_months = sum(1 for row in by_month if row["avg_clv_pct"] > 0)
    negative_clv_months = sum(1 for row in by_month if row["avg_clv_pct"] < 0)
    overall = _summary(matched, "overall")
    decision_reasons: list[str] = []
    if len(matched) < 200:
        decision_reasons.append("matched_bets<200")
    if missing.shape[0] > 0:
        decision_reasons.append("unmatched_bets>0")
    if overall["avg_clv_pct"] <= 0:
        decision_reasons.append("avg_clv<=0")
    if overall["positive_clv_rate"] < 0.5:
        decision_reasons.append("positive_clv_rate<0.5")
    if positive_clv_months <= negative_clv_months:
        decision_reasons.append("positive_clv_months<=negative_clv_months")
    warnings: list[str] = []
    if overall["avg_no_vig_closing_edge_pct"] <= 0:
        warnings.append("avg_no_vig_closing_edge<=0")
    report = {
        "method": "I2 draw final-bets CLV audit",
        "bets_path": str(bets_path),
        "seasons": seasons,
        "input_bets": int(len(bets)),
        "matched_bets": int(len(matched)),
        "unmatched_bets": int(len(missing)),
        "overall": overall,
        "positive_clv_months": int(positive_clv_months),
        "negative_clv_months": int(negative_clv_months),
        "by_season": by_season,
        "by_odds_band": by_band,
        "decision": "RAW_CLV_CONFIRMED_RESEARCH_ONLY" if not decision_reasons else "CLV_AUDIT_WARNING",
        "decision_reasons": decision_reasons,
        "warnings": warnings,
        "guardrail": "CLV is evaluated after settlement as a research diagnostic; it is not used to select these historical bets.",
    }
    return report, matched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bets", type=Path, default=Path("reports/feature_enriched_market_anchored_i2_stop3_cool3_v1/bets.csv"))
    parser.add_argument("--seasons", default=",".join(DEFAULT_SEASONS))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/i2_final_bets_clv_audit"))
    args = parser.parse_args()
    report, matched = audit_i2_clv(args.bets, tuple(item.strip() for item in args.seasons.split(",") if item.strip()))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    matched.to_csv(args.output_dir / "matched_bets.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
