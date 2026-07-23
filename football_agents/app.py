from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agents import DecisionWorkflow
from .agents.orchestrator import AgentOrchestrator
from .backtesting import BacktestEngine
from .config import settings
from .db import db
from .official_data import OfficialDataService
from .integrations import DataEnrichmentService
from .llm import LLMNewsAgent, QwenOpsAgent
from .historical_data import HistoricalDataService
from .historical_agent import HistoricalCollectionAgent
from .health import build_health_report
from .international_history_agent import InternationalHistoryAgent
from .features import build_features_for_official_matches
from .external_consensus_challenger import ExternalConsensusChallengerService
from .profit_allocation_readiness import build_profit_allocation_readiness
from .paper_portfolio import PaperPortfolioService
from .profit_data_domain_readiness import build_profit_data_domain_readiness
from .repository import Repository
from .schemas import BacktestRequest, EvaluateRequest, FeatureCreate, MatchCreate, MatchMetadataCreate, OddsCreate, ResultCreate, SettingsUpdate
from .scheduler import BackgroundAgentScheduler
from .services.task_runner_service import TaskRunnerService
from .research.prospective import ProspectiveResearchService


WEB_DIR = Path(__file__).with_name("web")
app = FastAPI(
    title="竞彩足球多 Agent 概率决策辅助系统",
    version="1.0.0",
    description="概率研究、赔率比较、风险控制与复盘；不保证收益，不自动下单。",
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.middleware("http")
async def disable_frontend_asset_cache(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if request.url.path.startswith("/static/") or content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


repository = Repository()
workflow = DecisionWorkflow(repository)
official_data = OfficialDataService(repository)
enrichment = DataEnrichmentService(repository)
llm_news = LLMNewsAgent(repository)
qwen_ops = QwenOpsAgent()
historical_data = HistoricalDataService(repository)
historical_agent = HistoricalCollectionAgent(repository)
international_history_agent = InternationalHistoryAgent(repository)
agent_orchestrator = AgentOrchestrator(repository)
task_runner = TaskRunnerService()
background_scheduler = BackgroundAgentScheduler(repository, task_runner)
prospective_research = ProspectiveResearchService(repository.db, repository, workflow)
external_consensus_challenger = ExternalConsensusChallengerService(repository.db, repository)


@app.on_event("startup")
def startup() -> None:
    db.initialize()
    historical_data.bootstrap_sample()
    background_scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    background_scheduler.stop()


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return build_health_report()


@app.post("/api/matches", status_code=201)
def create_match(payload: MatchCreate) -> dict:
    match_id = repository.create_match(payload.model_dump(mode="json"))
    return repository.get_match(match_id) or {}


@app.get("/api/matches/today")
def matches_today(target_date: date | None = None) -> list[dict]:
    return repository.list_matches((target_date or date.today()).isoformat())


@app.get("/api/matches")
def matches() -> list[dict]:
    return repository.list_matches()


@app.post("/api/matches/{match_id}/odds", status_code=201)
def add_official_odds(match_id: int, payload: OddsCreate) -> dict:
    _require_match(match_id)
    repository.add_odds(match_id, payload.odds.model_dump(), payload.source, payload.fetched_at.isoformat())
    return repository.latest_odds(match_id)


@app.post("/api/matches/{match_id}/market-odds", status_code=201)
def add_market_odds(match_id: int, payload: OddsCreate) -> dict:
    _require_match(match_id)
    repository.add_odds(match_id, payload.odds.model_dump(), payload.source, payload.fetched_at.isoformat(), external=True)
    return repository.latest_odds(match_id, external=True)


@app.post("/api/matches/{match_id}/features", status_code=201)
def add_features(match_id: int, payload: FeatureCreate) -> dict:
    _require_match(match_id)
    repository.add_features(match_id, payload.model_dump())
    return payload.model_dump()


@app.get("/api/matches/{match_id}/odds")
def get_odds(match_id: int) -> dict:
    _require_match(match_id)
    return {"official": repository.latest_odds(match_id), "market": repository.latest_odds(match_id, external=True)}


@app.post("/api/matches/{match_id}/evaluate")
def evaluate(match_id: int, payload: EvaluateRequest | None = None) -> dict:
    _require_match(match_id)
    if payload:
        timestamp = payload.fetched_at.isoformat() if payload.fetched_at else None
        if payload.official_odds:
            repository.add_odds(match_id, payload.official_odds.model_dump(), payload.official_source, timestamp)
        if payload.market_odds:
            repository.add_odds(match_id, payload.market_odds.model_dump(), payload.market_source, timestamp, external=True)
        if payload.features:
            repository.add_features(match_id, payload.features.model_dump())
    return qwen_ops.attach("model-critic-agent", workflow.evaluate(match_id))


@app.get("/api/predictions/{match_id}")
def prediction(match_id: int) -> dict:
    _require_match(match_id)
    result = repository.latest_prediction(match_id)
    if not result:
        raise HTTPException(404, "灏氭棤棰勬祴锛岃鍏堟墽琛?evaluate")
    return result


@app.get("/api/signals/today")
def signals_today() -> list[dict]:
    return repository.list_signals()


@app.get("/api/risk/bankroll/status")
def bankroll_status() -> dict:
    return {
        "bankroll": settings.bankroll,
        "single_limit": settings.bankroll * settings.max_single_stake,
        "daily_limit": settings.bankroll * settings.max_daily_exposure,
        "weekly_limit": settings.bankroll * settings.max_weekly_exposure,
        "rules": ["四分之一 Kelly", "连续亏损 3 单暂停", "禁止倍投和追损", "系统不执行自动下单"],
    }


@app.get("/api/profit/allocation-readiness")
def profit_allocation_readiness(daily_budget: float | None = None) -> dict:
    return build_profit_allocation_readiness(daily_budget)


@app.get("/api/profit/paper-portfolio")
def paper_portfolio() -> dict:
    return PaperPortfolioService(db).summary()


@app.get("/api/profit/data-domain-readiness")
def profit_data_domain_readiness() -> dict:
    return build_profit_data_domain_readiness(database=db)


@app.post("/api/official/sync")
def sync_official_data(force: bool = False) -> dict:
    task = task_runner.start_task_run("official_sp_sync")
    try:
        report = qwen_ops.attach("official-data-agent", official_data.sync(force=force))
        task_runner.finish_task_run_success(task["id"], affected_matches=report.get("matches", report.get("upserted", 0)),
                                            created_snapshots=report.get("hourly_observations", report.get("odds_snapshots", report.get("snapshots", 0))),
                                            warnings=report.get("warnings", []))
        return report
    except Exception as exc:
        task_runner.finish_task_run_failed(task["id"], str(exc))
        raise HTTPException(502, f"瀹樻柟鏁版嵁鍚屾澶辫触: {exc}") from exc


@app.get("/api/official/status")
def official_data_status() -> dict:
    return official_data.status()


@app.get("/api/official/odds-observations")
def official_odds_observations(official_match_id: str | None = None, limit: int = 1000) -> list[dict]:
    return repository.list_official_odds_observations(official_match_id, limit)


@app.get("/api/official/odds-timeseries/status")
def official_odds_timeseries_status() -> dict:
    return repository.official_odds_timeseries_status()


@app.get("/api/official/training-samples")
def official_odds_training_samples(limit: int = 10_000) -> list[dict]:
    return repository.list_official_odds_training_samples(limit)


@app.get("/api/research/prospective/status")
def prospective_research_status(study_id: str | None = None) -> dict:
    return prospective_research.progress(study_id)


@app.post("/api/research/prospective/capture")
def capture_prospective_research(limit: int = 100, study_id: str | None = None) -> dict:
    try:
        return prospective_research.capture(limit, study_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/research/prospective/confirm")
def confirm_prospective_research(study_id: str | None = None) -> dict:
    try:
        return prospective_research.run_confirmation_once(study_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/research/external-consensus-challenger")
def external_consensus_challenger_status(policy_id: str | None = None) -> dict:
    try:
        return external_consensus_challenger.report(policy_id)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown external consensus policy: {exc}") from exc


@app.post("/api/research/external-consensus-challenger/capture")
def capture_external_consensus_challenger(limit: int = 100) -> dict:
    result = external_consensus_challenger.capture(limit)
    path = Path(settings.external_consensus_challenger_report_path)
    if not path.is_absolute():
        path = settings.project_dir / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result["report"], ensure_ascii=False, indent=2), encoding="utf-8")
    return result


@app.post("/api/matches/{match_id}/result")
def save_match_result(match_id: int, payload: ResultCreate) -> dict:
    _require_match(match_id)
    return repository.upsert_result(
        match_id, payload.home_score, payload.away_score,
        payload.settled_at.isoformat() if payload.settled_at else None,
    )


@app.get("/api/official/matches")
def official_matches(target_date: date | None = None) -> list[dict]:
    china_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    selected_date = (target_date or china_today).isoformat()
    output = []
    for match in repository.list_official_matches(selected_date):
        odds = repository.latest_odds(match["id"])
        market = repository.latest_odds(match["id"], external=True)
        prediction = repository.latest_prediction(match["id"])
        output.append({**match, "official_odds": odds["odds"],
                       "odds_fetched_at": odds["fetched_at"], "odds_source": odds["source"],
                       "market_odds": market["odds"], "market_odds_source": market["source"],
                       "external_bookmaker_odds": repository.latest_external_bookmaker_odds(match["id"]),
                       "prediction": prediction, "news": repository.list_news(match["id"], 5),
                       "weather": repository.latest_weather(match["id"]),
                       "metadata": repository.get_match_metadata(match["id"]),
                       "signal": repository.latest_signal(match["id"]),
                       "llm_analysis": repository.latest_llm_analysis(match["id"]),
                       "features": repository.latest_features(match["id"])})
    return output


@app.get("/api/historical-matches")
def historical_matches(cutoff_time: str | None = None, league: str | None = None,
                       teams: str | None = None, limit: int = 20_000) -> list[dict]:
    team_list = [team.strip() for team in (teams or "").split(",") if team.strip()]
    return repository.list_historical_matches(cutoff_time, league, team_list, limit)


@app.get("/api/historical-matches/status")
def historical_matches_status() -> dict:
    rows = repository.list_historical_matches(limit=100_000)
    leagues = sorted({row["league"] for row in rows})
    teams = {row["home_team"] for row in rows} | {row["away_team"] for row in rows}
    return {"matches": len(rows), "leagues": len(leagues), "teams": len(teams),
            "first_match": rows[0]["played_at"] if rows else None,
            "last_match": rows[-1]["played_at"] if rows else None}


@app.post("/api/features/build")
def build_historical_features(limit: int = 100, include_finished: bool = False,
                              min_matches: int = 10, league: str | None = None) -> dict:
    return build_features_for_official_matches(repository, max(1, min(limit, 200)),
                                               include_finished, max(1, min_matches), league)


@app.post("/api/historical-matches/upload-csv")
async def upload_historical_matches(file: UploadFile = File(...)) -> dict:
    try:
        text = (await file.read()).decode("utf-8-sig")
        report = historical_data.import_csv_text(text, file.filename or "uploaded-csv")
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, f"鍘嗗彶 CSV 鏍煎紡閿欒: {exc}") from exc
    return {**report, **historical_matches_status()}


@app.post("/api/historical-matches/sync")
def sync_historical_matches(years_back: int = settings.historical_data_years_back,
                            divisions: str | None = None) -> dict:
    selected = [item.strip().upper() for item in (divisions or "").split(",") if item.strip()]
    try:
        return qwen_ops.attach("historical-data-agent",
                               historical_agent.sync(max(1, min(years_back, 10)), selected or None))
    except Exception as exc:
        raise HTTPException(502, f"鍘嗗彶鏁版嵁鍚屾澶辫触: {exc}") from exc


@app.post("/api/historical-matches/sync-worldwide")
def sync_worldwide_historical_matches(divisions: str | None = None) -> dict:
    selected = [item.strip().upper() for item in (divisions or "").split(",") if item.strip()]
    try:
        return qwen_ops.attach("historical-worldwide-data-agent",
                               historical_agent.sync_worldwide(selected or None))
    except Exception as exc:
        raise HTTPException(502, f"Worldwide historical data sync failed: {exc}") from exc


@app.post("/api/historical-matches/sync-international")
def sync_international_historical_matches() -> dict:
    try:
        return qwen_ops.attach("international-history-agent", international_history_agent.sync())
    except Exception as exc:
        raise HTTPException(502, f"鍥藉闃熷巻鍙叉暟鎹悓姝ュけ璐? {exc}") from exc


@app.post("/api/data/sync")
def sync_external_data(limit: int = 40) -> dict:
    task = task_runner.start_task_run("external_odds_sync")
    try:
        report = qwen_ops.attach("market-news-weather-agent", enrichment.sync(max(1, min(limit, 100))))
        task_runner.finish_task_run_success(task["id"], affected_matches=report.get("matches", 0),
                                            created_snapshots=report.get("market_odds", 0),
                                            created_predictions=report.get("predictions", 0),
                                            warnings=report.get("odds_warnings", []))
        return report
    except Exception as exc:
        task_runner.finish_task_run_failed(task["id"], str(exc))
        raise


@app.get("/api/data/status")
def external_data_status() -> dict:
    return enrichment.status()


@app.get("/api/llm/status")
def llm_status() -> dict:
    return llm_news.status()


@app.post("/api/agents/run")
def run_agents(limit: int = settings.agent_match_limit, include_history: bool = False,
               force_official: bool = False, force_qwen: bool = False) -> dict:
    return agent_orchestrator.run(max(1, min(limit, 100)), include_history, force_official, force_qwen)


@app.get("/api/agents/status")
def agents_status(limit: int = 20) -> dict:
    return agent_orchestrator.status(max(1, min(limit, 100)))


@app.post("/api/llm/analyze/{match_id}")
def analyze_match_news(match_id: int, force: bool = False) -> dict:
    _require_match(match_id)
    try:
        return llm_news.analyze(match_id, force=force)
    except Exception as exc:
        raise HTTPException(502, f"澶фā鍨嬫柊闂诲垎鏋愬け璐? {exc}") from exc


@app.get("/api/system/overview")
def system_overview() -> dict:
    counts = repository.data_counts()
    providers = repository.provider_status()
    official = repository.latest_fetch_log(settings.official_source_url)
    agents = [
        {"id": "official", "name": "瀹樻柟璧涚▼Agent", "state": "RUNNING" if official and official["success"] else "WARNING",
         "success_rate": 100 if official and official["success"] else 0, "latency": "鎸夐渶鍚屾",
         "task_count": official["record_count"] if official else 0, "last_updated": official["fetched_at"] if official else None},
    ]
    provider_names = {"the_odds_api":"璧旂巼閲囬泦Agent", "news_aggregator":"鏂伴椈Agent", "gdelt":"鏂伴椈Agent", "open_meteo":"澶╂皵Agent"}
    for item in providers:
        state = "RUNNING" if item["status"] == "success" else "DELAYED" if item["status"] in {
            "waiting_metadata", "waiting_horizon", "horizon_captured", "not_configured"
        } else "WARNING"
        agents.append({"id": item["provider"], "name": provider_names.get(item["provider"], item["provider"]),
                       "state": state, "success_rate": 100 if state == "RUNNING" else 0,
                       "latency": item["status"], "task_count": item["records"], "last_updated": item["synced_at"]})
    recent_runs = repository.list_agent_runs(1)
    if recent_runs:
        for step in recent_runs[0]["steps"]:
            state = "RUNNING" if step["status"] == "success" else "DELAYED" if step["status"] == "partial" else "WARNING"
            agents.append({"id": f'run-step-{step["id"]}', "name": step["agent_name"], "state": state,
                           "success_rate": 100 if state == "RUNNING" else 0, "latency": step["status"],
                           "task_count": len(step["output"]), "last_updated": step["finished_at"]})
    return {"counts": counts, "agents": agents, "logs": repository.list_audit_events(100),
            "alerts": [log for log in repository.list_audit_events(100) if str(log["result"]).lower() not in {"鎴愬姛","success"}][:20]}


@app.get("/api/audit-logs")
def audit_logs(limit: int = 200) -> list[dict]:
    return repository.list_audit_events(max(1, min(limit, 500)))


@app.get("/api/notifications")
def notifications() -> list[dict]:
    items = []
    for log in repository.list_audit_events(100):
        if str(log["result"]).lower() not in {"鎴愬姛", "success"}:
            items.append({"id": str(log["id"]), "type": "数据源状态", "title": log["action"],
                          "content": log["detail"], "created_at": log["time"], "read": False})
    return items


@app.get("/api/settings")
def get_settings() -> dict:
    defaults = {"account_name":"admin", "email":"", "refresh_seconds":60, "default_page":"/dashboard",
                "recommendation_notifications":True, "risk_notifications":True, "compact_table":False}
    return {**defaults, **repository.get_settings()}


@app.put("/api/settings")
def save_settings(payload: SettingsUpdate) -> dict:
    return repository.save_settings(payload.values)


@app.get("/api/rules")
def get_rules() -> dict:
    defaults = {"min_ev":settings.min_ev, "max_single_stake":settings.max_single_stake,
                "max_daily_exposure":settings.max_daily_exposure, "max_weekly_exposure":settings.max_weekly_exposure,
                "odds_max_age_minutes":settings.odds_max_age_minutes, "require_market_odds":True,
                "require_team_features":True}
    saved = repository.get_settings().get("rules", {})
    return {**defaults, **saved}


@app.put("/api/rules")
def save_rules(payload: SettingsUpdate) -> dict:
    return repository.save_settings({"rules": payload.values})["rules"]


@app.get("/api/backtest/reports")
def backtest_reports() -> list[dict]:
    return repository.list_backtest_reports()


@app.get("/api/bankroll/history")
def bankroll_history() -> dict:
    return {"status": bankroll_status(), "events": repository.bankroll_history()}


@app.put("/api/matches/{match_id}/metadata")
def update_match_metadata(match_id: int, payload: MatchMetadataCreate) -> dict:
    _require_match(match_id)
    repository.save_match_metadata(match_id, payload.model_dump())
    return repository.get_match_metadata(match_id) or {}


@app.post("/api/backtest/run")
def run_backtest(payload: BacktestRequest) -> dict:
    task = task_runner.start_task_run("backtest_run")
    report = BacktestEngine(payload.min_ev).run([row.model_dump(mode="json") for row in payload.rows], payload.bankroll)
    repository.save_backtest(report["id"], payload.name, report["parameters"], report["metrics"], report["equity"])
    task_runner.finish_task_run_success(task["id"], affected_matches=len(payload.rows))
    return report


@app.post("/api/backtest/upload-csv")
async def upload_backtest(file: UploadFile = File(...), bankroll: float = 10_000, min_ev: float = 0.05) -> dict:
    try:
        text = (await file.read()).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        history_report = repository.upsert_historical_matches(rows, file.filename or "backtest-csv")
        for row in rows:
            for key in ("home_score", "away_score"):
                row[key] = int(row[key])
            for key in ("sp_home", "sp_draw", "sp_away", "market_home", "market_draw", "market_away", "lambda_home", "lambda_away"):
                if row.get(key):
                    row[key] = float(row[key])
        report = BacktestEngine(min_ev).run(rows, bankroll)
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"CSV 鏍煎紡閿欒: {exc}") from exc
    repository.save_backtest(report["id"], file.filename or "CSV backtest", report["parameters"], report["metrics"], report["equity"])
    return report


@app.get("/api/backtest/reports/{report_id}")
def backtest_report(report_id: str) -> dict:
    report = repository.get_backtest(report_id)
    if not report:
        raise HTTPException(404, "回测报告不存在")
    return {**report, "history_import": history_report}


@app.get("/{frontend_path:path}", include_in_schema=False)
def frontend_routes(frontend_path: str) -> FileResponse:
    """Serve the React application for client-side routes."""
    return FileResponse(WEB_DIR / "index.html")


def _require_match(match_id: int) -> None:
    if not repository.get_match(match_id):
        raise HTTPException(404, "比赛不存在")


