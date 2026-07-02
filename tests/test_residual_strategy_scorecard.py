import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from residual_strategy_scorecard import build_scorecard  # noqa: E402


def _write_summary(root: Path, name: str, payload: dict) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(json.dumps(payload), encoding="utf-8")


def test_scorecard_promotes_only_stable_residual_candidates(tmp_path):
    _write_summary(tmp_path, "fixed_sp2_stable", {
        "method": "fixed SP2 market-residual edge strategy",
        "first_month": "2022-08",
        "last_month": "2026-05",
        "overall": {"bets": 160, "profit": 30.0, "roi_pct": 8.0, "max_drawdown": 20.0},
        "active_months": 30,
        "positive_months": 18,
        "negative_months": 10,
        "stability_assessment": {"latest_season": {"profit": 2.0}},
    })
    _write_summary(tmp_path, "fixed_sp2_unstable", {
        "method": "fixed SP2 market-residual edge strategy",
        "overall": {"bets": 160, "profit": 10.0, "roi_pct": 4.0, "max_drawdown": 20.0},
        "active_months": 30,
        "positive_months": 18,
        "negative_months": 10,
        "stability_assessment": {"latest_season": {"profit": 1.0}},
    })
    _write_summary(tmp_path, "market_bias_not_in_scope", {
        "overall": {"bets": 999, "profit": 999.0, "roi_pct": 99.0, "max_drawdown": 1.0},
    })

    scorecard = build_scorecard(tmp_path)

    assert scorecard["reports_scanned"] == 2
    by_name = {row["name"]: row for row in scorecard["rows"]}
    assert by_name["fixed_sp2_stable"]["tier"] == "SHADOW_RESEARCH_CANDIDATE"
    assert by_name["fixed_sp2_unstable"]["tier"] == "RESEARCH_POSITIVE_UNSTABLE_DRAWDOWN"
