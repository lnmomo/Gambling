from __future__ import annotations

import csv
import json
import subprocess
import sys


def _write_csv(path, count=12):
    fields = ["id", "date", "league", "home_team", "away_team", "home_score", "away_score", "sp_home", "sp_draw", "sp_away", "closing_home", "closing_draw", "closing_away"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in range(count):
            writer.writerow({
                "id": f"m{index}", "date": f"2025-02-{(index % 28) + 1:02d}", "league": "CLI League",
                "home_team": f"H{index % 4}", "away_team": f"A{index % 4}",
                "home_score": 2 if index % 2 else 0, "away_score": 1,
                "sp_home": 2.1, "sp_draw": 3.2, "sp_away": 3.4,
                "closing_home": 2.05, "closing_draw": 3.25, "closing_away": 3.45,
            })


def test_optimize_edge_quality_cli_writes_json(tmp_path):
    csv_path = tmp_path / "matches.csv"
    output = tmp_path / "result.json"
    _write_csv(csv_path)
    result = subprocess.run(
        [sys.executable, "-m", "football_agents.cli", "optimize-edge-quality", str(csv_path), "--max-configs", "3", "--min-samples", "10", "--output", str(output)],
        cwd=".",
        text=True,
        capture_output=True,
        check=True,
    )
    summary = json.loads(result.stdout)
    assert summary["title"] == "Edge Quality Optimization"
    assert summary["configs_tested"] == 3
    assert summary["promotion_decision"]
    assert output.exists()


def test_optimize_edge_quality_cli_no_write(tmp_path):
    csv_path = tmp_path / "matches.csv"
    output = tmp_path / "result.json"
    _write_csv(csv_path)
    subprocess.run(
        [sys.executable, "-m", "football_agents.cli", "optimize-edge-quality", str(csv_path), "--max-configs", "2", "--output", str(output), "--no-write"],
        cwd=".",
        text=True,
        capture_output=True,
        check=True,
    )
    assert not output.exists()
