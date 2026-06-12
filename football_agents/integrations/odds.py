from __future__ import annotations

import re
from collections import defaultdict
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
    def configured(self) -> bool:
        return bool(settings.odds_api_key)

    def events(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        if not self.configured():
            return [], {}
        output: list[dict[str, Any]] = []
        response_headers: dict[str, str] = {}
        for sport in settings.odds_api_sport_keys:
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
    def consensus(event: dict[str, Any]) -> dict[str, float] | None:
        prices: dict[str, list[float]] = defaultdict(list)
        home = event["home_team"]; away = event["away_team"]
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    key = "home" if name == home else "away" if name == away else "draw" if name == "Draw" else None
                    if key and float(outcome.get("price", 0)) > 1:
                        prices[key].append(float(outcome["price"]))
        if set(prices) != {"home", "draw", "away"}:
            return None
        return {key: round(sum(values) / len(values), 4) for key, values in prices.items()}
