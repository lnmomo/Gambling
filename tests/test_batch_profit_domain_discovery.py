from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from batch_profit_domain_discovery import select_domains  # noqa: E402


def test_select_domains_skips_rejected_and_existing_evidence_domains():
    readiness = {
        "domains": [
            {
                "code": "FIN",
                "readiness": "REJECTED_BY_EXISTING_STABILITY_GATES",
                "research_priority": "LOW_DO_NOT_LOOSEN",
                "best_odds_source": "AVG_CLOSE",
                "existing_evidence_status": "rejected",
            },
            {
                "code": "SP1",
                "readiness": "RESEARCH_WATCH_ONLY_EXISTING_GATES",
                "research_priority": "MEDIUM_RESEARCH",
                "best_odds_source": "B365_OPEN",
                "existing_evidence_status": "research_watch",
            },
            {
                "code": "ARG",
                "readiness": "SEARCH_READY_NOT_IN_CURRENT_POOL",
                "research_priority": "MEDIUM_SEARCH",
                "best_odds_source": "AVG_CLOSE",
                "existing_evidence_status": None,
            },
            {
                "code": "USA",
                "readiness": "SEARCH_READY_NOT_IN_CURRENT_POOL",
                "research_priority": "MEDIUM_SEARCH",
                "best_odds_source": "MAX_CLOSE",
                "existing_evidence_status": None,
            },
        ]
    }

    selected = select_domains(readiness, limit=3)

    assert [row["code"] for row in selected] == ["ARG", "USA"]


def test_select_domains_respects_limit_and_requires_odds_source():
    readiness = {
        "domains": [
            {
                "code": "EMPTY",
                "readiness": "SEARCH_READY_NOT_IN_CURRENT_POOL",
                "research_priority": "MEDIUM_SEARCH",
                "best_odds_source": None,
                "existing_evidence_status": None,
            },
            {
                "code": "ARG",
                "readiness": "SEARCH_READY_NOT_IN_CURRENT_POOL",
                "research_priority": "MEDIUM_SEARCH",
                "best_odds_source": "AVG_CLOSE",
                "existing_evidence_status": None,
            },
            {
                "code": "USA",
                "readiness": "SEARCH_READY_NOT_IN_CURRENT_POOL",
                "research_priority": "MEDIUM_SEARCH",
                "best_odds_source": "MAX_CLOSE",
                "existing_evidence_status": None,
            },
        ]
    }

    selected = select_domains(readiness, limit=1)

    assert [row["code"] for row in selected] == ["ARG"]


def test_select_domains_can_skip_already_scanned_domains():
    readiness = {
        "domains": [
            {
                "code": "ARG",
                "readiness": "SEARCH_READY_NOT_IN_CURRENT_POOL",
                "research_priority": "MEDIUM_SEARCH",
                "best_odds_source": "AVG_CLOSE",
                "existing_evidence_status": None,
            },
            {
                "code": "USA",
                "readiness": "SEARCH_READY_NOT_IN_CURRENT_POOL",
                "research_priority": "MEDIUM_SEARCH",
                "best_odds_source": "MAX_CLOSE",
                "existing_evidence_status": None,
            },
            {
                "code": "BRA",
                "readiness": "SEARCH_READY_NOT_IN_CURRENT_POOL",
                "research_priority": "MEDIUM_SEARCH",
                "best_odds_source": "AVG_CLOSE",
                "existing_evidence_status": None,
            },
        ]
    }

    selected = select_domains(readiness, limit=2, offset=1)

    assert [row["code"] for row in selected] == ["USA", "BRA"]
