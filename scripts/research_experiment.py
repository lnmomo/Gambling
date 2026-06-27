from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from football_agents.research.experiment import ExperimentConfig, run_from_directory


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the reproducible ESWA research experiment")
    parser.add_argument("--source", type=Path, default=Path("data/historical_csv/football-data"))
    parser.add_argument("--output", type=Path, default=Path("reports/research_experiment"))
    parser.add_argument("--first-test-month", default="2024-06")
    parser.add_argument("--test-months", type=int, default=12)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    args = parser.parse_args()
    config = ExperimentConfig(
        first_test_month=args.first_test_month,
        test_months=args.test_months,
        bootstrap_samples=args.bootstrap_samples,
    )
    report = run_from_directory(args.source, args.output, config)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
