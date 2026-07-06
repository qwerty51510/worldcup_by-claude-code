import json
import math
from datetime import datetime
from pathlib import Path
from src.config import FIFA_RANKINGS, BASE_LAMBDA, RANK_DECAY, AH_LINE_MULTIPLIER

# Log-linear mapping: P(win WC) → strength in range [0.5, 2.0]
# Calibrated so France(19.75%) → 2.0, Qatar(0.05%) → 0.5
_PM_LOG_A = 2.406
_PM_LOG_B = 0.2508

# Player data blend for OU only (AH uses pure ELO — grid search confirmed 0.4 is optimal)
_PLAYER_OU_ALPHA = 0.4

# ELO → strength: normalised around 1500 (average), compressed to 0.4–2.2 range
_ELO_BASE = 1500.0
_ELO_SCALE = 750.0  # 750 ELO points → 2x strength

_ELO_RATINGS: dict = {}
_WC_TEAM_STATS: dict = {}  # computed once from wc2026_results.json
_WC_RESULTS: list = []     # full results list for rest-days calculation
_FORMATIONS: dict = {}
_TEAM_HISTORY: dict = {}   # pre-tournament stats from team_history.json
_TUNED_PARAMS: dict = {}   # params from tuner (wc_league_avg, ah_line_multiplier)     # team formation + style
_VENUES: dict = {}         # venue metadata (altitude, weather)

# WC 2026 league average: 121 goals / 40 matches / 2 teams per match = 1.51
_WC_LEAGUE_AVG = 1.51

# Formation → (attack_multiplier, defense_multiplier)
# attack_mult  > 1 = scores more;  defense_mult < 1 = concedes less
_FORMATION_FACTORS: dict = {
    "3-4-3":   (1.10, 1.07),
    "4-3-3":   (1.06, 1.04),
    "4-2-3-1": (1.03, 1.02),
    "4-4-2":   (1.00, 1.00),
    "4-4-1-1": (0.97, 0.97),
    "4-5-1":   (0.92, 0.92),
    "4-1-4-1": (0.90, 0.90),
    "5-3-2":   (0.88, 0.88),
    "5-4-1":   (0.85, 0.85),
}

# (home_style, away_style) → (h_atk_mult, a_atk_mult)
# Encodes RELATIVE advantage from tactical matchup only — not absolute goal level.
# Formation factors already capture each team's base style; this layer only shifts
# who scores more within the match (h_sm × a_sm ≈ 1.0, preserving total goals).
# Key signal: counter style exploits space left by attacking/possession teams.
_STYLE_MATCHUP: dict = {
    ("attacking",  "attacking"):  (1.00, 1.00),
    ("attacking",  "possession"): (1.01, 0.99),
    ("attacking",  "balanced"):   (1.01, 0.99),
    ("attacking",  "counter"):    (0.98, 1.02),  # counter exploits space
    ("attacking",  "defensive"):  (1.01, 0.99),

    ("possession", "attacking"):  (0.99, 1.01),
    ("possession", "possession"): (1.00, 1.00),
    ("possession", "balanced"):   (1.00, 1.00),
    ("possession", "counter"):    (0.97, 1.03),  # strongest signal: counter vs possession
    ("possession", "defensive"):  (1.00, 1.00),

    ("balanced",   "attacking"):  (0.99, 1.01),
    ("balanced",   "possession"): (1.00, 1.00),
    ("balanced",   "balanced"):   (1.00, 1.00),
    ("balanced",   "counter"):    (0.99, 1.01),
    ("balanced",   "defensive"):  (1.01, 0.99),

    ("counter",    "attacking"):  (1.02, 0.98),  # counter thrives vs attacking
    ("counter",    "possession"): (1.03, 0.97),  # counter thrives vs possession
    ("counter",    "balanced"):   (1.01, 0.99),
    ("counter",    "counter"):    (1.00, 1.00),
    ("counter",    "defensive"):  (1.00, 1.00),

    ("defensive",  "attacking"):  (0.99, 1.01),
    ("defensive",  "possession"): (1.00, 1.00),
    ("defensive",  "balanced"):   (0.99, 1.01),
    ("defensive",  "counter"):    (1.00, 1.00),
    ("defensive",  "defensive"):  (1.00, 1.00),
}

STYLE_ZH: dict = {
    "attacking":  "進攻型",
    "possession": "控球進攻",
    "balanced":   "均衡",
    "counter":    "防守反擊",
    "defensive":  "防守型",
}


def _load_elo() -> dict:
    global _ELO_RATINGS
    if _ELO_RATINGS:
        return _ELO_RATINGS
    path = Path(__file__).parent.parent / "data" / "elo_ratings.json"
    if path.exists():
        _ELO_RATINGS = json.loads(path.read_text())
    return _ELO_RATINGS


def _load_wc_results() -> list:
    global _WC_RESULTS
    if _WC_RESULTS:
        return _WC_RESULTS
    path = Path(__file__).parent.parent / "data" / "wc2026_results.json"
    if path.exists():
        _WC_RESULTS = json.loads(path.read_text())
    return _WC_RESULTS


def _load_wc_team_stats() -> dict:
    """Load per-team attack/defense stats from WC 2026 results (computed once)."""
    global _WC_TEAM_STATS
    if _WC_TEAM_STATS:
        return _WC_TEAM_STATS
    tp = _load_tuned_params()
    recency_decay = tp.get("recency_decay", 1.0)
    _WC_TEAM_STATS = _build_stats(_load_wc_results(), recency_decay)
    return _WC_TEAM_STATS


def _load_formations() -> dict:
    global _FORMATIONS
    if _FORMATIONS:
        return _FORMATIONS
    path = Path(__file__).parent.parent / "data" / "formations.json"
    if path.exists():
        data = json.loads(path.read_text())
        _FORMATIONS = {k: v for k, v in data.items() if not k.startswith("_")}
    return _FORMATIONS


def _load_team_history() -> dict:
    """Load pre-tournament team stats from team_history.json (cached)."""
    global _TEAM_HISTORY
    if _TEAM_HISTORY:
        return _TEAM_HISTORY
    path = Path(__file__).parent.parent / "data" / "team_history.json"
    if path.exists():
        try:
            _TEAM_HISTORY = json.loads(path.read_text())
        except Exception:
            _TEAM_HISTORY = {}
    return _TEAM_HISTORY


def _load_tuned_params() -> dict:
    """Load tuned params from tuning.json (cached; reset by clear_caches)."""
    global _TUNED_PARAMS
    if _TUNED_PARAMS:
        return _TUNED_PARAMS
    path = Path(__file__).parent.parent / "data" / "tuning.json"
    if path.exists():
        try:
            _TUNED_PARAMS = json.loads(path.read_text())
        except Exception:
            _TUNED_PARAMS = {}
    return _TUNED_PARAMS


def _load_venues() -> dict:
    global _VENUES
    if _VENUES:
        return _VENUES
    path = Path(__file__).parent.parent / "data" / "venues.json"
    if path.exists():
        try:
            _VENUES = json.loads(path.read_text())
        except Exception:
            _VENUES = {}
    return _VENUES


def _load_injury_mults() -> dict:
    path = Path(__file__).parent.parent / "data" / "injuries.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    mults = {}
    for team, val in raw.items():
        if team.startswith("_"):
            continue
        if isinstance(val, dict) and ("attack_mult" in val or "defense_mult" in val):
            mults[team] = {
                "attack_mult": float(val.get("attack_mult", 1.0)),
                "defense_mult": float(val.get("defense_mult", 1.0)),
            }
    return mults


def load_team_discipline_stats() -> dict:
    """Aggregate corner kicks and cards per team.

    Returns {"wc": {team: {corners_pg, yellow_pg, red_pg, games}},
             "hist": {team: {corners_pg, yellow_pg, red_pg, games}}}
    WC stats come from match-day files (2026-06-22+).
    Historical stats come from data/discipline_historical.json (pre-WC ESPN boxscores).
    """
    data_dir = Path(__file__).parent.parent / "data" / "matches"
    WC_START = "2026-06-22"
    totals: dict = {}

    for f in sorted(data_dir.glob("*.json")):
        if f.stem < WC_START:
            continue
        try:
            day = json.loads(f.read_text())
        except Exception:
            continue
        for match_key, md in day.get("goal_events", {}).items():
            if not isinstance(md, dict):
                continue
            stats = md.get("stats", {})
            for side in ("home", "away"):
                s = stats.get(side, {})
                if not s:
                    continue
                parts = match_key.split("|")
                team = parts[0] if side == "home" else (parts[1] if len(parts) > 1 else "")
                if not team:
                    continue
                t = totals.setdefault(team, {"corners": 0, "yellow_cards": 0, "red_cards": 0, "games": 0})
                try:
                    t["corners"] += int(s.get("Corner Kicks", 0) or 0)
                    t["yellow_cards"] += int(s.get("Yellow Cards", 0) or 0)
                    t["red_cards"] += int(s.get("Red Cards", 0) or 0)
                    t["games"] += 1
                except (ValueError, TypeError):
                    pass

    wc: dict = {}
    for team, t in totals.items():
        g = t["games"]
        if g == 0:
            continue
        wc[team] = {
            "corners_pg": round(t["corners"] / g, 1),
            "yellow_pg": round(t["yellow_cards"] / g, 1),
            "red_pg": round(t["red_cards"] / g, 1),
            "games": g,
        }

    hist_path = Path(__file__).parent.parent / "data" / "discipline_historical.json"
    try:
        hist = json.loads(hist_path.read_text())
    except Exception:
        hist = {}

    return {"wc": wc, "hist": hist}


def _venue_lambda_factors(home: str, away: str, match: dict) -> tuple:
    """Returns (home_mult, away_mult) based on altitude and weather at match venue."""
    venues = _load_venues()
    if not venues:
        return 1.0, 1.0

    stage = match.get("stage", "GROUP_STAGE")
    round_key = {"LAST_32": "R32", "LAST_16": "R16"}.get(stage)
    if not round_key:
        return 1.0, 1.0

    round_map = venues.get("match_venue", {}).get(round_key, {})
    venue_name = round_map.get(f"{home} vs {away}") or round_map.get(f"{away} vs {home}")
    if not venue_name:
        return 1.0, 1.0

    venue = venues.get("venues", {}).get(venue_name)
    if not venue:
        return 1.0, 1.0

    alt_m = venue.get("altitude_m", 0)
    temp_c = venue.get("july_temp_c", 25)
    is_dome = venue.get("is_dome", False)
    acclimatized = venues.get("altitude_acclimatized_teams", {})

    home_home_alt = acclimatized.get(home, 0)
    away_home_alt = acclimatized.get(away, 0)
    home_acclim = home_home_alt >= alt_m * 0.5
    away_acclim = away_home_alt >= alt_m * 0.5

    h_mult = 1.0
    a_mult = 1.0

    if alt_m >= 500:
        # ~1% attacking penalty per 100m above 500m for non-acclimatized teams
        alt_penalty = min(0.15, (alt_m - 500) / 100 * 0.01)
        if not home_acclim:
            h_mult *= 1.0 - alt_penalty
        if not away_acclim:
            a_mult *= 1.0 - alt_penalty
        # Acclimatized team vs non-acclimatized opponent: small edge
        if home_acclim and not away_acclim:
            h_mult *= 1.03
        elif away_acclim and not home_acclim:
            a_mult *= 1.03

    # Outdoor heat above 30°C reduces both teams' attacking output
    if not is_dome and temp_c > 30:
        heat_penalty = min(0.06, (temp_c - 30) * 0.005)
        h_mult *= 1.0 - heat_penalty
        a_mult *= 1.0 - heat_penalty

    return round(h_mult, 3), round(a_mult, 3)


def clear_caches() -> None:
    """Reset in-memory caches after wc2026_results.json is updated."""
    global _WC_TEAM_STATS, _WC_RESULTS, _TUNED_PARAMS, _VENUES
    _WC_TEAM_STATS = {}
    _WC_RESULTS = []
    _TUNED_PARAMS = {}
    _VENUES = {}


def _rest_days(team: str, match_date: str, results: list = None) -> int:
    """Days since team's last WC match. Returns 999 if first match."""
    if results is None:
        results = _load_wc_results()
    past = [r["date"] for r in results
            if (r["home"] == team or r["away"] == team) and r["date"] < match_date]
    if not past:
        return 999
    last = max(past)
    return (datetime.strptime(match_date, "%Y-%m-%d") - datetime.strptime(last, "%Y-%m-%d")).days


def _stamina_factor(days: int) -> float:
    if days <= 3:
        return 0.93
    if days <= 4:
        return 0.97
    return 1.00


def _elo_to_strength(elo: float) -> float:
    """Convert ELO rating to relative strength (1.0 = average team)."""
    return max(0.4, 2.0 ** ((elo - _ELO_BASE) / _ELO_SCALE))


def _derive_ou_line(lh: float, la: float) -> float:
    return max(2.0, round((lh + la) * 2) / 2)


def compute_incentive_score(must_win: bool, safe_draw: bool, dead_rubber: bool) -> float:
    if dead_rubber:
        return 0.2
    if must_win:
        return 0.85
    if safe_draw:
        return 0.45
    return 0.6


def _compute_group_context(home: str, away: str, group: str, before_date: str) -> dict:
    """Compute group standings + tournament motivation context before a given match date."""
    if not group:
        return {}
    results_path = Path(__file__).parent.parent / "data" / "wc2026_results.json"
    if not results_path.exists():
        return {}
    all_results = json.loads(results_path.read_text())

    group_code = group.replace("GROUP_", "") if group.startswith("GROUP_") else group
    group_results = [
        r for r in all_results
        if r.get("group") == group_code and r.get("date", "9999") < before_date
    ]

    from collections import defaultdict
    st = defaultdict(lambda: {"pts": 0, "gf": 0, "ga": 0, "played": 0, "last": None})
    for r in sorted(group_results, key=lambda x: x.get("date", "")):
        h, a, hg, ag = r["home"], r["away"], r["home_goals"], r["away_goals"]
        st[h]["played"] += 1; st[a]["played"] += 1
        st[h]["gf"] += hg; st[h]["ga"] += ag
        st[a]["gf"] += ag; st[a]["ga"] += hg
        st[h]["last"] = {"opp": a, "hg": hg, "ag": ag, "home": True}
        st[a]["last"] = {"opp": h, "hg": hg, "ag": ag, "home": False}
        if hg > ag:
            st[h]["pts"] += 3
        elif hg == ag:
            st[h]["pts"] += 1; st[a]["pts"] += 1
        else:
            st[a]["pts"] += 3

    for t in st:
        st[t]["gd"] = st[t]["gf"] - st[t]["ga"]

    sorted_teams = sorted(st.keys(), key=lambda t: (-st[t]["pts"], -st[t]["gd"], -st[t]["gf"]))
    other_teams = [t for t in sorted_teams if t not in (home, away)]

    def _can_finish_top2_if(team: str, team_pts_after: int, team_gd_after: int) -> bool:
        # Use each other team's MAX reachable pts (current + 3 per remaining match)
        # to avoid false safe_draw/must_win flags in MD1/MD2
        sure_above = sum(
            1 for t in other_teams
            if st[t]["pts"] + 3 * (3 - st[t]["played"]) > team_pts_after or
               (st[t]["pts"] + 3 * (3 - st[t]["played"]) == team_pts_after and st[t]["gd"] > team_gd_after)
        )
        return sure_above < 2

    h_pts = st[home]["pts"] if home in st else 0
    a_pts = st[away]["pts"] if away in st else 0
    h_gd = st[home]["gd"] if home in st else 0
    a_gd = st[away]["gd"] if away in st else 0

    # Determine flags (from each team's perspective)
    h_safe_draw = _can_finish_top2_if(home, h_pts + 1, h_gd)
    a_safe_draw = _can_finish_top2_if(away, a_pts + 1, a_gd)
    h_safe_loss = _can_finish_top2_if(home, h_pts, h_gd - 2)
    a_safe_loss = _can_finish_top2_if(away, a_pts, a_gd - 2)
    h_must_win = not _can_finish_top2_if(home, h_pts + 1, h_gd) and _can_finish_top2_if(home, h_pts + 3, h_gd + 2)
    a_must_win = not _can_finish_top2_if(away, a_pts + 1, a_gd) and _can_finish_top2_if(away, a_pts + 3, a_gd + 2)
    # Dead rubber: both already qualified (safe even with a loss) OR both mathematically eliminated
    h_eliminated = not _can_finish_top2_if(home, h_pts + 3, h_gd + 10)
    a_eliminated = not _can_finish_top2_if(away, a_pts + 3, a_gd + 10)
    dead_rubber = (h_safe_loss and a_safe_loss) or (h_eliminated and a_eliminated)

    return {
        "group": group_code,
        "standings": {t: dict(st[t]) for t in sorted_teams},
        "home_standing": dict(st[home]) if home in st else {},
        "away_standing": dict(st[away]) if away in st else {},
        "sorted_teams": sorted_teams,
        "must_win_home": h_must_win,
        "must_win_away": a_must_win,
        "safe_draw_home": h_safe_draw,
        "safe_draw_away": a_safe_draw,
        "home_eliminated": h_eliminated,
        "away_eliminated": a_eliminated,
        "dead_rubber": dead_rubber,
    }


def compute_sharp_signal(open_handicap: float, current_handicap: float) -> float:
    # positive = line moved toward away team; negative = toward home team
    return current_handicap - open_handicap


def _rank_to_strength(rank: int) -> float:
    return 2.0 * (1.0 / (1.0 + (rank - 1) * RANK_DECAY))


def _pm_to_strength(p_win_wc: float) -> float:
    """Convert Polymarket WC winner probability to team strength (0.5–2.0 range)."""
    p = max(p_win_wc, 0.0005)  # floor at 0.05% to avoid log(0)
    return max(0.5, min(2.0, _PM_LOG_A + _PM_LOG_B * math.log(p)))


def _round_ah(line: float) -> float:
    return round(line * 4) / 4


def _strengths_to_lambdas(home_str: float, away_str: float) -> tuple:
    # Use geometric model: lh = BASE * sqrt(h/a), la = BASE * sqrt(a/h)
    # This makes total expected goals vary by mismatch (lopsided = more goals)
    # and AH line reflect real strength gap. Avoids the prior bug where
    # lh+la was always constant (= 2*BASE) regardless of team quality.
    tp = _load_tuned_params()
    ah_mult = tp.get("ah_line_multiplier", AH_LINE_MULTIPLIER)
    ratio = max(home_str, 0.1) / max(away_str, 0.1)
    lh = round(max(0.4, BASE_LAMBDA * math.sqrt(ratio) + 0.1), 3)   # +0.1 home advantage
    la = round(max(0.3, BASE_LAMBDA * math.sqrt(1.0 / ratio)), 3)
    implied_ah = _round_ah(-(lh - la) * ah_mult)
    implied_ou = _derive_ou_line(lh, la)
    return lh, la, implied_ah, implied_ou


def _lambda_from_pm(home: str, away: str, pm_strengths: dict) -> tuple:
    """Use Polymarket WC winner probabilities as team strength signal."""
    h_str = _pm_to_strength(pm_strengths[home]) if home in pm_strengths else None
    a_str = _pm_to_strength(pm_strengths[away]) if away in pm_strengths else None

    # fall back to FIFA for teams not in PM market
    if h_str is None:
        h_str = _rank_to_strength(FIFA_RANKINGS.get(home, 40))
    if a_str is None:
        a_str = _rank_to_strength(FIFA_RANKINGS.get(away, 40))

    return _strengths_to_lambdas(h_str, a_str)


def _lambda_from_rankings(home: str, away: str) -> tuple:
    home_str = _rank_to_strength(FIFA_RANKINGS.get(home, 40))
    away_str = _rank_to_strength(FIFA_RANKINGS.get(away, 40))
    return _strengths_to_lambdas(home_str, away_str)


def _lambda_from_wc_form(home: str, away: str, match_date: str = "",
                         prior_results: list = None):
    """
    Bayesian-smoothed Dixon-Coles lambda with formation, stamina, and team history.
    prior_results: if provided, use this list instead of the global cache
                   (used by validate.py walk-forward to avoid leaking future data).
    Tuned params (wc_league_avg, ah_line_multiplier) loaded from tuning.json if available.
    """
    # Load tuned params; fall back to config constants
    tp = _load_tuned_params()
    league_avg = tp.get("wc_league_avg", _WC_LEAGUE_AVG)
    ah_mult = tp.get("ah_line_multiplier", AH_LINE_MULTIPLIER)
    recency_decay = tp.get("recency_decay", 1.0)

    stats = _load_wc_team_stats() if prior_results is None else _build_stats(prior_results, recency_decay)
    elo = _load_elo()
    team_history = _load_team_history()

    PRIOR = 2.0

    def team_strength(team: str) -> float:
        if team in elo:
            return _elo_to_strength(elo[team])
        return _rank_to_strength(FIFA_RANKINGS.get(team, 40))

    # Average G/match in our H2H dataset (2022-2026 international matches)
    # Used to normalize historical rates to WC-level context
    _H2H_AVG = 1.31

    # Player strength cache for prior substitution (built once per call)
    try:
        from src.player_strength import build_team_strengths as _bts
        _ps_cache = _bts()
    except Exception:
        _ps_cache = {}

    def _player_prior_rate(team: str, stat: str):
        """Player per90-based prior rate (goals/game). None if data unavailable."""
        ps = _ps_cache.get(team, {})
        if not isinstance(ps, dict):
            return None
        atk = ps.get("attack", 0)
        def_ = ps.get("defense", 0)
        if atk == 0 and def_ == 0:
            return None
        if stat == "scored":
            return atk * league_avg if atk > 0 else None
        else:
            return (1.0 / max(0.3, def_)) * league_avg if def_ > 0 else None

    def smooth_rate(team: str, stat: str) -> float:
        s = stats.get(team, {"scored": 0, "conceded": 0, "played": 0})
        strength = team_strength(team)
        elo_prior = (strength if stat == "scored" else 1.0 / strength) * league_avg

        h = team_history.get(team, {"scored": 0, "conceded": 0, "played": 0})
        if h["played"] >= 3:
            # Historical pre-tournament data available: blend ELO + history
            hist_strength = (h[stat] / h["played"]) / _H2H_AVG
            hist_prior = hist_strength * league_avg
            blend = min(h["played"] / 10.0, 0.5)
            prior_rate = elo_prior * (1 - blend) + hist_prior * blend
        else:
            # No historical data: blend ELO with player per90 prior.
            # Player weight decays as WC data accumulates (0 games→60%, 5 games→20%).
            pl_rate = _player_prior_rate(team, stat)
            if pl_rate is not None:
                wc_played = s["played"]
                pl_w = max(0.15, 0.6 - wc_played * 0.08)
                prior_rate = elo_prior * (1 - pl_w) + pl_rate * pl_w
            else:
                prior_rate = elo_prior

        raw = (s[stat] + PRIOR * prior_rate) / (s["played"] + PRIOR) / league_avg
        # Floor defensive rate at 0.40 to prevent unrealistically low values from
        # small samples (e.g. 0 goals conceded in 4 games overfits to near-zero).
        if stat == "conceded":
            raw = max(0.40, raw)
        return raw

    h_atk = smooth_rate(home, "scored")
    h_def = smooth_rate(home, "conceded")
    a_atk = smooth_rate(away, "scored")
    a_def = smooth_rate(away, "conceded")

    # ── Formation adjustment ─────────────────────────────────────────────────
    formations = _load_formations()
    h_form = formations.get(home, {}).get("formation", "4-4-2")
    a_form = formations.get(away, {}).get("formation", "4-4-2")
    h_style = formations.get(home, {}).get("style", "balanced")
    a_style = formations.get(away, {}).get("style", "balanced")
    h_atk_m, h_def_m = _FORMATION_FACTORS.get(h_form, (1.0, 1.0))
    a_atk_m, a_def_m = _FORMATION_FACTORS.get(a_form, (1.0, 1.0))
    h_atk *= h_atk_m
    h_def *= h_def_m
    a_atk *= a_atk_m
    a_def *= a_def_m

    # ── Stamina / rest-days adjustment ───────────────────────────────────────
    if match_date:
        rest_src = prior_results if prior_results is not None else None
        h_days = _rest_days(home, match_date, rest_src)
        a_days = _rest_days(away, match_date, rest_src)
        h_stam = _stamina_factor(h_days)
        a_stam = _stamina_factor(a_days)
        h_atk *= h_stam
        a_atk *= a_stam
        # fatigue also slightly opens up defense (tired teams concede more)
        h_def *= (2.0 - h_stam)
        a_def *= (2.0 - a_stam)

    # ── Home advantage (host nations only) ──────────────────────────────────
    _HOST_NATIONS = {"United States", "Canada", "Mexico"}
    home_bonus = 0.10 if home in _HOST_NATIONS else 0.0
    lh = round(max(0.3, league_avg * h_atk * a_def + home_bonus), 3)
    la = round(max(0.3, league_avg * a_atk * h_def), 3)
    ah_line = _round_ah(-(lh - la) * ah_mult)
    ou_mult = tp.get("ou_line_multiplier", 1.0)
    return lh, la, ah_line, _derive_ou_line(lh * ou_mult, la * ou_mult)


def _build_stats(results: list, recency_decay: float = 1.0) -> dict:
    # Group results per team newest-first; weight recent goals higher.
    # played stays = actual game count so Bayesian prior balance is unchanged.
    sorted_r = sorted(results, key=lambda m: m.get("date", ""))
    team_games: dict = {}
    for m in reversed(sorted_r):
        for team, scored, conceded in [
            (m["home"], m["home_goals"], m["away_goals"]),
            (m["away"], m["away_goals"], m["home_goals"]),
        ]:
            team_games.setdefault(team, []).append((scored, conceded))

    stats: dict = {}
    for team, game_list in team_games.items():
        n = len(game_list)
        raw_w = sum(recency_decay ** i for i in range(n))
        norm = n / raw_w if raw_w > 0 and recency_decay != 1.0 else 1.0
        s_scored = s_conceded = 0.0
        for idx, (sc, co) in enumerate(game_list):
            w = (recency_decay ** idx) * norm
            s_scored += sc * w
            s_conceded += co * w
        stats[team] = {"scored": s_scored, "conceded": s_conceded, "played": float(n)}
    return stats


def _ah_from_1x2(p_home: float, p_away: float, ou_line: float) -> float:
    """
    Derive implied AH line from 1X2 win probabilities + OU totals line.
    Standard betting-market technique: strength ratio from win probs × total goals.
    Exponent 0.7 calibrated against WC historical data.
    ou_line=None is allowed; falls back to WC average of 2.5.
    """
    if p_home <= 0 or p_away <= 0:
        return 0.0
    r = max(0.05, min(50.0, (p_home / p_away) ** 0.7))
    S = max(1.5, ou_line if ou_line is not None else 2.5)
    lh = S * r / (r + 1.0)
    la = S - lh
    return _round_ah(-(lh - la))


def _extract_ah_ou(bookmakers: list, home_team: str = "", away_team: str = "") -> tuple:
    """
    Extract AH line and OU line from bookmaker data.
    Returns (ah_line, ou_line, ah_is_native) where:
      ah_is_native=True  → came from asian_handicap market (most reliable)
      ah_is_native=False → derived from h2h + totals (implied, still market-based)
      ah_line=None       → no market data at all
    """
    native_ah = None
    ou_line = None
    h2h_prices: dict = {}

    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market["key"] in ("asian_handicap", "spreads"):
                for outcome in market.get("outcomes", []):
                    if outcome.get("point") is not None:
                        try:
                            native_ah = float(outcome["point"])
                            break
                        except (TypeError, ValueError):
                            pass
            if market["key"] == "totals" and ou_line is None:
                for outcome in market.get("outcomes", []):
                    if outcome.get("point") is not None:
                        try:
                            ou_line = float(outcome["point"])
                            break
                        except (TypeError, ValueError):
                            pass
            if market["key"] == "h2h" and not h2h_prices:
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    try:
                        price = float(outcome.get("price", 0))
                        if price > 1.0 and name:
                            h2h_prices[name] = price
                    except (TypeError, ValueError):
                        pass

    if native_ah is not None:
        return native_ah, ou_line, True

    # Derive AH from h2h odds when asian_handicap market unavailable.
    # OU totals not required — use bookmaker OU if available, else default 2.5.
    if h2h_prices:
        def _find_price(team: str) -> float:
            if team in h2h_prices:
                return h2h_prices[team]
            for k, v in h2h_prices.items():
                if k.lower() in team.lower() or team.lower() in k.lower():
                    return v
            return 0.0

        ph_raw = _find_price(home_team)
        pa_raw = _find_price(away_team)

        # Fallback: if name matching fails use the two non-Draw outcomes in order
        if (not ph_raw or not pa_raw) and h2h_prices:
            non_draw = {k: v for k, v in h2h_prices.items() if k.lower() != "draw"}
            if len(non_draw) == 2:
                sorted_prices = sorted(non_draw.values())
                ph_raw, pa_raw = sorted_prices[0], sorted_prices[1]

        if ph_raw > 1.0 and pa_raw > 1.0:
            p_home_raw = 1.0 / ph_raw
            p_away_raw = 1.0 / pa_raw
            p_draw_raw = 1.0 / h2h_prices.get("Draw", 99)
            total = p_home_raw + p_away_raw + p_draw_raw
            _ou = ou_line if ou_line is not None else 2.5
            derived_ah = _ah_from_1x2(p_home_raw / total, p_away_raw / total, _ou)
            print(f"[features] h2h→AH: {home_team}({ph_raw}) vs {away_team}({pa_raw}) OU={_ou} → {derived_ah}")
            return derived_ah, ou_line, False

    return None, ou_line, False


def _lambda_from_ah_line(ah_line: float) -> tuple:
    home_base = 1.3 - (ah_line * 0.25)
    away_base = 1.3 + (ah_line * 0.25)
    return max(0.5, home_base), max(0.3, away_base)


def build_features(matches: list, odds: dict, calibration: dict, pm_strengths: dict = None,
                   espn_odds: dict = None) -> list:
    if pm_strengths is None:
        pm_strengths = {}
    if espn_odds is None:
        espn_odds = {}
    from src.fetch_data import _normalize_team
    results = []
    for match in matches:
        match_id = str(match.get("id", ""))
        ht = match.get("homeTeam") or {}
        at = match.get("awayTeam") or {}
        home = _normalize_team(ht.get("name") or "")
        away = _normalize_team(at.get("name") or "")
        if not home or not away:
            continue  # skip TBD matches

        odds_entry = None
        for entry in odds.values():
            eh = _normalize_team(entry.get("home_team", ""))
            ea = _normalize_team(entry.get("away_team", ""))
            if eh == home and ea == away:
                odds_entry = entry
                break

        # ESPN DraftKings lines take priority over Odds API h2h derivation
        # espn_odds keys are pipe-separated strings e.g. "Australia|Egypt"
        dk = (espn_odds.get(f"{home}|{away}")
              or espn_odds.get(f"{away}|{home}")
              or espn_odds.get((home, away))
              or espn_odds.get((away, home))
              or {})
        dk_ah = dk.get("ah_line")
        dk_ou = dk.get("ou_line")

        bookmakers = odds_entry.get("bookmakers", []) if odds_entry else []
        odds_home = odds_entry.get("home_team", home) if odds_entry else home
        odds_away = odds_entry.get("away_team", away) if odds_entry else away
        ah_line, ou_line, ah_is_native = _extract_ah_ou(bookmakers, odds_home, odds_away)

        # Override with DK real lines when available
        if dk_ah is not None:
            ah_line = dk_ah
            ah_is_native = True
        if dk_ou is not None:
            ou_line = dk_ou
        ou_from_market = ou_line is not None

        match_date = (match.get("utcDate", "") or "")[:10]
        elo = _load_elo()
        tp = _load_tuned_params()
        wc_form = _lambda_from_wc_form(home, away, match_date)

        if ah_is_native:
            # Native AH line (from DK ESPN or AH market): use WC form lambdas + real AH line
            lambda_home, lambda_away, _, ou_line_model = wc_form if wc_form else _lambda_from_ah_line(ah_line) + (None, None)
            if ou_line is None:
                ou_line = ou_line_model
            data_source = "DraftKings盤口" if dk_ah is not None else "盤口線（AH市場）"
        elif ah_line is not None and wc_form is not None:
            # AH derived from h2h+totals: use our WC form lambdas (better signal)
            # but the market-derived AH line for display and probability calculation
            lambda_home, lambda_away, _, ou_line_model = wc_form
            if ou_line is None:
                ou_line = ou_line_model
            data_source = "盤口線（h2h推算）"
        elif wc_form is not None:
            # No market odds at all — use WC form model
            lambda_home, lambda_away, _, ou_line_model = wc_form
            # Market-calibrated AH line (≈ expected goal diff)
            ah_line = _round_ah(-(lambda_home - lambda_away))
            if ou_line is None:
                ou_line = ou_line_model
            data_source = "WC 2026 實戰數據"
        elif elo.get(home) or elo.get(away):
            h_str = _elo_to_strength(elo.get(home, _ELO_BASE))
            a_str = _elo_to_strength(elo.get(away, _ELO_BASE))
            if home in pm_strengths:
                h_str = (h_str + _pm_to_strength(pm_strengths[home])) / 2
            if away in pm_strengths:
                a_str = (a_str + _pm_to_strength(pm_strengths[away])) / 2
            lambda_home, lambda_away, _, ou_model = _strengths_to_lambdas(h_str, a_str)
            ah_line = _round_ah(-(lambda_home - lambda_away))
            if ou_line is None:
                ou_line = ou_model
            data_source = "ELO歷史+Polymarket" if (home in pm_strengths or away in pm_strengths) else "ELO歷史數據"
        elif pm_strengths and (home in pm_strengths or away in pm_strengths):
            lambda_home, lambda_away, _, ou_model = _lambda_from_pm(home, away, pm_strengths)
            ah_line = _round_ah(-(lambda_home - lambda_away))
            if ou_line is None:
                ou_line = ou_model
            data_source = "Polymarket 實力評估"
        else:
            lambda_home, lambda_away, _, ou_model = _lambda_from_rankings(home, away)
            ah_line = _round_ah(-(lambda_home - lambda_away))
            if ou_line is None:
                ou_line = ou_model
            data_source = "FIFA排名（推算盤口）"

        # Bookmaker OU takes priority; fall back to model-derived line
        if ou_line is None:
            ou_line = _derive_ou_line(lambda_home, lambda_away)

        # For WC-form paths, lambdas are inflated by tuned league_avg (1.8).
        # ou_mult normalises them back to realistic goal totals for OU prob calculation.
        # Player data (alpha=0.4) blended into OU only — grid search: AH stays 52.4%, OU 60.4%→68.8%.
        _ou_mult = _load_tuned_params().get("ou_line_multiplier", 1.0)
        from src.player_strength import player_lambdas as _pl_lambdas, build_team_strengths as _build_ps
        _ps_strengths = _build_ps()
        _league_avg_val = _load_tuned_params().get("wc_league_avg", _WC_LEAGUE_AVG)
        lh_pl, la_pl = _pl_lambdas(home, away, _ps_strengths, league_avg=_league_avg_val)

        if lh_pl is not None and la_pl is not None:
            # Blend player per90 data into AH lambda (35%) — captures current squad form
            # Only when WC form data exists; ELO/PM paths already lack per-match context
            if data_source in ("WC 2026 實戰數據", "盤口線（h2h推算）", "DraftKings盤口"):
                _PLAYER_AH_ALPHA = 0.15  # grid search on 12 WC matches: 0-0.15 best
                lambda_home = round((1 - _PLAYER_AH_ALPHA) * lambda_home + _PLAYER_AH_ALPHA * lh_pl, 3)
                lambda_away = round((1 - _PLAYER_AH_ALPHA) * lambda_away + _PLAYER_AH_ALPHA * la_pl, 3)

            # Blend into OU lambda (40%) for all paths
            blended_h = (1 - _PLAYER_OU_ALPHA) * lambda_home + _PLAYER_OU_ALPHA * lh_pl
            blended_a = (1 - _PLAYER_OU_ALPHA) * lambda_away + _PLAYER_OU_ALPHA * la_pl
            ou_lambda_home = round(blended_h * _ou_mult, 3)
            ou_lambda_away = round(blended_a * _ou_mult, 3)
        else:
            ou_lambda_home = round(lambda_home * _ou_mult, 3)
            ou_lambda_away = round(lambda_away * _ou_mult, 3)

        if not ou_from_market:
            ou_line = _derive_ou_line(ou_lambda_home, ou_lambda_away)

        # Fix B: KO stage ELO floor — WC form can undervalue elite teams when
        # strong group-stage opponents compress lambda (e.g. England λ=0.74 due to
        # Mexico's low concede rate). One-directional floor: only pulls up, never down,
        # so Norway-type overperformers are unaffected.
        ko_elo_floor = tp.get("ko_elo_floor", 0.0)
        _ko_stages = {"LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "FINAL"}
        if ko_elo_floor > 0 and match.get("stage") in _ko_stages and data_source == "WC 2026 實戰數據":
            lh_elo, la_elo, _, _ = _lambda_from_rankings(home, away)
            lambda_home = max(lambda_home, round(lh_elo * ko_elo_floor, 3))
            lambda_away = max(lambda_away, round(la_elo * ko_elo_floor, 3))
            ou_lambda_home = max(ou_lambda_home, round(lh_elo * ko_elo_floor, 3))
            ou_lambda_away = max(ou_lambda_away, round(la_elo * ko_elo_floor, 3))

        # PM validation: compare derived AH against Polymarket-implied AH.
        # If AH comes from a market source (bookmaker h2h / native AH), only flag the gap.
        # If AH is model-derived (WC form / ELO / FIFA), adopt PM when gap >= 0.5.
        pm_ah_gap = None
        if pm_strengths and (home in pm_strengths or away in pm_strengths):
            lh_pm, la_pm, _, _ = _lambda_from_pm(home, away, pm_strengths)
            pm_ah = _round_ah(-(lh_pm - la_pm))
            gap = round(pm_ah - ah_line, 2)

            is_market_ah = data_source in ("盤口線（AH市場）", "盤口線（h2h推算）")
            if not is_market_ah and abs(gap) >= 0.5:
                # Model AH diverges from PM: trust PM (aggregates broader market intelligence)
                print(f"[features] PM校驗: {home} vs {away} AH {ah_line}→{pm_ah} (差距{gap:+.2f})")
                ah_line = pm_ah
                data_source = data_source + "＋PM校驗"
                gap = 0.0
            if abs(gap) >= 0.5:
                pm_ah_gap = gap  # positive = pm_ah > ah_line → PM values away more (match is closer)

        group_raw = match.get("group", "") or ""
        group = group_raw.replace("GROUP_", "") if group_raw.startswith("GROUP_") else group_raw
        group_ctx = _compute_group_context(home, away, group, match_date) if group else {}

        must_win_home = group_ctx.get("must_win_home", False)
        must_win_away = group_ctx.get("must_win_away", False)
        safe_draw_home = group_ctx.get("safe_draw_home", False)
        safe_draw_away = group_ctx.get("safe_draw_away", False)
        dead_rubber = group_ctx.get("dead_rubber", False)

        boost = calibration.get("incentive_boost", 0.15)
        damp = calibration.get("dead_rubber_damp", 0.08)
        if must_win_home:
            lambda_home *= (1 + boost)
        if must_win_away:
            lambda_away *= (1 + boost)
        if dead_rubber:
            lambda_home *= (1 - damp)
            lambda_away *= (1 - damp)

        # Knockout stage: teams play more defensively → scale down lambdas
        ko_stages = {"LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "FINAL"}
        if match.get("stage", "") in ko_stages:
            ko_scale = tp.get("knockout_lambda_scale", 1.0)
            lambda_home = round(lambda_home * ko_scale, 3)
            lambda_away = round(lambda_away * ko_scale, 3)

        # Venue: altitude and weather adjustments (R32/R16 only — venue mappings available)
        h_venue_m, a_venue_m = _venue_lambda_factors(home, away, match)
        if h_venue_m != 1.0 or a_venue_m != 1.0:
            lambda_home = round(lambda_home * h_venue_m, 3)
            lambda_away = round(lambda_away * a_venue_m, 3)
            ou_lambda_home = round(ou_lambda_home * h_venue_m, 3)
            ou_lambda_away = round(ou_lambda_away * a_venue_m, 3)

        # Injury/suspension multipliers: attack_mult reduces scorer's lambda;
        # defense_mult > 1 means weaker defense → opponent scores more.
        _inj = _load_injury_mults()
        h_inj = _inj.get(home, {})
        a_inj = _inj.get(away, {})
        h_atk = h_inj.get("attack_mult", 1.0)
        h_def = h_inj.get("defense_mult", 1.0)
        a_atk = a_inj.get("attack_mult", 1.0)
        a_def = a_inj.get("defense_mult", 1.0)
        if h_atk != 1.0 or a_def != 1.0:
            lambda_home = round(lambda_home * h_atk * a_def, 3)
            ou_lambda_home = round(ou_lambda_home * h_atk * a_def, 3)
        if a_atk != 1.0 or h_def != 1.0:
            lambda_away = round(lambda_away * a_atk * h_def, 3)
            ou_lambda_away = round(ou_lambda_away * a_atk * h_def, 3)

        incentive_home = compute_incentive_score(must_win_home, safe_draw_home, dead_rubber)
        incentive_away = compute_incentive_score(must_win_away, safe_draw_away, dead_rubber)
        incentive_score = max(incentive_home, incentive_away)

        formations = _load_formations()
        h_form_info = formations.get(home, {"formation": "4-4-2", "style": "balanced"})
        a_form_info = formations.get(away, {"formation": "4-4-2", "style": "balanced"})
        h_rest = _rest_days(home, match_date) if match_date else 999
        a_rest = _rest_days(away, match_date) if match_date else 999

        results.append({
            "match_id": match_id,
            "home_team": home,
            "away_team": away,
            "kickoff_utc": match.get("utcDate", ""),
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "ou_lambda_home": ou_lambda_home,
            "ou_lambda_away": ou_lambda_away,
            "ah_line": ah_line,
            "ou_line": ou_line,
            "sharp_signal": compute_sharp_signal(ah_line, ah_line),
            "incentive_score": round(incentive_score, 3),
            "must_win_home": must_win_home,
            "must_win_away": must_win_away,
            "safe_draw_home": safe_draw_home,
            "safe_draw_away": safe_draw_away,
            "dead_rubber": dead_rubber,
            "group_context": group_ctx,
            "data_source": data_source,
            "pm_ah_gap": pm_ah_gap,
            "formation_home": h_form_info.get("formation", "4-4-2"),
            "formation_away": a_form_info.get("formation", "4-4-2"),
            "style_home": h_form_info.get("style", "balanced"),
            "style_away": a_form_info.get("style", "balanced"),
            "rest_days_home": h_rest,
            "rest_days_away": a_rest,
            "stage": match.get("stage", "GROUP_STAGE"),
            "dk_ml_home": dk.get("ml_home"),
            "dk_ml_draw": dk.get("ml_draw"),
            "dk_ml_away": dk.get("ml_away"),
        })
    return results
