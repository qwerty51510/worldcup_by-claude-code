"""
pm_match_ev.py — 單場勝負市場 EV 掃描器

抓取 Polymarket 各場 R32/R16/QF 比賽的主勝/平/客勝市場，
與我方 Poisson 模型比對，輸出 EV 機會表。

用法：
  python3 -m src.pm_match_ev
  python3 -m src.pm_match_ev --min-ev 0.05
"""

import os
import argparse
import requests
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.pm_predict import match_win_probs

GAMMA_BASE = "https://gamma-api.polymarket.com"
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

# football-data.org team name → Polymarket FIFA slug code
TEAM_CODES = {
    "South Africa":          "rsa",
    "Canada":                "can",
    "Brazil":                "bra",
    "Japan":                 "jpn",
    "Germany":               "ger",
    "Paraguay":              "par",
    "Netherlands":           "ned",
    "Morocco":               "mar",
    "Ivory Coast":           "civ",
    "Norway":                "nor",
    "France":                "fra",
    "Sweden":                "swe",
    "Mexico":                "mex",
    "Ecuador":               "ecu",
    "England":               "eng",
    "Congo DR":              "cod",
    "Belgium":               "bel",
    "Senegal":               "sen",
    "United States":         "usa",
    "Bosnia-Herzegovina":    "bih",
    "Spain":                 "esp",
    "Austria":               "aut",
    "Portugal":              "por",
    "Croatia":               "cro",
    "Switzerland":           "sui",
    "Algeria":               "alg",
    "Australia":             "aus",
    "Egypt":                 "egy",
    "Argentina":             "arg",
    "Cape Verde Islands":    "cpv",
    "Colombia":              "col",
    "Ghana":                 "gha",
}


def _fetch_fixtures() -> list:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(
            f"{FOOTBALL_DATA_BASE}/competitions/2000/matches",
            headers={"X-Auth-Token": key},
            params={"status": "SCHEDULED,TIMED"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("matches", [])
    except Exception as e:
        print(f"[pm_match_ev] fixture fetch failed: {e}")
        return []


def _fetch_match_market(home: str, away: str, date_str: str):
    """
    回傳 {
      "home_win": 0.58, "draw": 0.26, "away_win": 0.16,
      "token_ids": {"home_win": "0x...", "draw": "0x...", "away_win": "0x..."}
    } 或 None
    """
    import json as _json
    h = TEAM_CODES.get(home, "")
    a = TEAM_CODES.get(away, "")
    if not h or not a:
        return None

    slug = f"fifwc-{h}-{a}-{date_str}"
    try:
        r = requests.get(f"{GAMMA_BASE}/events", params={"slug": slug}, timeout=10)
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        markets = data[0].get("markets", [])
    except Exception:
        return None

    prices = {}
    token_ids = {}
    for m in markets:
        q = m.get("question", "").lower()
        try:
            raw_prices = _json.loads(m.get("outcomePrices", "[]"))
            yes_price = float(raw_prices[0]) if raw_prices else 0.0
            clob_ids = _json.loads(m.get("clobTokenIds", "[]"))
            yes_token = clob_ids[0] if clob_ids else ""
        except Exception:
            continue

        if "draw" in q:
            prices["draw"] = yes_price
            token_ids["draw"] = yes_token
        elif home.lower().split()[0] in q or h in q:
            prices["home_win"] = yes_price
            token_ids["home_win"] = yes_token
        elif away.lower().split()[0] in q or a in q:
            prices["away_win"] = yes_price
            token_ids["away_win"] = yes_token

    if len(prices) < 3:
        ordered_prices, ordered_tokens = [], []
        for m in markets:
            try:
                raw = _json.loads(m.get("outcomePrices", "[]"))
                tok = _json.loads(m.get("clobTokenIds", "[]"))
                ordered_prices.append(float(raw[0]) if raw else 0.0)
                ordered_tokens.append(tok[0] if tok else "")
            except Exception:
                pass
        if len(ordered_prices) == 3:
            prices = {"home_win": ordered_prices[0], "draw": ordered_prices[1], "away_win": ordered_prices[2]}
            token_ids = {"home_win": ordered_tokens[0], "draw": ordered_tokens[1], "away_win": ordered_tokens[2]}

    if len(prices) < 3:
        return None
    return {**prices, "token_ids": token_ids}


def scan(min_ev: float = 0.03) -> list:
    fixtures = _fetch_fixtures()
    results = []

    for m in fixtures:
        home = m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("name", "")
        date_str = m.get("utcDate", "")[:10]
        if not home or not away or not date_str:
            continue

        market = _fetch_match_market(home, away, date_str)
        if not market:
            continue

        try:
            ph, pd, pa = match_win_probs(home, away)
        except Exception:
            continue

        ev_home = ph - market["home_win"]
        ev_draw = pd - market["draw"]
        ev_away = pa - market["away_win"]

        token_ids = market.get("token_ids", {})
        entry = {
            "date": date_str,
            "home": home,
            "away": away,
            "market": {k: v for k, v in market.items() if k != "token_ids"},
            "token_ids": token_ids,
            "model": {"home_win": round(ph, 3), "draw": round(pd, 3), "away_win": round(pa, 3)},
            "ev": {
                "home_win": round(ev_home, 3),
                "draw":     round(ev_draw, 3),
                "away_win": round(ev_away, 3),
            },
        }
        results.append(entry)

    # 只回傳有正EV機會的
    results.sort(key=lambda x: max(x["ev"].values()), reverse=True)
    return results


def _fmt(label: str, model: float, market: float, ev: float) -> str:
    sign = "+" if ev > 0 else ""
    ev_str = f"{sign}{ev*100:.1f}¢"
    flag = " ⭐" if ev >= 0.08 else (" ▲" if ev >= 0.05 else "")
    return (f"  {label:<8} 模型:{model*100:.1f}%  市場:{market*100:.1f}%  "
            f"EV:{ev_str}{flag}")


def print_report(results: list, min_ev: float = 0.03) -> None:
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    print(f"\n{'═'*72}")
    print(f"  PM 單場勝負 EV 掃描   {now}")
    print(f"{'═'*72}\n")

    found = False
    for r in results:
        evs = r["ev"]
        best_ev = max(evs.values())
        if best_ev < min_ev:
            continue
        found = True
        home, away = r["home"], r["away"]
        print(f"  {r['date']}  {home} vs {away}")
        print(_fmt("主勝", r["model"]["home_win"], r["market"]["home_win"], evs["home_win"]))
        print(_fmt("平局", r["model"]["draw"],     r["market"]["draw"],     evs["draw"]))
        print(_fmt("客勝", r["model"]["away_win"], r["market"]["away_win"], evs["away_win"]))
        print()

    if not found:
        print(f"  無 EV ≥ {min_ev*100:.0f}¢ 的機會\n")
    print(f"{'═'*72}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ev", type=float, default=0.03)
    args = ap.parse_args()
    results = scan(args.min_ev)
    print_report(results, args.min_ev)
