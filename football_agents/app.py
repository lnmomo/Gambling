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
from .repository import Repository
from .schemas import BacktestRequest, EvaluateRequest, FeatureCreate, MatchCreate, OddsCreate


WEB_DIR = Path(__file__).with_name("web")
app = FastAPI(
    title="竞彩足球多 Agent 概率决策辅助系统",
    version="1.0.0",
    description="概率研究、赔率比较、风险控制与复盘；不保证收益，不自动下单。",
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
repository = Repository()
workflow = DecisionWorkflow(repository)


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


def _require_match(match_id: int) -> None:
    if not repository.get_match(match_id):
        raise HTTPException(404, "比赛不存在")

