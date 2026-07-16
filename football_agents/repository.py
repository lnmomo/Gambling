from __future__ import annotations

import json
import uuid
import hashlib
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

    def archive_official_odds_observation(self, match_id: int, official_match_id: str,
                                          odds: dict[str, float], observed_at: str,
                                          kickoff_time: str, sale_status: str,
                                          source: str, source_url: str, raw_hash: str) -> int:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        kickoff = datetime.fromisoformat(kickoff_time.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        minutes = (kickoff - observed).total_seconds() / 60
        stage = ("POST_MATCH" if minutes < 0 else "T_MINUS_1H" if minutes <= 60 else
                 "T_MINUS_6H" if minutes <= 360 else "T_MINUS_24H" if minutes <= 1440 else "EARLY")
        with self.db.connect() as c:
            cursor = c.execute("""INSERT INTO official_odds_observations
                (match_id,official_match_id,observed_at,kickoff_time,sale_status,
                 home_sp,draw_sp,away_sp,is_pre_match,minutes_to_kickoff,capture_stage,
                 source,source_url,raw_hash)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (match_id, official_match_id, observed_at, kickoff_time, sale_status,
                 float(odds["home"]), float(odds["draw"]), float(odds["away"]),
                 int(minutes >= 0), minutes, stage, source, source_url, raw_hash))
            return int(cursor.lastrowid)

    def list_official_odds_observations(self, official_match_id: str | None = None,
                                        limit: int = 1000) -> list[dict[str, Any]]:
        query = "SELECT * FROM official_odds_observations"
        params: list[Any] = []
        if official_match_id:
            query += " WHERE official_match_id=?"
            params.append(official_match_id)
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100_000)))
        with self.db.connect() as c:
            return [dict(row) for row in c.execute(query, tuple(params)).fetchall()]

    def official_odds_timeseries_status(self) -> dict[str, Any]:
        with self.db.connect() as c:
            row = c.execute("""SELECT COUNT(*) observations,COUNT(DISTINCT match_id) matches,
                MIN(observed_at) first_observed_at,MAX(observed_at) last_observed_at,
                SUM(CASE WHEN is_pre_match=1 THEN 1 ELSE 0 END) pre_match_observations
                FROM official_odds_observations""").fetchone()
            closing = c.execute("SELECT COUNT(*) FROM official_odds_closing_observations").fetchone()[0]
            settled = c.execute("""SELECT COUNT(*) FROM results r WHERE EXISTS(
                SELECT 1 FROM official_odds_observations o WHERE o.match_id=r.match_id)""").fetchone()[0]
        return {**dict(row), "closing_observations": int(closing), "settled_matches": int(settled)}

    def upsert_result(self, match_id: int, home_score: int, away_score: int,
                      settled_at: str | None = None) -> dict[str, Any]:
        outcome = "home" if home_score > away_score else "draw" if home_score == away_score else "away"
        timestamp = settled_at or utcnow()
        with self.db.connect() as c:
            c.execute("""INSERT INTO results(match_id,home_score,away_score,outcome,settled_at)
                VALUES(?,?,?,?,?) ON CONFLICT(match_id) DO UPDATE SET
                home_score=excluded.home_score,away_score=excluded.away_score,
                outcome=excluded.outcome,settled_at=excluded.settled_at""",
                (match_id, home_score, away_score, outcome, timestamp))
            row = c.execute("SELECT * FROM results WHERE match_id=?", (match_id,)).fetchone()
        return dict(row)

    def list_official_odds_training_samples(self, limit: int = 10_000) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("""SELECT m.official_match_id,m.league,m.home_team,m.away_team,m.kickoff_time,
                opening.observed_at opening_observed_at,opening.home_sp opening_home_sp,
                opening.draw_sp opening_draw_sp,opening.away_sp opening_away_sp,
                closing.observed_at closing_observed_at,closing.home_sp closing_home_sp,
                closing.draw_sp closing_draw_sp,closing.away_sp closing_away_sp,
                r.home_score,r.away_score,r.outcome,r.settled_at
                FROM results r JOIN matches m ON m.id=r.match_id
                JOIN official_odds_closing_observations closing ON closing.match_id=m.id
                JOIN official_odds_observations opening ON opening.id=(
                    SELECT first.id FROM official_odds_observations first
                    WHERE first.match_id=m.id AND first.is_pre_match=1
                    ORDER BY first.observed_at ASC LIMIT 1)
                ORDER BY m.kickoff_time DESC LIMIT ?""", (max(1, min(limit, 100_000)),)).fetchall()
        return [dict(row) for row in rows]

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

    def add_external_bookmaker_odds(self, match_id: int, bookmakers: list[dict[str, Any]],
                                    fetched_at: str | None = None) -> int:
        timestamp = fetched_at or utcnow()
        valid = [item for item in bookmakers if all(float(item.get("odds", {}).get(key, 0)) > 1
                                                     for key in ("home", "draw", "away"))]
        with self.db.connect() as c:
            c.executemany("""INSERT INTO external_bookmaker_odds
                (match_id,bookmaker,bookmaker_key,market,home_odds,draw_odds,away_odds,last_update,fetched_at)
                VALUES(?,?,?,?,?,?,?,?,?)""", [
                (match_id, item["bookmaker"], item.get("bookmaker_key"), item.get("market", "H2H"),
                 item["odds"]["home"], item["odds"]["draw"], item["odds"]["away"],
                 item.get("last_update") or timestamp, timestamp) for item in valid
            ])
        return len(valid)

    def latest_external_bookmaker_odds(self, match_id: int) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("""SELECT bookmaker,bookmaker_key,market,home_odds,draw_odds,away_odds,last_update
                FROM external_bookmaker_odds WHERE match_id=? AND fetched_at=(
                    SELECT MAX(fetched_at) FROM external_bookmaker_odds WHERE match_id=?
                ) ORDER BY bookmaker""", (match_id, match_id)).fetchall()
        return [{"bookmaker": row["bookmaker"], "bookmaker_key": row["bookmaker_key"],
                 "market": row["market"], "odds": {"home": row["home_odds"],
                 "draw": row["draw_odds"], "away": row["away_odds"]},
                 "last_update": row["last_update"], "source": "The Odds API"} for row in rows]

    def add_features(self, match_id: int, features: dict[str, Any], version: str = "v1") -> None:
        with self.db.connect() as c:
            c.execute("INSERT INTO match_features(match_id,feature_version,feature_json,created_at) VALUES(?,?,?,?)",
                      (match_id, version, json.dumps(features, ensure_ascii=False), utcnow()))

    def add_profit_scorer_evidence(self, evidence: dict[str, Any]) -> bool:
        with self.db.connect() as c:
            cursor = c.execute("""INSERT OR IGNORE INTO profit_scorer_evidence(
                match_id,official_odds_observation_id,scorer_artifact_sha256,strategy_label,
                selected_outcome,feature_engine,feature_json,market_probability,
                predicted_probability,predicted_ev,passes_scorer,scored_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                int(evidence["match_id"]),
                int(evidence["official_odds_observation_id"]),
                str(evidence["scorer_artifact_sha256"]),
                str(evidence["strategy_label"]),
                str(evidence["selected_outcome"]).upper(),
                str(evidence["feature_engine"]),
                json.dumps(evidence["features"], ensure_ascii=False, sort_keys=True),
                float(evidence["market_probability"]),
                float(evidence["predicted_probability"]),
                float(evidence["predicted_ev"]),
                int(bool(evidence["passes_scorer"])),
                str(evidence.get("scored_at") or utcnow()),
            ))
            return cursor.rowcount > 0

    def list_profit_scorer_evidence(self, strategy_label: str | None = None,
                                    limit: int = 1000) -> list[dict[str, Any]]:
        where = " WHERE strategy_label=?" if strategy_label else ""
        params: tuple[Any, ...] = (strategy_label,) if strategy_label else ()
        query = (
            "SELECT * FROM profit_scorer_evidence" + where
            + " ORDER BY scored_at DESC,id DESC LIMIT ?"
        )
        with self.db.connect() as c:
            rows = c.execute(query, (*params, max(1, min(limit, 100_000)))).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["features"] = json.loads(item.pop("feature_json"))
            output.append(item)
        return output

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

    def list_official_matches(self, from_date: str | None = None) -> list[dict[str, Any]]:
        date_filter = " AND substr(kickoff_time,1,10)>=?" if from_date else ""
        params = (from_date,) if from_date else ()
        with self.db.connect() as c:
            rows = c.execute(
                f"""SELECT * FROM matches
                   WHERE official_match_id LIKE 'sporttery-%'
                     AND source_url IS NOT NULL
                     {date_filter}
                   ORDER BY kickoff_time""",
                params,
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
            verified_at = None
            if rows and not external:
                match = c.execute("SELECT last_seen_at FROM matches WHERE id=?", (match_id,)).fetchone()
                verified_at = match["last_seen_at"] if match and match["last_seen_at"] else None
        fetched_at = rows[0]["fetched_at"] if rows else None
        if verified_at and (not fetched_at or verified_at > fetched_at):
            fetched_at = verified_at
        return {"odds": {r["option"]: r["value"] for r in rows},
                "source": rows[0]["source"] if rows else None,
                "fetched_at": fetched_at}

    def latest_features(self, match_id: int) -> dict[str, Any]:
        with self.db.connect() as c:
            row = c.execute("SELECT feature_json FROM match_features WHERE match_id=? ORDER BY created_at DESC LIMIT 1",
                            (match_id,)).fetchone()
        return json.loads(row["feature_json"]) if row else {}

    def upsert_historical_matches(self, rows: Iterable[dict[str, Any]], source: str = "csv") -> dict[str, int]:
        imported = updated = dropped = 0
        with self.db.connect() as c:
            for row in rows:
                try:
                    league = str(row.get("league") or "").strip()
                    home_team = str(row.get("home_team") or row.get("homeTeam") or "").strip()
                    away_team = str(row.get("away_team") or row.get("awayTeam") or "").strip()
                    played_at = str(row.get("played_at") or row.get("playedAt") or row.get("date") or "").strip()
                    home_goals = int(row.get("home_goals", row.get("homeGoals", row.get("home_score"))))
                    away_goals = int(row.get("away_goals", row.get("awayGoals", row.get("away_score"))))
                    match_type = str(row.get("match_type") or row.get("matchType") or "LEAGUE").upper()
                    if not league or not home_team or not away_team or home_team == away_team or not played_at:
                        raise ValueError("invalid historical match")
                    if home_goals < 0 or away_goals < 0 or match_type not in {"LEAGUE", "CUP", "FRIENDLY"}:
                        raise ValueError("invalid historical result")
                    natural_key = f"{league}|{home_team}|{away_team}|{played_at}"
                    row_id = str(row.get("id") or hashlib.sha256(natural_key.encode("utf-8")).hexdigest()[:24])
                    existed = c.execute("SELECT 1 FROM historical_matches WHERE id=?", (row_id,)).fetchone()
                    c.execute("""INSERT INTO historical_matches
                        (id,league,home_team,away_team,home_goals,away_goals,played_at,match_type,source,imported_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                        league=excluded.league,home_team=excluded.home_team,away_team=excluded.away_team,
                        home_goals=excluded.home_goals,away_goals=excluded.away_goals,played_at=excluded.played_at,
                        match_type=excluded.match_type,source=excluded.source,imported_at=excluded.imported_at""",
                        (row_id, league, home_team, away_team, home_goals, away_goals, played_at,
                         match_type, source, utcnow()))
                    if existed:
                        updated += 1
                    else:
                        imported += 1
                except (TypeError, ValueError):
                    dropped += 1
        return {"imported": imported, "updated": updated, "dropped": dropped}

    def list_historical_matches(self, cutoff_time: str | None = None, league: str | None = None,
                                teams: Iterable[str] | None = None, limit: int = 20_000) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if cutoff_time:
            conditions.append("played_at < ?")
            params.append(cutoff_time)
        if league:
            conditions.append("league = ?")
            params.append(league)
        team_list = [team for team in (teams or []) if team]
        if team_list:
            placeholders = ",".join("?" for _ in team_list)
            conditions.append(f"(home_team IN ({placeholders}) OR away_team IN ({placeholders}))")
            params.extend(team_list)
            params.extend(team_list)
        query = "SELECT * FROM historical_matches"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY played_at ASC LIMIT ?"
        params.append(max(1, min(limit, 100_000)))
        with self.db.connect() as c:
            return [dict(row) for row in c.execute(query, tuple(params)).fetchall()]

    def historical_match_count(self) -> int:
        with self.db.connect() as c:
            return int(c.execute("SELECT COUNT(*) FROM historical_matches").fetchone()[0])

    def latest_prediction(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("""SELECT * FROM model_predictions WHERE match_id=?
                AND model_name IN ('contextual_ensemble','ensemble','baseline')
                AND EXISTS (SELECT 1 FROM match_features f WHERE f.match_id=model_predictions.match_id)
                ORDER BY predicted_at DESC, CASE model_name WHEN 'contextual_ensemble' THEN 0 WHEN 'ensemble' THEN 1 ELSE 2 END LIMIT 1""",
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

    def start_agent_run(self, trigger_name: str) -> str:
        run_id = uuid.uuid4().hex
        with self.db.connect() as c:
            c.execute("INSERT INTO agent_runs(id,status,trigger_name,started_at) VALUES(?,?,?,?)",
                      (run_id, "running", trigger_name, utcnow()))
        return run_id

    def start_agent_step(self, run_id: str, agent_name: str, inputs: dict[str, Any] | None = None) -> int:
        with self.db.connect() as c:
            cursor = c.execute("""INSERT INTO agent_run_steps
                (run_id,agent_name,status,input_json,started_at) VALUES(?,?,?,?,?)""",
                (run_id, agent_name, "running", json.dumps(inputs or {}, ensure_ascii=False), utcnow()))
            return int(cursor.lastrowid)

    def finish_agent_step(self, step_id: int, status: str, output: dict[str, Any] | None = None,
                          error_message: str | None = None) -> None:
        with self.db.connect() as c:
            c.execute("""UPDATE agent_run_steps SET status=?,output_json=?,error_message=?,finished_at=?
                WHERE id=?""", (status, json.dumps(output or {}, ensure_ascii=False), error_message, utcnow(), step_id))

    def finish_agent_run(self, run_id: str, status: str, summary: dict[str, Any]) -> None:
        with self.db.connect() as c:
            c.execute("UPDATE agent_runs SET status=?,summary_json=?,finished_at=? WHERE id=?",
                      (status, json.dumps(summary, ensure_ascii=False), utcnow(), run_id))

    def get_agent_run(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connect() as c:
            run = c.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                return None
            steps = c.execute("SELECT * FROM agent_run_steps WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        result = dict(run)
        result["summary"] = json.loads(result.pop("summary_json"))
        result["steps"] = []
        for row in steps:
            item = dict(row)
            item["input"] = json.loads(item.pop("input_json"))
            item["output"] = json.loads(item.pop("output_json"))
            result["steps"].append(item)
        return result

    def list_agent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute("SELECT id FROM agent_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [run for row in rows if (run := self.get_agent_run(row["id"]))]

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

    def add_audit_event(self, operator: str, module: str, action: str, detail: str, result: str) -> None:
        with self.db.connect() as c:
            c.execute("INSERT INTO audit_events(operator,module,action,detail,result,created_at) VALUES(?,?,?,?,?,?)",
                      (operator, module, action, detail, result, utcnow()))

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
                "historical_matches": "SELECT COUNT(*) FROM historical_matches",
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

