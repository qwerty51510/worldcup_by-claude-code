"""
Team composite evaluation for WC 2026.

Combines: ELO + squad market value + WC 2026 actual form + per90 player strength
to identify undervalued or overvalued teams versus market pricing.

Usage:
    python -m src.team_report                    # all remaining teams
    python -m src.team_report Egypt Australia    # specific matchup
"""

import json
import csv
import sys
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_elo() -> dict:
    with open(ROOT / "data" / "elo_ratings.json") as f:
        return json.load(f)


def _load_wc_stats() -> dict:
    with open(ROOT / "data" / "wc2026_results.json") as f:
        results = json.load(f)
    stats = defaultdict(lambda: {"scored": 0, "conceded": 0, "played": 0})
    for m in results:
        h, a = m["home"], m["away"]
        hs, as_ = m["home_goals"], m["away_goals"]
        stats[h]["scored"] += hs
        stats[h]["conceded"] += as_
        stats[h]["played"] += 1
        stats[a]["scored"] += as_
        stats[a]["conceded"] += hs
        stats[a]["played"] += 1
    return dict(stats)


def _load_squad_values() -> dict:
    """Top-11 Transfermarkt value per team (EUR)."""
    squads = defaultdict(list)
    with open(ROOT / "data" / "player_data" / "squads.csv") as f:
        for row in csv.DictReader(f):
            val = float(row.get("rt_value_estimate_eur") or 0)
            squads[row["country"]].append((row["player_name"], row["position"], val))
    result = {}
    for country, players in squads.items():
        top11 = sorted(players, key=lambda x: -x[2])[:11]
        result[country] = {
            "total_m": sum(p[2] for p in top11) / 1e6,
            "stars": top11[:3],  # top 3 most valuable
        }
    return result


def _load_player_strength() -> dict:
    from src.player_strength import build_team_strengths
    return build_team_strengths()


def _elo_to_win_pct(elo_a: float, elo_b: float) -> float:
    """Expected win% for team A vs team B from ELO only."""
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def build_team_profiles(teams: list = None) -> dict:
    """
    Returns dict[team] -> profile with all evaluation dimensions + ranks.
    """
    elo_data = _load_elo()
    wc_data = _load_wc_stats()
    squad_data = _load_squad_values()
    ps_data = _load_player_strength()

    if teams is None:
        # Use all teams that appear in any data source
        all_teams = set(elo_data) | set(wc_data) | set(squad_data) | set(ps_data)
        teams = sorted(all_teams)

    profiles = {}
    for t in teams:
        wcs = wc_data.get(t, {"scored": 0, "conceded": 0, "played": 0})
        played = wcs["played"]
        gf_pg = wcs["scored"] / played if played else 0.0
        ga_pg = wcs["conceded"] / played if played else 0.0

        # WC form score: attack weighted 1.5x, defense 0.8x (goals conceded hurts)
        wc_form = gf_pg * 1.5 - ga_pg * 0.8

        sq = squad_data.get(t, {"total_m": 0, "stars": []})

        ps_str = ps_data.get(t, {})
        ps_atk = ps_str.get("attack", 0.0) if isinstance(ps_str, dict) else 0.0
        ps_def = ps_str.get("defense", 0.0) if isinstance(ps_str, dict) else 0.0

        profiles[t] = {
            "elo": elo_data.get(t, 1500),
            "squad_value_m": round(sq["total_m"], 1),
            "squad_stars": sq["stars"],
            "wc_played": played,
            "wc_gf_pg": round(gf_pg, 2),
            "wc_ga_pg": round(ga_pg, 2),
            "wc_form": round(wc_form, 3),
            "ps_attack": round(ps_atk, 3),
            "ps_defense": round(ps_def, 3),
        }

    # Rank each dimension (lower rank = better)
    def rank_by(key, reverse=True):
        sorted_t = sorted(profiles, key=lambda t: profiles[t][key], reverse=reverse)
        return {t: i + 1 for i, t in enumerate(sorted_t)}

    elo_r = rank_by("elo")
    squad_r = rank_by("squad_value_m")
    wc_r = rank_by("wc_form")
    ps_r = rank_by("ps_attack")

    for t, p in profiles.items():
        p["elo_rank"] = elo_r[t]
        p["squad_rank"] = squad_r[t]
        p["wc_rank"] = wc_r[t]
        p["ps_rank"] = ps_r[t]
        # Composite = average rank across 3 non-ELO signals
        non_elo_avg = (squad_r[t] + wc_r[t] + ps_r[t]) / 3
        p["composite_rank"] = round(non_elo_avg, 1)
        # Positive gap = ELO underrates them vs player/form signals
        p["undervalue_gap"] = round(elo_r[t] - non_elo_avg, 1)

    return profiles


def _print_matchup(home: str, away: str, profiles: dict):
    """Print detailed head-to-head comparison."""
    dims = [
        ("ELO", "elo", "elo_rank", False),
        ("Squad Value (M EUR)", "squad_value_m", "squad_rank", False),
        ("WC Goals/Game", "wc_gf_pg", "wc_rank", False),
        ("WC Conceded/Game", "wc_ga_pg", None, True),  # lower is better
        ("Player Attack", "ps_attack", "ps_rank", False),
        ("Player Defense", "ps_defense", None, False),
    ]
    h = profiles.get(home, {})
    a = profiles.get(away, {})

    print(f"\n{'═'*60}")
    print(f"  {home:25s}  vs  {away}")
    print(f"{'═'*60}")
    print(f"{'指標':<22} {'主隊':>12} {'客隊':>12}  {'優勢'}")
    print(f"{'-'*60}")

    for label, key, rank_key, lower_better in dims:
        hv = h.get(key, 0)
        av = a.get(key, 0)
        hr = f"(#{h.get(rank_key,'?')})" if rank_key else ""
        ar = f"(#{a.get(rank_key,'?')})" if rank_key else ""
        adv = ""
        if isinstance(hv, float) and isinstance(av, float):
            if lower_better:
                adv = "← 主" if hv < av else "客 →" if av < hv else "="
            else:
                adv = "← 主" if hv > av else "客 →" if av > hv else "="
        hstr = f"{hv:.1f}{hr}" if isinstance(hv, float) else f"{hv}{hr}"
        astr = f"{av:.1f}{ar}" if isinstance(av, float) else f"{av}{ar}"
        print(f"{label:<22} {hstr:>12} {astr:>12}  {adv}")

    print(f"{'-'*60}")
    hg = h.get("undervalue_gap", 0)
    ag = a.get("undervalue_gap", 0)
    print(f"{'被低估信號':<22} {hg:>+12.1f} {ag:>+12.1f}  (正值=ELO低估)")

    # Star players
    for team, p in [(home, h), (away, a)]:
        stars = p.get("squad_stars", [])
        if stars:
            names = ", ".join(f"{n}(€{v/1e6:.1f}M)" for n, pos, v in stars[:3])
            print(f"  {team} 核心球員: {names}")

    # ELO-based match probability
    h_elo = h.get("elo", 1500)
    a_elo = a.get("elo", 1500)
    h_win_elo = _elo_to_win_pct(h_elo, a_elo)
    print(f"\n  ELO 推算主勝率: {h_win_elo:.1%}  客勝率: {1-h_win_elo:.1%}")
    print(f"  WC 攻防: {home} {h.get('wc_gf_pg',0):.1f}進{h.get('wc_ga_pg',0):.1f}失 / "
          f"{away} {a.get('wc_gf_pg',0):.1f}進{a.get('wc_ga_pg',0):.1f}失")
    print()


def _print_ranking_table(profiles: dict, top_n: int = 30):
    """Print overall ranking by composite score."""
    items = sorted(profiles.items(), key=lambda x: x[1]["composite_rank"])[:top_n]

    print(f"\n{'═'*80}")
    print(f"{'WC 2026 球隊綜合評估':^80}")
    print(f"{'（依球員實力+WC實際表現+陣容市值排名，ELO差距=被低估信號）':^80}")
    print(f"{'═'*80}")
    print(f"{'隊伍':<18} {'ELO':>5} {'#ELO':>5} {'陣容M':>7} {'WC進':>5} {'WC失':>5} "
          f"{'玩家攻':>7} {'綜合#':>6} {'低估↑':>6}")
    print(f"{'-'*80}")

    for t, p in items:
        gap = p["undervalue_gap"]
        gap_str = f"+{gap:.0f}" if gap > 0 else f"{gap:.0f}"
        print(f"{t:<18} {p['elo']:>5.0f} {p['elo_rank']:>5} {p['squad_value_m']:>7.1f} "
              f"{p['wc_gf_pg']:>5.2f} {p['wc_ga_pg']:>5.2f} "
              f"{p['ps_attack']:>7.3f} {p['composite_rank']:>6.1f} {gap_str:>6}")

    print(f"\n* 低估↑ 正值越大 = 球員實力/WC表現明顯強過其ELO排名 = 市場可能低估")


def _find_undervalued(profiles: dict, min_gap: float = 5.0) -> list:
    """Return teams where player/form signals >> ELO (potential market undervaluation)."""
    results = []
    for t, p in profiles.items():
        gap = p.get("undervalue_gap", 0)
        if gap >= min_gap and p.get("wc_played", 0) >= 2:
            results.append((t, p, gap))
    return sorted(results, key=lambda x: -x[2])


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) >= 2:
        # Matchup mode
        home, away = args[0], args[1]
        profiles = build_team_profiles([home, away])
        _print_matchup(home, away, profiles)
    else:
        # Full ranking mode - limit to WC 2026 contenders
        wc_teams_file = ROOT / "data" / "wc2026_results.json"
        with open(wc_teams_file) as f:
            results = json.load(f)
        wc_teams = set()
        for m in results:
            wc_teams.add(m["home"])
            wc_teams.add(m["away"])

        profiles = build_team_profiles(list(wc_teams))
        _print_ranking_table(profiles)

        print(f"\n{'━'*50}")
        print("被 ELO 低估的隊伍（球員實力+WC表現 >> ELO）：")
        undervalued = _find_undervalued(profiles, min_gap=5.0)
        for t, p, gap in undervalued[:10]:
            stars = p.get("squad_stars", [])
            star_str = ", ".join(n for n, pos, v in stars[:2]) if stars else "無資料"
            print(f"  {t:<20} 低估幅度 +{gap:.0f}名  核心:{star_str}")
            print(f"    WC: {p['wc_gf_pg']:.1f}進{p['wc_ga_pg']:.1f}失/{p['wc_played']}場 "
                  f"| 球員攻 {p['ps_attack']:.3f} | ELO {p['elo']:.0f}(#{p['elo_rank']})")
