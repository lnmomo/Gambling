from football_agents.international_odds_agent import InternationalOddsHistoryAgent


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
