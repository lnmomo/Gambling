from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from ..config import settings
from .http import get_json

TEAM_ALIASES = {
    "美国":"unitedstates", "德国":"germany", "澳大利亚":"australia", "瑞士":"switzerland",
    "巴拿马":"panama", "波黑":"bosniaandherzegovina", "英格兰":"england", "新西兰":"newzealand",
    "玻利维亚":"bolivia", "苏格兰":"scotland", "巴西":"brazil", "埃及":"egypt",
    "委内瑞拉":"venezuela", "土耳其":"turkey", "阿根廷":"argentina", "洪都拉斯":"honduras",
    "克罗地亚":"croatia", "斯洛文尼":"slovenia", "斯洛文尼亚":"slovenia", "摩洛哥":"morocco",
    "挪威":"norway", "加拿大":"canada", "巴拉圭":"paraguay", "荷兰":"netherlands",
    "日本":"japan", "西班牙":"spain", "法国":"france", "意大利":"italy", "葡萄牙":"portugal",
    "墨西哥":"mexico", "韩国":"southkorea", "比利时":"belgium", "乌拉圭":"uruguay",
}


def normalize_team(name: str) -> str:
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", name.lower())
    return TEAM_ALIASES.get(compact, compact)


class OddsApiClient:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def configured(self) -> bool:
        return bool(settings.odds_api_key)

    def events(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        if not self.configured():
            return [], {}
        self.warnings = []
        output: list[dict[str, Any]] = []
        response_headers: dict[str, str] = {}
        sports, response_headers = get_json(
            f"{settings.odds_api_base_url}/sports", {"apiKey": settings.odds_api_key},
            settings.enrichment_timeout_seconds,
        )
        active_keys = {item.get("key") for item in sports if item.get("active")}
        selected = [sport for sport in settings.odds_api_sport_keys if sport in active_keys]
        missing = [sport for sport in settings.odds_api_sport_keys if sport not in active_keys]
        if missing:
            self.warnings.append("The Odds API 当前无可用项目: " + ", ".join(missing))
        if not selected:
            raise RuntimeError("配置的 ODDS_API_SPORT_KEYS 当前均不可用")
        for sport in selected:
            data, response_headers = get_json(
                f"{settings.odds_api_base_url}/sports/{sport}/odds",
                {"apiKey": settings.odds_api_key, "regions": "uk,eu", "markets": "h2h", "oddsFormat": "decimal"},
                settings.enrichment_timeout_seconds,
            )
            output.extend(data)
        return output, response_headers

    @staticmethod
    def match_event(match: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
        kickoff = datetime.fromisoformat(match["kickoff_time"])
        best: tuple[float, dict[str, Any]] | None = None
        home = normalize_team(match["home_team"]); away = normalize_team(match["away_team"])
        for event in events:
            event_time = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
            if abs((event_time - kickoff).total_seconds()) > 8 * 3600:
                continue
            direct = (SequenceMatcher(None, home, normalize_team(event["home_team"])).ratio() +
                      SequenceMatcher(None, away, normalize_team(event["away_team"])).ratio()) / 2
            reverse = (SequenceMatcher(None, home, normalize_team(event["away_team"])).ratio() +
                       SequenceMatcher(None, away, normalize_team(event["home_team"])).ratio()) / 2
            score = max(direct, reverse)
            if score >= 0.72 and (best is None or score > best[0]):
                best = (score, event)
        return best[1] if best else None

    @staticmethod
    def bookmaker_odds(event: dict[str, Any]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        home = event["home_team"]; away = event["away_team"]
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                odds: dict[str, float] = {}
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    key = "home" if name == home else "away" if name == away else "draw" if name == "Draw" else None
                    if key and float(outcome.get("price", 0)) > 1:
                        odds[key] = float(outcome["price"])
                if set(odds) == {"home", "draw", "away"}:
                    output.append({"bookmaker": bookmaker.get("title") or bookmaker.get("key") or "Unknown",
                                   "bookmaker_key": bookmaker.get("key"), "market": "H2H", "odds": odds,
                                   "last_update": market.get("last_update") or bookmaker.get("last_update")})
        return output

    @staticmethod
    def consensus(event: dict[str, Any]) -> dict[str, float] | None:
        bookmaker_probabilities: list[dict[str, float]] = []
        for item in OddsApiClient.bookmaker_odds(event):
            odds = item["odds"]
            inverse = {key: 1 / value for key, value in odds.items()}
            overround_total = sum(inverse.values())
            bookmaker_probabilities.append(
                {key: probability / overround_total for key, probability in inverse.items()}
            )
        if not bookmaker_probabilities:
            return None
        consensus_probability = {
            key: sum(item[key] for item in bookmaker_probabilities) / len(bookmaker_probabilities)
            for key in ("home", "draw", "away")
        }
        return {key: round(1 / probability, 4) for key, probability in consensus_probability.items()}
