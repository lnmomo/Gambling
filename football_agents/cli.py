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
    parser = argparse.ArgumentParser(description="Football agents probability decision support system")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start API and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("init-db", help="Initialize database")
    sub.add_parser("seed-demo", help="Seed demo matches")

    sync = sub.add_parser("sync-official", help="Sync official Sporttery fixtures and SP")
    sync.add_argument("--force", action="store_true", help="Ignore minimum sync interval")

    data_sync = sub.add_parser("sync-data", help="Sync external odds, news, weather, and model signals")
    data_sync.add_argument("--limit", type=int, default=40)

    build_features = sub.add_parser("build-features", help="Build real historical team features for official matches")
    build_features.add_argument("--limit", type=int, default=100)
    build_features.add_argument("--include-finished", action="store_true")
    build_features.add_argument("--min-matches", type=int, default=10)
    build_features.add_argument("--league", default="", help="Only build features for official matches whose league contains this text")

    llm = sub.add_parser("analyze-news", help="Analyze match news with LLM")
    llm.add_argument("match_id", type=int)
    llm.add_argument("--force", action="store_true")

    backtest = sub.add_parser("backtest", help="Run historical CSV backtest")
    backtest.add_argument("csv")
    backtest.add_argument("--bankroll", type=float, default=10_000)
    backtest.add_argument("--min-ev", type=float, default=0.05)

    optimize = sub.add_parser("optimize-edge-quality", help="Optimize True Odds Filter parameters by historical backtest")
    optimize.add_argument("csv", nargs="?", default=settings.auto_backtest_csv_path)
    optimize.add_argument("--from-date", default="")
    optimize.add_argument("--to-date", default="")
    optimize.add_argument("--league", default="")
    optimize.add_argument("--config-grid", default="default", choices=["default", "conservative", "aggressive"])
    optimize.add_argument("--max-configs", type=int, default=50)
    optimize.add_argument("--output", default="")
    optimize.add_argument("--min-samples", type=int, default=200)
    optimize.add_argument("--shadow-only", action="store_true")
    optimize.add_argument("--no-write", action="store_true")

    create_shadow = sub.add_parser("create-shadow-config", help="Create a True Odds shadow config version")
    create_shadow.add_argument("--from-optimization", default="")
    create_shadow.add_argument("--name", default="true-odds-shadow")
    create_shadow.add_argument("--optimization-json", default="")

    start_shadow = sub.add_parser("start-shadow-validation", help="Start shadow validation for a config version")
    start_shadow.add_argument("config_version_id")

    run_shadow = sub.add_parser("run-shadow", help="Run live shadow predictions for active matches")
    run_shadow.add_argument("config_version_id")

    eval_shadow = sub.add_parser("evaluate-shadow", help="Evaluate pending shadow predictions")
    eval_shadow.add_argument("config_version_id")

    shadow_metrics = sub.add_parser("shadow-metrics", help="Show shadow validation metrics")
    shadow_metrics.add_argument("config_version_id")

    eval_promo = sub.add_parser("evaluate-promotion", help="Evaluate shadow promotion gate")
    eval_promo.add_argument("config_version_id")

    activate = sub.add_parser("activate-filter-only", help="Manually activate FILTER_ONLY after promotion gate")
    activate.add_argument("config_version_id")
    activate.add_argument("--confirm", action="store_true")
    activate.add_argument("--force", action="store_true")

    history = sub.add_parser("import-history", help="Import historical match CSV")
    history.add_argument("csv")

    collect = sub.add_parser("sync-history", help="Incrementally sync real historical CSV sources")
    collect.add_argument("--years-back", type=int, default=settings.historical_data_years_back)
    collect.add_argument("--divisions", default="", help="Comma-separated division codes, e.g. E0,D1,I1,SP1")

    worldwide = sub.add_parser("sync-worldwide-history", help="Sync Football-Data worldwide CSV history")
    worldwide.add_argument("--divisions", default="", help="Comma-separated codes, e.g. FIN,USA,BRA,JPN")

    sub.add_parser("sync-international-history", help="Sync real international-team historical results")

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
    elif args.command == "sync-worldwide-history":
        from .historical_agent import HistoricalCollectionAgent
        from .llm import QwenOpsAgent
        db.initialize()
        divisions = [item.strip().upper() for item in args.divisions.split(",") if item.strip()]
        report = HistoricalCollectionAgent().sync_worldwide(divisions or None)
        print(json.dumps(QwenOpsAgent().attach("historical-worldwide-data-agent", report), ensure_ascii=False, indent=2))
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
    elif args.command == "optimize-edge-quality":
        from .edge_quality_optimizer import run_edge_quality_optimization, write_optimization_json
        with Path(args.csv).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if args.from_date:
            rows = [row for row in rows if str(row.get("date") or row.get("kickoff_time") or "") >= args.from_date]
        if args.to_date:
            rows = [row for row in rows if str(row.get("date") or row.get("kickoff_time") or "") <= args.to_date]
        if args.league:
            rows = [row for row in rows if args.league.lower() in str(row.get("league") or "").lower()]
        result = run_edge_quality_optimization(rows, None, None, {
            "max_configs": args.max_configs,
            "min_samples": args.min_samples,
            "shadow_only": args.shadow_only,
        })
        if args.output and not args.no_write:
            write_optimization_json(result, args.output)
        best = result.ranking[0] if result.ranking else None
        summary = {
            "title": "Edge Quality Optimization",
            "configs_tested": len(result.variant_results),
            "matches": result.baseline_metrics.get("sample_count", 0),
            "baseline_recommendations": result.baseline_metrics.get("recommendation_count", 0),
            "best_config": result.best_config.to_dict() if result.best_config else None,
            "best_metrics": best["metrics"] if best else None,
            "promotion_decision": result.promotion_decision,
            "recommended_for_production": result.recommended_for_production,
            "promotion_reasons": result.promotion_reasons,
            "warnings": result.warnings,
            "output": args.output if args.output and not args.no_write else None,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.command == "create-shadow-config":
        from .shadow_prediction_store import ShadowPredictionStore
        from .true_odds_config import TrueOddsFilterConfig, get_default_true_odds_filter_config
        db.initialize()
        config = get_default_true_odds_filter_config()
        summary = None
        if args.optimization_json:
            payload = json.loads(Path(args.optimization_json).read_text(encoding="utf-8"))
            best = payload.get("best_config") or payload.get("bestConfig")
            if best:
                config = TrueOddsFilterConfig(**{**config.to_dict(), **best})
            summary = payload
        version = ShadowPredictionStore().create_config_version(config, args.from_optimization or None, summary, args.name)
        print(json.dumps(version.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "start-shadow-validation":
        from .shadow_prediction_store import ShadowPredictionStore
        db.initialize()
        print(json.dumps(ShadowPredictionStore().start_shadow_validation(args.config_version_id).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "run-shadow":
        from .live_shadow_validation import run_shadow_for_active_matches
        db.initialize()
        print(json.dumps(run_shadow_for_active_matches(args.config_version_id), ensure_ascii=False, indent=2))
    elif args.command == "evaluate-shadow":
        from .shadow_evaluator import evaluate_pending_shadow_predictions
        db.initialize()
        print(json.dumps(evaluate_pending_shadow_predictions(args.config_version_id), ensure_ascii=False, indent=2))
    elif args.command == "shadow-metrics":
        from .shadow_evaluator import build_shadow_validation_metrics
        db.initialize()
        print(json.dumps(build_shadow_validation_metrics(args.config_version_id).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "evaluate-promotion":
        from .promotion_gate import evaluate_promotion_gate, save_promotion_gate_result
        from .shadow_evaluator import build_shadow_validation_metrics
        from .shadow_prediction_store import ShadowPredictionStore
        db.initialize()
        store = ShadowPredictionStore()
        version = store.get_config_version(args.config_version_id)
        if not version:
            raise SystemExit(f"config version not found: {args.config_version_id}")
        metrics = build_shadow_validation_metrics(args.config_version_id)
        result = evaluate_promotion_gate(metrics, version)
        save_promotion_gate_result(result, metrics)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "activate-filter-only":
        from .shadow_prediction_store import ShadowPredictionStore
        db.initialize()
        print(json.dumps(ShadowPredictionStore().activate_filter_only(args.config_version_id, args.confirm, args.force).to_dict(), ensure_ascii=False, indent=2))
    else:
        with Path(args.csv).open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        report = BacktestEngine(args.min_ev).run(rows, args.bankroll)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
