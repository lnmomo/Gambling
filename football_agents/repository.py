from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from .db import Database, db


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, database: Database = db) -> None:
        self.db = database

    def create_match(self, item: dict[str, Any]) -> int:
        with self.db.connect() as c:
            c.execute(
                """INSERT INTO matches(official_match_id, league, home_team, away_team, kickoff_time, status)
                VALUES(?,?,?,?,?,?) ON CONFLICT(official_match_id) DO UPDATE SET
                league=excluded.league, home_team=excluded.home_team, away_team=excluded.away_team,
                kickoff_time=excluded.kickoff_time, status=excluded.status""",
                (item["official_match_id"], item["league"], item["home_team"], item["away_team"],
                 item["kickoff_time"], item.get("status", "scheduled")),
            )
            row = c.execute("SELECT id FROM matches WHERE official_match_id=?", (item["official_match_id"],)).fetchone()
            return int(row["id"])

    def add_odds(self, match_id: int, odds: dict[str, float], source: str, fetched_at: str | None = None,
                 external: bool = False) -> None:
        table = "market_odds_snapshots" if external else "odds_snapshots"
        source_col = "bookmaker" if external else "source"
        value_col = "odds" if external else "sp"
        timestamp = fetched_at or utcnow()
        with self.db.connect() as c:
            c.executemany(
                f"INSERT INTO {table}(match_id,{source_col},market,option,{value_col},fetched_at) VALUES(?,?,'1x2',?,?,?)",
                [(match_id, source, option, value, timestamp) for option, value in odds.items()],
            )

    def add_features(self, match_id: int, features: dict[str, Any], version: str = "v1") -> None:
        with self.db.connect() as c:
            c.execute("INSERT INTO match_features(match_id,feature_version,feature_json,created_at) VALUES(?,?,?,?)",
                      (match_id, version, json.dumps(features, ensure_ascii=False), utcnow()))

    def add_prediction(self, match_id: int, model: str, probabilities: dict[str, float],
                       metadata: dict[str, Any] | None = None, version: str = "v1") -> None:
        with self.db.connect() as c:
            c.execute("""INSERT INTO model_predictions
                (match_id,model_name,model_version,p_home,p_draw,p_away,predicted_at,metadata_json)
                VALUES(?,?,?,?,?,?,?,?)""",
                (match_id, model, version, probabilities["home"], probabilities["draw"], probabilities["away"],
                 utcnow(), json.dumps(metadata or {}, ensure_ascii=False)))

    def add_critic(self, match_id: int, report: dict[str, Any]) -> None:
        with self.db.connect() as c:
            c.execute("INSERT INTO critic_reports(match_id,pass_check,risk_level,reasons_json,checks_json,created_at) VALUES(?,?,?,?,?,?)",
                      (match_id, int(report["passed"]), report["risk_level"],
                       json.dumps(report["reasons"], ensure_ascii=False),
                       json.dumps(report["checks"], ensure_ascii=False), utcnow()))

    def add_signal(self, match_id: int, signal: dict[str, Any]) -> int:
        with self.db.connect() as c:
            cursor = c.execute("""INSERT INTO bet_signals
                (match_id,market,option,sp,probability,fair_odds,ev,stake,status,confidence,reasons_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (match_id, "1x2", signal.get("option"), signal.get("sp"), signal.get("probability"),
                 signal.get("fair_odds"), signal.get("ev"), signal.get("stake", 0), signal["status"],
                 signal["confidence"], json.dumps(signal["reasons"], ensure_ascii=False), utcnow()))
            return int(cursor.lastrowid)

    def get_match(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
            return dict(row) if row else None

    def list_matches(self, date: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM matches"
        params: tuple[Any, ...] = ()
        if date:
            query += " WHERE substr(kickoff_time,1,10)=?"
            params = (date,)
        query += " ORDER BY kickoff_time"
        with self.db.connect() as c:
            return [dict(row) for row in c.execute(query, params).fetchall()]

    def latest_odds(self, match_id: int, external: bool = False) -> dict[str, Any]:
        table = "market_odds_snapshots" if external else "odds_snapshots"
        value_col = "odds" if external else "sp"
        source_col = "bookmaker" if external else "source"
        with self.db.connect() as c:
            rows = c.execute(f"""SELECT option,{value_col} value,{source_col} source,fetched_at FROM {table}
                WHERE match_id=? AND fetched_at=(SELECT MAX(fetched_at) FROM {table} WHERE match_id=?)""",
                (match_id, match_id)).fetchall()
        return {"odds": {r["option"]: r["value"] for r in rows},
                "source": rows[0]["source"] if rows else None,
                "fetched_at": rows[0]["fetched_at"] if rows else None}

    def latest_features(self, match_id: int) -> dict[str, Any]:
        with self.db.connect() as c:
            row = c.execute("SELECT feature_json FROM match_features WHERE match_id=? ORDER BY created_at DESC LIMIT 1",
                            (match_id,)).fetchone()
        return json.loads(row["feature_json"]) if row else {}

    def latest_prediction(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM model_predictions WHERE match_id=? AND model_name='ensemble' ORDER BY predicted_at DESC LIMIT 1",
                            (match_id,)).fetchone()
        return dict(row) if row else None

    def latest_signal(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM bet_signals WHERE match_id=? ORDER BY created_at DESC LIMIT 1", (match_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["reasons"] = json.loads(result.pop("reasons_json"))
        return result

    def list_signals(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("""SELECT s.*,m.official_match_id,m.league,m.home_team,m.away_team,m.kickoff_time
                FROM bet_signals s JOIN matches m ON m.id=s.match_id
                WHERE s.id IN (SELECT MAX(id) FROM bet_signals GROUP BY match_id)
                ORDER BY m.kickoff_time LIMIT ?""", (limit,)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["reasons"] = json.loads(item.pop("reasons_json"))
            output.append(item)
        return output

    def save_backtest(self, report_id: str, name: str, parameters: dict[str, Any], metrics: dict[str, Any],
                      equity: Iterable[float]) -> None:
        with self.db.connect() as c:
            c.execute("INSERT INTO backtest_reports VALUES(?,?,?,?,?,?)",
                      (report_id, name, json.dumps(parameters), json.dumps(metrics), json.dumps(list(equity)), utcnow()))

    def get_backtest(self, report_id: str) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM backtest_reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        for key in ("parameters_json", "metrics_json", "equity_json"):
            item[key.removesuffix("_json")] = json.loads(item.pop(key))
        return item

