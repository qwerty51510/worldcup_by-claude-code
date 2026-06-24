"""
Walk-forward parameter tuning.
Grid-searches wc_league_avg and ah_line_multiplier to minimise AH Brier score.
Then searches ou_line_multiplier to minimise OU Brier (given best league_avg).
Saves best params to data/tuning.json; features.py loads them on the next prediction run.
"""
import itertools
import json
import math
from pathlib import Path

from src.predict import _poisson_ah_prob, _poisson_ou_prob

DATA_DIR = Path(__file__).parent.parent / "data"


def _score_params(league_avg: float, ah_mult: float) -> float:
    """Walk-forward AH Brier for given (league_avg, ah_mult). Returns inf on error."""
    from src.features import (
        _load_elo, _elo_to_strength, _round_ah, _load_formations,
        _FORMATION_FACTORS, _stamina_factor, _derive_ou_line, _load_team_history,
    )
    from src.config import FIFA_RANKINGS, RANK_DECAY

    results_path = DATA_DIR / "wc2026_results.json"
    if not results_path.exists():
        return float("inf")

    matches = sorted(json.loads(results_path.read_text()), key=lambda m: m["date"])
    elo = _load_elo()
    formations = _load_formations()
    team_history = _load_team_history()
    PRIOR = 2.0

    def team_strength(team: str) -> float:
        if team in elo:
            return _elo_to_strength(elo[team])
        rank = FIFA_RANKINGS.get(team, 40)
        return 2.0 * (1.0 / (1.0 + (rank - 1) * RANK_DECAY))

    briers: list = []
    completed: list = []

    for match in matches:
        home, away = match["home"], match["away"]

        # Build rolling stats from completed matches only (no future leakage)
        stats: dict = {}
        for m in completed:
            for team, sc, cn in [
                (m["home"], m["home_goals"], m["away_goals"]),
                (m["away"], m["away_goals"], m["home_goals"]),
            ]:
                s = stats.setdefault(team, {"scored": 0, "conceded": 0, "played": 0})
                s["scored"] += sc
                s["conceded"] += cn
                s["played"] += 1

        _H2H_AVG = 1.31  # avg goals/match in H2H dataset (2022-2026)

        def smooth_rate(team: str, stat: str) -> float:
            s = stats.get(team, {"scored": 0, "conceded": 0, "played": 0})
            strength = team_strength(team)
            elo_prior = (strength if stat == "scored" else 1.0 / strength) * league_avg
            h = team_history.get(team, {"scored": 0, "conceded": 0, "played": 0})
            if h["played"] >= 3:
                hist_strength = (h[stat] / h["played"]) / _H2H_AVG
                hist_prior = hist_strength * league_avg
                blend = min(h["played"] / 10.0, 0.5)
                prior_rate = elo_prior * (1 - blend) + hist_prior * blend
            else:
                prior_rate = elo_prior
            return (s[stat] + PRIOR * prior_rate) / (s["played"] + PRIOR) / league_avg

        h_atk = smooth_rate(home, "scored")
        h_def = smooth_rate(home, "conceded")
        a_atk = smooth_rate(away, "scored")
        a_def = smooth_rate(away, "conceded")

        h_form = formations.get(home, {}).get("formation", "4-4-2")
        a_form = formations.get(away, {}).get("formation", "4-4-2")
        h_atk_m, h_def_m = _FORMATION_FACTORS.get(h_form, (1.0, 1.0))
        a_atk_m, a_def_m = _FORMATION_FACTORS.get(a_form, (1.0, 1.0))
        h_atk *= h_atk_m; h_def *= h_def_m
        a_atk *= a_atk_m; a_def *= a_def_m

        if match["date"]:
            from datetime import datetime as _dt

            def _days(team):
                past = [r["date"] for r in completed
                        if (r["home"] == team or r["away"] == team)
                        and r["date"] < match["date"]]
                if not past:
                    return 999
                return (_dt.strptime(match["date"], "%Y-%m-%d")
                        - _dt.strptime(max(past), "%Y-%m-%d")).days

            h_stam = _stamina_factor(_days(home))
            a_stam = _stamina_factor(_days(away))
            h_atk *= h_stam; a_atk *= a_stam
            h_def *= (2.0 - h_stam); a_def *= (2.0 - a_stam)

        _HOST_NATIONS = {"United States", "Canada", "Mexico"}
        home_bonus = 0.10 if home in _HOST_NATIONS else 0.0
        lh = max(0.3, league_avg * h_atk * a_def + home_bonus)
        la = max(0.3, league_avg * a_atk * h_def)
        ah_line = _round_ah(-(lh - la) * ah_mult)

        hg, ag = match["home_goals"], match["away_goals"]
        completed.append(match)
        if hg == ag:  # push — exclude from AH accuracy
            continue

        actual_ah = "home" if hg > ag else "away"
        ah_prob = min(0.95, max(0.05, _poisson_ah_prob(lh, la, ah_line)))
        outcome = 1.0 if (ah_prob > 0.5) == (actual_ah == "home") else 0.0
        briers.append((ah_prob - outcome) ** 2)

    return sum(briers) / len(briers) if briers else float("inf")


def _score_ou_params(league_avg: float, ah_mult: float, ou_mult: float) -> float:
    """Walk-forward OU Brier for given (league_avg, ah_mult, ou_mult). Returns inf on error."""
    from src.features import (
        _load_elo, _elo_to_strength, _round_ah, _load_formations,
        _FORMATION_FACTORS, _stamina_factor, _derive_ou_line, _load_team_history,
    )
    from src.config import FIFA_RANKINGS, RANK_DECAY

    results_path = DATA_DIR / "wc2026_results.json"
    if not results_path.exists():
        return float("inf")

    matches = sorted(json.loads(results_path.read_text()), key=lambda m: m["date"])
    elo = _load_elo()
    formations = _load_formations()
    team_history = _load_team_history()
    PRIOR = 2.0

    def team_strength(team: str) -> float:
        if team in elo:
            return _elo_to_strength(elo[team])
        rank = FIFA_RANKINGS.get(team, 40)
        return 2.0 * (1.0 / (1.0 + (rank - 1) * RANK_DECAY))

    briers: list = []
    completed: list = []

    for match in matches:
        home, away = match["home"], match["away"]

        stats: dict = {}
        for m in completed:
            for team, sc, cn in [
                (m["home"], m["home_goals"], m["away_goals"]),
                (m["away"], m["away_goals"], m["home_goals"]),
            ]:
                s = stats.setdefault(team, {"scored": 0, "conceded": 0, "played": 0})
                s["scored"] += sc
                s["conceded"] += cn
                s["played"] += 1

        _H2H_AVG = 1.31

        def smooth_rate(team: str, stat: str) -> float:
            s = stats.get(team, {"scored": 0, "conceded": 0, "played": 0})
            strength = team_strength(team)
            elo_prior = (strength if stat == "scored" else 1.0 / strength) * league_avg
            h = team_history.get(team, {"scored": 0, "conceded": 0, "played": 0})
            if h["played"] >= 3:
                hist_strength = (h[stat] / h["played"]) / _H2H_AVG
                hist_prior = hist_strength * league_avg
                blend = min(h["played"] / 10.0, 0.5)
                prior_rate = elo_prior * (1 - blend) + hist_prior * blend
            else:
                prior_rate = elo_prior
            return (s[stat] + PRIOR * prior_rate) / (s["played"] + PRIOR) / league_avg

        h_atk = smooth_rate(home, "scored")
        h_def = smooth_rate(home, "conceded")
        a_atk = smooth_rate(away, "scored")
        a_def = smooth_rate(away, "conceded")

        h_form = formations.get(home, {}).get("formation", "4-4-2")
        a_form = formations.get(away, {}).get("formation", "4-4-2")
        h_atk_m, h_def_m = _FORMATION_FACTORS.get(h_form, (1.0, 1.0))
        a_atk_m, a_def_m = _FORMATION_FACTORS.get(a_form, (1.0, 1.0))
        h_atk *= h_atk_m; h_def *= h_def_m
        a_atk *= a_atk_m; a_def *= a_def_m

        if match["date"]:
            from datetime import datetime as _dt

            def _days(team):
                past = [r["date"] for r in completed
                        if (r["home"] == team or r["away"] == team)
                        and r["date"] < match["date"]]
                if not past:
                    return 999
                return (_dt.strptime(match["date"], "%Y-%m-%d")
                        - _dt.strptime(max(past), "%Y-%m-%d")).days

            h_stam = _stamina_factor(_days(home))
            a_stam = _stamina_factor(_days(away))
            h_atk *= h_stam; a_atk *= a_stam
            h_def *= (2.0 - h_stam); a_def *= (2.0 - a_stam)

        _HOST_NATIONS = {"United States", "Canada", "Mexico"}
        home_bonus = 0.10 if home in _HOST_NATIONS else 0.0
        lh = max(0.3, league_avg * h_atk * a_def + home_bonus)
        la = max(0.3, league_avg * a_atk * h_def)

        ou_lh = lh * ou_mult
        ou_la = la * ou_mult
        ou_line = _derive_ou_line(ou_lh, ou_la)

        hg, ag = match["home_goals"], match["away_goals"]
        completed.append(match)
        total = hg + ag
        if total == ou_line:
            continue  # push — exclude from OU accuracy

        actual_ou_over = total > ou_line
        ou_prob = min(0.95, max(0.05, _poisson_ou_prob(ou_lh, ou_la, ou_line)))
        outcome = 1.0 if actual_ou_over else 0.0
        briers.append((ou_prob - outcome) ** 2)

    return sum(briers) / len(briers) if briers else float("inf")


def tune_params() -> dict:
    """
    Step 1: Grid search over wc_league_avg × ah_line_multiplier to minimise AH Brier.
    Step 2: Given best league_avg, grid search ou_line_multiplier to minimise OU Brier.
    Returns best params dict.
    """
    league_avgs = [1.3, 1.4, 1.51, 1.6, 1.7, 1.8]
    ah_mults = [0.22, 0.25, 0.28, 0.30, 0.33, 0.35, 0.38]
    combos = list(itertools.product(league_avgs, ah_mults))

    print(f"[tuner] AH grid search: {len(combos)} combinations...")
    best_ah_brier = float("inf")
    best_params: dict = {}

    for league_avg, ah_mult in combos:
        b = _score_params(league_avg, ah_mult)
        if b < best_ah_brier:
            best_ah_brier = b
            best_params = {
                "wc_league_avg": league_avg,
                "ah_line_multiplier": ah_mult,
                "ah_brier": round(b, 4),
            }

    print(
        f"[tuner] AH best: league_avg={best_params.get('wc_league_avg')}, "
        f"ah_mult={best_params.get('ah_line_multiplier')} → "
        f"AH Brier={best_params.get('ah_brier')}"
    )

    # Step 2: tune ou_line_multiplier for OU Brier (given best league_avg)
    best_la = best_params["wc_league_avg"]
    best_am = best_params["ah_line_multiplier"]
    ou_mults = [0.60, 0.65, 0.70, 0.75, 0.80, 0.84, 0.88, 0.92, 1.0]
    print(f"[tuner] OU grid search: {len(ou_mults)} ou_mults (league_avg={best_la})...")
    best_ou_brier = float("inf")
    best_ou_mult = 0.84  # sensible default: 1.51/1.8

    for ou_mult in ou_mults:
        b = _score_ou_params(best_la, best_am, ou_mult)
        if b < best_ou_brier:
            best_ou_brier = b
            best_ou_mult = ou_mult

    print(f"[tuner] OU best: ou_mult={best_ou_mult} → OU Brier={round(best_ou_brier, 4)}")
    best_params["ou_line_multiplier"] = best_ou_mult
    best_params["ou_brier"] = round(best_ou_brier, 4)

    return best_params


def save_tuned_params(params: dict) -> None:
    path = DATA_DIR / "tuning.json"
    path.write_text(json.dumps(params, ensure_ascii=False, indent=2))
    print(f"[tuner] 調校參數已儲存至 {path}")


def load_tuned_params() -> dict:
    path = DATA_DIR / "tuning.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}
