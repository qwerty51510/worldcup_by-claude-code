import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from src.config import FOOTBALL_DATA_BASE, ODDS_API_BASE, POLYMARKET_BASE, WORLD_CUP_COMPETITION_ID

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
_ESPN_HEADERS = {"User-Agent": "Mozilla/5.0"}

DATA_DIR = Path(__file__).parent.parent / "data"

# Authoritative canonical names for all 48 WC 2026 teams
_WC2026_CANONICAL_TEAMS: frozenset = frozenset({
    "Algeria", "Argentina", "Australia", "Austria", "Belgium",
    "Bosnia and Herzegovina", "Brazil", "Cabo Verde", "Canada", "Colombia",
    "Croatia", "Curaçao", "Czechia", "DR Congo", "Ecuador", "Egypt",
    "England", "France", "Germany", "Ghana", "Haiti", "Iran", "Iraq",
    "Ivory Coast", "Japan", "Jordan", "Mexico", "Morocco", "Netherlands",
    "New Zealand", "Norway", "Panama", "Paraguay", "Portugal", "Qatar",
    "Saudi Arabia", "Scotland", "Senegal", "South Africa", "South Korea",
    "Spain", "Sweden", "Switzerland", "Tunisia", "Turkey", "United States",
    "Uruguay", "Uzbekistan",
})


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


def fetch_espn_odds(local_date: str) -> dict:
    """
    Fetch DraftKings lines (AH, OU, 1X2) from ESPN API.
    Queries both local_date and local_date-1 (ESPN uses US date; early-morning
    local matches map to the previous US date). Returns merged dict keyed by
    (canonical_home, canonical_away).
    """
    base_dt = datetime.strptime(local_date, "%Y-%m-%d")
    # Query yesterday, today, tomorrow — matches fetch_matches() 2-day window
    # so late-UTC matches (e.g. 21:00 UTC = next ESPN date) are never missed
    dates_to_try = [base_dt - timedelta(days=1), base_dt, base_dt + timedelta(days=1)]
    result: dict = {}

    for dt in dates_to_try:
        espn_date = dt.strftime("%Y%m%d")
        try:
            r = requests.get(ESPN_SCOREBOARD, headers=_ESPN_HEADERS,
                             params={"dates": espn_date}, timeout=10)
            r.raise_for_status()
            events = r.json().get("events", [])
        except Exception as e:
            print(f"[fetch_espn_odds] {espn_date} failed: {e}")
            continue

        for event in events:
            comp = event["competitions"][0]
            competitors = comp.get("competitors", [])
            home_c = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away_c = next((c for c in competitors if c.get("homeAway") == "away"), {})
            ht = _normalize_team(home_c.get("team", {}).get("displayName", ""))
            at = _normalize_team(away_c.get("team", {}).get("displayName", ""))
            if not ht or not at:
                continue

            odds_list = comp.get("odds", [])
            if not odds_list:
                continue
            o = odds_list[0]
            if not o:
                continue

            record: dict = {}
            ml = o.get("moneyline", {}) or {}
            ps = o.get("pointSpread", {}) or {}
            tot = o.get("total", {}) or {}

            h_ml = (ml.get("home") or {}).get("close", {}).get("odds")
            d_ml = (ml.get("draw") or {}).get("close", {}).get("odds")
            a_ml = (ml.get("away") or {}).get("close", {}).get("odds")
            if h_ml and d_ml and a_ml:
                record["ml_home"] = h_ml
                record["ml_draw"] = d_ml
                record["ml_away"] = a_ml

            ah_line = (ps.get("home") or {}).get("close", {}).get("line")
            ah_odds = (ps.get("home") or {}).get("close", {}).get("odds")
            if ah_line is not None:
                record["ah_line"] = float(ah_line)
                record["ah_odds"] = ah_odds

            ou_line = o.get("overUnder")
            over_odds = (tot.get("over") or {}).get("close", {}).get("odds")
            under_odds = (tot.get("under") or {}).get("close", {}).get("odds")
            if ou_line is not None:
                record["ou_line"] = float(ou_line)
                record["over_odds"] = over_odds
                record["under_odds"] = under_odds

            if record:
                result[(ht, at)] = record

    print(f"[fetch_espn_odds] Got DK lines for {len(result)} matches")
    return result


def fetch_pm_match_odds(home: str, away: str) -> dict:
    """
    Fetch Polymarket match-specific win probabilities for one match.
    Returns {"home_win": float, "draw": float, "away_win": float} or {}.
    """
    query = f"{home} vs {away} 2026"
    try:
        r = requests.get(f"{POLYMARKET_BASE}/markets",
                         params={"q": query, "limit": 20}, timeout=10)
        r.raise_for_status()
        markets = r.json() if isinstance(r.json(), list) else []
    except Exception:
        return {}

    result: dict = {}
    for m in markets:
        q = (m.get("question") or "").lower()
        # Look for binary home/draw/away markets
        outs = m.get("outcomes", [])
        if isinstance(outs, str):
            try: outs = json.loads(outs)
            except Exception: continue
        prices = m.get("outcomePrices", [])
        if isinstance(prices, str):
            try: prices = json.loads(prices)
            except Exception: continue
        if outs != ["Yes", "No"] or not prices:
            continue
        try:
            yes_p = float(prices[0])
        except Exception:
            continue

        h_lower = home.lower(); a_lower = away.lower()
        if h_lower in q and ("win" in q or "beat" in q):
            result["home_win"] = yes_p
        elif a_lower in q and ("win" in q or "beat" in q):
            result["away_win"] = yes_p
        elif "draw" in q or "tie" in q:
            result["draw"] = yes_p

    return result


def _fetch_espn_summary(event_id: str) -> dict:
    """Fetch ESPN summary for a single event (lineup, formation, subs, stats)."""
    import urllib.request
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={event_id}"
    try:
        req = urllib.request.Request(url, headers=_ESPN_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _parse_summary(summary: dict, home_short: str, away_short: str) -> dict:
    """Extract formation, lineup, subs, stats, and key events from ESPN summary."""
    result: dict = {"formations": {}, "lineups": {}, "substitutions": [], "stats": {}}

    # Rosters: formation + starters + subs used
    for roster in summary.get("rosters", []):
        side = "home" if roster.get("homeAway") == "home" else "away"
        team_name = home_short if side == "home" else away_short
        formation = roster.get("formation", "")
        athletes = roster.get("roster", [])
        starters = [a["athlete"]["shortName"] for a in athletes if a.get("starter")]
        subs_used = [a["athlete"]["shortName"] for a in athletes
                     if not a.get("starter") and a.get("subbedIn")]
        result["formations"][side] = formation
        result["lineups"][side] = {"starters": starters, "subs_used": subs_used}

    # Key events: goals, substitutions, cards
    _SUB_TYPES = {"Substitution"}
    _GOAL_TYPES = {t for t in ["Goal", "Goal - Header", "Goal - Left Foot",
                               "Goal - Right Foot", "Penalty"]}
    for ke in summary.get("keyEvents", []):
        etype = ke.get("type", {}).get("text", "")
        clock = ke.get("clock", {}).get("displayValue", "?")
        team_name = ke.get("team", {}).get("shortDisplayName", "")
        text = ke.get("text", "")
        if etype in _SUB_TYPES:
            result["substitutions"].append({
                "minute": clock, "team": team_name, "text": text,
            })

    # Boxscore stats
    for team_data in summary.get("boxscore", {}).get("teams", []):
        tname = team_data.get("team", {}).get("shortDisplayName", "")
        side = "home" if home_short.lower() in tname.lower() or tname.lower() in home_short.lower() else "away"
        stats = {s["label"]: s.get("displayValue", "") for s in team_data.get("statistics", [])}
        result["stats"][side] = stats

    # Linescores: [H1, H2, ET1, ET2, Pens] from header competitors
    header_comps = summary.get("header", {}).get("competitions", [{}])
    if header_comps:
        for c in header_comps[0].get("competitors", []):
            tname = c.get("team", {}).get("shortDisplayName", "")
            side = "home" if home_short.lower() in tname.lower() or tname.lower() in home_short.lower() else "away"
            ls = [int(x.get("displayValue", 0) or 0) for x in c.get("linescores", [])]
            result.setdefault("linescores", {})[side] = ls

    # Penalty shootout: {home: [{player, scored}, ...], away: [...]}
    shootout_raw = summary.get("shootout", [])
    if shootout_raw and isinstance(shootout_raw, list) and isinstance(shootout_raw[0], dict):
        pens: dict = {}
        for team_entry in shootout_raw:
            tname = team_entry.get("team", "")
            side = "home" if home_short.lower() in tname.lower() or tname.lower() in home_short.lower() else "away"
            shots = [{"player": s.get("player",""), "scored": s.get("didScore", False)}
                     for s in team_entry.get("shots", [])]
            pens[side] = shots
        result["penalties"] = pens

    # Determine match termination stage
    ls_home = result.get("linescores", {}).get("home", [])
    if len(ls_home) >= 5 and ls_home[4] > 0:
        result["decided"] = "penalties"
    elif len(ls_home) >= 4 and (ls_home[2] + ls_home[3]) > 0:
        result["decided"] = "extra_time"
    elif ls_home:
        result["decided"] = "90min"

    return result


def fetch_goal_events(date: str) -> dict:
    """Fetch goal times, lineups, formations, subs, and stats for all matches on a given date.

    Returns dict keyed by "HomeTeam|AwayTeam" → {events, formations, lineups, substitutions, stats}
    """
    import urllib.request
    result: dict = {}
    prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y%m%d")
    for date_str in [prev_date, date.replace("-", "")]:
        url = f"{ESPN_SCOREBOARD}?dates={date_str}"
        try:
            req = urllib.request.Request(url, headers=_ESPN_HEADERS)
            with urllib.request.urlopen(req, timeout=8) as r:
                sched = json.loads(r.read())
        except Exception:
            continue
        for ev in sched.get("events", []):
            comp = ev.get("competitions", [{}])[0]
            state = comp.get("status", {}).get("type", {}).get("state", "")
            if state not in ("in", "post"):
                continue
            competitors = comp.get("competitors", [])
            team_map = {c["team"]["id"]: c["team"].get("shortDisplayName", c["team"].get("displayName", "?"))
                        for c in competitors}
            home_short = competitors[0]["team"].get("shortDisplayName", "?") if competitors else "?"
            away_short = competitors[1]["team"].get("shortDisplayName", "?") if len(competitors) > 1 else "?"
            key = f"{home_short}|{away_short}"
            if key in result:
                continue

            # Goal / card events from scoreboard details
            events = []
            for d in comp.get("details", []):
                if not d.get("scoringPlay") and not d.get("yellowCard") and not d.get("redCard"):
                    continue
                minute = d.get("clock", {}).get("displayValue", "?")
                team_id = d.get("team", {}).get("id", "")
                team_name = team_map.get(team_id, "?")
                athletes = d.get("athletesInvolved", [])
                player = athletes[0].get("shortName", "") if athletes else ""
                etype = d.get("type", {}).get("text", "")
                events.append({
                    "minute": minute, "team": team_name, "player": player, "type": etype,
                    "is_goal": d.get("scoringPlay", False),
                    "is_own_goal": d.get("ownGoal", False),
                    "is_penalty": d.get("penaltyKick", False),
                    "is_shootout": d.get("shootout", False),
                    "yellow_card": d.get("yellowCard", False),
                    "red_card": d.get("redCard", False),
                })

            # Detailed summary: lineup, formation, subs, stats
            event_id = ev.get("id", "")
            summary_data = _fetch_espn_summary(event_id) if event_id else {}
            parsed = _parse_summary(summary_data, home_short, away_short)

            result[key] = {
                "events": events,
                "formations": parsed["formations"],
                "lineups": parsed["lineups"],
                "substitutions": parsed["substitutions"],
                "stats": parsed["stats"],
                "linescores": parsed.get("linescores", {}),
                "penalties": parsed.get("penalties", {}),
                "decided": parsed.get("decided", "90min"),
            }
    return result


def save_match_day(date: str, data: dict) -> None:
    out_dir = Path(DATA_DIR) / "matches"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{date}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


# Comprehensive variant → canonical name mapping (football-data.org + other sources)
_TEAM_NAME_MAP: dict = {
    # Korea
    "Korea Republic": "South Korea",
    "Republic of Korea": "South Korea",
    # Ivory Coast
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Cote dIvoire": "Ivory Coast",
    # Iran
    "IR Iran": "Iran",
    "Islamic Republic of Iran": "Iran",
    # Bosnia
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Bosnia-Herzegowina": "Bosnia and Herzegovina",
    # USA
    "USA": "United States",
    "US": "United States",
    # Cape Verde
    "Cape Verde Islands": "Cabo Verde",
    "Cape Verde": "Cabo Verde",
    # Turkey
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    # DR Congo
    "Congo DR": "DR Congo",
    "Democratic Republic of Congo": "DR Congo",
    "DR Congo": "DR Congo",
    # Czech Republic
    "Czech Republic": "Czechia",
    # Scotland, Norway (usually consistent but just in case)
    # Australia
    "Socceroos": "Australia",
    # Ecuador
    "Ecuador": "Ecuador",
    # Curacao
    "Curacao": "Curaçao",
    "Curaçao": "Curaçao",
    # New Zealand
    "New Zealand": "New Zealand",
}


def _normalize_team(name: str) -> str:
    return _TEAM_NAME_MAP.get(name, name)


def fetch_completed_results() -> list:
    """Fetch all FINISHED WC 2026 matches from football-data.org."""
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        print("[fetch_completed_results] FOOTBALL_DATA_API_KEY not set, skipping")
        return []
    headers = {"X-Auth-Token": key}
    url = f"{FOOTBALL_DATA_BASE}/competitions/{WORLD_CUP_COMPETITION_ID}/matches"
    try:
        r = requests.get(url, headers=headers, params={"status": "FINISHED"}, timeout=15)
        r.raise_for_status()
        time.sleep(6)
        matches = r.json().get("matches", [])
        print(f"[fetch_completed_results] Got {len(matches)} finished matches")
        return matches
    except Exception as e:
        print(f"[fetch_completed_results] failed: {e}")
        return []


def update_wc_results() -> int:
    """
    Pull all finished WC 2026 matches, merge into wc2026_results.json.
    Deduplication uses (sorted_pair, matchday) to catch home/away swaps and
    date mismatches. After merge, validates that unique team count ≤ 48.
    Returns number of new matches added.
    """
    raw = fetch_completed_results()
    if not raw:
        return 0

    results_path = DATA_DIR / "wc2026_results.json"
    existing = json.loads(results_path.read_text()) if results_path.exists() else []

    # Pair-based key: use sorted team pair + date (avoids matchday/round mismatch)
    def _r_pair(r):
        h = r.get("home") or r.get("home_team", "")
        a = r.get("away") or r.get("away_team", "")
        return (tuple(sorted([h, a])), (r.get("date", "") or "")[:10])

    existing_keys = {_r_pair(r) for r in existing}

    new_records = []
    for m in raw:
        home = _normalize_team(m.get("homeTeam", {}).get("name", ""))
        away = _normalize_team(m.get("awayTeam", {}).get("name", ""))
        date_str = (m.get("utcDate", "") or "")[:10]
        score_obj = m.get("score", {})
        duration = score_obj.get("duration", "REGULAR")
        ft = score_obj.get("fullTime", {})
        et = score_obj.get("extraTime", {}) or {}
        pens = score_obj.get("penalties", {}) or {}
        home_goals = ft.get("home")
        away_goals = ft.get("away")
        group_raw = m.get("group", "") or ""
        group = group_raw.replace("GROUP_", "") if group_raw.startswith("GROUP_") else ""
        matchday = m.get("matchday") or 0

        if not home or not away or home_goals is None or away_goals is None:
            continue

        # Derive 90-minute score: fullTime includes ET and penalty goals
        et_h = et.get("home") or 0
        et_a = et.get("away") or 0
        pen_h = pens.get("home") or 0
        pen_a = pens.get("away") or 0
        home_goals_90 = int(home_goals) - et_h - pen_h
        away_goals_90 = int(away_goals) - et_a - pen_a

        pair_key = (tuple(sorted([home, away])), date_str)
        if pair_key in existing_keys:
            continue

        # Warn about unrecognised team names
        for team in (home, away):
            if team not in _WC2026_CANONICAL_TEAMS:
                print(f"[update_wc_results] WARNING: unknown team '{team}' — check _TEAM_NAME_MAP")

        new_records.append({
            "date": date_str,
            "group": group,
            "home": home,
            "away": away,
            "home_goals": home_goals_90,
            "away_goals": away_goals_90,
            "home_goals_final": int(home_goals),
            "away_goals_final": int(away_goals),
            "duration": duration,
            "round": int(matchday),
        })
        existing_keys.add(pair_key)

    if new_records:
        merged = sorted(existing + new_records, key=lambda r: r["date"])

        # Validate team count integrity (support both home/away and home_team/away_team schemas)
        def _get_pair(r):
            return (r.get("home") or r.get("home_team", ""), r.get("away") or r.get("away_team", ""))
        all_teams = {t for r in merged for t in _get_pair(r)}
        unknown = all_teams - _WC2026_CANONICAL_TEAMS
        if unknown:
            print(f"[update_wc_results] WARNING: unrecognised teams in merged data: {unknown}")
        if len(all_teams) > 48:
            print(
                f"[update_wc_results] ERROR: {len(all_teams)} unique teams > 48 — "
                "possible duplicate match entries!"
            )

        results_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
        print(f"[update_wc_results] Added {len(new_records)} new result(s), {len(all_teams)} teams total")
    else:
        print("[update_wc_results] No new results")

    return len(new_records)


def update_pm_actuals() -> int:
    """
    Backfill actual match results into data/backtest/pm_dk_discrepancies.json.
    After each match finishes, adds: actual_result, actual_score, ah_actual, ou_actual.
    Returns number of records updated.
    """
    tracker_path = DATA_DIR / "backtest" / "pm_dk_discrepancies.json"
    if not tracker_path.exists():
        return 0

    results_path = DATA_DIR / "wc2026_results.json"
    if not results_path.exists():
        return 0

    results = json.loads(results_path.read_text())
    result_lookup = {(r["home"], r["away"]): r for r in results}
    # Also index by reverse order
    result_lookup.update({(r["away"], r["home"]): {**r, "home": r["away"], "away": r["home"],
                           "home_goals": r["away_goals"], "away_goals": r["home_goals"]} for r in results})

    tracker = json.loads(tracker_path.read_text())
    updated = 0
    for rec in tracker:
        if rec.get("actual_result"):
            continue
        result = result_lookup.get((rec["home"], rec["away"]))
        if not result:
            continue
        hg = result["home_goals"]
        ag = result["away_goals"]
        actual = "home" if hg > ag else ("away" if ag > hg else "draw")
        rec["actual_score"] = f"{hg}-{ag}"
        rec["actual_result"] = actual

        # AH actual
        ah_line = rec.get("ah_edge") and rec.get("ah_edge", 0)
        # Find the DK AH line from predictions file
        pred_path = DATA_DIR / "predictions" / f"{rec['date']}.json"
        if pred_path.exists():
            preds = json.loads(pred_path.read_text())
            for pr in preds:
                if pr.get("home_team") == rec["home"] and pr.get("away_team") == rec["away"]:
                    dk_ah = pr.get("dk_ah_line")
                    dk_ou = pr.get("dk_ou_line")
                    if dk_ah is not None:
                        diff = hg - ag
                        cover = diff + dk_ah
                        rec["dk_ah_line"] = dk_ah
                        rec["ah_actual"] = "cover" if cover > 0 else ("push" if cover == 0 else "loss")
                    if dk_ou is not None:
                        total = hg + ag
                        rec["dk_ou_line"] = dk_ou
                        rec["ou_actual"] = "over" if total > dk_ou else ("push" if total == dk_ou else "under")
                    break

        # Was PM correct? (compare PM implied winner vs actual)
        pm_h = rec.get("pm_home"); pm_a = rec.get("pm_away"); pm_d = rec.get("pm_draw")
        if pm_h and pm_a and pm_d:
            pm_pick = "home" if pm_h == max(pm_h, pm_d, pm_a) else ("away" if pm_a == max(pm_h, pm_d, pm_a) else "draw")
            model_pick = "home" if rec["model_home"] == max(rec["model_home"], rec["model_draw"], rec["model_away"]) else \
                         ("away" if rec["model_away"] == max(rec["model_home"], rec["model_draw"], rec["model_away"]) else "draw")
            rec["pm_pick"] = pm_pick
            rec["pm_correct"] = pm_pick == actual
            rec["model_pick"] = model_pick
            rec["model_correct"] = model_pick == actual

        updated += 1

    if updated:
        tracker_path.write_text(json.dumps(tracker, ensure_ascii=False, indent=2))
        print(f"[update_pm_actuals] Backfilled {updated} record(s)")
    return updated


def _fetch_wc_team_ids() -> dict:
    """Return {canonical_team_name: football_data_id} for all WC 2026 teams."""
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        return {}
    headers = {"X-Auth-Token": key}
    url = f"{FOOTBALL_DATA_BASE}/competitions/{WORLD_CUP_COMPETITION_ID}/teams"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        time.sleep(6)
        return {
            _normalize_team(t["name"]): t["id"]
            for t in r.json().get("teams", [])
        }
    except Exception as e:
        print(f"[_fetch_wc_team_ids] failed: {e}")
        return {}


def fetch_team_history() -> dict:
    """
    Fetch pre-tournament international match stats for all WC 2026 teams.
    Covers 2025-01-01 → 2026-06-10 (before tournament start).
    Returns {team_name: {scored, conceded, played}}.
    Requires ~5 minutes due to API rate limiting (10 req/min free tier).
    """
    team_ids = _fetch_wc_team_ids()
    if not team_ids:
        print("[fetch_team_history] No team IDs available, skipping")
        return {}

    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        return {}

    headers = {"X-Auth-Token": key}
    history: dict = {}
    total = len(team_ids)

    for i, (team_name, team_id) in enumerate(team_ids.items()):
        url = f"{FOOTBALL_DATA_BASE}/teams/{team_id}/matches"
        params = {"dateFrom": "2025-01-01", "dateTo": "2026-06-10", "status": "FINISHED"}
        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
            r.raise_for_status()
            time.sleep(6)
            scored = conceded = played = 0
            for m in r.json().get("matches", []):
                home_n = _normalize_team(m.get("homeTeam", {}).get("name", ""))
                away_n = _normalize_team(m.get("awayTeam", {}).get("name", ""))
                sc = m.get("score", {}).get("fullTime", {})
                hg, ag = sc.get("home"), sc.get("away")
                if hg is None or ag is None:
                    continue
                if home_n == team_name:
                    scored += int(hg); conceded += int(ag)
                elif away_n == team_name:
                    scored += int(ag); conceded += int(hg)
                else:
                    continue
                played += 1
            history[team_name] = {"scored": scored, "conceded": conceded, "played": played}
            print(f"[fetch_team_history] {i+1}/{total} {team_name}: {played}場 {scored}進/{conceded}失")
        except Exception as e:
            print(f"[fetch_team_history] {team_name} ({team_id}): {e}")

    return history


def _espn_event_id_map(date_str: str) -> dict:
    """Query ESPN scoreboard for date_str (YYYY-MM-DD) and return
    {(canonical_home, canonical_away): espn_event_id} mapping."""
    import urllib.request
    result: dict = {}
    for ds in [date_str, (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")]:
        espn_date = ds.replace("-", "")
        try:
            req = urllib.request.Request(
                f"{ESPN_SCOREBOARD}?dates={espn_date}", headers=_ESPN_HEADERS)
            with urllib.request.urlopen(req, timeout=8) as r:
                sched = json.loads(r.read())
        except Exception:
            continue
        for ev in sched.get("events", []):
            espn_id = ev.get("id", "")
            if not espn_id:
                continue
            comp = ev.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home_c = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away_c = next((c for c in competitors if c.get("homeAway") == "away"), {})
            ht = _normalize_team(home_c.get("team", {}).get("displayName", ""))
            at = _normalize_team(away_c.get("team", {}).get("displayName", ""))
            if ht and at:
                result[(ht, at)] = espn_id
    return result


def fetch_pre_kickoff_lineups(matches: list) -> dict:
    """
    For matches kicking off within the next 90 minutes, fetch confirmed
    ESPN lineups/rosters. Returns {match_id: {"home": [...], "away": [...]}}
    where each list is confirmed starters by shortName.

    Uses ESPN's own event IDs (looked up by date) rather than football-data.org IDs.
    """
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)

    # Build ESPN event ID map for each relevant date
    date_maps: dict = {}

    result = {}
    for m in matches:
        kickoff_str = m.get("utcDate", "")
        if not kickoff_str:
            continue
        try:
            kickoff = datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        mins = (kickoff - now_utc).total_seconds() / 60
        if not (-30 <= mins <= 120):  # up to 2 hours before / 30 min after kickoff
            continue

        date_str = kickoff.strftime("%Y-%m-%d")
        if date_str not in date_maps:
            date_maps[date_str] = _espn_event_id_map(date_str)
        id_map = date_maps[date_str]

        # Look up ESPN event ID by canonical team names
        home_name = _normalize_team(m.get("homeTeam", {}).get("name", ""))
        away_name = _normalize_team(m.get("awayTeam", {}).get("name", ""))
        espn_id = id_map.get((home_name, away_name)) or id_map.get((away_name, home_name))
        if not espn_id:
            # Fallback: try football-data.org id directly
            espn_id = str(m.get("id", ""))
        if not espn_id:
            continue

        summary = _fetch_espn_summary(espn_id)
        rosters = summary.get("rosters", [])
        if not rosters:
            continue
        lineups: dict = {}
        for roster in rosters:
            side = "home" if roster.get("homeAway") == "home" else "away"
            athletes = roster.get("roster", [])
            starters = [a["athlete"].get("shortName", a["athlete"].get("displayName", ""))
                        for a in athletes if a.get("starter")]
            if starters:
                lineups[side] = starters
        if lineups:
            fd_id = str(m.get("id", ""))
            result[fd_id] = lineups
            print(f"[pre_kickoff] Got lineup for {home_name} vs {away_name} (espn={espn_id}): "
                  f"home={len(lineups.get('home',[]))} away={len(lineups.get('away',[]))} starters")
    return result


def detect_and_notify_lineup_changes(matches: list, lineups: dict) -> list:
    """
    From confirmed ESPN rosters, detect:
      1. Players flagged with injury status in the roster
      2. Notable players (from injuries.json watch list) absent from starters

    Updates injuries.json notes and sends Telegram alert.
    Returns list of change dicts.
    """
    from src.notify import alert_injury_update, send_telegram

    inj_path = DATA_DIR / "injuries.json"
    try:
        injuries = json.loads(inj_path.read_text()) if inj_path.exists() else {}
    except Exception:
        injuries = {}

    event_to_match = {str(m.get("id", "")): m for m in matches}
    all_changes = []

    for event_id, sides in lineups.items():
        m = event_to_match.get(event_id, {})
        home_name = m.get("homeTeam", {}).get("name", "")
        away_name = m.get("awayTeam", {}).get("name", "")
        match_label = f"{home_name} vs {away_name}"

        changes_this_match = []

        # Re-fetch full summary to get injury status per player
        summary = _fetch_espn_summary(event_id)
        for roster in summary.get("rosters", []):
            side = "home" if roster.get("homeAway") == "home" else "away"
            team_name = home_name if side == "home" else away_name
            for athlete_entry in roster.get("roster", []):
                athlete = athlete_entry.get("athlete", {})
                inj_status = athlete.get("injuryStatus", "")  # e.g. "Questionable", "Out"
                display_name = athlete.get("displayName", "")
                is_starter = athlete_entry.get("starter", False)
                is_active = athlete_entry.get("active", True)

                # Flag players with injury status or marked inactive
                if inj_status and inj_status.lower() not in ("active", "healthy", ""):
                    severity = "確定缺陣" if inj_status.lower() in ("out", "injured") else f"疑問（{inj_status}）"
                    changes_this_match.append({
                        "team": team_name,
                        "player": display_name,
                        "status": severity,
                        "impact": "ESPN 陣容標記",
                    })
                elif not is_active and not is_starter:
                    # Check if this player was in our injuries watch list
                    team_inj = injuries.get(team_name, {})
                    watch = [inj["player"] for inj in team_inj.get("injuries", [])
                             if display_name.split()[-1].lower() in inj["player"].lower()]
                    if watch:
                        changes_this_match.append({
                            "team": team_name,
                            "player": display_name,
                            "status": "未入選首發（傷兵關注名單）",
                            "impact": "請確認是否缺陣",
                        })

        # Send lineup confirmation + changes to Telegram
        home_starters = sides.get("home", [])
        away_starters = sides.get("away", [])
        lineup_msg = (
            f"📋 <b>首發確認</b> [{match_label}]\n\n"
            f"<b>{home_name}</b>: {', '.join(home_starters[:5])}...\n"
            f"<b>{away_name}</b>: {', '.join(away_starters[:5])}..."
        )
        send_telegram(lineup_msg)

        if changes_this_match:
            all_changes.extend(changes_this_match)
            # Append new notes to injuries.json
            for c in changes_this_match:
                team = c["team"]
                if team not in injuries:
                    injuries[team] = {"injuries": []}
                existing = injuries[team].get("injuries", [])
                already = any(c["player"].split()[-1] in inj["player"] for inj in existing)
                if not already:
                    from datetime import date as _date
                    injuries[team]["injuries"] = existing + [{
                        "player": c["player"],
                        "note": f"{c['status']}，ESPN自動偵測",
                        "known_from": _date.today().strftime("%Y-%m-%d"),
                        "attack_mult": 1.0,
                        "defense_mult": 1.0,
                    }]
            alert_injury_update(match_label, changes_this_match)

    if all_changes:
        inj_path.write_text(json.dumps(injuries, ensure_ascii=False, indent=2))
        print(f"[pre_kickoff] injuries.json updated with {len(all_changes)} change(s)")

    return all_changes


def update_team_history() -> bool:
    """
    Fetch and cache pre-tournament team history if missing or >7 days old.
    Returns True if the file was updated.
    """
    path = DATA_DIR / "team_history.json"
    if path.exists():
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days < 7:
            print("[update_team_history] 歷史數據在7天內，跳過重新抓取")
            return False

    print("[update_team_history] 抓取各隊賽前歷史數據（約需5分鐘）...")
    history = fetch_team_history()
    if history:
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2))
        print(f"[update_team_history] 已儲存 {len(history)} 支球隊的歷史數據")
        return True
    return False
