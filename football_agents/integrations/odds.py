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

# Source pages use abbreviated Chinese club names while The Odds API uses the
# clubs' international names. Unicode escapes keep this mapping encoding-safe.
TEAM_ALIASES.update({
    "\u74e6\u52d2\u4f26\u52a0": "valerenga",
    "\u5965\u52d2\u677e": "alesund",
    "\u535a\u5854\u5f17\u6208": "botafogo",
    "\u6851\u6258\u65af": "santos",
    "\u7ef4\u591a\u5229\u4e9a": "vitoria",
    "\u8fbe\u4f3d\u9a6c": "vascodagama",
    "\u8499\u7279\u5229\u5c14": "cfmontreal",
    "\u591a\u4f26\u591a": "torontofc",
    "\u829d\u52a0\u54e5": "chicagofire",
    "\u6e29\u54e5\u534e": "vancouverwhitecaps",
    "\u5723\u8def\u6613\u57ce": "stlouiscitysc",
    "\u582a\u8428\u65af\u57ce": "sportingkansascity",
    "\u897f\u96c5\u56fe": "seattlesounders",
    "\u6ce2\u7279\u5170": "portlandtimbers",
    "\u54e5\u5fb7\u5821": "ifkgoteborg",
    "\u5e03\u9c81\u9a6c\u6ce2": "brommapojkarna",
    "\u7c73\u4e9a\u5c14\u6bd4": "mjallby",
    "\u97e6\u65af\u7279\u7f57": "vasterassk",
    "\u535a\u5fb7\u95ea\u8000": "bodoglimt",
    "\u8153\u7279\u70c8": "fredrikstad",
    "\u5df4\u4f0a\u4e9a": "bahia",
    "\u6c99\u4f69\u79d1": "chapecoense",
    "\u5f17\u9c81\u7c73\u5ae9": "fluminense",
    "\u5e03\u62c9\u5e72rb": "redbullbragantino",
    "\u7c73\u62c9\u7d22\u5c14": "mirassol",
    "\u683c\u96f7\u7c73\u5965": "gremio",
    "\u7eb3\u4ec0\u7ef4\u5c14": "nashvillesc",
    "\u4e9a\u7279\u8054": "atlantaunited",
})

LEAGUE_SPORT_KEYS = {
    "\u4e16\u754c\u676f": "soccer_fifa_world_cup",
    "\u5df4\u7532": "soccer_brazil_campeonato",
    "\u5df4\u897f\u7532": "soccer_brazil_campeonato",
    "\u7f8e\u804c": "soccer_usa_mls",
    "mls": "soccer_usa_mls",
    "\u632a\u8d85": "soccer_norway_eliteserien",
    "\u745e\u8d85": "soccer_sweden_allsvenskan",
    "\u82ac\u8d85": "soccer_finland_veikkausliiga",
    "\u97e9\u804c": "soccer_korea_kleague1",
    "\u82f1\u8d85": "soccer_epl",
    "\u82f1\u51a0": "soccer_efl_champ",
    "\u82f1\u7532": "soccer_england_league1",
    "\u82f1\u4e59": "soccer_england_league2",
    "\u82f1\u8054\u676f": "soccer_england_efl_cup",
    "\u897f\u7532": "soccer_spain_la_liga",
    "\u5fb7\u7532": "soccer_germany_bundesliga",
    "\u5fb7\u4e59": "soccer_germany_bundesliga2",
    "\u5fb7\u4e19": "soccer_germany_liga3",
    "\u5fb7\u56fd\u676f": "soccer_germany_dfb_pokal",
    "\u610f\u7532": "soccer_italy_serie_a",
    "\u6cd5\u7532": "soccer_france_ligue_one",
    "\u8377\u7532": "soccer_netherlands_eredivisie",
    "\u82cf\u8d85": "soccer_spl",
    "\u6bd4\u7532": "soccer_belgium_first_div",
    "\u5965\u7532": "soccer_austria_bundesliga",
    "\u4e39\u8d85": "soccer_denmark_superliga",
    "\u745e\u58eb\u8d85": "soccer_switzerland_superleague",
    "\u4fc4\u8d85": "soccer_russia_premier_league",
    "\u58a8\u8d85": "soccer_mexico_ligamx",
    "\u4e2d\u8d85": "soccer_china_superleague",
    "\u963f\u7532": "soccer_argentina_primera_division",
    "\u5df4\u4e59": "soccer_brazil_serie_b",
    "\u667a\u7532": "soccer_chile_campeonato",
    "\u745e\u5178\u7532": "soccer_sweden_superettan",
    "\u89e3\u653e\u8005\u676f": "soccer_conmebol_copa_libertadores",
    "\u5357\u7f8e\u676f": "soccer_conmebol_copa_sudamericana",
}


def normalize_team(name: str) -> str:
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", name.lower())
    return TEAM_ALIASES.get(compact, compact)


class OddsApiClient:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def configured(self) -> bool:
        return bool(settings.odds_api_key)

    @staticmethod
    def sport_keys_for_leagues(leagues: set[str]) -> tuple[str, ...]:
        keys = {
            LEAGUE_SPORT_KEYS[compact]
            for league in leagues
            if (compact := re.sub(r"\s+", "", str(league).strip().lower())) in LEAGUE_SPORT_KEYS
        }
        return tuple(sorted(keys))

    def events(self, leagues: set[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
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
        configured = settings.odds_api_sport_keys
        derived = self.sport_keys_for_leagues(leagues or set())
        requested = derived if settings.odds_api_auto_sport_keys and derived else configured
        selected = [sport for sport in requested if sport in active_keys]
        missing = [sport for sport in requested if sport not in active_keys]
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
