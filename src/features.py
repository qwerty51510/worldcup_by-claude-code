import json
import math
from datetime import datetime
from pathlib import Path
from src.config import FIFA_RANKINGS, BASE_LAMBDA, RANK_DECAY, AH_LINE_MULTIPLIER

# Log-linear mapping: P(win WC) → strength in range [0.5, 2.0]
# Calibrated so France(19.75%) → 2.0, Qatar(0.05%) → 0.5
_PM_LOG_A = 2.406
_PM_LOG_B = 0.2508

# ELO → strength: normalised around 1500 (average), compressed to 0.4–2.2 range
_ELO_BASE = 1500.0
_ELO_SCALE = 750.0  # 750 ELO points → 2x strength

_ELO_RATINGS: dict = {}
_WC_TEAM_STATS: dict = {}  # computed once from wc2026_results.json
_WC_RESULTS: list = []     # full results list for rest-days calculation
_FORMATIONS: dict = {}
_TEAM_HISTORY: dict = {}   # pre-tournament stats from team_history.json
_TUNED_PARAMS: dict = {}   # params from tuner (wc_league_avg, ah_line_multiplier)     # team formation + style

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
    stats: dict = {}
    for m in _load_wc_results():
        for team, scored, conceded in [
            (m["home"], m["home_goals"], m["away_goals"]),
            (m["away"], m["away_goals"], m["home_goals"]),
        ]:
            s = stats.setdefault(team, {"scored": 0, "conceded": 0, "played": 0})
            s["scored"] += scored
            s["conceded"] += conceded
            s["played"] += 1
    _WC_TEAM_STATS = stats
    return stats


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


def clear_caches() -> None:
    """Reset in-memory caches after wc2026_results.json is updated."""
    global _WC_TEAM_STATS, _WC_RESULTS, _TUNED_PARAMS
    _WC_TEAM_STATS = {}
    _WC_RESULTS = []
    _TUNED_PARAMS = {}  # force reload of tuned params on next prediction


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
    return max(1.5, round((lh + la) * 2) / 2)


def compute_incentive_score(must_win: bool, safe_draw: bool, dead_rubber: bool) -> float:
    if dead_rubber:
        return 0.2
    if must_win:
        return 0.85
    if safe_draw:
        return 0.45
    return 0.6


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
    stats = _load_wc_team_stats() if prior_results is None else _build_stats(prior_results)
    elo = _load_elo()
    team_history = _load_team_history()

    # Load tuned params; fall back to config constants
    tp = _load_tuned_params()
    league_avg = tp.get("wc_league_avg", _WC_LEAGUE_AVG)
    ah_mult = tp.get("ah_line_multiplier", AH_LINE_MULTIPLIER)

    PRIOR = 2.0

    def team_strength(team: str) -> float:
        if team in elo:
            return _elo_to_strength(elo[team])
        return _rank_to_strength(FIFA_RANKINGS.get(team, 40))

    # Average G/match in our H2H dataset (2022-2026 international matches)
    # Used to normalize historical rates to WC-level context
    _H2H_AVG = 1.31

    def smooth_rate(team: str, stat: str) -> float:
        s = stats.get(team, {"scored": 0, "conceded": 0, "played": 0})
        strength = team_strength(team)
        elo_prior = (strength if stat == "scored" else 1.0 / strength) * league_avg

        # Blend ELO prior with pre-tournament historical rate (if available).
        # Normalize hist_rate by H2H dataset avg first so the blend stays in
        # WC-context units (avoids pulling prior toward the lower H2H average).
        h = team_history.get(team, {"scored": 0, "conceded": 0, "played": 0})
        if h["played"] >= 3:
            hist_strength = (h[stat] / h["played"]) / _H2H_AVG  # relative to H2H avg
            hist_prior = hist_strength * league_avg               # scaled to WC context
            blend = min(h["played"] / 10.0, 0.5)
            prior_rate = elo_prior * (1 - blend) + hist_prior * blend
        else:
            prior_rate = elo_prior

        return (s[stat] + PRIOR * prior_rate) / (s["played"] + PRIOR) / league_avg

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
    return lh, la, ah_line, _derive_ou_line(lh, la)


def _build_stats(results: list) -> dict:
    stats: dict = {}
    for m in results:
        for team, scored, conceded in [
            (m["home"], m["home_goals"], m["away_goals"]),
            (m["away"], m["away_goals"], m["home_goals"]),
        ]:
            s = stats.setdefault(team, {"scored": 0, "conceded": 0, "played": 0})
            s["scored"] += scored
            s["conceded"] += conceded
            s["played"] += 1
    return stats


def _ah_from_1x2(p_home: float, p_away: float, ou_line: float) -> float:
    """
    Derive implied AH line from 1X2 win probabilities + OU totals line.
    Standard betting-market technique: strength ratio from win probs × total goals.
    Exponent 0.7 calibrated against WC historical data.
    """
    if p_home <= 0 or p_away <= 0 or ou_line is None:
        return 0.0
    r = max(0.05, min(50.0, (p_home / p_away) ** 0.7))
    S = max(1.5, ou_line)
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
            if market["key"] == "totals":
                for outcome in market.get("outcomes", []):
                    if outcome.get("point") is not None:
                        try:
                            ou_line = float(outcome["point"])
                            break
                        except (TypeError, ValueError):
                            pass
            if market["key"] == "h2h":
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

    # Derive AH from h2h + totals when asian_handicap market unavailable
    if ou_line is not None and h2h_prices:
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
            derived_ah = _ah_from_1x2(p_home_raw / total, p_away_raw / total, ou_line)
            print(f"[features] h2h→AH: {home_team}({ph_raw}) vs {away_team}({pa_raw}) OU={ou_line} → {derived_ah}")
            return derived_ah, ou_line, False

    return None, ou_line, False


def _lambda_from_ah_line(ah_line: float) -> tuple:
    home_base = 1.3 - (ah_line * 0.25)
    away_base = 1.3 + (ah_line * 0.25)
    return max(0.5, home_base), max(0.3, away_base)


def build_features(matches: list, odds: dict, calibration: dict, pm_strengths: dict = None) -> list:
    if pm_strengths is None:
        pm_strengths = {}
    results = []
    for match in matches:
        match_id = str(match.get("id", ""))
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]

        odds_entry = None
        for entry in odds.values():
            if entry.get("home_team") == home and entry.get("away_team") == away:
                odds_entry = entry
                break

        bookmakers = odds_entry.get("bookmakers", []) if odds_entry else []
        odds_home = odds_entry.get("home_team", home) if odds_entry else home
        odds_away = odds_entry.get("away_team", away) if odds_entry else away
        ah_line, ou_line, ah_is_native = _extract_ah_ou(bookmakers, odds_home, odds_away)

        match_date = (match.get("utcDate", "") or "")[:10]
        elo = _load_elo()
        wc_form = _lambda_from_wc_form(home, away, match_date)

        if ah_is_native:
            # Native asian_handicap market: use market-implied lambdas + market AH line
            lambda_home, lambda_away = _lambda_from_ah_line(ah_line)
            data_source = "盤口線（AH市場）"
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

        # PM-implied AH line for comparison (detect large discrepancies)
        pm_ah_gap = None
        if pm_strengths and (home in pm_strengths or away in pm_strengths):
            lh_pm, la_pm, _, _ = _lambda_from_pm(home, away, pm_strengths)
            pm_ah = _round_ah(-(lh_pm - la_pm))
            gap = round(pm_ah - ah_line, 2)
            if abs(gap) >= 0.75:
                pm_ah_gap = gap  # positive = PM implies home stronger than our line

        must_win_home = False
        must_win_away = False
        safe_draw = False
        dead_rubber = False

        incentive_home = compute_incentive_score(must_win_home, safe_draw, dead_rubber)
        incentive_away = compute_incentive_score(must_win_away, safe_draw, dead_rubber)
        incentive_score = max(incentive_home, incentive_away)

        boost = calibration.get("incentive_boost", 0.15)
        if must_win_home:
            lambda_home *= (1 + boost)
        if must_win_away:
            lambda_away *= (1 + boost)

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
            "ah_line": ah_line,
            "ou_line": ou_line,
            "sharp_signal": compute_sharp_signal(ah_line, ah_line),
            "incentive_score": round(incentive_score, 3),
            "must_win_home": must_win_home,
            "must_win_away": must_win_away,
            "data_source": data_source,
            "pm_ah_gap": pm_ah_gap,
            "formation_home": h_form_info.get("formation", "4-4-2"),
            "formation_away": a_form_info.get("formation", "4-4-2"),
            "style_home": h_form_info.get("style", "balanced"),
            "style_away": a_form_info.get("style", "balanced"),
            "rest_days_home": h_rest,
            "rest_days_away": a_rest,
        })
    return results
