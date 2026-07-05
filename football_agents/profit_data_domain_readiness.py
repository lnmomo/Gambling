from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Database, db
from .official_pool_research import _league_evidence, map_league_to_history_code
from .repository import Repository


ODDS_COLUMN_SETS = {
    "B365_OPEN": ("B365H", "B365D", "B365A"),
    "AVG_OPEN": ("AvgH", "AvgD", "AvgA"),
    "PS_OPEN": ("PSH", "PSD", "PSA"),
    "MAX_OPEN": ("MaxH", "MaxD", "MaxA"),
    "B365_CLOSE": ("B365CH", "B365CD", "B365CA"),
    "AVG_CLOSE": ("AvgCH", "AvgCD", "AvgCA"),
    "PS_CLOSE": ("PSCH", "PSCD", "PSCA"),
    "MAX_CLOSE": ("MaxCH", "MaxCD", "MaxCA"),
}

MIN_SEARCH_ROWS = 1000
MIN_SEARCH_ACTIVE_MONTHS = 24
MIN_ODDS_ROWS = 300
KNOWN_EVIDENCE_CODES = {"I2", "SP1", "JPN", "FIN", "WORLD_CUP", "INTERNATIONAL"}


@dataclass(frozen=True)
class DomainStats:
    code: str
    paths: list[str]
    rows: int
    first_date: str | None
    last_date: str | None
    active_months: int
    odds_coverage: dict[str, int]
    best_odds_source: str | None
    best_odds_rows: int
    official_pool_matches: int
    official_pool_with_odds: int
    readiness: str
    research_priority: str
    blocker: str
    existing_evidence_status: str | None
    evidence_reports: list[str]
    suggested_commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for dayfirst in (True, False):
        try:
            if "/" in raw:
                parsed = datetime.strptime(raw.split()[0], "%d/%m/%Y" if dayfirst else "%m/%d/%Y")
            else:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            continue
    return None


def _float_gt_one(value: Any) -> bool:
    try:
        return float(value) > 1.0
    except (TypeError, ValueError):
        return False


def _candidate_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    paths = [path for path in root.glob("*/*.csv") if path.is_file()]
    paths.extend(path for path in (root / "new").glob("*.csv") if path.is_file())
    return sorted(set(paths))


def _scan_path(path: Path) -> dict[str, Any]:
    rows = 0
    dates: set[str] = set()
    odds_coverage = {source: 0 for source in ODDS_COLUMN_SETS}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows += 1
                date_value = row.get("Date") or row.get("date") or row.get("played_at") or row.get("match_date")
                parsed = _parse_date(date_value)
                if parsed:
                    dates.add(parsed)
                for source, columns in ODDS_COLUMN_SETS.items():
                    if all(column in row and _float_gt_one(row.get(column)) for column in columns):
                        odds_coverage[source] += 1
    except OSError:
        pass
    return {"rows": rows, "dates": dates, "odds_coverage": odds_coverage}


def _official_pool_counts(database: Database) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    repository = Repository(database)
    try:
        matches = repository.list_official_matches()
    except Exception:
        return counts
    for match in matches:
        code = map_league_to_history_code(match.get("league"))
        if not code:
            continue
        bucket = counts.setdefault(code, {"matches": 0, "with_odds": 0})
        bucket["matches"] += 1
        try:
            odds = repository.latest_odds(int(match["id"])).get("odds") or {}
            if all(_float_gt_one(odds.get(key)) for key in ("home", "draw", "away")):
                bucket["with_odds"] += 1
        except Exception:
            continue
    return counts


def _readiness(
    rows: int,
    active_months: int,
    best_odds_rows: int,
    official_matches: int,
) -> tuple[str, str, str]:
    if best_odds_rows <= 0:
        return (
            "FEATURES_ONLY_NO_1X2_ODDS",
            "DATA_ONLY",
            "Historical results exist, but no usable 1X2 odds columns were found for edge validation.",
        )
    if rows < 120 or active_months < 3:
        return (
            "TOO_SMALL_FOR_WALK_FORWARD",
            "LOW",
            "The domain has odds, but too few rows/months for no-lookahead monthly validation.",
        )
    if rows < MIN_SEARCH_ROWS or active_months < MIN_SEARCH_ACTIVE_MONTHS or best_odds_rows < MIN_ODDS_ROWS:
        return (
            "RESEARCH_ONLY_SMALL_SAMPLE",
            "MEDIUM_RESEARCH" if official_matches else "LOW_RESEARCH",
            "The domain has odds, but sample size or active-month coverage is still below the main search standard.",
        )
    if official_matches:
        return (
            "SEARCH_READY_CURRENT_OFFICIAL_POOL",
            "HIGH_CURRENT_POOL",
            "The domain has enough odds-backed history and is currently represented in the official pool.",
        )
    return (
        "SEARCH_READY_NOT_IN_CURRENT_POOL",
        "MEDIUM_SEARCH",
        "The domain has enough odds-backed history, but is not currently represented in the official pool.",
    )


def _commands(code: str, best_odds_source: str | None, readiness: str) -> list[str]:
    if not best_odds_source:
        if code in {"INTERNATIONAL", "WORLD_CUP"}:
            return [
                "python -m football_agents.cli sync-international-odds-history --provider odds-api",
                "Import or archive settled 1X2 odds before running a profit search.",
            ]
        return ["Collect historical 1X2 odds CSV before running walk-forward profit search."]
    if readiness in {"SEARCH_READY_CURRENT_OFFICIAL_POOL", "SEARCH_READY_NOT_IN_CURRENT_POOL"}:
        return [
            (
                f"python scripts/market_bias_diagnostics.py --seasons {code} --odds-source {best_odds_source} "
                f"--min-samples 150 --min-active-months 18 --output-dir reports\\market_bias_diagnostics_{code.lower()}_{best_odds_source.lower()}"
            ),
            (
                f"python scripts/cross_league_rule_search.py --seasons {code} --league-group-scope {code} "
                f"--output-dir reports\\cross_league_rule_search_{code.lower()}_next"
            ),
        ]
    return [
        (
            f"python scripts/market_bias_diagnostics.py --seasons {code} --odds-source {best_odds_source} "
            f"--min-samples 50 --min-active-months 6 --output-dir reports\\market_bias_diagnostics_{code.lower()}_small_sample"
        )
    ]


def build_profit_data_domain_readiness(
    root: Path | str = Path("data/historical_csv/football-data"),
    database: Database = db,
) -> dict[str, Any]:
    root_path = Path(root)
    use_existing_evidence = root_path == Path("data/historical_csv/football-data")
    by_code: dict[str, dict[str, Any]] = {}
    for path in _candidate_paths(root_path):
        code = path.stem.upper()
        bucket = by_code.setdefault(code, {
            "paths": [],
            "rows": 0,
            "dates": set(),
            "odds_coverage": {source: 0 for source in ODDS_COLUMN_SETS},
        })
        scanned = _scan_path(path)
        bucket["paths"].append(str(path))
        bucket["rows"] += int(scanned["rows"])
        bucket["dates"].update(scanned["dates"])
        for source, count in scanned["odds_coverage"].items():
            bucket["odds_coverage"][source] += int(count)

    official_counts = _official_pool_counts(database)
    domains: list[DomainStats] = []
    for code, bucket in by_code.items():
        dates = sorted(bucket["dates"])
        months = {item[:7] for item in dates}
        odds_coverage = dict(bucket["odds_coverage"])
        best_source, best_rows = max(odds_coverage.items(), key=lambda item: item[1])
        if best_rows <= 0:
            best_source = None
        official = official_counts.get(code, {"matches": 0, "with_odds": 0})
        readiness, priority, blocker = _readiness(
            int(bucket["rows"]),
            len(months),
            int(best_rows),
            int(official["matches"]),
        )
        evidence = _league_evidence(code) if use_existing_evidence and code in KNOWN_EVIDENCE_CODES else None
        evidence_reports: list[str] = []
        if evidence:
            evidence_reports = list(evidence.get("reports") or [])
            evidence_status = str(evidence.get("status") or "")
            evidence_priority = str(evidence.get("priority") or "")
            if evidence_priority == "LOW_DO_NOT_LOOSEN" or evidence_status.startswith("rejected"):
                readiness = "REJECTED_BY_EXISTING_STABILITY_GATES"
                priority = "LOW_DO_NOT_LOOSEN"
                blocker = str(evidence.get("blocker") or blocker)
            elif evidence_status.startswith("research_") or evidence_status.startswith("research_watch"):
                readiness = "RESEARCH_WATCH_ONLY_EXISTING_GATES"
                priority = evidence_priority or "MEDIUM_RESEARCH"
                blocker = str(evidence.get("blocker") or blocker)
            elif evidence_status.startswith("validated"):
                priority = "HIGH_CURRENT_POOL" if int(official["matches"]) else "HIGH_WHEN_PRESENT"
                blocker = str(evidence.get("blocker") or blocker)
        else:
            evidence_status = None
        domains.append(DomainStats(
            code=code,
            paths=sorted(bucket["paths"]),
            rows=int(bucket["rows"]),
            first_date=dates[0] if dates else None,
            last_date=dates[-1] if dates else None,
            active_months=len(months),
            odds_coverage=odds_coverage,
            best_odds_source=best_source,
            best_odds_rows=int(best_rows),
            official_pool_matches=int(official["matches"]),
            official_pool_with_odds=int(official["with_odds"]),
            readiness=readiness,
            research_priority=priority,
            blocker=blocker,
            existing_evidence_status=evidence_status,
            evidence_reports=evidence_reports,
            suggested_commands=list(evidence.get("commands") or []) if evidence else _commands(code, best_source, readiness),
        ))

    priority_rank = {
        "HIGH_CURRENT_POOL": 0,
        "HIGH_WHEN_PRESENT": 1,
        "MEDIUM_SEARCH": 2,
        "MEDIUM_RESEARCH": 3,
        "LOW_RESEARCH": 4,
        "DATA_ONLY": 5,
        "LOW": 6,
        "LOW_DO_NOT_LOOSEN": 7,
    }
    domains.sort(key=lambda item: (
        priority_rank.get(item.research_priority, 99),
        -item.official_pool_matches,
        -item.best_odds_rows,
        -item.active_months,
        item.code,
    ))
    status_counts: dict[str, int] = {}
    for domain in domains:
        status_counts[domain.readiness] = status_counts.get(domain.readiness, 0) + 1
    search_ready = [
        domain for domain in domains
        if domain.readiness.startswith("SEARCH_READY") and domain.research_priority != "LOW_DO_NOT_LOOSEN"
    ]
    return {
        "method": "profit historical data domain readiness",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root_path),
        "domain_count": len(domains),
        "search_ready_domains": len(search_ready),
        "status_counts": [
            {"readiness": key, "domains": value}
            for key, value in sorted(status_counts.items(), key=lambda item: item[1], reverse=True)
        ],
        "top_domains": [domain.to_dict() for domain in domains[:20]],
        "domains": [domain.to_dict() for domain in domains],
        "next_algorithmic_action": (
            "Run no-lookahead diagnostics on HIGH_CURRENT_POOL domains first."
            if any(domain.research_priority == "HIGH_CURRENT_POOL" for domain in domains)
            else "Run no-lookahead diagnostics on the highest-ranked search-ready domains not already rejected."
            if search_ready
            else "Collect broader historical 1X2 odds before searching for a new allocation algorithm."
        ),
        "guardrail": "Domain readiness only prioritizes data for research; it does not promote any strategy without walk-forward, audit, calibration, and official-SP validation.",
    }
