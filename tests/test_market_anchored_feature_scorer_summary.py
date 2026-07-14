from __future__ import annotations

import json

from scripts.market_anchored_feature_scorer_summary import summarize_feature_scorer_reports


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _row(rule: str, decision: str = "RESEARCH_CANDIDATE_NEEDS_AUDIT") -> dict:
    return {
        "rule_description": rule,
        "label": f"{rule}_label",
        "decision": decision,
        "bets": 200,
        "profit": 50.0,
        "roi_pct": 5.0,
        "max_drawdown": 20.0,
        "active_pass_rate": 0.7,
        "latest_season_profit": 5.0,
        "decision_reasons": [] if decision == "RESEARCH_CANDIDATE_NEEDS_AUDIT" else ["failed"],
    }


def test_summary_requires_same_rule_to_pass_each_source(tmp_path) -> None:
    first = tmp_path / "first" / "summary.json"
    second = tmp_path / "second" / "summary.json"
    _write(first, {"odds_source": "AVG_OPEN", "results": [_row("rule_a")]})
    _write(second, {"odds_source": "AVG_CLOSE", "results": [_row("rule_b")]})

    summary = summarize_feature_scorer_reports([first, second])

    assert summary["decision"] == "NO_CROSS_SOURCE_FEATURE_SCORER_CANDIDATE"
    assert summary["rules_passing_all_sources"] == 0


def test_summary_promotes_same_rule_across_sources(tmp_path) -> None:
    first = tmp_path / "first" / "summary.json"
    second = tmp_path / "second" / "summary.json"
    _write(first, {"odds_source": "AVG_OPEN", "results": [_row("rule_a")]})
    _write(second, {"odds_source": "AVG_CLOSE", "results": [_row("rule_a")]})

    summary = summarize_feature_scorer_reports([first, second])

    assert summary["decision"] == "FEATURE_SCORER_CROSS_SOURCE_CANDIDATE"
    assert summary["rules_passing_all_sources"] == 1
    assert summary["rules"][0]["rule"] == "rule_a"
