from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agents import DecisionWorkflow
from .backtesting import BacktestEngine
from .config import settings
from .db import db
from .official_data import OfficialDataService
from .integrations import DataEnrichmentService
from .llm import LLMNewsAgent
from .repository import Repository
from .schemas import BacktestRequest, EvaluateRequest, FeatureCreate, MatchCreate, MatchMetadataCreate, OddsCreate, SettingsUpdate


WEB_DIR = Path(__file__).with_name("web")
app = FastAPI(
    title="竞彩足球多 Agent 概率决策辅助系统",
    version="1.0.0",
    description="概率研究、赔率比较、风险控制与复盘；不保证收益，不自动下单。",
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
repository = Repository()
workflow = DecisionWorkflow(repository)
official_data = OfficialDataService(repository)
enrichment = DataEnrichmentService(repository)
llm_news = LLMNewsAgent(repository)


@app.on_event("startup")
def startup() -> None:
    db.initialize()


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.app_env, "disclaimer": "仅供概率研究与理性决策参考"}


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
    return workflow.evaluate(match_id)


@app.get("/api/predictions/{match_id}")
def prediction(match_id: int) -> dict:
    _require_match(match_id)
    result = repository.latest_prediction(match_id)
    if not result:
        raise HTTPException(404, "尚无预测，请先执行 evaluate")
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
        "rules": ["四分之一凯利", "连续亏损 3 单暂停", "禁止倍投和追损", "系统不执行自动下单"],
    }


@app.post("/api/official/sync")
def sync_official_data(force: bool = False) -> dict:
    try:
        return official_data.sync(force=force)
    except Exception as exc:
        raise HTTPException(502, f"官方数据同步失败: {exc}") from exc


@app.get("/api/official/status")
def official_data_status() -> dict:
    return official_data.status()


@app.get("/api/official/matches")
def official_matches() -> list[dict]:
    output = []
    for match in repository.list_official_matches():
        odds = repository.latest_odds(match["id"])
        market = repository.latest_odds(match["id"], external=True)
        prediction = repository.latest_prediction(match["id"])
        output.append({**match, "official_odds": odds["odds"],
                       "odds_fetched_at": odds["fetched_at"], "odds_source": odds["source"],
                       "market_odds": market["odds"], "market_odds_source": market["source"],
                       "prediction": prediction, "news": repository.list_news(match["id"], 5),
                       "weather": repository.latest_weather(match["id"]),
                       "metadata": repository.get_match_metadata(match["id"]),
                       "signal": repository.latest_signal(match["id"]),
                       "llm_analysis": repository.latest_llm_analysis(match["id"]),
                       "features": repository.latest_features(match["id"])})
    return output


@app.post("/api/data/sync")
def sync_external_data(limit: int = 40) -> dict:
    return enrichment.sync(max(1, min(limit, 100)))


@app.get("/api/data/status")
def external_data_status() -> dict:
    return enrichment.status()


@app.get("/api/llm/status")
def llm_status() -> dict:
    return llm_news.status()


@app.post("/api/llm/analyze/{match_id}")
def analyze_match_news(match_id: int, force: bool = False) -> dict:
    _require_match(match_id)
    try:
        return llm_news.analyze(match_id, force=force)
    except Exception as exc:
        raise HTTPException(502, f"大模型新闻分析失败: {exc}") from exc


@app.get("/api/system/overview")
def system_overview() -> dict:
    counts = repository.data_counts()
    providers = repository.provider_status()
    official = repository.latest_fetch_log()
    agents = [
        {"id": "official", "name": "官方赛程Agent", "state": "RUNNING" if official and official["success"] else "WARNING",
         "success_rate": 100 if official and official["success"] else 0, "latency": "按需同步",
         "task_count": official["record_count"] if official else 0, "last_updated": official["fetched_at"] if official else None},
    ]
    provider_names = {"the_odds_api":"赔率采集Agent", "news_aggregator":"新闻Agent", "gdelt":"新闻Agent", "open_meteo":"天气Agent"}
    for item in providers:
        state = "RUNNING" if item["status"] == "success" else "DELAYED" if item["status"] in {"waiting_metadata", "not_configured"} else "WARNING"
        agents.append({"id": item["provider"], "name": provider_names.get(item["provider"], item["provider"]),
                       "state": state, "success_rate": 100 if state == "RUNNING" else 0,
                       "latency": item["status"], "task_count": item["records"], "last_updated": item["synced_at"]})
    agents.extend([
        {"id":"features","name":"特征工程Agent","state":"RUNNING" if counts["features"] else "DELAYED",
         "success_rate":0,"latency":"等待真实球队特征","task_count":counts["features"],"last_updated":None},
        {"id":"prediction","name":"概率预测Agent","state":"RUNNING" if counts["predictions"] else "DELAYED",
         "success_rate":0,"latency":"等待完整输入","task_count":counts["predictions"],"last_updated":None},
        {"id":"decision","name":"推荐决策Agent","state":"RUNNING","success_rate":100,
         "latency":"按需评估","task_count":counts["signals"],"last_updated":None},
    ])
    return {"counts": counts, "agents": agents, "logs": repository.list_audit_events(100),
            "alerts": [log for log in repository.list_audit_events(100) if str(log["result"]).lower() not in {"成功","success"}][:20]}


@app.get("/api/audit-logs")
def audit_logs(limit: int = 200) -> list[dict]:
    return repository.list_audit_events(max(1, min(limit, 500)))


@app.get("/api/notifications")
def notifications() -> list[dict]:
    items = []
    for log in repository.list_audit_events(100):
        if str(log["result"]).lower() not in {"成功", "success"}:
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
    report = BacktestEngine(payload.min_ev).run([row.model_dump(mode="json") for row in payload.rows], payload.bankroll)
    repository.save_backtest(report["id"], payload.name, report["parameters"], report["metrics"], report["equity"])
    return report


@app.post("/api/backtest/upload-csv")
async def upload_backtest(file: UploadFile = File(...), bankroll: float = 10_000, min_ev: float = 0.05) -> dict:
    try:
        text = (await file.read()).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        for row in rows:
            for key in ("home_score", "away_score"):
                row[key] = int(row[key])
            for key in ("sp_home", "sp_draw", "sp_away", "market_home", "market_draw", "market_away", "lambda_home", "lambda_away"):
                if row.get(key):
                    row[key] = float(row[key])
        report = BacktestEngine(min_ev).run(rows, bankroll)
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"CSV 格式错误: {exc}") from exc
    repository.save_backtest(report["id"], file.filename or "CSV backtest", report["parameters"], report["metrics"], report["equity"])
    return report


@app.get("/api/backtest/reports/{report_id}")
def backtest_report(report_id: str) -> dict:
    report = repository.get_backtest(report_id)
    if not report:
        raise HTTPException(404, "回测报告不存在")
    return report


@app.get("/{frontend_path:path}", include_in_schema=False)
def frontend_routes(frontend_path: str) -> FileResponse:
    """Serve the React application for client-side routes."""
    return FileResponse(WEB_DIR / "index.html")


def _require_match(match_id: int) -> None:
    if not repository.get_match(match_id):
        raise HTTPException(404, "比赛不存在")

