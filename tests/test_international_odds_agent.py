from football_agents.international_odds_agent import InternationalOddsHistoryAgent


def test_football_data_world_cup_workbook_conversion_supports_finals_and_qualifiers():
    import pandas as pd
    from io import BytesIO

    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame([
            {
                "Competition": "World Cup 2022",
                "Home": "Argentina",
                "Away": "France",
                "Date": "2022-12-18",
                "HGFT": 2,
                "AGFT": 2,
                "H-Avg": 2.63,
                "D-Avg": 3.12,
                "A-Avg": 2.84,
                "H-Max": 2.70,
                "D-Max": 3.20,
                "A-Max": 2.90,
            },
            {
                "Competition": "World Cup 2022",
                "Home": "Bad",
                "Away": "Row",
                "Date": "2022-12-18",
                "HGFT": 1,
                "AGFT": 0,
            },
        ]).to_excel(writer, sheet_name="WorldCup2022", index=False)
        pd.DataFrame([
            {
                "Home": "Iraq",
                "Away": "Bolivia",
                "Date": "2026-04-01",
                "HG": 2,
                "AG": 1,
                "H_Avg": 3.08,
                "D_Avg": 2.89,
                "A_Avg": 2.41,
            },
        ]).to_excel(writer, sheet_name="WorldCup2026Qualifiers", index=False)

    csv_text, report = InternationalOddsHistoryAgent.build_football_data_world_cup_csv(workbook.getvalue())

    assert report["matched"] == 2
    assert report["dropped"] == 1
    assert "World,World Cup 2022,2022,18/12/2022,Argentina,France,2,2,D,2.63,3.12,2.84,2.7,3.2,2.9" in csv_text
    assert "World,World Cup Qualifiers,2026,01/04/2026,Iraq,Bolivia,2,1,H,3.08,2.89,2.41" in csv_text


def test_world_cup_odds_conversion_outputs_football_data_style_csv():
    results = [
        {
            "id": "99723",
            "matchDate": "14-06-18 17:00",
            "Country": "World",
            "League": "World Cup - Final phase",
            "Season": "2018",
            "homeTeam": "Russia",
            "awayTeam": "Saudi Arabia",
            "FTHG": "5",
            "FTAG": "0",
            "FTR": "H",
        }
    ]
    odds = [
        {
            "id": "99723",
            "matchDate": "14-06-18 17:00",
            "Country": "World",
            "League": "World Cup - Final phase",
            "Season": "2018",
            "homeTeam": "Russia",
            "awayTeam": "Saudi Arabia",
            "H": "1.48",
            "D": "4.44",
            "A": "8.90",
        }
    ]

    csv_text, report = InternationalOddsHistoryAgent.build_world_cup_csv(results, odds)

    assert report["matched"] == 1
    assert report["dropped"] == 0
    assert "Country,League,Season,Date,Home,Away,HG,AG,Res,AvgCH,AvgCD,AvgCA" in csv_text
    assert "World,World Cup,2018,14/06/2018,Russia,Saudi Arabia,5,0,H,1.48,4.44,8.9" in csv_text


def test_world_cup_odds_conversion_drops_unmatched_or_invalid_rows():
    results = [
        {
            "id": "1",
            "matchDate": "01-01-22 12:00",
            "homeTeam": "A",
            "awayTeam": "B",
            "Season": "2022",
            "FTHG": "1",
            "FTAG": "0",
            "FTR": "H",
        }
    ]
    odds = [
        {"id": "1", "H": "0", "D": "3.0", "A": "4.0"},
        {"id": "2", "H": "2.0", "D": "3.0", "A": "4.0"},
    ]

    csv_text, report = InternationalOddsHistoryAgent.build_world_cup_csv(results, odds)

    assert report["matched"] == 0
    assert report["dropped"] == 2
    assert csv_text.count("\n") == 1


def test_odds_api_conversion_joins_settled_results_and_averages_bookmakers():
    snapshots = [
        {
            "sport_key": "soccer_uefa_nations_league",
            "data": [
                {
                    "id": "evt-1",
                    "commence_time": "2024-09-06T18:45:00Z",
                    "home_team": "France",
                    "away_team": "Italy",
                    "bookmakers": [
                        {
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "France", "price": 1.80},
                                        {"name": "Draw", "price": 3.40},
                                        {"name": "Italy", "price": 4.60},
                                    ],
                                }
                            ]
                        },
                        {
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "France", "price": 1.90},
                                        {"name": "Draw", "price": 3.20},
                                        {"name": "Italy", "price": 4.40},
                                    ],
                                }
                            ]
                        },
                    ],
                }
            ],
        }
    ]
    results = [
        {
            "league": "UEFA Nations League",
            "home_team": "France",
            "away_team": "Italy",
            "home_goals": 1,
            "away_goals": 3,
            "played_at": "2024-09-06",
            "match_type": "CUP",
        }
    ]

    csv_text, report = InternationalOddsHistoryAgent.build_odds_api_csv(
        snapshots,
        results,
        {"soccer_uefa_nations_league": "UEFA Nations League"},
    )

    assert report["matched"] == 1
    assert report["scanned_events"] == 1
    assert "World,UEFA Nations League,2024,06/09/2024,France,Italy,1,3,A,1.971749,3.516421,4.797174" in csv_text


def test_odds_api_conversion_rejects_snapshot_at_or_after_kickoff():
    snapshots = [{
        "sport_key": "soccer_uefa_nations_league",
        "timestamp": "2024-09-06T20:00:00Z",
        "data": [{
            "id": "evt-after-kickoff",
            "commence_time": "2024-09-06T19:00:00Z",
            "home_team": "France",
            "away_team": "Italy",
            "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [
                {"name": "France", "price": 1.8}, {"name": "Draw", "price": 3.4}, {"name": "Italy", "price": 4.6},
            ]}]}],
        }],
    }]
    results = [{"league": "UEFA Nations League", "home_team": "France", "away_team": "Italy", "home_goals": 1,
                "away_goals": 3, "played_at": "2024-09-06", "match_type": "CUP"}]

    _csv_text, report = InternationalOddsHistoryAgent.build_odds_api_csv(snapshots, results)

    assert report["matched"] == 0
    assert report["dropped"]["snapshot_not_pre_match"] == 1


def test_odds_api_conversion_drops_unmatched_results():
    snapshots = [
        {
            "sport_key": "soccer_fifa_world_cup",
            "data": [
                {
                    "id": "evt-2",
                    "commence_time": "2026-06-11T19:00:00Z",
                    "home_team": "Mexico",
                    "away_team": "Canada",
                    "bookmakers": [
                        {
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Mexico", "price": 2.10},
                                        {"name": "Draw", "price": 3.10},
                                        {"name": "Canada", "price": 3.80},
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ],
        }
    ]

    csv_text, report = InternationalOddsHistoryAgent.build_odds_api_csv(snapshots, [])

    assert report["matched"] == 0
    assert report["dropped"]["unmatched_result"] == 1
    assert csv_text.count("\n") == 1
