import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from src.config import FOOTBALL_DATA_BASE
import src.pm_portfolio as portfolio

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
_ESPN_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_live_matches() -> list:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    headers = {"X-Auth-Token": key}
    try:
        r = requests.get(
            f"{FOOTBALL_DATA_BASE}/competitions/2000/matches",
            headers=headers, params={"status": "IN_PLAY"}, timeout=10,
        )
        r.raise_for_status()
        return r.json().get("matches", [])
    except Exception as e:
        print(f"[pm_monitor] football-data live fetch failed: {e}")
        return _fetch_live_espn()


def _fetch_live_espn() -> list:
    try:
        r = requests.get(ESPN_SCOREBOARD, headers=_ESPN_HEADERS, timeout=10)
        r.raise_for_status()
        events = r.json().get("events", [])
        live = []
        for ev in events:
            status = ev.get("status", {}).get("type", {}).get("state", "")
            if status == "in":
                comp = ev["competitions"][0]
                live.append({
                    "id": ev["id"],
                    "homeTeam": {"name": comp["competitors"][0]["team"]["displayName"]},
                    "awayTeam": {"name": comp["competitors"][1]["team"]["displayName"]},
                    "_source": "espn",
                })
        return live
    except Exception as e:
        print(f"[pm_monitor] ESPN fallback failed: {e}")
        return []


def fetch_match_events(fixture_id: int) -> list:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    headers = {"X-Auth-Token": key}
    try:
        r = requests.get(
            f"{FOOTBALL_DATA_BASE}/matches/{fixture_id}",
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("bookings", []) + data.get("goals", [])
    except Exception as e:
        print(f"[pm_monitor] event fetch failed for {fixture_id}: {e}")
        return []


def _classify_event(event: dict) -> str:
    """Return event type string.

    Handles both test-style events ({"type": "YELLOW_RED_CARD", ...}) and
    real football-data.org API events:
      - bookings: {"card": "RED_CARD"|"YELLOW_CARD"|"YELLOW_RED_CARD", ...}
      - goals: {"team": {...}, "minute": ...} (no "card" key)
    """
    if "type" in event:
        return event["type"]
    card = event.get("card")
    if card:
        return card
    return "GOAL"


def detect_exit_triggers(
    events: list,
    our_team: str,
    must_win: bool = False,
    score: tuple = (0, 0),
) -> Optional[str]:
    for ev in events:
        etype = _classify_event(ev)
        team_name = ev.get("team", {}).get("name", "")
        is_ours = team_name == our_team

        if etype in ("YELLOW_RED_CARD", "RED_CARD") and is_ours:
            return "RED_CARD"
        if etype == "GOAL":
            if not is_ours and must_win and score[0] <= score[1]:
                return "GOAL_AGAINST_MUST_WIN"
            if is_ours and score[0] > score[1]:
                return "LOCK_PROFIT"
    return None


def run_once(positions: Optional[list] = None) -> None:
    if positions is None:
        positions = portfolio.load().get("positions", [])
    live = fetch_live_matches()
    if not live:
        return

    live_ids = {str(m.get("id", "")): m for m in live}
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

    for pos in positions:
        fixture_id = pos.get("fixture_id")
        if not fixture_id or str(fixture_id) not in live_ids:
            continue
        events = fetch_match_events(fixture_id)
        our_team = pos.get("team", "")
        trigger = detect_exit_triggers(events, our_team)
        if trigger:
            print(f"[{ts}] pm_monitor: EXIT signal {trigger} for {our_team}")
            portfolio.push_exit_signal(pos["market_id"], trigger)


def run_daemon(interval: int = 60) -> None:
    print(f"[pm_monitor] daemon started, interval={interval}s")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[pm_monitor] error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()
    if args.daemon:
        run_daemon(args.interval)
    else:
        run_once()
