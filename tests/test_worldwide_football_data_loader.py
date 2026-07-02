import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from cross_league_rule_search import load_seasons  # noqa: E402
from monthly_shadow_backtest import load_matches  # noqa: E402


def test_load_matches_supports_worldwide_new_format_with_closing_odds(tmp_path):
    csv_path = tmp_path / "FIN.csv"
    csv_path.write_text(
        "Country,League,Season,Date,Home,Away,HG,AG,Res,AvgCH,AvgCD,AvgCA\n"
        "Finland,Veikkausliiga,2025,01/06/2025,HJK,VPS,2,0,H,1.50,4.10,6.20\n",
        encoding="utf-8",
    )

    frame = load_matches(csv_path)

    assert len(frame) == 1
    assert frame.iloc[0]["league"] == "FIN"
    assert frame.iloc[0]["HomeTeam"] == "HJK"
    assert frame.iloc[0]["AwayTeam"] == "VPS"
    assert frame.iloc[0]["odds_home"] == 1.5


def test_load_seasons_accepts_worldwide_code_from_new_directory():
    frame = load_seasons(("FIN",))

    assert not frame.empty
    assert set(frame["league"]) == {"FIN"}
    assert {"HomeTeam", "AwayTeam", "FTHG", "FTAG", "AvgCH", "AvgCD", "AvgCA"}.issubset(frame.columns)
