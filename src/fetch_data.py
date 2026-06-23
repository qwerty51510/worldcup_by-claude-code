import json
import os
import time
from pathlib import Path

import requests

from src.config import FOOTBALL_DATA_BASE, ODDS_API_BASE, POLYMARKET_BASE, WORLD_CUP_COMPETITION_ID

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
