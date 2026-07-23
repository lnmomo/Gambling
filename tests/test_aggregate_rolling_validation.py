import json

from scripts.aggregate_rolling_validation import main


def test_aggregator_combines_single_fold_outputs(tmp_path, monkeypatch):
    paths = []
    for month, profit in (("2024-03", 2.0), ("2024-09", -1.0)):
        payload = {
            "method": {"folds": 1, "variants": ["candidate"]},
            "folds": [{"train_window": month, "selected_holdout": {"bets": 12, "staked": 10.0, "profit": profit,
                       "roi_pct": profit * 10, "max_drawdown": 3.0}}],
            "fixed_candidate_holdout_aggregate": {"candidate": {"bets": 12, "staked": 10.0, "profit": profit,
                "roi_pct": profit * 10, "max_fold_drawdown": 3.0}},
        }
        path = tmp_path / f"{month}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    output = tmp_path / "summary.json"
    monkeypatch.setattr("sys.argv", ["aggregate", *(str(path) for path in paths), "--output", str(output)])

    main()

    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["train_selected_aggregate"]["profit"] == 1.0
    assert summary["fixed_candidate_holdout_aggregate"]["candidate"]["positive_folds"] == 1
    assert summary["candidate_decisions"]["candidate"]["status"] == "REJECTED"
