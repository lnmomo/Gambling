from __future__ import annotations

import itertools
import json
from pathlib import Path

import monthly_shadow_backtest as shadow


def main() -> None:
    matches = shadow.load_matches(Path("data/historical_csv/football-data/2425"))
    validation_months = ("2025-01", "2025-02", "2025-03")
    results: list[dict] = []
    for blend, haircut, minimum, max_odds in itertools.product(
        (0.40, 0.50, 0.60),
        (0.05, 0.10),
        (0.01, 0.03),
        (5.0,),
    ):
        shadow.IMPROVED_CONFIG.update({
            "model_blend": blend,
            "uncertainty_haircut": haircut,
            "min_lower_bound_ev": minimum,
            "max_odds": max_odds,
        })
        summaries = [
            shadow.run_backtest(matches, month, 100.0, 100.0, "improved", True)[0]
            for month in validation_months
        ]
        bets = sum(item["bets"] for item in summaries)
        staked = sum(item["total_staked"] for item in summaries)
        profit = sum(item["net_profit"] for item in summaries)
        roi = profit / staked if staked else -1.0
        results.append({
            "model_blend": blend,
            "uncertainty_haircut": haircut,
            "min_lower_bound_ev": minimum,
            "max_odds": max_odds,
            "bets": bets,
            "total_staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi": round(roi, 6),
        })
    eligible = [item for item in results if item["bets"] >= 30]
    ranking = sorted(eligible, key=lambda item: (item["roi"], item["profit"], -item["max_odds"]), reverse=True)
    output = {"validation_months": validation_months, "minimum_bets": 30, "best": ranking[0], "top_10": ranking[:10]}
    target = Path("reports/monthly_shadow_backtest/improved/tuning_2025Q1.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
