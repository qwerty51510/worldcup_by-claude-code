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


_KO_STAGES = {"LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "FINAL"}


def _score_params(league_avg: float, ah_mult: float, ko_scale: float = 1.0) -> float:
    """Walk-forward AH Brier for given (league_avg, ah_mult, ko_scale). Returns inf on error."""
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
        if match.get("stage", "") in _KO_STAGES:
            lh = round(lh * ko_scale, 3)
            la = round(la * ko_scale, 3)
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
            raw = (s[stat] + PRIOR * prior_rate) / (s["played"] + PRIOR) / league_avg
            if stat == "conceded":
                raw = max(0.40, raw)
            return raw

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


def tune_injury_scale(best_la: float, best_am: float) -> float:
    """
    Grid-search injury_scale against matches where injury adjustments were applied.
    Returns best scale (falls back to 1.0 if insufficient data).
    """
    from src.features import _round_ah
    results_path = DATA_DIR / "wc2026_results.json"
    if not results_path.exists():
        return 1.0

    results_by_key: dict = {}
    for m in json.loads(results_path.read_text()):
        results_by_key[(m["home"], m["away"])] = m

    # Collect injury-affected matches from saved predictions
    injury_matches = []
    for pred_path in sorted((DATA_DIR / "predictions").glob("*.json")):
        try:
            preds = json.loads(pred_path.read_text())
        except Exception:
            continue
        for p in preds:
            h_atk = p.get("injury_h_atk_base", 1.0)
            h_def = p.get("injury_h_def_base", 1.0)
            a_atk = p.get("injury_a_atk_base", 1.0)
            a_def = p.get("injury_a_def_base", 1.0)
            if h_atk == 1.0 and h_def == 1.0 and a_atk == 1.0 and a_def == 1.0:
                continue  # no injury adjustment — skip
            home = p.get("home_team", "")
            away = p.get("away_team", "")
            result = results_by_key.get((home, away))
            if result is None:
                continue
            injury_matches.append({
                "lh_base": p.get("lambda_home_base", p.get("lambda_home", 1.0)),
                "la_base": p.get("lambda_away_base", p.get("lambda_away", 1.0)),
                "h_atk": h_atk, "h_def": h_def,
                "a_atk": a_atk, "a_def": a_def,
                "home_goals": result["home_goals"],
                "away_goals": result["away_goals"],
            })

    if len(injury_matches) < 3:
        print(f"[tuner] 傷兵調校：樣本不足 ({len(injury_matches)} 場)，保持 injury_scale=1.0")
        return 1.0

    scales = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
    best_scale = 1.0
    best_brier = float("inf")

    for s in scales:
        briers = []
        for m in injury_matches:
            h_atk_s = 1.0 - (1.0 - m["h_atk"]) * s
            a_def_s = 1.0 - (1.0 - m["a_def"]) * s
            a_atk_s = 1.0 - (1.0 - m["a_atk"]) * s
            h_def_s = 1.0 - (1.0 - m["h_def"]) * s
            lh = max(0.3, m["lh_base"] * h_atk_s * a_def_s)
            la = max(0.3, m["la_base"] * a_atk_s * h_def_s)
            ah_line = _round_ah(-(lh - la) * best_am)
            hg, ag = m["home_goals"], m["away_goals"]
            if hg == ag:
                continue
            actual_ah = "home" if hg > ag else "away"
            ah_prob = min(0.95, max(0.05, _poisson_ah_prob(lh, la, ah_line)))
            outcome = 1.0 if (ah_prob > 0.5) == (actual_ah == "home") else 0.0
            briers.append((ah_prob - outcome) ** 2)
        if not briers:
            continue
        b = sum(briers) / len(briers)
        if b < best_brier:
            best_brier = b
            best_scale = s

    print(f"[tuner] 傷兵調校：{len(injury_matches)} 場，best injury_scale={best_scale} → Brier={round(best_brier, 4)}")
    return best_scale


def tune_params() -> dict:
    """
    Step 1: Grid search over wc_league_avg × ah_line_multiplier to minimise AH Brier.
    Step 2: Given best league_avg, grid search ou_line_multiplier to minimise OU Brier.
    Returns best params dict.
    """
    league_avgs = [1.3, 1.4, 1.51, 1.6, 1.7, 1.8]
    ah_mults = [0.22, 0.25, 0.28, 0.30, 0.33, 0.35, 0.38]
    ko_scales = [0.75, 0.80, 0.85, 0.90, 0.95, 1.0]
    combos = list(itertools.product(league_avgs, ah_mults, ko_scales))

    print(f"[tuner] AH grid search: {len(combos)} combinations...")
    best_ah_brier = float("inf")
    best_params: dict = {}

    for league_avg, ah_mult, ko_scale in combos:
        b = _score_params(league_avg, ah_mult, ko_scale)
        if b < best_ah_brier:
            best_ah_brier = b
            best_params = {
                "wc_league_avg": league_avg,
                "ah_line_multiplier": ah_mult,
                "knockout_lambda_scale": ko_scale,
                "ah_brier": round(b, 4),
            }

    print(
        f"[tuner] AH best: league_avg={best_params.get('wc_league_avg')}, "
        f"ah_mult={best_params.get('ah_line_multiplier')} → "
        f"AH Brier={best_params.get('ah_brier')}"
    )

    # Step 2: derive ou_line_multiplier analytically (not via Brier grid search).
    # Brier search is biased: inflated lines → always predict under → low Brier on small samples.
    # Instead: ou_mult = actual WC avg goals / league_avg, so OU lines center on reality.
    best_la = best_params["wc_league_avg"]
    best_am = best_params["ah_line_multiplier"]
    results_path = DATA_DIR / "wc2026_results.json"
    if results_path.exists():
        matches = json.loads(results_path.read_text())
        totals = [m["home_goals"] + m["away_goals"] for m in matches
                  if "home_goals" in m and "away_goals" in m]
        actual_avg = sum(totals) / len(totals) if totals else 1.51
    else:
        actual_avg = 1.51
    best_ou_mult = round(actual_avg / (2 * best_la), 3)
    best_ou_brier = _score_ou_params(best_la, best_am, best_ou_mult)
    print(
        f"[tuner] OU analytic: actual_avg={round(actual_avg, 3)}, "
        f"ou_mult={best_ou_mult} → OU Brier={round(best_ou_brier, 4)}"
    )
    best_params["ou_line_multiplier"] = best_ou_mult
    best_params["ou_brier"] = round(best_ou_brier, 4)

    # Step 3: tune injury_scale on matches where injury adjustments were applied
    best_params["injury_scale"] = tune_injury_scale(best_la, best_am)

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
