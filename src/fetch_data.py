import json
import os
import time
from pathlib import Path

import requests

from src.config import FOOTBALL_DATA_BASE, ODDS_API_BASE, POLYMARKET_BASE, WORLD_CUP_COMPETITION_ID

DATA_DIR = Path(__file__).parent.parent / "data"


def fetch_matches(date: str) -> list:
    """Fetch WC matches for `date` and the following day (UTC), deduped by id.
    Covers cross-midnight kicks that fall on UTC+next-day but are the same round.
    """
    from datetime import datetime, timedelta
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        print("[fetch_matches] FOOTBALL_DATA_API_KEY not set, returning empty")
        return []
    headers = {"X-Auth-Token": key}
    url = f"{FOOTBALL_DATA_BASE}/competitions/{WORLD_CUP_COMPETITION_ID}/matches"
    next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    params = {"dateFrom": date, "dateTo": next_day}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        time.sleep(6)  # respect 10 req/min free tier limit
        matches = r.json().get("matches", [])
        print(f"[fetch_matches] Got {len(matches)} matches ({date} → {next_day})")
        return matches
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
    """Fetch Polymarket WC 2026 winner market probabilities (team → P(win WC))."""
    url = f"{POLYMARKET_BASE}/markets"
    params = {"q": "win the 2026 FIFA World Cup", "limit": 60}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return {}
    except Exception as e:
        print(f"[fetch_polymarket] failed: {e}")
        return {}

    result = {}
    for m in data:
        if not isinstance(m, dict):
            continue
        q = m.get("question", "")
        if "win the 2026 FIFA World Cup" not in q:
            continue
        outs = m.get("outcomes", [])
        if isinstance(outs, str):
            try:
                outs = json.loads(outs)
            except Exception:
                continue
        if outs != ["Yes", "No"]:
            continue
        prices = m.get("outcomePrices", [])
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                continue
        try:
            yes_p = float(prices[0])
        except (ValueError, TypeError, IndexError):
            continue
        team = (
            q.replace("Will ", "")
            .replace(" win the 2026 FIFA World Cup?", "")
            .replace(" win the 2026 FIFA World Cup", "")
            .strip()
        )
        result[team] = yes_p

    print(f"[fetch_polymarket] Got WC winner probs for {len(result)} teams")
    return result


def save_match_day(date: str, data: dict) -> None:
    out_dir = Path(DATA_DIR) / "matches"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{date}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
