from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import uvicorn

from .backtesting import BacktestEngine
from .db import db
from .seed import seed_demo


def main() -> None:
    parser = argparse.ArgumentParser(description="竞彩足球多 Agent 概率决策辅助系统")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="启动 API 和看板")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("init-db", help="初始化数据库")
    sub.add_parser("seed-demo", help="写入并评估演示比赛")
    backtest = sub.add_parser("backtest", help="运行历史 CSV 回测")
    backtest.add_argument("csv")
    backtest.add_argument("--bankroll", type=float, default=10_000)
    backtest.add_argument("--min-ev", type=float, default=0.05)
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("football_agents.app:app", host=args.host, port=args.port, reload=False)
    elif args.command == "init-db":
        db.initialize()
        print(f"Database initialized: {db.path}")
    elif args.command == "seed-demo":
        print(json.dumps(seed_demo(), ensure_ascii=False, indent=2))
    else:
        with Path(args.csv).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        report = BacktestEngine(args.min_ev).run(rows, args.bankroll)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

