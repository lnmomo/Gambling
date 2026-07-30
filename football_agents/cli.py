from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

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

    official_results = sub.add_parser("sync-official-results",
                                      help="Backfill auditable 90-minute final scores from the official result archive")
    official_results.add_argument("--lookback-days", type=int,
                                  default=settings.official_results_lookback_days)

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

    market_bias_monitor = sub.add_parser("refresh-market-bias-monitor", help="Refresh market-bias shadow metrics, official-SP validation, and promotion gate")
    market_bias_monitor.add_argument("--no-run-shadow", action="store_true", help="Only refresh reports; do not create live shadow predictions")
    market_bias_monitor.add_argument("--no-ensure-shadow-config", action="store_true", help="Do not auto-create a market-bias shadow config when none is active")

    eval_promo = sub.add_parser("evaluate-promotion", help="Evaluate shadow promotion gate")
    eval_promo.add_argument("config_version_id")

    official_bias = sub.add_parser("validate-market-bias-official-sp", help="Validate frozen market-bias rule on settled official SP snapshots")
    official_bias.add_argument("--limit", type=int, default=100_000)
    official_bias.add_argument("--strategy-id", default="", help="Optional frozen market-bias strategy id to validate")
    official_bias.add_argument("--output", default="")

    official_bias_diag = sub.add_parser("diagnose-market-bias-official-sp", help="Diagnose why official SP market-bias samples are missing")
    official_bias_diag.add_argument("--limit", type=int, default=100_000)
    official_bias_diag.add_argument("--draw-low", type=float, default=2.8)
    official_bias_diag.add_argument("--draw-high", type=float, default=3.5)
    official_bias_diag.add_argument("--output", default="")

    official_pool_relevance = sub.add_parser("diagnose-market-bias-official-pool", help="Diagnose whether the current official pool is covered by validated market-bias strategies")
    official_pool_relevance.add_argument("--output", default="")

    official_pool_research = sub.add_parser("plan-official-pool-profit-research", help="Plan profit-algorithm experiments from the current official pool")
    official_pool_research.add_argument("--output", default="")

    profit_strategies = sub.add_parser("profit-strategies", help="List validated profit-strategy research packages")
    profit_strategies.add_argument("--output", default="")

    allocation_readiness = sub.add_parser("profit-allocation-readiness", help="Decide whether the daily profit budget can be allocated")
    allocation_readiness.add_argument("--daily-budget", type=float, default=settings.profit_daily_budget)
    allocation_readiness.add_argument("--output", default="")

    domain_readiness = sub.add_parser("profit-data-domain-readiness", help="Rank historical odds domains for the next profit-algorithm search")
    domain_readiness.add_argument("--root", default="data/historical_csv/football-data")
    domain_readiness.add_argument("--output", default="")

    profit_scorer = sub.add_parser("diagnose-profit-scorer-official-pool", help="Score official pool readiness for the exported profit scorer")
    profit_scorer.add_argument("--scorer", default=settings.profit_scorer_artifact_path)
    profit_scorer.add_argument("--limit", type=int, default=500)
    profit_scorer.add_argument("--output", default="")

    profit_scorer_validate = sub.add_parser("validate-profit-scorer-official-sp", help="Prospectively validate the exported profit scorer on earliest pre-match official SP snapshots")
    profit_scorer_validate.add_argument("--scorer", default=settings.profit_scorer_artifact_path)
    profit_scorer_validate.add_argument("--limit", type=int, default=100_000)
    profit_scorer_validate.add_argument("--output", default="")

    official_sp_quality = sub.add_parser("official-sp-evidence-quality", help="Audit official SP freshness, closing-price, and settlement evidence")
    official_sp_quality.add_argument("--output", default=settings.official_sp_evidence_quality_report_path)

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

    sub.add_parser("sync-extra-history", help="Sync licensed CSV URLs from HISTORICAL_DATA_EXTRA_CSV_SOURCES")

    sub.add_parser("sync-international-history", help="Sync real international-team historical results")
    free_history = sub.add_parser("sync-free-historical-data", help="Sync the free international results and World Cup odds evidence plan")
    free_history.add_argument("--with-footiqo-fallback", action="store_true",
                              help="Use Footiqo World Cup closing odds only if the primary free workbook fails")
    free_capture = sub.add_parser("capture-free-prospective-odds", help="Capture quota-aware T-6h/T-1h named-book odds evidence")
    free_capture.add_argument("--limit", type=int, default=settings.agent_match_limit)
    international_odds = sub.add_parser("sync-international-odds-history", help="Sync international-team historical 1X2 odds where available")
    international_odds.add_argument("--provider", choices=["football-data-world-cup", "footiqo", "odds-api"], default="football-data-world-cup")
    international_odds.add_argument("--sport-keys", default="", help="Comma-separated The Odds API sport keys")
    international_odds.add_argument("--from-date", default="2020-06-06")
    international_odds.add_argument("--to-date", default="")
    international_odds.add_argument("--step-days", type=int, default=7)
    international_odds.add_argument("--max-snapshots", type=int, default=10)
    source_research = sub.add_parser("research-international-odds-sources", help="Find usable broad international 1X2 odds data sources")
    source_research.add_argument("--no-probe-api", action="store_true", help="Do not call The Odds API /sports endpoint")
    source_research.add_argument("--output", default="")

    agent_run = sub.add_parser("run-agents", help="Run data, Qwen, model, and critic agents")
    agent_run.add_argument("--limit", type=int, default=settings.agent_match_limit)
    agent_run.add_argument("--include-history", action="store_true")
    agent_run.add_argument("--force-official", action="store_true")
    agent_run.add_argument("--force-qwen", action="store_true")

    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
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
    elif args.command == "sync-official-results":
        from .official_data import OfficialResultService
        from .llm import QwenOpsAgent
        db.initialize()
        report = OfficialResultService().sync()
        print(json.dumps(QwenOpsAgent().attach("official-results-agent", report), ensure_ascii=False, indent=2))
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
    elif args.command == "sync-extra-history":
        from .historical_agent import HistoricalCollectionAgent
        from .llm import QwenOpsAgent
        db.initialize()
        report = HistoricalCollectionAgent().sync_extra()
        print(json.dumps(QwenOpsAgent().attach("historical-extra-data-agent", report), ensure_ascii=False, indent=2))
    elif args.command == "sync-international-history":
        from .international_history_agent import InternationalHistoryAgent
        from .llm import QwenOpsAgent
        db.initialize()
        report = InternationalHistoryAgent().sync()
        print(json.dumps(QwenOpsAgent().attach("international-history-agent", report), ensure_ascii=False, indent=2))
    elif args.command == "sync-free-historical-data":
        from .free_historical_data_plan import FreeHistoricalDataPlan
        db.initialize()
        report = FreeHistoricalDataPlan().sync(args.with_footiqo_fallback)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.command == "capture-free-prospective-odds":
        from .free_prospective import FreeProspectiveOddsService
        db.initialize()
        print(json.dumps(FreeProspectiveOddsService().capture(args.limit), ensure_ascii=False, indent=2))
    elif args.command == "sync-international-odds-history":
        from .international_odds_agent import InternationalOddsHistoryAgent
        from .llm import QwenOpsAgent
        db.initialize()
        agent = InternationalOddsHistoryAgent()
        if args.provider == "odds-api":
            sport_keys = [item.strip() for item in args.sport_keys.split(",") if item.strip()]
            report = agent.sync_odds_api_historical(
                sport_keys or None,
                args.from_date,
                args.to_date or None,
                args.step_days,
                args.max_snapshots,
            )
        elif args.provider == "football-data-world-cup":
            report = agent.sync_football_data_world_cup()
        else:
            report = agent.sync_world_cup()
        print(json.dumps(QwenOpsAgent().attach("international-odds-history-agent", report), ensure_ascii=False, indent=2))
    elif args.command == "research-international-odds-sources":
        from .international_odds_sources import find_international_odds_sources
        payload = find_international_odds_sources(probe_api=not args.no_probe_api)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
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
    elif args.command == "refresh-market-bias-monitor":
        from .market_bias_monitor import MarketBiasMonitorService
        db.initialize()
        print(json.dumps(MarketBiasMonitorService(db).refresh(
            run_shadow=not args.no_run_shadow,
            ensure_shadow_config=not args.no_ensure_shadow_config,
        ), ensure_ascii=False, indent=2))
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
    elif args.command == "validate-market-bias-official-sp":
        from .market_bias_official_validation import validate_market_bias_on_official_sp
        db.initialize()
        result = validate_market_bias_on_official_sp(db, args.limit, args.strategy_id or None)
        payload = result.to_dict()
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "diagnose-market-bias-official-sp":
        from .market_bias_official_validation import diagnose_market_bias_official_sp_funnel
        db.initialize()
        payload = diagnose_market_bias_official_sp_funnel(db, args.limit, args.draw_low, args.draw_high)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "diagnose-market-bias-official-pool":
        from .market_bias_pool_relevance import diagnose_market_bias_official_pool_relevance
        db.initialize()
        payload = diagnose_market_bias_official_pool_relevance(db)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "plan-official-pool-profit-research":
        from .official_pool_research import plan_official_pool_profit_research
        db.initialize()
        payload = plan_official_pool_profit_research(db)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "profit-strategies":
        from .profit_strategy_registry import list_profit_strategy_packages
        payload = {"strategies": list_profit_strategy_packages()}
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "profit-allocation-readiness":
        from .profit_allocation_readiness import build_profit_allocation_readiness
        payload = build_profit_allocation_readiness(args.daily_budget)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "profit-data-domain-readiness":
        from .profit_data_domain_readiness import build_profit_data_domain_readiness
        db.initialize()
        payload = build_profit_data_domain_readiness(Path(args.root), db)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "diagnose-profit-scorer-official-pool":
        from .profit_scorer_official import diagnose_official_profit_scorer_pool
        db.initialize()
        payload = diagnose_official_profit_scorer_pool(db, args.scorer, args.limit)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "validate-profit-scorer-official-sp":
        from .profit_scorer_prospective import validate_profit_scorer_on_official_sp
        db.initialize()
        payload = validate_profit_scorer_on_official_sp(db, args.scorer, args.limit)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "official-sp-evidence-quality":
        from .official_sp_evidence_quality import build_official_sp_evidence_quality
        db.initialize()
        payload = build_official_sp_evidence_quality(db)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
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
