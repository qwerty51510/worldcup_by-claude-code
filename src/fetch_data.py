import json
import os
import time
from pathlib import Path

import requests

from src.config import FOOTBALL_DATA_BASE, ODDS_API_BASE, POLYMARKET_BASE, WORLD_CUP_COMPETITION_ID

DATA_DIR = Path(__file__).parent.parent / "data"


def fetch_matches(date: str) -> list:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        print("[fetch_matches] FOOTBALL_DATA_API_KEY not set, returning empty")
        return []
    headers = {"X-Auth-Token": key}
    url = f"{FOOTBALL_DATA_BASE}/competitions/{WORLD_CUP_COMPETITION_ID}/matches"
    params = {"dateFrom": date, "dateTo": date}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        time.sleep(6)  # respect 10 req/min free tier limit
        return r.json().get("matches", [])
    except Exception as e:
        print(f"[fetch_matches] failed: {e}")
        return []


def fetch_odds(match_ids: list) -> dict:
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        print("[fetch_odds] ODDS_API_KEY not set, skipping")
        return {}
    url = f"{ODDS_API_BASE}/sports/soccer_fifa_world_cup/odds/"
    # try asian_handicap first; free tier may only support h2h+totals
    for markets in ("asian_handicap,totals", "h2h,totals"):
        params = {
            "apiKey": key,
            "markets": markets,
            "oddsFormat": "decimal",
            "regions": "us,uk,eu,au",
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 422:
            print(f"[fetch_odds] 422 with markets={markets}, trying fallback")
            continue
        r.raise_for_status()
        games = r.json()
        print(f"[fetch_odds] Got {len(games)} games with markets={markets}")
        return {g["id"]: g for g in games}
    print("[fetch_odds] All market options failed, returning empty")
    return {}


def fetch_polymarket() -> dict:
    url = f"{POLYMARKET_BASE}/markets"
    params = {"tag": "world-cup-2026", "limit": 100}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        # API returns list directly or dict with "markets" key
        markets = data if isinstance(data, list) else data.get("markets", [])
    except Exception as e:
        print(f"[fetch_polymarket] failed: {e}")
        return {}
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
