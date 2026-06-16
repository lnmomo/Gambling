from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RiskLimits:
    min_ev: float = 0.05
    min_source_confidence: float = 0.70
    max_model_disagreement: float = 0.06
    max_odds_age_minutes: int = 10
    max_single_fraction: float = 0.01
    max_daily_fraction: float = 0.03
    max_weekly_fraction: float = 0.08
    stop_after_losses: int = 3


def allowed_odds_age_minutes(kickoff_time: str | None = None, default_minutes: int = 10,
                             now: datetime | None = None) -> int:
    if not kickoff_time:
        return default_minutes
    now = now or datetime.now(timezone.utc)
    try:
        kickoff = datetime.fromisoformat(kickoff_time.replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
    except ValueError:
        return default_minutes
    minutes_to_kickoff = (kickoff - now).total_seconds() / 60
    if minutes_to_kickoff <= 120:
        return 15
    if minutes_to_kickoff <= 720:
        return 120
    return 360


def fractional_kelly(probability: float, odds: float, fraction: float = 0.25) -> float:
    if odds <= 1:
        return 0.0
    full = (probability * odds - 1) / (odds - 1)
    return max(0.0, full * fraction)


def calculate_stake(bankroll: float, probability: float, odds: float, limits: RiskLimits,
                    daily_exposure: float = 0, weekly_exposure: float = 0) -> float:
    kelly = fractional_kelly(probability, odds)
    available_daily = max(0.0, limits.max_daily_fraction * bankroll - daily_exposure)
    available_weekly = max(0.0, limits.max_weekly_fraction * bankroll - weekly_exposure)
    return round(min(kelly * bankroll, limits.max_single_fraction * bankroll,
                     available_daily, available_weekly), 2)


class CriticPolicy:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def evaluate(self, *, odds_fetched_at: str | None, source_confidence: float, disagreement: float,
                 ev: float, match_status: str, backtest_roi: float | None = None,
                 daily_exposure_fraction: float = 0, weekly_exposure_fraction: float = 0,
                 consecutive_losses: int = 0, kickoff_time: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        max_age = allowed_odds_age_minutes(kickoff_time, self.limits.max_odds_age_minutes, now)
        try:
            fetched = datetime.fromisoformat(odds_fetched_at) if odds_fetched_at else None
            if fetched and fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            age = (now - fetched).total_seconds() / 60 if fetched else float("inf")
        except ValueError:
            age = float("inf")
        checks = {
            "data_fresh": age <= max_age,
            "source_reliable": source_confidence >= self.limits.min_source_confidence,
            "models_agree": disagreement <= self.limits.max_model_disagreement,
            "ev_sufficient": ev >= self.limits.min_ev,
            "match_open": match_status == "scheduled",
            "backtest_supported": backtest_roi is None or backtest_roi > 0,
            "daily_limit_ok": daily_exposure_fraction < self.limits.max_daily_fraction,
            "weekly_limit_ok": weekly_exposure_fraction < self.limits.max_weekly_fraction,
            "loss_pause_clear": consecutive_losses < self.limits.stop_after_losses,
        }
        labels = {
            "data_fresh": "官方赔率已过期或缺失",
            "source_reliable": "数据来源置信度不足",
            "models_agree": "模型分歧超过阈值",
            "ev_sufficient": "理论 EV 未达到 5% 门槛",
            "match_open": "比赛不处于可评估状态",
            "backtest_supported": "同类历史回测不支持该信号",
            "daily_limit_ok": "单日风险额度已用尽",
            "weekly_limit_ok": "单周风险额度已用尽",
            "loss_pause_clear": "连续亏损达到暂停阈值",
        }
        reasons = [labels[key] for key, passed in checks.items() if not passed]
        passed = all(checks.values())
        failures = len(reasons)
        risk_level = "LOW" if passed else "MEDIUM" if failures <= 2 else "HIGH"
        return {"passed": passed, "risk_level": risk_level, "checks": checks, "reasons": reasons,
                "data_freshness": {"age_minutes": age, "allowed_minutes": max_age}}
