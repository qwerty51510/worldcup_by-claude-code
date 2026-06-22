import json
import os
import responses as resp_mock
from unittest.mock import patch
from src.fetch_data import fetch_matches, fetch_odds, fetch_polymarket, save_match_day
from src.config import FOOTBALL_DATA_BASE, ODDS_API_BASE, POLYMARKET_BASE


@resp_mock.activate
def test_fetch_matches_returns_list():
    resp_mock.add(
        resp_mock.GET,
        f"{FOOTBALL_DATA_BASE}/competitions/2000/matches",
        json={"matches": [{"id": 1, "homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Morocco"},
                           "score": {"fullTime": {"home": 1, "away": 1}},
                           "utcDate": "2026-06-13T15:00:00Z", "status": "FINISHED"}]},
        status=200,
    )
    with patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test_key"}):
        result = fetch_matches("2026-06-13")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["homeTeam"]["name"] == "Brazil"


@resp_mock.activate
def test_fetch_odds_returns_dict():
    resp_mock.add(
        resp_mock.GET,
        f"{ODDS_API_BASE}/sports/soccer_fifa_world_cup/odds/",
        json=[{"id": "abc123", "home_team": "Brazil", "away_team": "Morocco",
               "bookmakers": [{"markets": [{"key": "asian_handicap",
                                            "outcomes": [{"name": "Brazil", "price": 1.85, "point": -0.5},
                                                         {"name": "Morocco", "price": 2.05, "point": 0.5}]}]}]}],
        status=200,
    )
    with patch.dict(os.environ, {"ODDS_API_KEY": "test_key"}):
        result = fetch_odds(["abc123"])
    assert isinstance(result, dict)


@resp_mock.activate
def test_fetch_polymarket_returns_dict():
    resp_mock.add(
        resp_mock.GET,
        f"{POLYMARKET_BASE}/markets",
        json={"markets": [{"question": "Will Brazil win the 2026 World Cup?",
                           "outcomePrices": ["0.18", "0.82"]}]},
        status=200,
    )
    result = fetch_polymarket()
    assert isinstance(result, dict)


def test_save_match_day_writes_json(tmp_path, monkeypatch):
    monkeypatch.setattr("src.fetch_data.DATA_DIR", tmp_path)
    save_match_day("2026-06-13", {"matches": [], "odds": {}})
    out = tmp_path / "matches" / "2026-06-13.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert "matches" in data
