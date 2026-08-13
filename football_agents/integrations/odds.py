from __future__ import annotations

import hashlib
import json
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
    # Current official-pool abbreviations for The Odds API's Champions League
    # qualifying and Brazilian Serie A fixtures. These mappings are exact
    # transliterations, never time-only guesses.
    "\u5e93\u5965\u76ae\u5965": "kupskuopio",
    "\u8428\u5df4\u8d6b": "sabahfk",
    "\u54c8\u8328": "hearts",
    "\u683c\u98ce\u66b4": "sksturm",
    "\u963f\u62c9\u6728\u56fe": "fckairat",
    "\u5965\u83ab\u5c3c\u4e9a": "omonoiafc",
    "\u6ce2\u5179\u5357": "lechpoznan",
    "\u5965\u80e1\u65af": "agfaarhus",
    "\u91cc\u83ab": "remo",
    "\u5df4\u897f\u56fd\u9645": "internacional",
    "\u5f17\u62c9\u95e8\u6208": "flamengo",
    "\u5e15\u6885\u62c9\u65af": "palmeiras",
    "\u79d1\u6797\u8482\u5b89": "corinthians",
    "\u5df4\u7ade\u6280": "atleticoparanaense",
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
    # K League official-pool names. The Odds API publishes these clubs in
    # English, while the official Sporttery source uses Chinese short names.
    "\u6d4e\u5ddesk": "jejuunitedfc",
    "\u6c5f\u539ffc": "gangwonfc",
    "\u5168\u5317\u73b0\u4ee3": "jeonbukhundaimotors",
    "\u5927\u7530\u5e02\u6c11": "daejeoncitizen",
    "\u851a\u5c71\u73b0\u4ee3": "ulsanhyundaifc",
    "\u4ec1\u5ddd\u8054": "incheonunited",
})

LEAGUE_SPORT_KEYS = {
    "e0": "soccer_epl",
    "e1": "soccer_efl_champ",
    "bra": "soccer_brazil_campeonato",
    "\u4e16\u754c\u676f": "soccer_fifa_world_cup",
    "\u6b27\u51a0": "soccer_uefa_champs_league_qualification",
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
        self.request_audits: list[dict[str, Any]] = []

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
        self.request_audits = []
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
        try:
            max_sports = max(1, int(settings.prospective_max_active_sports))
        except (TypeError, ValueError):
            max_sports = 3
        selected = selected[:max_sports]
        missing = [sport for sport in requested if sport not in active_keys]
        if missing:
            self.warnings.append("The Odds API 当前无可用项目: " + ", ".join(missing))
        if not selected:
            raise RuntimeError("配置的 ODDS_API_SPORT_KEYS 当前均不可用")
        for sport in selected:
            data, response_headers = get_json(
                f"{settings.odds_api_base_url}/sports/{sport}/odds",
                {"apiKey": settings.odds_api_key, "regions": settings.odds_api_regions,
                 "markets": "h2h", "oddsFormat": "decimal"},
                settings.enrichment_timeout_seconds,
            )
            canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            self.request_audits.append({
                "sport_key": sport,
                "endpoint": f"/sports/{sport}/odds",
                "regions": settings.odds_api_regions,
                "markets": "h2h",
                "estimated_cost": max(1, len([item for item in settings.odds_api_regions.split(",") if item.strip()])),
                "credits_last": response_headers.get("x-requests-last"),
                "credits_remaining": response_headers.get("x-requests-remaining"),
                "credits_used": response_headers.get("x-requests-used"),
                "events_returned": len(data),
                "response_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            })
            output.extend(data)
        return output, response_headers

    def fixture_events(
        self, sport_keys: tuple[str, ...],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Fetch future fixture metadata from the provider's zero-cost endpoint."""
        if not self.configured():
            return [], {}
        output: list[dict[str, Any]] = []
        response_headers: dict[str, str] = {}
        self.request_audits = []
        for sport_key in sport_keys:
            rows, response_headers = get_json(
                f"{settings.odds_api_base_url}/sports/{sport_key}/events",
                {"apiKey": settings.odds_api_key, "dateFormat": "iso"},
                settings.enrichment_timeout_seconds,
            )
            canonical = json.dumps(
                rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            self.request_audits.append({
                "sport_key": sport_key,
                "endpoint": f"/sports/{sport_key}/events",
                "regions": "none",
                "markets": "none",
                "estimated_cost": 0,
                "credits_last": response_headers.get("x-requests-last"),
                "credits_remaining": response_headers.get("x-requests-remaining"),
                "credits_used": response_headers.get("x-requests-used"),
                "events_returned": len(rows),
                "response_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            })
            output.extend(rows)
        return output, response_headers

    def scores(
        self, sport_key: str, days_from: int = 3,
    ) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
        rows, headers = get_json(
            f"{settings.odds_api_base_url}/sports/{sport_key}/scores",
            {
                "apiKey": settings.odds_api_key,
                "daysFrom": max(1, min(int(days_from), 3)),
                "dateFormat": "iso",
            },
            settings.enrichment_timeout_seconds,
        )
        canonical = json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        audit = {
            "sport_key": sport_key,
            "endpoint": f"/sports/{sport_key}/scores",
            "regions": "none",
            "markets": "scores",
            "estimated_cost": max(1, min(int(days_from), 3)),
            "credits_last": headers.get("x-requests-last"),
            "credits_remaining": headers.get("x-requests-remaining"),
            "credits_used": headers.get("x-requests-used"),
            "events_returned": len(rows),
            "response_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }
        return rows, headers, audit

    @staticmethod
    def match_event(match: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
        external_id = str(match.get("official_match_id") or "")
        if external_id.startswith("oddsapi-"):
            event_id = external_id.removeprefix("oddsapi-")
            return next((event for event in events if str(event.get("id")) == event_id), None)
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
