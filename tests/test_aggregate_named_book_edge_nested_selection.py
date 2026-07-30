from scripts.aggregate_named_book_edge_nested_selection import build_report


def _payload(selected: str, profit: float) -> dict:
    return {
        "nested_selection": {"enabled": True},
        "folds": [{
            "holdout_window": "2025-01-01..2025-03-31",
            "selected_on_train": selected,
            "candidates": {
                "candidate": {
                    "bets": 30, "staked": 20.0, "profit": profit,
                    "roi_pct": profit / 20 * 100, "max_drawdown": 4.0,
                },
            },
        }],
    }


def test_aggregate_rejects_sparse_nested_selection(tmp_path) -> None:
    directory = tmp_path / "part"
    directory.mkdir()
    (directory / "rolling_validation_summary.json").write_text(
        __import__("json").dumps(_payload("candidate", 2.0)), encoding="utf-8"
    )

    report = build_report([directory])

    assert report["decision"] == "REJECTED_NESTED_SELECTION"
    assert "active_holdout_folds<5" in report["reasons"]
