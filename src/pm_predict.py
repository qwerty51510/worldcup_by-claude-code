import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from src.config import FOOTBALL_DATA_BASE, BASE_LAMBDA, RANK_DECAY, FIFA_RANKINGS
from src.player_strength import player_lambdas
import src.pm_portfolio as portfolio

ELO_PATH = Path(__file__).parent.parent / "data" / "elo_ratings_hybrid.json"
_elo_cache: dict = {}


def _load_elo() -> dict:
    global _elo_cache
    if not _elo_cache:
        with open(ELO_PATH) as f:
            _elo_cache = json.load(f)
    return _elo_cache


def _elo_lambdas(home: str, away: str) -> tuple:
    elo = _load_elo()
    elo_h = elo.get(home, 1500.0)
    elo_a = elo.get(away, 1500.0)
    diff = elo_h - elo_a
    rank_h = FIFA_RANKINGS.get(home, 48)
    rank_a = FIFA_RANKINGS.get(away, 48)
    lh = max(0.3, BASE_LAMBDA * math.exp(RANK_DECAY * (rank_a - rank_h)) * (1 + diff / 800))
    la = max(0.3, BASE_LAMBDA * math.exp(RANK_DECAY * (rank_h - rank_a)) * (1 - diff / 800))
    return round(lh, 3), round(la, 3)


def _poisson_match_probs(lh: float, la: float, max_goals: int = 10) -> tuple:
    def pois(lam: float, k: int) -> float:
        return (lam ** k) * math.exp(-lam) / math.factorial(k)

    p_home = p_draw = p_away = 0.0
    for h in range(max_goals):
        for a in range(max_goals):
            p = pois(lh, h) * pois(la, a)
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    return p_home / total, p_draw / total, p_away / total


def match_win_probs(home: str, away: str) -> tuple:
    lh, la = player_lambdas(home, away)
    if lh is None:
        lh, la = _elo_lambdas(home, away)
    return _poisson_match_probs(lh, la)


def _upcoming_fixtures() -> list:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        return []
    import requests
    headers = {"X-Auth-Token": key}
    url = f"{FOOTBALL_DATA_BASE}/competitions/2000/matches"
    try:
        r = requests.get(url, headers=headers,
                         params={"status": "SCHEDULED,TIMED"}, timeout=10)
        r.raise_for_status()
        return r.json().get("matches", [])
    except Exception as e:
        print(f"[pm_predict] fixture fetch failed: {e}")
        return []


def run_once() -> None:
    ts = datetime.now(timezone.utc).isoformat()
    fixtures = _upcoming_fixtures()
    match_probs: dict = {}
    data = portfolio.load()
    cal = data["calibration"]["factor"]
    for m in fixtures[:20]:
        home = m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("name", "")
        mid = str(m.get("id", ""))
        if not home or not away:
            continue
        ph, pd, pa = match_win_probs(home, away)
        ph = min(0.99, ph * cal)
        pa = min(0.99, pa * cal)
        pd = max(0.01, 1.0 - ph - pa)
        match_probs[mid] = {
            "home": home, "away": away,
            "p_home_win": round(ph, 4),
            "p_draw": round(pd, 4),
            "p_away_win": round(pa, 4),
        }
    data["match_probs"] = match_probs
    data["model_probs_updated_at"] = ts
    portfolio.save(data)
    print(f"[{ts}] pm_predict: wrote {len(match_probs)} match probs")


def run_daemon(interval: int = 300) -> None:
    print(f"[pm_predict] daemon started, interval={interval}s")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[pm_predict] error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()
    if args.daemon:
        run_daemon(args.interval)
    else:
        run_once()
