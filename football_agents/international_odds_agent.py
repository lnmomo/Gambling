from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .config import settings
from .historical_data import HistoricalDataService
from .integrations.http import get_json
from .international_history_agent import InternationalHistoryAgent
from .repository import Repository


FOOTIQO_WORLD_CUP_URL = "https://footiqo.com/database/leagues/world-cup/"
FOOTIQO_AJAX_URL = "https://footiqo.com/wp-admin/admin-ajax.php?action=get_wdtable&table_id={table_id}"
WORLD_CUP_RESULTS_TABLE_ID = 1720
WORLD_CUP_ODDS_TABLE_ID = 1729
FOOTBALL_DATA_WORLD_CUP_ARCHIVE_NAME = "world_cup_football_data.xlsx"

RESULT_COLUMNS = ("id", "matchDate", "Country", "League", "Season", "homeTeam", "awayTeam", "referee", "FTHG", "FTAG", "FTR")
ODDS_COLUMNS = (
    "id", "matchDate", "Country", "League", "Season", "homeTeam", "awayTeam",
    "H", "D", "A", "O05", "U05", "O15", "U15", "O25", "U25", "O35", "U35", "O45", "U45", "BTTSY", "BTTSN",
)


@dataclass(frozen=True)
class FootiqoTable:
    table_id: int
    nonce: str
    columns: tuple[str, ...]


class InternationalOddsHistoryAgent:
    """Archives international 1X2 odds where public pre-match odds history exists.

    The current implemented source is Footiqo's World Cup database. Footiqo states
    that its historical odds are closing odds sourced from 1xBet.
    """

    def __init__(
        self,
        repository: Repository | None = None,
        archive_dir: Path | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.repository = repository or Repository()
        self.archive_dir = archive_dir or Path("data") / "historical_csv" / "footiqo"
        self.output_dir = output_dir or Path("data") / "historical_csv" / "football-data" / "new"
        self._opener = build_opener(HTTPCookieProcessor())

    def _request(self, url: str, data: bytes | None = None) -> str:
        attempts = max(1, settings.historical_data_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                request = Request(
                    url,
                    data=data,
                    headers={
                        "User-Agent": "football-agents-international-odds/1.0",
                        "Referer": FOOTIQO_WORLD_CUP_URL,
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
                with self._opener.open(request, timeout=settings.historical_data_timeout_seconds) as response:
                    return response.read().decode("utf-8", "replace")
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise
                time.sleep(settings.historical_data_retry_backoff_seconds * (2 ** attempt))
        raise last_error or RuntimeError("international odds request failed")

    def fetch_page(self) -> str:
        return self._request(FOOTIQO_WORLD_CUP_URL)

    @staticmethod
    def _nonce(page_html: str, table_id: int) -> str:
        pattern = rf'id=["\']wdtNonceFrontendServerSide_{table_id}["\'][^>]*value=["\']([^"\']+)["\']'
        match = re.search(pattern, page_html)
        if not match:
            raise ValueError(f"Footiqo nonce not found for table {table_id}")
        return match.group(1)

    @staticmethod
    def _table_payload(table: FootiqoTable, length: int = 5000) -> bytes:
        params: dict[str, str] = {
            "draw": "1",
            "start": "0",
            "length": str(length),
            "search[value]": "",
            "search[regex]": "false",
            "order[0][column]": "1",
            "order[0][dir]": "asc",
            "wdtNonce": table.nonce,
        }
        for index, column in enumerate(table.columns):
            params[f"columns[{index}][data]"] = str(index)
            params[f"columns[{index}][name]"] = column
            params[f"columns[{index}][searchable]"] = "true"
            params[f"columns[{index}][orderable]"] = "true"
            params[f"columns[{index}][search][value]"] = ""
            params[f"columns[{index}][search][regex]"] = "false"
        return urlencode(params).encode()

    def fetch_table(self, table: FootiqoTable) -> list[dict[str, Any]]:
        text = self._request(
            FOOTIQO_AJAX_URL.format(table_id=table.table_id),
            data=self._table_payload(table),
        )
        if not text.strip():
            raise ValueError(f"Footiqo table {table.table_id} returned an empty response")
        payload = json.loads(text)
        rows = []
        for raw in payload.get("data") or []:
            if len(raw) < len(table.columns):
                continue
            rows.append({column: raw[index] for index, column in enumerate(table.columns)})
        return rows

    @staticmethod
    def _date(value: str) -> str:
        parsed = datetime.strptime(str(value).strip(), "%d-%m-%y %H:%M")
        return parsed.strftime("%d/%m/%Y")

    @staticmethod
    def _float(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 1 else None

    @staticmethod
    def _result_code(home_goals: int, away_goals: int) -> str:
        if home_goals > away_goals:
            return "H"
        if home_goals < away_goals:
            return "A"
        return "D"

    @staticmethod
    def _football_data_league(sheet_name: str, row: Any) -> str:
        competition = str(row.get("Competition") or "").strip()
        if competition:
            return competition
        if "qualifier" in sheet_name.casefold():
            return "World Cup Qualifiers"
        return "World Cup"

    @staticmethod
    def _football_data_season(sheet_name: str, played_at: datetime) -> str:
        match = re.search(r"(20\d{2})", sheet_name)
        return match.group(1) if match else str(played_at.year)

    @staticmethod
    def _first_float(row: Any, columns: tuple[str, ...]) -> float | None:
        for column in columns:
            if column in row:
                value = InternationalOddsHistoryAgent._float(row.get(column))
                if value is not None:
                    return value
        return None

    @staticmethod
    def _write_football_data_csv(output_rows: list[dict[str, Any]]) -> str:
        columns = [
            "Country", "League", "Season", "Date", "Home", "Away", "HG", "AG", "Res",
            "AvgCH", "AvgCD", "AvgCA", "MaxCH", "MaxCD", "MaxCA",
            "Bookmaker", "Source", "SourceMatchId",
        ]
        from io import StringIO

        handle = StringIO()
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
        return handle.getvalue()

    @staticmethod
    def build_world_cup_csv(results: list[dict[str, Any]], odds: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        results_by_id = {str(row.get("id")): row for row in results}
        output_rows: list[dict[str, Any]] = []
        dropped = 0
        for odds_row in odds:
            match_id = str(odds_row.get("id"))
            result = results_by_id.get(match_id)
            if result is None:
                dropped += 1
                continue
            home_odds = InternationalOddsHistoryAgent._float(odds_row.get("H"))
            draw_odds = InternationalOddsHistoryAgent._float(odds_row.get("D"))
            away_odds = InternationalOddsHistoryAgent._float(odds_row.get("A"))
            if home_odds is None or draw_odds is None or away_odds is None:
                dropped += 1
                continue
            try:
                home_goals = int(float(result["FTHG"]))
                away_goals = int(float(result["FTAG"]))
                date_text = InternationalOddsHistoryAgent._date(result["matchDate"])
            except (KeyError, TypeError, ValueError):
                dropped += 1
                continue
            output_rows.append({
                "Country": "World",
                "League": "World Cup",
                "Season": result.get("Season") or odds_row.get("Season"),
                "Date": date_text,
                "Home": result.get("homeTeam"),
                "Away": result.get("awayTeam"),
                "HG": home_goals,
                "AG": away_goals,
                "Res": result.get("FTR"),
                "AvgCH": home_odds,
                "AvgCD": draw_odds,
                "AvgCA": away_odds,
                "Bookmaker": "1xBet",
                "Source": FOOTIQO_WORLD_CUP_URL,
                "SourceMatchId": match_id,
            })
        output_rows.sort(key=lambda row: (datetime.strptime(row["Date"], "%d/%m/%Y"), str(row["Home"])))
        columns = [
            "Country", "League", "Season", "Date", "Home", "Away", "HG", "AG", "Res",
            "AvgCH", "AvgCD", "AvgCA", "Bookmaker", "Source", "SourceMatchId",
        ]
        from io import StringIO

        handle = StringIO()
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
        return handle.getvalue(), {
            "matched": len(output_rows),
            "dropped": dropped,
            "results_rows": len(results),
            "odds_rows": len(odds),
            "first_date": output_rows[0]["Date"] if output_rows else None,
            "last_date": output_rows[-1]["Date"] if output_rows else None,
        }

    def sync_world_cup(self) -> dict[str, Any]:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        page_html = self.fetch_page()
        raw_hash = hashlib.sha256(page_html.encode("utf-8")).hexdigest()
        (self.archive_dir / "world_cup.html").write_text(page_html, encoding="utf-8")
        results_table = FootiqoTable(WORLD_CUP_RESULTS_TABLE_ID, self._nonce(page_html, WORLD_CUP_RESULTS_TABLE_ID), RESULT_COLUMNS)
        odds_table = FootiqoTable(WORLD_CUP_ODDS_TABLE_ID, self._nonce(page_html, WORLD_CUP_ODDS_TABLE_ID), ODDS_COLUMNS)
        results = self.fetch_table(results_table)
        odds = self.fetch_table(odds_table)
        (self.archive_dir / "world_cup_results_past.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.archive_dir / "world_cup_odds_past.json").write_text(json.dumps(odds, ensure_ascii=False, indent=2), encoding="utf-8")
        csv_text, conversion = self.build_world_cup_csv(results, odds)
        csv_path = self.output_dir / "WORLD_CUP.csv"
        csv_path.write_text(csv_text, encoding="utf-8")
        import_report = HistoricalDataService(self.repository).import_csv_text(csv_text, str(csv_path))
        report = {
            "source": FOOTIQO_WORLD_CUP_URL,
            "source_note": "Footiqo historical World Cup closing odds, 1xBet",
            "archive_html": str(self.archive_dir / "world_cup.html"),
            "archive_results": str(self.archive_dir / "world_cup_results_past.json"),
            "archive_odds": str(self.archive_dir / "world_cup_odds_past.json"),
            "csv_path": str(csv_path),
            "raw_hash": raw_hash,
            "conversion": conversion,
            "import": import_report,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        self.repository.add_audit_event(
            "international-odds-history-agent",
            "World Cup historical odds",
            "sync",
            json.dumps({"matched": conversion["matched"], **import_report}, ensure_ascii=False),
            "success" if conversion["matched"] > 0 else "failed",
        )
        return report

    @staticmethod
    def _parse_date(value: str) -> date:
        raw = str(value).strip()
        if not raw:
            raise ValueError("empty date")
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        return datetime.fromisoformat(raw).date()

    @staticmethod
    def _result_index(results: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
        index: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in results:
            try:
                played_at = str(row["played_at"])
                home = str(row["home_team"]).strip()
                away = str(row["away_team"]).strip()
            except KeyError:
                continue
            if played_at and home and away:
                index[(played_at, home.casefold(), away.casefold())] = row
        return index

    @staticmethod
    def _event_consensus_1x2(event: dict[str, Any]) -> dict[str, float] | None:
        home_team = str(event.get("home_team") or "").strip()
        away_team = str(event.get("away_team") or "").strip()
        if not home_team or not away_team:
            return None
        prices: dict[str, list[float]] = {"home": [], "draw": [], "away": []}
        for bookmaker in event.get("bookmakers") or []:
            for market in bookmaker.get("markets") or []:
                if market.get("key") != "h2h":
                    continue
                seen: dict[str, float] = {}
                for outcome in market.get("outcomes") or []:
                    name = str(outcome.get("name") or "").strip()
                    price = InternationalOddsHistoryAgent._float(outcome.get("price"))
                    if price is None:
                        continue
                    if name.casefold() == home_team.casefold():
                        seen["home"] = price
                    elif name.casefold() == away_team.casefold():
                        seen["away"] = price
                    elif name.casefold() == "draw":
                        seen["draw"] = price
                if set(seen) == {"home", "draw", "away"}:
                    for key, value in seen.items():
                        prices[key].append(value)
        if not all(prices.values()):
            return None
        return {key: round(sum(values) / len(values), 6) for key, values in prices.items()}

    @staticmethod
    def build_odds_api_csv(
        snapshots: list[dict[str, Any]],
        results: list[dict[str, Any]],
        sport_titles: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        result_index = InternationalOddsHistoryAgent._result_index(results)
        sport_titles = sport_titles or {}
        output_rows: list[dict[str, Any]] = []
        seen_matches: set[tuple[str, str, str, str]] = set()
        dropped = {
            "missing_consensus": 0,
            "unmatched_result": 0,
            "duplicate": 0,
            "invalid_event": 0,
        }
        scanned_events = 0
        for snapshot in snapshots:
            sport_key = str(snapshot.get("sport_key") or snapshot.get("sportKey") or "")
            league = sport_titles.get(sport_key) or str(snapshot.get("sport_title") or snapshot.get("sportTitle") or sport_key)
            events = snapshot.get("data") if isinstance(snapshot.get("data"), list) else snapshot.get("events")
            if not isinstance(events, list):
                dropped["invalid_event"] += 1
                continue
            for event in events:
                scanned_events += 1
                home = str(event.get("home_team") or "").strip()
                away = str(event.get("away_team") or "").strip()
                commence_time = str(event.get("commence_time") or "").strip()
                if not home or not away or not commence_time:
                    dropped["invalid_event"] += 1
                    continue
                try:
                    played_at = InternationalOddsHistoryAgent._parse_date(commence_time).isoformat()
                except ValueError:
                    dropped["invalid_event"] += 1
                    continue
                consensus = InternationalOddsHistoryAgent._event_consensus_1x2(event)
                if consensus is None:
                    dropped["missing_consensus"] += 1
                    continue
                result = result_index.get((played_at, home.casefold(), away.casefold()))
                if result is None:
                    dropped["unmatched_result"] += 1
                    continue
                match_key = (sport_key, played_at, home.casefold(), away.casefold())
                if match_key in seen_matches:
                    dropped["duplicate"] += 1
                    continue
                seen_matches.add(match_key)
                home_goals = int(result["home_goals"])
                away_goals = int(result["away_goals"])
                output_rows.append({
                    "Country": "World",
                    "League": league,
                    "Season": played_at[:4],
                    "Date": datetime.strptime(played_at, "%Y-%m-%d").strftime("%d/%m/%Y"),
                    "Home": home,
                    "Away": away,
                    "HG": home_goals,
                    "AG": away_goals,
                    "Res": InternationalOddsHistoryAgent._result_code(home_goals, away_goals),
                    "AvgCH": consensus["home"],
                    "AvgCD": consensus["draw"],
                    "AvgCA": consensus["away"],
                    "Bookmaker": "The Odds API consensus",
                    "Source": "The Odds API historical odds",
                    "SourceMatchId": event.get("id") or "",
                })
        output_rows.sort(key=lambda row: (datetime.strptime(row["Date"], "%d/%m/%Y"), str(row["League"]), str(row["Home"])))
        columns = [
            "Country", "League", "Season", "Date", "Home", "Away", "HG", "AG", "Res",
            "AvgCH", "AvgCD", "AvgCA", "Bookmaker", "Source", "SourceMatchId",
        ]
        from io import StringIO

        handle = StringIO()
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
        return handle.getvalue(), {
            "matched": len(output_rows),
            "scanned_events": scanned_events,
            "dropped": dropped,
            "first_date": output_rows[0]["Date"] if output_rows else None,
            "last_date": output_rows[-1]["Date"] if output_rows else None,
        }

    def _load_international_results(self) -> list[dict[str, Any]]:
        archive = Path("data") / "historical_csv" / "international" / "results.csv"
        if archive.exists():
            return InternationalHistoryAgent.normalize_csv(archive.read_text(encoding="utf-8-sig"))
        return InternationalHistoryAgent().normalize_csv(InternationalHistoryAgent().fetch())

    @staticmethod
    def _snapshot_dates(from_date: str, to_date: str, step_days: int, max_snapshots: int) -> list[date]:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
        if end < start:
            raise ValueError("--to-date must be on or after --from-date")
        step = max(1, step_days)
        dates: list[date] = []
        current = start
        while current <= end and len(dates) < max(1, max_snapshots):
            dates.append(current)
            current += timedelta(days=step)
        return dates

    def fetch_odds_api_snapshot(self, sport_key: str, snapshot_date: date) -> tuple[dict[str, Any], dict[str, str]]:
        if not settings.odds_api_key:
            raise ValueError("THE_ODDS_API_KEY is missing")
        data, headers = get_json(
            f"{settings.odds_api_base_url}/historical/sports/{sport_key}/odds",
            {
                "apiKey": settings.odds_api_key,
                "regions": "uk,eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "date": f"{snapshot_date.isoformat()}T12:00:00Z",
            },
            settings.enrichment_timeout_seconds,
        )
        payload = data if isinstance(data, dict) else {"data": data}
        payload["sport_key"] = sport_key
        payload["snapshot_date"] = snapshot_date.isoformat()
        return payload, headers

    def sync_odds_api_historical(
        self,
        sport_keys: list[str] | None = None,
        from_date: str = "2020-06-06",
        to_date: str | None = None,
        step_days: int = 7,
        max_snapshots: int = 10,
    ) -> dict[str, Any]:
        selected_keys = sport_keys or list(settings.international_odds_sport_keys)
        if not selected_keys:
            raise ValueError("No international odds sport keys configured")
        end_date = to_date or datetime.now(timezone.utc).date().isoformat()
        snapshot_dates = self._snapshot_dates(from_date, end_date, step_days, max_snapshots)
        archive_root = Path("data") / "historical_csv" / "the_odds_api" / "international"
        archive_root.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        snapshots: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        headers_seen: dict[str, str] = {}
        for sport_key in selected_keys:
            for snapshot_date in snapshot_dates:
                try:
                    payload, headers = self.fetch_odds_api_snapshot(sport_key, snapshot_date)
                    headers_seen = headers
                    archive_path = archive_root / sport_key / f"{snapshot_date.isoformat()}.json"
                    archive_path.parent.mkdir(parents=True, exist_ok=True)
                    archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    snapshots.append(payload)
                    sources.append({
                        "sport_key": sport_key,
                        "snapshot_date": snapshot_date.isoformat(),
                        "status": "success",
                        "events": len(payload.get("data") or []),
                        "archive": str(archive_path),
                    })
                except Exception as exc:
                    sources.append({
                        "sport_key": sport_key,
                        "snapshot_date": snapshot_date.isoformat(),
                        "status": "failed",
                        "error": str(exc),
                    })

        sport_titles = {
            "soccer_fifa_world_cup": "FIFA World Cup",
            "soccer_uefa_european_championship": "UEFA Euro",
            "soccer_conmebol_copa_america": "Copa America",
            "soccer_uefa_nations_league": "UEFA Nations League",
        }
        results = self._load_international_results()
        csv_text, conversion = self.build_odds_api_csv(snapshots, results, sport_titles)
        csv_path = self.output_dir / "INTERNATIONAL_ODDS_API.csv"
        csv_path.write_text(csv_text, encoding="utf-8")
        import_report = HistoricalDataService(self.repository).import_csv_text(csv_text, str(csv_path)) if conversion["matched"] else {
            "imported": 0,
            "updated": 0,
            "dropped": 0,
            "pandas_rows": 0,
            "pandas_dropped": 0,
        }
        report = {
            "source": "The Odds API historical odds",
            "source_note": "Historical h2h snapshots converted to football-data-style settled international CSV",
            "sport_keys": selected_keys,
            "snapshot_dates": [item.isoformat() for item in snapshot_dates],
            "archive_root": str(archive_root),
            "csv_path": str(csv_path),
            "conversion": conversion,
            "import": import_report,
            "quota_headers": {
                key: headers_seen.get(key)
                for key in ("x-requests-remaining", "x-requests-used", "x-requests-last")
                if headers_seen.get(key) is not None
            },
            "sources": sources,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        self.repository.add_audit_event(
            "international-odds-history-agent",
            "The Odds API international historical odds",
            "sync",
            json.dumps({"matched": conversion["matched"], **import_report}, ensure_ascii=False),
            "success" if conversion["matched"] > 0 else "partial",
        )
        return report

    def fetch_football_data_world_cup_workbook(self) -> bytes:
        request = Request(
            settings.international_football_data_world_cup_url,
            headers={"User-Agent": "football-agents-football-data-world-cup/1.0"},
        )
        with self._opener.open(request, timeout=settings.historical_data_timeout_seconds) as response:
            return response.read()

    @staticmethod
    def build_football_data_world_cup_csv(workbook_bytes: bytes) -> tuple[str, dict[str, Any]]:
        import pandas as pd

        workbook = pd.ExcelFile(BytesIO(workbook_bytes))
        output_rows: list[dict[str, Any]] = []
        dropped = 0
        sheet_reports: list[dict[str, Any]] = []
        for sheet_name in workbook.sheet_names:
            if "worldcup" not in sheet_name.casefold():
                continue
            frame = pd.read_excel(workbook, sheet_name=sheet_name)
            sheet_matched = 0
            sheet_dropped = 0
            for index, row in frame.iterrows():
                try:
                    home = str(row.get("Home") or "").strip()
                    away = str(row.get("Away") or "").strip()
                    played_at = pd.to_datetime(row.get("Date"), errors="coerce")
                    home_goals_raw = row.get("HG") if "HG" in frame.columns else row.get("HGFT")
                    away_goals_raw = row.get("AG") if "AG" in frame.columns else row.get("AGFT")
                    if not home or not away or home == away or pd.isna(played_at):
                        raise ValueError("missing match identity")
                    home_goals = int(float(home_goals_raw))
                    away_goals = int(float(away_goals_raw))
                    avg_home = InternationalOddsHistoryAgent._first_float(row, ("H-Avg", "H_Avg", "AvgH", "AvgCH", "bet365-H"))
                    avg_draw = InternationalOddsHistoryAgent._first_float(row, ("D-Avg", "D_Avg", "AvgD", "AvgCD", "bet365-D"))
                    avg_away = InternationalOddsHistoryAgent._first_float(row, ("A-Avg", "A_Avg", "AvgA", "AvgCA", "bet365-A"))
                    if avg_home is None or avg_draw is None or avg_away is None:
                        raise ValueError("missing 1x2 odds")
                    max_home = InternationalOddsHistoryAgent._first_float(row, ("H-Max", "H_Max", "MaxH", "MaxCH"))
                    max_draw = InternationalOddsHistoryAgent._first_float(row, ("D-Max", "D_Max", "MaxD", "MaxCD"))
                    max_away = InternationalOddsHistoryAgent._first_float(row, ("A-Max", "A_Max", "MaxA", "MaxCA"))
                    played_dt = played_at.to_pydatetime()
                    source_match_id = f"{sheet_name}|{played_dt.date().isoformat()}|{home}|{away}"
                    output_rows.append({
                        "Country": "World",
                        "League": InternationalOddsHistoryAgent._football_data_league(sheet_name, row),
                        "Season": InternationalOddsHistoryAgent._football_data_season(sheet_name, played_dt),
                        "Date": played_dt.strftime("%d/%m/%Y"),
                        "Home": home,
                        "Away": away,
                        "HG": home_goals,
                        "AG": away_goals,
                        "Res": InternationalOddsHistoryAgent._result_code(home_goals, away_goals),
                        "AvgCH": avg_home,
                        "AvgCD": avg_draw,
                        "AvgCA": avg_away,
                        "MaxCH": max_home or "",
                        "MaxCD": max_draw or "",
                        "MaxCA": max_away or "",
                        "Bookmaker": "football-data average",
                        "Source": settings.international_football_data_world_cup_url,
                        "SourceMatchId": hashlib.sha256(source_match_id.encode("utf-8")).hexdigest()[:24],
                    })
                    sheet_matched += 1
                except (TypeError, ValueError):
                    dropped += 1
                    sheet_dropped += 1
                    continue
            sheet_reports.append({
                "sheet": sheet_name,
                "rows": int(len(frame)),
                "matched": sheet_matched,
                "dropped": sheet_dropped,
            })
        output_rows.sort(key=lambda item: (datetime.strptime(item["Date"], "%d/%m/%Y"), str(item["League"]), str(item["Home"])))
        csv_text = InternationalOddsHistoryAgent._write_football_data_csv(output_rows)
        return csv_text, {
            "matched": len(output_rows),
            "dropped": dropped,
            "sheets": sheet_reports,
            "first_date": output_rows[0]["Date"] if output_rows else None,
            "last_date": output_rows[-1]["Date"] if output_rows else None,
        }

    def sync_football_data_world_cup(self) -> dict[str, Any]:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        workbook_bytes = self.fetch_football_data_world_cup_workbook()
        raw_hash = hashlib.sha256(workbook_bytes).hexdigest()
        archive_path = self.archive_dir / FOOTBALL_DATA_WORLD_CUP_ARCHIVE_NAME
        archive_path.write_bytes(workbook_bytes)
        csv_text, conversion = self.build_football_data_world_cup_csv(workbook_bytes)
        csv_path = self.output_dir / "WORLD_CUP.csv"
        csv_path.write_text(csv_text, encoding="utf-8")
        import_report = HistoricalDataService(self.repository).import_csv_text(csv_text, str(csv_path)) if conversion["matched"] else {
            "imported": 0,
            "updated": 0,
            "dropped": 0,
            "pandas_rows": 0,
            "pandas_dropped": 0,
        }
        report = {
            "source": settings.international_football_data_world_cup_url,
            "source_note": "football-data.co.uk World Cup workbook converted to football-data-style settled international CSV",
            "archive_workbook": str(archive_path),
            "csv_path": str(csv_path),
            "raw_hash": raw_hash,
            "conversion": conversion,
            "import": import_report,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        self.repository.add_audit_event(
            "international-odds-history-agent",
            "football-data World Cup historical odds",
            "sync",
            json.dumps({"matched": conversion["matched"], **import_report}, ensure_ascii=False),
            "success" if conversion["matched"] > 0 else "failed",
        )
        return report
