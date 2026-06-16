from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import uvicorn

from .backtesting import BacktestEngine
from .config import settings
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
    sync = sub.add_parser("sync-official", help="低频同步中国竞彩网公开赛程与 SP")
    sync.add_argument("--force", action="store_true", help="忽略最小同步间隔")
    data_sync = sub.add_parser("sync-data", help="同步外部赔率、新闻、天气并运行模型")
    data_sync.add_argument("--limit", type=int, default=40)
    build_features = sub.add_parser("build-features", help="Build real historical team features for official matches")
    build_features.add_argument("--limit", type=int, default=100)
    build_features.add_argument("--include-finished", action="store_true")
    build_features.add_argument("--min-matches", type=int, default=10)
    build_features.add_argument("--league", default="", help="Only build features for official matches whose league contains this text")
    llm = sub.add_parser("analyze-news", help="使用大模型分析指定比赛新闻")
    llm.add_argument("match_id", type=int)
    llm.add_argument("--force", action="store_true")
    backtest = sub.add_parser("backtest", help="运行历史 CSV 回测")
    backtest.add_argument("csv")
    backtest.add_argument("--bankroll", type=float, default=10_000)
    backtest.add_argument("--min-ev", type=float, default=0.05)
    history = sub.add_parser("import-history", help="导入历史比赛 CSV")
    history.add_argument("csv")
    collect = sub.add_parser("sync-history", help="从公开 CSV 来源增量同步真实历史赛果")
    collect.add_argument("--years-back", type=int, default=settings.historical_data_years_back)
    collect.add_argument("--divisions", default="", help="逗号分隔，如 E0,D1,I1,SP1")
    sub.add_parser("sync-international-history", help="同步真实国家队历史赛果")
    agent_run = sub.add_parser("run-agents", help="Run data, Qwen, model, and critic agents")
    agent_run.add_argument("--limit", type=int, default=settings.agent_match_limit)
    agent_run.add_argument("--include-history", action="store_true")
    agent_run.add_argument("--force-official", action="store_true")
    agent_run.add_argument("--force-qwen", action="store_true")
    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("football_agents.app:app", host=args.host, port=args.port, reload=False)
    elif args.command == "init-db":
        db.initialize()
        print(f"Database initialized: {db.path}")
    elif args.command == "seed-demo":
        print(json.dumps(seed_demo(), ensure_ascii=False, indent=2))
    elif args.command == "sync-official":
        from .official_data import OfficialDataService
        from .llm import QwenOpsAgent
        db.initialize()
        report = OfficialDataService().sync(force=args.force)
        print(json.dumps(QwenOpsAgent().attach("official-data-agent", report), ensure_ascii=False, indent=2))
    elif args.command == "sync-data":
        from .integrations import DataEnrichmentService
        from .llm import QwenOpsAgent
        db.initialize()
        report = DataEnrichmentService().sync(limit=args.limit)
        print(json.dumps(QwenOpsAgent().attach("market-news-weather-agent", report), ensure_ascii=False, indent=2))
    elif args.command == "build-features":
        from .features import build_features_for_official_matches
        db.initialize()
        report = build_features_for_official_matches(limit=args.limit, include_finished=args.include_finished,
                                                     min_matches=args.min_matches, league=args.league or None)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "analyze-news":
        from .llm import LLMNewsAgent
        db.initialize()
        print(json.dumps(LLMNewsAgent().analyze(args.match_id, force=args.force), ensure_ascii=False, indent=2))
    elif args.command == "import-history":
        from .historical_data import HistoricalDataService
        db.initialize()
        text = Path(args.csv).read_text(encoding="utf-8-sig")
        print(json.dumps(HistoricalDataService().import_csv_text(text, str(args.csv)), ensure_ascii=False, indent=2))
    elif args.command == "sync-history":
        from .historical_agent import HistoricalCollectionAgent
        from .llm import QwenOpsAgent
        db.initialize()
        divisions = [item.strip().upper() for item in args.divisions.split(",") if item.strip()]
        report = HistoricalCollectionAgent().sync(args.years_back, divisions or None)
        print(json.dumps(QwenOpsAgent().attach("historical-data-agent", report), ensure_ascii=False, indent=2))
    elif args.command == "sync-international-history":
        from .international_history_agent import InternationalHistoryAgent
        from .llm import QwenOpsAgent
        db.initialize()
        report = InternationalHistoryAgent().sync()
        print(json.dumps(QwenOpsAgent().attach("international-history-agent", report), ensure_ascii=False, indent=2))
    elif args.command == "run-agents":
        from .agents.orchestrator import AgentOrchestrator
        db.initialize()
        result = AgentOrchestrator().run(args.limit, args.include_history, args.force_official,
                                         args.force_qwen, trigger_name="cli")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        with Path(args.csv).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        report = BacktestEngine(args.min_ev).run(rows, args.bankroll)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

