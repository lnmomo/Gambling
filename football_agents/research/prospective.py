from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from football_agents.agents.workflow import DecisionWorkflow
from football_agents.config import settings
from football_agents.db import Database, db
from football_agents.independent_model import INDEPENDENT_MODEL_WEIGHTS
from football_agents.repository import Repository

from .evaluation import evaluate_probabilities


OUTCOMES = ("home", "draw", "away")
PRE_MATCH_STATUSES = {"scheduled", "not_started", "live"}
FROZEN_ARTIFACTS = (
    "football_agents/agents/workflow.py",
    "football_agents/models/elo.py",
    "football_agents/models/poisson.py",
    "football_agents/models/ensemble.py",
    "football_agents/independent_model.py",
    "football_agents/features.py",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class ProspectiveResearchService:
    """Registers and evaluates immutable, exact-timestamp prospective predictions."""

    def __init__(self, database: Database = db, repository: Repository | None = None,
                 workflow: DecisionWorkflow | None = None) -> None:
        self.db = database
        self.repository = repository or Repository(database)
        self.workflow = workflow or DecisionWorkflow(self.repository)

    def current_manifest(self) -> dict[str, Any]:
        files: dict[str, str] = {}
        for relative in FROZEN_ARTIFACTS:
            path = settings.project_dir / relative
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        config = {
            "model_name": "ensemble", "model_version": "v1",
            "ensemble_weights": self.workflow.ensemble.weights,
            "independent_model_weights": INDEPENDENT_MODEL_WEIGHTS,
            "probability_outcomes": list(OUTCOMES),
            "market_devig": "multiplicative",
            "qwen_probability_adjustment": False,
        }
        algorithm_hash = hashlib.sha256(_canonical({"files": files, "config": config}).encode()).hexdigest()
        return {"algorithm_hash": algorithm_hash, "files": files, "config": config}

    def freeze_current_model(self) -> dict[str, Any]:
        manifest = self.current_manifest()
        freeze_id = f"freeze-{manifest['algorithm_hash'][:20]}"
        record = {
            "freeze_id": freeze_id, "algorithm_name": "deterministic-production-ensemble",
            "model_version": "v1", "algorithm_hash": manifest["algorithm_hash"],
            "config_json": _canonical(manifest["config"]),
            "artifact_manifest_json": _canonical(manifest["files"]), "registered_at": utcnow(),
        }
        with self.db.connect() as connection:
            connection.execute("""INSERT OR IGNORE INTO prospective_model_freezes
                (freeze_id,algorithm_name,model_version,algorithm_hash,config_json,artifact_manifest_json,registered_at)
                VALUES(:freeze_id,:algorithm_name,:model_version,:algorithm_hash,:config_json,
                       :artifact_manifest_json,:registered_at)""", record)
            row = connection.execute("SELECT * FROM prospective_model_freezes WHERE freeze_id=?", (freeze_id,)).fetchone()
        return self._decode_freeze(dict(row))

    def ensure_default_study(self) -> dict[str, Any]:
        freeze = self.freeze_current_model()
        return self.register_study(
            settings.prospective_research_study_name,
            "At T-60 to T-120 minutes, frozen ensemble has lower multiclass Log Loss than de-vigged official odds.",
            freeze["freeze_id"], max(1, settings.prospective_research_min_settled),
            max(0, settings.prospective_research_min_days), 60, 60,
        )

    def register_study(self, name: str, hypothesis: str, freeze_id: str,
                       min_settled_matches: int, min_calendar_days: int,
                       primary_horizon_minutes: int = 60, horizon_tolerance_minutes: int = 60,
                       starts_at: str | None = None) -> dict[str, Any]:
        with self.db.connect() as connection:
            existing = connection.execute("""SELECT * FROM prospective_research_studies
                WHERE study_name=? AND freeze_id=?""",
                (name, freeze_id)).fetchone()
            if existing:
                return dict(existing)
            now = utcnow()
            study = {
                "study_id": f"study-{uuid.uuid4().hex}",
                "study_name": name, "hypothesis": hypothesis, "freeze_id": freeze_id,
                "starts_at": starts_at or now, "min_settled_matches": max(1, min_settled_matches),
                "min_calendar_days": max(0, min_calendar_days), "registered_at": now,
                "primary_horizon_minutes": max(1, primary_horizon_minutes),
                "horizon_tolerance_minutes": max(0, horizon_tolerance_minutes),
            }
            connection.execute("""INSERT INTO prospective_research_studies
                (study_id,study_name,hypothesis,freeze_id,starts_at,min_settled_matches,min_calendar_days,registered_at,
                 primary_horizon_minutes,horizon_tolerance_minutes)
                VALUES(:study_id,:study_name,:hypothesis,:freeze_id,:starts_at,:min_settled_matches,
                       :min_calendar_days,:registered_at,:primary_horizon_minutes,:horizon_tolerance_minutes)""", study)
        return study

    def capture(self, limit: int = 100, study_id: str | None = None) -> dict[str, Any]:
        study = self._get_study(study_id) if study_id else self.ensure_default_study()
        freeze = self.get_freeze(study["freeze_id"])
        current_hash = self.current_manifest()["algorithm_hash"]
        if current_hash != freeze["algorithm_hash"]:
            raise RuntimeError("frozen algorithm hash no longer matches the running code; register a new study")
        now = datetime.now(timezone.utc)
        captured = duplicates = skipped = eligible_pre_match = 0
        skip_reasons: dict[str, int] = {}
        warnings: list[str] = []
        pool = self.repository.list_official_matches(now.date().isoformat())
        matches = sorted(
            pool,
            key=lambda match: (
                0 if (
                    str(match.get("status") or "").strip().lower() in PRE_MATCH_STATUSES
                    and _parse_time(match["kickoff_time"]) > now
                ) else 1,
                _parse_time(match["kickoff_time"]),
            ),
        )[:max(1, min(limit, 500))]
        for match in matches:
            status = str(match.get("status") or "").strip().lower()
            if status not in PRE_MATCH_STATUSES:
                skipped += 1
                skip_reasons["ineligible_status"] = skip_reasons.get("ineligible_status", 0) + 1
                continue
            if _parse_time(match["kickoff_time"]) <= now:
                skipped += 1
                skip_reasons["kickoff_not_in_future"] = skip_reasons.get("kickoff_not_in_future", 0) + 1
                continue
            eligible_pre_match += 1
            observation = self._latest_pre_match_observation(match["id"])
            if not observation:
                skipped += 1
                skip_reasons["missing_pre_match_official_sp"] = (
                    skip_reasons.get("missing_pre_match_official_sp", 0) + 1
                )
                continue
            try:
                self.workflow.evaluate(match["id"])
            except Exception as exc:
                skipped += 1
                skip_reasons["workflow_error"] = skip_reasons.get("workflow_error", 0) + 1
                warnings.append(f"{match['official_match_id']}: {exc}")
                continue
            source_prediction = self._latest_ensemble_prediction(match["id"])
            if not source_prediction:
                skipped += 1
                skip_reasons["missing_ensemble_prediction"] = (
                    skip_reasons.get("missing_ensemble_prediction", 0) + 1
                )
                continue
            inserted = self._insert_prediction(study, freeze, match, observation, source_prediction)
            captured += int(inserted)
            duplicates += int(not inserted)
        if eligible_pre_match and not captured and not duplicates:
            warnings.append("eligible_pre_match_matches_produced_no_frozen_predictions")
        progress = self.progress(study["study_id"])
        return {
            "matches": len(matches),
            "eligible_pre_match": eligible_pre_match,
            "predictions": captured,
            "duplicates": duplicates,
            "skipped": skipped,
            "skip_reasons": skip_reasons,
            "warnings": warnings[:20],
            "study": progress,
        }

    def progress(self, study_id: str | None = None) -> dict[str, Any]:
        study = self._get_study(study_id)
        with self.db.connect() as connection:
            counts = connection.execute("""SELECT COUNT(*) predictions,
                COUNT(DISTINCT p.match_id) matches,
                COUNT(DISTINCT CASE WHEN o.minutes_to_kickoff BETWEEN ? AND ? THEN p.match_id END) eligible_matches,
                COUNT(DISTINCT CASE WHEN r.outcome IN ('home','draw','away')
                    AND o.minutes_to_kickoff BETWEEN ? AND ? THEN p.match_id END) settled_matches,
                MIN(p.predicted_at) first_prediction_at,MAX(p.predicted_at) last_prediction_at
                FROM prospective_predictions p
                JOIN official_odds_observations o ON o.id=p.official_odds_observation_id
                LEFT JOIN results r ON r.match_id=p.match_id
                WHERE p.study_id=?""", (
                    study["primary_horizon_minutes"],
                    study["primary_horizon_minutes"] + study["horizon_tolerance_minutes"],
                    study["primary_horizon_minutes"],
                    study["primary_horizon_minutes"] + study["horizon_tolerance_minutes"],
                    study["study_id"],
                )).fetchone()
            run = connection.execute("SELECT * FROM prospective_confirmation_runs WHERE study_id=?",
                                     (study["study_id"],)).fetchone()
        elapsed_days = max(0, (datetime.now(timezone.utc) - _parse_time(study["starts_at"])).days)
        settled = int(counts["settled_matches"] or 0)
        ready = settled >= study["min_settled_matches"] and elapsed_days >= study["min_calendar_days"]
        status = "COMPLETED" if run else "READY" if ready else "COLLECTING"
        return {**study, **dict(counts), "elapsed_days": elapsed_days, "ready": ready, "status": status,
                "remaining_matches": max(0, study["min_settled_matches"] - settled),
                "remaining_days": max(0, study["min_calendar_days"] - elapsed_days),
                "confirmation": self._decode_run(dict(run)) if run else None}

    def run_confirmation_once(self, study_id: str | None = None) -> dict[str, Any]:
        progress = self.progress(study_id)
        if progress["confirmation"]:
            return progress["confirmation"]
        if not progress["ready"]:
            raise RuntimeError(
                f"study is not ready: {progress['remaining_matches']} matches and "
                f"{progress['remaining_days']} days remaining"
            )
        rows = self._settled_rows(progress["study_id"])
        outcomes = np.array([row["outcome"] for row in rows])
        proposed = np.array([[row[f"p_{key}"] for key in OUTCOMES] for row in rows], dtype=float)
        market = np.array([[row[f"market_p_{key}"] for key in OUTCOMES] for row in rows], dtype=float)
        proposed_metrics = evaluate_probabilities(proposed, outcomes)
        market_metrics = evaluate_probabilities(market, outcomes)
        indices = np.array([OUTCOMES.index(value) for value in outcomes])
        delta = -np.log(proposed[np.arange(len(rows)), indices]) + np.log(market[np.arange(len(rows)), indices])
        rng = np.random.default_rng(20260622)
        bootstrap = np.empty(5000)
        for start in range(0, len(bootstrap), 250):
            size = min(250, len(bootstrap) - start)
            selected = rng.integers(0, len(delta), size=(size, len(delta)))
            bootstrap[start:start + size] = delta[selected].mean(axis=1)
        difference = float(delta.mean())
        result = {
            "proposed": proposed_metrics, "market": market_metrics,
            "log_loss_difference": difference,
            "ci95_low": float(np.quantile(bootstrap, 0.025)),
            "ci95_high": float(np.quantile(bootstrap, 0.975)),
            "probability_proposed_better": float(np.mean(bootstrap < 0)),
        }
        decision = "SUPERIOR" if result["ci95_high"] < 0 else "INFERIOR" if result["ci95_low"] > 0 else "INCONCLUSIVE"
        record = {
            "run_id": f"confirm-{uuid.uuid4().hex}", "study_id": progress["study_id"],
            "freeze_id": progress["freeze_id"], "executed_at": utcnow(),
            "settled_matches": len(rows), "elapsed_days": progress["elapsed_days"],
            "primary_metric": "multiclass_log_loss", "result_json": _canonical(result), "decision": decision,
        }
        with self.db.connect() as connection:
            connection.execute("""INSERT INTO prospective_confirmation_runs
                (run_id,study_id,freeze_id,executed_at,settled_matches,elapsed_days,primary_metric,result_json,decision)
                VALUES(:run_id,:study_id,:freeze_id,:executed_at,:settled_matches,:elapsed_days,
                       :primary_metric,:result_json,:decision)""", record)
        return self._decode_run(record)

    def get_freeze(self, freeze_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM prospective_model_freezes WHERE freeze_id=?", (freeze_id,)).fetchone()
        if not row:
            raise KeyError(freeze_id)
        return self._decode_freeze(dict(row))

    def _get_study(self, study_id: str | None) -> dict[str, Any]:
        with self.db.connect() as connection:
            if study_id:
                row = connection.execute("SELECT * FROM prospective_research_studies WHERE study_id=?", (study_id,)).fetchone()
            else:
                row = connection.execute("SELECT * FROM prospective_research_studies ORDER BY registered_at DESC LIMIT 1").fetchone()
        if not row:
            return self.ensure_default_study()
        return dict(row)

    def _latest_pre_match_observation(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            row = connection.execute("""SELECT * FROM official_odds_observations
                WHERE match_id=? AND is_pre_match=1 ORDER BY observed_at DESC LIMIT 1""", (match_id,)).fetchone()
        return dict(row) if row else None

    def _latest_ensemble_prediction(self, match_id: int) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            row = connection.execute("""SELECT * FROM model_predictions WHERE match_id=? AND model_name='ensemble'
                ORDER BY predicted_at DESC LIMIT 1""", (match_id,)).fetchone()
        return dict(row) if row else None

    def _insert_prediction(self, study: dict[str, Any], freeze: dict[str, Any], match: dict[str, Any],
                           observation: dict[str, Any], prediction: dict[str, Any]) -> bool:
        probabilities = np.array([prediction[f"p_{key}"] for key in OUTCOMES], dtype=float)
        probabilities /= probabilities.sum()
        inverse = 1 / np.array([observation[f"{key}_sp"] for key in OUTCOMES], dtype=float)
        market = inverse / inverse.sum()
        payload = {
            "study_id": study["study_id"], "freeze_id": freeze["freeze_id"],
            "official_match_id": match["official_match_id"], "observation_id": observation["id"],
            "source_prediction_id": prediction["id"], "probabilities": probabilities.tolist(),
            "market": market.tolist(),
        }
        record = {
            "prediction_id": f"prospective-{uuid.uuid4().hex}", "study_id": study["study_id"],
            "freeze_id": freeze["freeze_id"], "match_id": match["id"],
            "official_match_id": match["official_match_id"],
            "official_odds_observation_id": observation["id"], "source_prediction_id": prediction["id"],
            "predicted_at": prediction["predicted_at"], "kickoff_time": match["kickoff_time"],
            "model_name": prediction["model_name"], "model_version": prediction["model_version"],
            "p_home": probabilities[0], "p_draw": probabilities[1], "p_away": probabilities[2],
            "market_p_home": market[0], "market_p_draw": market[1], "market_p_away": market[2],
            "payload_hash": hashlib.sha256(_canonical(payload).encode()).hexdigest(), "created_at": utcnow(),
        }
        if _parse_time(record["predicted_at"]) >= _parse_time(record["kickoff_time"]):
            raise ValueError("post-kickoff prediction cannot enter a prospective study")
        if _parse_time(record["predicted_at"]) < _parse_time(observation["observed_at"]):
            raise ValueError("prediction cannot reference an odds observation from the future")
        with self.db.connect() as connection:
            cursor = connection.execute("""INSERT OR IGNORE INTO prospective_predictions
                (prediction_id,study_id,freeze_id,match_id,official_match_id,official_odds_observation_id,
                 source_prediction_id,predicted_at,kickoff_time,model_name,model_version,p_home,p_draw,p_away,
                 market_p_home,market_p_draw,market_p_away,payload_hash,created_at)
                VALUES(:prediction_id,:study_id,:freeze_id,:match_id,:official_match_id,
                 :official_odds_observation_id,:source_prediction_id,:predicted_at,:kickoff_time,:model_name,
                 :model_version,:p_home,:p_draw,:p_away,:market_p_home,:market_p_draw,:market_p_away,
                 :payload_hash,:created_at)""", record)
            return cursor.rowcount == 1

    def _settled_rows(self, study_id: str) -> list[dict[str, Any]]:
        study = self._get_study(study_id)
        lower = study["primary_horizon_minutes"]
        upper = lower + study["horizon_tolerance_minutes"]
        with self.db.connect() as connection:
            rows = connection.execute("""SELECT * FROM (
                SELECT p.*,r.outcome,o.minutes_to_kickoff,
                ROW_NUMBER() OVER (PARTITION BY p.match_id
                    ORDER BY ABS(o.minutes_to_kickoff-?)) selection_rank
                FROM prospective_predictions p
                JOIN official_odds_observations o ON o.id=p.official_odds_observation_id
                JOIN results r ON r.match_id=p.match_id
                WHERE p.study_id=? AND r.outcome IN ('home','draw','away')
                AND o.minutes_to_kickoff BETWEEN ? AND ?
                ) ranked WHERE selection_rank=1 ORDER BY kickoff_time""",
                (lower, study_id, lower, upper)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _decode_freeze(row: dict[str, Any]) -> dict[str, Any]:
        row["config"] = json.loads(row.pop("config_json"))
        row["artifact_manifest"] = json.loads(row.pop("artifact_manifest_json"))
        return row

    @staticmethod
    def _decode_run(row: dict[str, Any]) -> dict[str, Any]:
        row["result"] = json.loads(row.pop("result_json"))
        return row
