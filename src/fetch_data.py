import json
import os
import time
from pathlib import Path

import requests

from src.config import FOOTBALL_DATA_BASE, ODDS_API_BASE, POLYMARKET_BASE, WORLD_CUP_COMPETITION_ID

DATA_DIR = Path(__file__).parent.parent / "data"


def fetch_matches(date: str) -> list:
    headers = {"X-Auth-Token": os.environ["FOOTBALL_DATA_API_KEY"]}
    url = f"{FOOTBALL_DATA_BASE}/competitions/{WORLD_CUP_COMPETITION_ID}/matches"
    params = {"dateFrom": date, "dateTo": date}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    time.sleep(6)  # respect 10 req/min free tier limit
    return r.json().get("matches", [])


def fetch_odds(match_ids: list) -> dict:
    key = os.environ["ODDS_API_KEY"]
    url = f"{ODDS_API_BASE}/sports/soccer_fifa_world_cup/odds/"
    params = {"apiKey": key, "markets": "asian_handicap,totals", "oddsFormat": "decimal"}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    games = r.json()
    return {g["id"]: g for g in games}


def fetch_polymarket() -> dict:
    url = f"{POLYMARKET_BASE}/markets"
    params = {"tag": "world-cup-2026", "limit": 100}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    markets = r.json().get("markets", [])
    result = {}
    for m in markets:
        q = m.get("question", "")
        prices = m.get("outcomePrices", [])
        if "win" in q.lower() and len(prices) >= 1:
            try:
                result[q] = float(prices[0])
            except (ValueError, TypeError):
                pass
    return result


def save_match_day(date: str, data: dict) -> None:
    out_dir = Path(DATA_DIR) / "matches"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{date}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
