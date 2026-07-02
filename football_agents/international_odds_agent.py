from __future__ import annotations

import csv
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from lxml import html as lxml_html

from .config import settings
from .historical_data import HistoricalDataService
from .repository import Repository


FOOTIQO_WORLD_CUP_URL = "https://footiqo.com/database/leagues/world-cup/"
FOOTIQO_AJAX_URL = "https://footiqo.com/wp-admin/admin-ajax.php?action=get_wdtable&table_id={table_id}"
WORLD_CUP_RESULTS_TABLE_ID = 1720
WORLD_CUP_ODDS_TABLE_ID = 1729

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
        tree = lxml_html.fromstring(page_html)
        values = tree.xpath(f'//input[@id="wdtNonceFrontendServerSide_{table_id}"]/@value')
        if not values:
            raise ValueError(f"Footiqo nonce not found for table {table_id}")
        return str(values[0])

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
