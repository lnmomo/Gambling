import json

from scripts.true_ev_research_summary import summarize_true_ev_search


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_true_ev_summary_rejects_when_all_screens_fail(tmp_path):
    discovery = tmp_path / "discovery" / "summary.json"
    _write_json(discovery, {
        "selected_domains": ["USA", "ARG"],
        "domain_count": 2,
        "domains_with_diagnostic_hits": 2,
    })
    usa = tmp_path / "usa" / "summary.json"
    _write_json(usa, {
        "seasons": ["USA"],
        "candidate_count": 1,
        "passed_count": 0,
        "rule_summary": [{
            "rule": "league|outcome|odds_bucket=USA|home|[2.2,2.8)",
            "combined_roi_pct": -3.39,
            "total_portfolio_bets": 107,
            "worst_source_roi_pct": -18.85,
            "passes_all_validation_sources": False,
            "source_results": [{
                "odds_source": "PS_CLOSE",
                "fail_reasons": ["profit<=0", "roi<3%"],
            }],
        }],
    })
    arg = tmp_path / "arg" / "summary.json"
    _write_json(arg, {
        "seasons": ["ARG"],
        "candidate_count": 0,
        "passed_count": 0,
        "rule_summary": [],
    })

    summary = summarize_true_ev_search(discovery_path=discovery, screen_paths=[usa, arg])

    assert summary["decision"] == "NO_TRUE_EV_CANDIDATE_FOUND"
    assert summary["screen_passed_rules"] == 0
    assert summary["screens"][0]["status"] == "REJECTED_BY_CROSS_SOURCE_SCREEN"
    assert summary["screens"][1]["status"] == "NO_SURVIVING_RULE_AFTER_RECENT_FORM_FILTER"


def test_true_ev_summary_does_not_promote_without_multi_window_pass(tmp_path):
    discovery = tmp_path / "discovery" / "summary.json"
    _write_json(discovery, {"selected_domains": ["X"], "domain_count": 1, "domains_with_diagnostic_hits": 1})
    screen = tmp_path / "x" / "summary.json"
    _write_json(screen, {
        "seasons": ["X"],
        "candidate_count": 1,
        "passed_count": 1,
        "rule_summary": [{
            "rule": "league|outcome=X|home",
            "combined_roi_pct": 4.0,
            "total_portfolio_bets": 200,
            "worst_source_roi_pct": 3.0,
            "passes_all_validation_sources": True,
            "source_results": [],
        }],
    })
    multi_window = tmp_path / "mw" / "summary.json"
    _write_json(multi_window, {
        "candidate_summaries": [{
            "candidate_id": "x",
            "decision": "RESEARCH_ONLY_UNSTABLE_WINDOWS",
            "total_bets": 200,
            "combined_roi_pct": 4.0,
            "active_pass_rate": 0.25,
            "source_pass_rate": 0.5,
            "worst_source_roi_pct": 3.0,
        }],
    })

    summary = summarize_true_ev_search(
        discovery_path=discovery,
        screen_paths=[screen],
        multi_window_paths=[multi_window],
    )

    assert summary["decision"] == "CROSS_SOURCE_PASS_BUT_MULTI_WINDOW_UNPROVEN"
    assert summary["screen_passed_rules"] == 1
    assert summary["multi_window_passed_candidates"] == 0


def test_true_ev_summary_prefers_nonzero_multi_window_candidate(tmp_path):
    discovery = tmp_path / "discovery" / "summary.json"
    _write_json(discovery, {"selected_domains": ["X"], "domain_count": 1, "domains_with_diagnostic_hits": 1})
    screen = tmp_path / "x" / "summary.json"
    _write_json(screen, {"seasons": ["X"], "candidate_count": 0, "passed_count": 0, "rule_summary": []})
    multi_window = tmp_path / "mw" / "summary.json"
    _write_json(multi_window, {
        "candidate_summaries": [
            {
                "candidate_id": "zero-bet",
                "decision": "REJECT_UNSTABLE",
                "total_bets": 0,
                "combined_roi_pct": 0.0,
            },
            {
                "candidate_id": "tested-loser",
                "decision": "REJECT_UNSTABLE",
                "total_bets": 214,
                "combined_roi_pct": -12.88,
                "active_pass_rate": 0.0,
                "source_pass_rate": 0.0,
                "worst_source_roi_pct": -20.0,
            },
        ],
    })

    summary = summarize_true_ev_search(
        discovery_path=discovery,
        screen_paths=[screen],
        multi_window_paths=[multi_window],
    )

    assert summary["multi_window"][0]["best_candidate_id"] == "tested-loser"
    assert summary["multi_window"][0]["best_total_bets"] == 214
