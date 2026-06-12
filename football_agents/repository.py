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

    def upsert_official_match(self, item: dict[str, Any]) -> tuple[int, bool, str | None]:
        now = utcnow()
        with self.db.connect() as c:
            previous = c.execute("SELECT id,status FROM matches WHERE official_match_id=?",
                                 (item["official_match_id"],)).fetchone()
            c.execute("""INSERT INTO matches
                (official_match_id,match_no,league,home_team,away_team,kickoff_time,status,source_url,
                 first_seen_at,last_seen_at,data_quality_score,raw_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(official_match_id) DO UPDATE SET
                match_no=excluded.match_no,league=excluded.league,home_team=excluded.home_team,
                away_team=excluded.away_team,kickoff_time=excluded.kickoff_time,status=excluded.status,
                source_url=excluded.source_url,last_seen_at=excluded.last_seen_at,
                data_quality_score=excluded.data_quality_score,raw_hash=excluded.raw_hash""",
                (item["official_match_id"], item.get("match_no"), item["league"], item["home_team"],
                 item["away_team"], item["kickoff_time"], item["status"], item.get("source_url"),
                 now, now, item.get("data_quality_score", 1.0), item.get("raw_hash")))
            row = c.execute("SELECT id FROM matches WHERE official_match_id=?",
                            (item["official_match_id"],)).fetchone()
            match_id = int(row["id"])
            old_status = previous["status"] if previous else None
            changed = old_status is not None and old_status != item["status"]
            if changed:
                c.execute("INSERT INTO match_status_events(match_id,old_status,new_status,detected_at,reason) VALUES(?,?,?,?,?)",
                          (match_id, old_status, item["status"], now, "official_sync"))
            return match_id, previous is None, old_status

    def add_official_odds(self, match_id: int, odds: dict[str, float], source: str,
                          fetched_at: str, source_url: str, raw_hash: str,
                          parse_version: str = "sporttery-dom-v1") -> bool:
        with self.db.connect() as c:
            duplicate = c.execute("SELECT 1 FROM odds_snapshots WHERE match_id=? AND raw_hash=? LIMIT 1",
                                  (match_id, raw_hash)).fetchone()
            if duplicate:
                return False
            c.executemany("""INSERT INTO odds_snapshots
                (match_id,source,market,option,sp,fetched_at,source_url,raw_hash,parse_version)
                VALUES(?,?,'1x2',?,?,?,?,?,?)""",
                [(match_id, source, option, value, fetched_at, source_url, raw_hash, parse_version)
                 for option, value in odds.items()])
            return True

    def save_fetch_log(self, source_name: str, source_url: str, success: bool,
                       raw_hash: str | None = None, record_count: int = 0,
                       error_message: str | None = None, status_code: int | None = None) -> None:
        with self.db.connect() as c:
            c.execute("""INSERT INTO official_fetch_logs
                (source_name,source_url,fetched_at,success,status_code,raw_hash,record_count,error_message)
                VALUES(?,?,?,?,?,?,?,?)""", (source_name, source_url, utcnow(), int(success), status_code,
                                                raw_hash, record_count, error_message))

    def latest_fetch_log(self) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM official_fetch_logs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def list_fetch_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            return [dict(row) for row in c.execute(
                "SELECT * FROM official_fetch_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

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
        fair_odds = {option: 1 / probability for option, probability in probabilities.items()}
        with self.db.connect() as c:
            c.execute("""INSERT INTO model_predictions
                (match_id,model_name,model_version,p_home,p_draw,p_away,
                 fair_odds_home,fair_odds_draw,fair_odds_away,predicted_at,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (match_id, model, version, probabilities["home"], probabilities["draw"], probabilities["away"],
                 fair_odds["home"], fair_odds["draw"], fair_odds["away"],
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

    def list_official_matches(self) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute(
                """SELECT * FROM matches
                   WHERE official_match_id LIKE 'sporttery-%'
                     AND source_url IS NOT NULL
                   ORDER BY kickoff_time"""
            ).fetchall()
            return [dict(row) for row in rows]

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
            row = c.execute("""SELECT * FROM model_predictions WHERE match_id=?
                AND model_name IN ('ensemble','baseline')
                AND EXISTS (SELECT 1 FROM match_features f WHERE f.match_id=model_predictions.match_id)
                ORDER BY predicted_at DESC, CASE model_name WHEN 'ensemble' THEN 0 ELSE 1 END LIMIT 1""",
                            (match_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json"))
        return result

    def latest_signal(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM bet_signals WHERE match_id=? ORDER BY created_at DESC LIMIT 1", (match_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["reasons"] = json.loads(result.pop("reasons_json"))
        return result

    def add_news_event(self, match_id: int, event: dict[str, Any]) -> bool:
        with self.db.connect() as c:
            duplicate = c.execute(
                "SELECT 1 FROM news_events WHERE match_id=? AND source_url=? LIMIT 1",
                (match_id, event.get("source_url")),
            ).fetchone()
            if duplicate:
                return False
            c.execute("""INSERT INTO news_events
                (match_id,team,player,event_type,severity,confidence,source_url,published_at,raw_text)
                VALUES(?,?,?,?,?,?,?,?,?)""", (match_id, event.get("team"), event.get("player"),
                event.get("event_type", "news"), event.get("severity", 0), event.get("confidence", 0.6),
                event.get("source_url"), event["published_at"], event.get("raw_text")))
            return True

    def list_news(self, match_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM news_events WHERE match_id=? ORDER BY published_at DESC LIMIT ?",
                             (match_id, limit)).fetchall()
            return [dict(row) for row in rows]

    def add_weather(self, match_id: int, weather: dict[str, Any]) -> None:
        with self.db.connect() as c:
            c.execute("""INSERT INTO weather_snapshots
                (match_id,temperature,humidity,rainfall,wind_speed,fetched_at)
                VALUES(?,?,?,?,?,?)""", (match_id, weather.get("temperature"), weather.get("humidity"),
                weather.get("rainfall"), weather.get("wind_speed"), weather.get("fetched_at", utcnow())))

    def latest_weather(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM weather_snapshots WHERE match_id=? ORDER BY fetched_at DESC LIMIT 1",
                            (match_id,)).fetchone()
            return dict(row) if row else None

    def get_match_metadata(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM match_metadata WHERE match_id=?", (match_id,)).fetchone()
            return dict(row) if row else None

    def save_match_metadata(self, match_id: int, metadata: dict[str, Any]) -> None:
        with self.db.connect() as c:
            c.execute("""INSERT INTO match_metadata
                (match_id,venue,city,country,latitude,longitude,source,updated_at) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(match_id) DO UPDATE SET venue=excluded.venue,city=excluded.city,
                country=excluded.country,latitude=excluded.latitude,longitude=excluded.longitude,
                source=excluded.source,updated_at=excluded.updated_at""", (match_id, metadata.get("venue"),
                metadata.get("city"), metadata.get("country"), metadata.get("latitude"),
                metadata.get("longitude"), metadata.get("source"), utcnow()))

    def log_provider_sync(self, provider: str, status: str, records: int = 0,
                          message: str | None = None, match_id: int | None = None) -> None:
        with self.db.connect() as c:
            c.execute("INSERT INTO provider_sync_logs(provider,match_id,status,records,message,synced_at) VALUES(?,?,?,?,?,?)",
                      (provider, match_id, status, records, message, utcnow()))

    def provider_status(self) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("""SELECT p.* FROM provider_sync_logs p
                JOIN (SELECT provider,MAX(id) id FROM provider_sync_logs GROUP BY provider) x ON x.id=p.id
                ORDER BY p.provider""").fetchall()
            return [dict(row) for row in rows]

    def save_settings(self, values: dict[str, Any], operator: str = "admin") -> dict[str, Any]:
        now = utcnow()
        with self.db.connect() as c:
            for key, value in values.items():
                c.execute("""INSERT INTO app_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)
                    ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,
                    updated_at=excluded.updated_at""", (key, json.dumps(value, ensure_ascii=False), now))
            c.execute("INSERT INTO audit_events(operator,module,action,detail,result,created_at) VALUES(?,?,?,?,?,?)",
                      (operator, "设置", "更新配置", ", ".join(values.keys()), "成功", now))
        return self.get_settings()

    def get_settings(self) -> dict[str, Any]:
        with self.db.connect() as c:
            rows = c.execute("SELECT setting_key,setting_value FROM app_settings").fetchall()
        return {row["setting_key"]: json.loads(row["setting_value"]) for row in rows}

    def list_audit_events(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            own = [dict(row) for row in c.execute(
                "SELECT id,created_at time,operator,module,action,detail,result FROM audit_events ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()]
            official = [dict(row) for row in c.execute("""SELECT 'official-'||id id,fetched_at time,'system' operator,
                '官方数据' module,'同步' action,source_name||'：'||record_count||' 条' detail,
                CASE success WHEN 1 THEN '成功' ELSE '失败' END result FROM official_fetch_logs ORDER BY id DESC LIMIT ?""",
                (limit,)).fetchall()]
            providers = [dict(row) for row in c.execute("""SELECT 'provider-'||id id,synced_at time,'system' operator,
                '外部数据' module,'同步' action,provider||'：'||COALESCE(message,'') detail,status result
                FROM provider_sync_logs ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()]
        return sorted(own + official + providers, key=lambda item: item["time"], reverse=True)[:limit]

    def list_backtest_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM backtest_reports ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["parameters"] = json.loads(item.pop("parameters_json"))
            item["metrics"] = json.loads(item.pop("metrics_json"))
            item["equity"] = json.loads(item.pop("equity_json"))
            output.append(item)
        return output

    def bankroll_history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("""SELECT b.*,m.home_team,m.away_team FROM bankroll_events b
                LEFT JOIN bet_signals s ON s.id=b.signal_id LEFT JOIN matches m ON m.id=s.match_id
                ORDER BY b.occurred_at DESC LIMIT ?""", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def data_counts(self) -> dict[str, int]:
        with self.db.connect() as c:
            official_ids = "SELECT id FROM matches WHERE source_url IS NOT NULL"
            queries = {
                "matches": f"SELECT COUNT(*) FROM matches WHERE id IN ({official_ids})",
                "official_odds": f"SELECT COUNT(*) FROM odds_snapshots WHERE match_id IN ({official_ids})",
                "market_odds": f"SELECT COUNT(*) FROM market_odds_snapshots WHERE match_id IN ({official_ids})",
                "news": f"SELECT COUNT(*) FROM news_events WHERE match_id IN ({official_ids})",
                "weather": f"SELECT COUNT(*) FROM weather_snapshots WHERE match_id IN ({official_ids})",
                "features": f"SELECT COUNT(*) FROM match_features WHERE match_id IN ({official_ids})",
                "predictions": f"SELECT COUNT(*) FROM model_predictions WHERE match_id IN ({official_ids})",
                "signals": f"SELECT COUNT(*) FROM bet_signals WHERE match_id IN ({official_ids})",
                "backtests": "SELECT COUNT(*) FROM backtest_reports",
                "llm_analyses": f"SELECT COUNT(*) FROM llm_match_analyses WHERE match_id IN ({official_ids})",
            }
            return {key: int(c.execute(query).fetchone()[0]) for key, query in queries.items()}

    def save_llm_analysis(self, match_id: int, provider: str, model: str,
                          input_hash: str, analysis: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        with self.db.connect() as c:
            c.execute("""INSERT INTO llm_match_analyses(match_id,provider,model,input_hash,analysis_json,created_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(match_id,provider,model,input_hash) DO UPDATE SET
                analysis_json=excluded.analysis_json,created_at=excluded.created_at""",
                (match_id, provider, model, input_hash, json.dumps(analysis, ensure_ascii=False), now))
            row = c.execute("SELECT * FROM llm_match_analyses WHERE match_id=? AND provider=? AND model=? AND input_hash=?",
                            (match_id, provider, model, input_hash)).fetchone()
            c.execute("INSERT INTO audit_events(operator,module,action,detail,result,created_at) VALUES(?,?,?,?,?,?)",
                      (model, "大模型", "新闻分析", f"match_id={match_id}", "成功", now))
        return self._decode_llm(dict(row))

    def latest_llm_analysis(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM llm_match_analyses WHERE match_id=? ORDER BY id DESC LIMIT 1",
                            (match_id,)).fetchone()
        return self._decode_llm(dict(row)) if row else None

    def find_llm_analysis(self, match_id: int, provider: str, model: str,
                          input_hash: str) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM llm_match_analyses WHERE match_id=? AND provider=? AND model=? AND input_hash=?",
                            (match_id, provider, model, input_hash)).fetchone()
        return self._decode_llm(dict(row)) if row else None

    @staticmethod
    def _decode_llm(item: dict[str, Any]) -> dict[str, Any]:
        item["analysis"] = json.loads(item.pop("analysis_json"))
        return item

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

