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
    dates_to_try = [base_dt, base_dt - timedelta(days=1)]
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

    # Pair-based key: catches swapped home/away and date mismatches
    existing_keys = {
        (tuple(sorted([r["home"], r["away"]])), r.get("round", 0))
        for r in existing
    }

    new_records = []
    for m in raw:
        home = _normalize_team(m.get("homeTeam", {}).get("name", ""))
        away = _normalize_team(m.get("awayTeam", {}).get("name", ""))
        date_str = (m.get("utcDate", "") or "")[:10]
        score = m.get("score", {}).get("fullTime", {})
        home_goals = score.get("home")
        away_goals = score.get("away")
        group_raw = m.get("group", "") or ""
        group = group_raw.replace("GROUP_", "") if group_raw.startswith("GROUP_") else ""
        matchday = m.get("matchday") or 0

        if not home or not away or home_goals is None or away_goals is None:
            continue

        pair_key = (tuple(sorted([home, away])), matchday)
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
            "home_goals": int(home_goals),
            "away_goals": int(away_goals),
            "round": int(matchday),
        })
        existing_keys.add(pair_key)

    if new_records:
        merged = sorted(existing + new_records, key=lambda r: r["date"])

        # Validate team count integrity
        all_teams = {t for r in merged for t in (r["home"], r["away"])}
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
