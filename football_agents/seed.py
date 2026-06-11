from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .agents import DecisionWorkflow
from .db import db
from .repository import Repository


def seed_demo() -> list[dict]:
    db.initialize()
    repository = Repository()
    workflow = DecisionWorkflow(repository)
    now = datetime.now(timezone.utc)
    demos = [
        ("DEMO-001", "国际友谊赛", "海城联", "山河竞技", 1.92, 3.45, 4.10, 2.12, 3.35, 3.55, 1.72, 0.86, 1575, 1450),
        ("DEMO-002", "欧洲联赛", "北方城", "港湾 FC", 2.28, 3.20, 3.05, 2.30, 3.25, 3.10, 1.34, 1.16, 1510, 1490),
        ("DEMO-003", "亚洲联赛", "东方体育", "绿茵联", 2.75, 3.10, 2.52, 2.70, 3.15, 2.58, 1.08, 1.37, 1470, 1530),
    ]
    output = []
    for index, item in enumerate(demos):
        oid, league, home, away, sh, sd, sa, mh, md, ma, lh, la, rh, ra = item
        match_id = repository.create_match({
            "official_match_id": oid, "league": league, "home_team": home, "away_team": away,
            "kickoff_time": (now + timedelta(hours=3 + index * 2)).isoformat(), "status": "scheduled",
        })
        repository.add_odds(match_id, {"home": sh, "draw": sd, "away": sa}, "demo_official", now.isoformat())
        repository.add_odds(match_id, {"home": mh, "draw": md, "away": ma}, "demo_market", now.isoformat(), external=True)
        repository.add_features(match_id, {"lambda_home": lh, "lambda_away": la, "home_rating": rh,
                                            "away_rating": ra, "source_confidence": 0.95, "backtest_roi": None})
        output.append(workflow.evaluate(match_id))
    return output

