"""
Walk-forward validation on WC 2026 group stage.

For each match, we predict using ONLY data available BEFORE that match:
- Round 1: use pre-tournament FIFA rankings only
- Round 2: use Round 1 results + FIFA rankings (rolling form)
"""
import json
from pathlib import Path
from src.predict import _poisson_ah_prob, _poisson_ou_prob, _predict_score
from src.config import FIFA_RANKINGS, RANK_DECAY, AH_LINE_MULTIPLIER, DEFAULT_CALIBRATION

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_FILE = DATA_DIR / "wc2026_results.json"


def _lambda_for_match(home: str, away: str, completed_before: list,
                      match_date: str = "") -> tuple:
    """
    Walk-forward lambda — mirrors features.py logic exactly (formation + stamina).
    Only uses data available before this match (no future leakage).
    Returns (lambda_home, lambda_away, ah_line, ou_line, method).
    """
    from src.features import (
        _load_elo, _elo_to_strength, _WC_LEAGUE_AVG, _round_ah,
        _load_formations, _FORMATION_FACTORS, _stamina_factor, _derive_ou_line,
        _load_team_history, _load_tuned_params,
    )

    elo = _load_elo()
    team_history = _load_team_history()

    # Respect tuned params (updated by tuner after each validation run)
    tp = _load_tuned_params()
    league_avg = tp.get("wc_league_avg", _WC_LEAGUE_AVG)
    ah_mult = tp.get("ah_line_multiplier", AH_LINE_MULTIPLIER)
    ou_mult = tp.get("ou_line_multiplier", 1.0)

    PRIOR = 2.0

    stats: dict = {}
    for m in completed_before:
        for team, sc, cn in [
            (m["home"], m["home_goals"], m["away_goals"]),
            (m["away"], m["away_goals"], m["home_goals"]),
        ]:
            s = stats.setdefault(team, {"scored": 0, "conceded": 0, "played": 0})
            s["scored"] += sc
            s["conceded"] += cn
            s["played"] += 1

    def team_strength(team: str) -> float:
        if team in elo:
            return _elo_to_strength(elo[team])
        rank = FIFA_RANKINGS.get(team, 40)
        return 2.0 * (1.0 / (1.0 + (rank - 1) * RANK_DECAY))

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

    # Formation adjustment (same coefficients as features.py)
    formations = _load_formations()
    h_form = formations.get(home, {}).get("formation", "4-4-2")
    a_form = formations.get(away, {}).get("formation", "4-4-2")
    h_atk_m, h_def_m = _FORMATION_FACTORS.get(h_form, (1.0, 1.0))
    a_atk_m, a_def_m = _FORMATION_FACTORS.get(a_form, (1.0, 1.0))
    h_atk *= h_atk_m
    h_def *= h_def_m
    a_atk *= a_atk_m
    a_def *= a_def_m

    # Stamina / rest-days (use completed_before so no future data leaks)
    if match_date:
        from datetime import datetime as _dt

        def _days(team):
            past = [r["date"] for r in completed_before
                    if (r["home"] == team or r["away"] == team) and r["date"] < match_date]
            if not past:
                return 999
            last = max(past)
            return (_dt.strptime(match_date, "%Y-%m-%d") - _dt.strptime(last, "%Y-%m-%d")).days

        h_stam = _stamina_factor(_days(home))
        a_stam = _stamina_factor(_days(away))
        h_atk *= h_stam
        a_atk *= a_stam
        h_def *= (2.0 - h_stam)
        a_def *= (2.0 - a_stam)

    _HOST_NATIONS = {"United States", "Canada", "Mexico"}
    home_bonus = 0.10 if home in _HOST_NATIONS else 0.0
    lh = round(max(0.3, league_avg * h_atk * a_def + home_bonus), 3)
    la = round(max(0.3, league_avg * a_atk * h_def), 3)
    ah_line = _round_ah(-(lh - la) * ah_mult)
    ou_line = _derive_ou_line(lh * ou_mult, la * ou_mult)
    ou_lh = round(lh * ou_mult, 3)
    ou_la = round(la * ou_mult, 3)

    played_home = stats.get(home, {}).get("played", 0)
    played_away = stats.get(away, {}).get("played", 0)
    method = "ELO+WC實績" if (played_home + played_away) > 0 else "ELO基準"

    return lh, la, ah_line, ou_line, method, ou_lh, ou_la


def _predict_single(home: str, away: str, lh: float, la: float,
                    ah_line: float, ou_line: float, calibration: dict,
                    rho: float = 0.0, ou_lh: float = None, ou_la: float = None) -> dict:
    """Run Poisson prediction for one match. rho=0 → plain Poisson; rho<0 → Dixon-Coles."""
    ah_prob_home = _poisson_ah_prob(lh, la, ah_line, rho=rho)
    ah_prob_home = min(0.95, max(0.05, ah_prob_home))
    ah_pred = "home" if ah_prob_home > 0.5 else "away"
    ah_conf = min(100, max(0, int(abs(ah_prob_home - 0.5) * 200)))

    _ou_lh = ou_lh if ou_lh is not None else lh
    _ou_la = ou_la if ou_la is not None else la
    ou_prob_over = _poisson_ou_prob(_ou_lh, _ou_la, ou_line, rho=rho)
    ou_pred = "over" if ou_prob_over > 0.5 else "under"
    ou_conf = min(100, max(0, int(abs(ou_prob_over - 0.5) * 200)))

    score_info = _predict_score(lh, la)

    return {
        "home": home, "away": away,
        "ah_pred": ah_pred, "ah_conf": ah_conf, "ah_prob": round(ah_prob_home, 3),
        "ou_pred": ou_pred, "ou_conf": ou_conf, "ou_prob": round(ou_prob_over, 3),
        "lambda_home": lh, "lambda_away": la,
        "ah_line": ah_line, "ou_line": ou_line,
        "predicted_score": score_info["predicted_score"],
    }


def _actual_ah_result(match: dict):
    """Returns 'home'/'away' if decisive, None if draw (AH push — exclude from accuracy stats)."""
    hg, ag = match["home_goals"], match["away_goals"]
    if hg > ag:
        return "home"
    if ag > hg:
        return "away"
    return None  # draw = push on AH 0 line


def _actual_ou_result(match: dict, ou_line: float) -> str:
    total = match["home_goals"] + match["away_goals"]
    return "over" if total > ou_line else "under"


def run_validation(calibration: dict = None, rho: float = 0.0) -> dict:
    """Run walk-forward validation on all 40 completed WC 2026 matches."""
    if calibration is None:
        calibration = dict(DEFAULT_CALIBRATION)

    matches = json.loads(RESULTS_FILE.read_text())
    matches_by_date = sorted(matches, key=lambda m: m["date"])

    results = []
    completed = []  # matches completed before current prediction

    for match in matches_by_date:
        lh, la, ah_line, ou_line, method, ou_lh, ou_la = _lambda_for_match(
            match["home"], match["away"], completed, match_date=match["date"]
        )
        pred = _predict_single(match["home"], match["away"], lh, la, ah_line, ou_line, calibration, rho=rho,
                               ou_lh=ou_lh, ou_la=ou_la)
        actual_ah = _actual_ah_result(match)  # None if draw (push)
        actual_ou = _actual_ou_result(match, ou_line)

        # AH: None means push — exclude from accuracy but record the fact
        ah_is_push = actual_ah is None
        ah_correct = (not ah_is_push) and (pred["ah_pred"] == actual_ah)
        ah_brier = None if ah_is_push else round((pred["ah_prob"] - (1.0 if (pred["ah_pred"] == actual_ah) else 0.0)) ** 2, 3)

        ou_correct = pred["ou_pred"] == actual_ou
        ou_brier = round(((1 - pred["ou_prob"]) - (1.0 if ou_correct else 0.0)) ** 2, 3)

        results.append({
            "date": match["date"], "group": match["group"], "round": match["round"],
            "home": match["home"], "away": match["away"],
            "predicted_score": pred["predicted_score"],
            "score": "%d-%d" % (match["home_goals"], match["away_goals"]),
            "lambda_home": lh, "lambda_away": la,
            "ah_line": ah_line, "ou_line": ou_line,
            "ah_pred": pred["ah_pred"], "ah_prob": pred["ah_prob"],
            "actual_ah": actual_ah, "ah_is_push": ah_is_push,
            "ah_correct": ah_correct, "ah_brier": ah_brier,
            "ou_pred": pred["ou_pred"], "ou_prob": pred["ou_prob"],
            "actual_ou": actual_ou, "ou_correct": ou_correct, "ou_brier": round(ou_brier, 3),
            "method": method,
        })
        completed.append(match)

    # AH accuracy: exclude push (draw) matches — in real AH they are refunded
    decisive = [r for r in results if not r["ah_is_push"]]
    pushes = [r for r in results if r["ah_is_push"]]
    ah_acc = sum(r["ah_correct"] for r in decisive) / len(decisive) if decisive else 0
    ou_acc = sum(r["ou_correct"] for r in results) / len(results)
    ah_briers = [r["ah_brier"] for r in decisive if r["ah_brier"] is not None]
    avg_ah_brier = sum(ah_briers) / len(ah_briers) if ah_briers else 0
    avg_ou_brier = sum(r["ou_brier"] for r in results) / len(results)

    def _round_stats(subset):
        dec = [r for r in subset if not r["ah_is_push"]]
        return {
            "matches": len(subset),
            "decisive_matches": len(dec),
            "push_matches": len(subset) - len(dec),
            "ah_accuracy": round(sum(r["ah_correct"] for r in dec) / len(dec), 3) if dec else 0,
            "ou_accuracy": round(sum(r["ou_correct"] for r in subset) / len(subset), 3) if subset else 0,
        }

    r1 = [r for r in results if r["round"] == 1]
    r2 = [r for r in results if r["round"] == 2]

    return {
        "total_matches": len(results),
        "decisive_matches": len(decisive),
        "push_matches": len(pushes),
        "ah_accuracy": round(ah_acc, 3),
        "ou_accuracy": round(ou_acc, 3),
        "ah_brier": round(avg_ah_brier, 3),
        "ou_brier": round(avg_ou_brier, 3),
        "round1": _round_stats(r1),
        "round2": _round_stats(r2),
        "failures": [r for r in decisive if not r["ah_correct"]],
        "pushes": pushes,
        "all_results": results,
    }


def print_report(report: dict) -> None:
    print(f"\n{'='*60}")
    print(f"  WC 2026 Walk-Forward 驗證報告（共 {report['total_matches']} 場）")
    print(f"  其中決出勝負：{report['decisive_matches']} 場  平局（push）：{report['push_matches']} 場")
    print(f"{'='*60}")
    print(f"  讓球盤準確率：{report['ah_accuracy']*100:.1f}%（排除 push）  Brier={report['ah_brier']:.3f}")
    print(f"  大小球準確率：{report['ou_accuracy']*100:.1f}%  Brier={report['ou_brier']:.3f}")
    r1, r2 = report["round1"], report["round2"]
    print(f"\n  第 1 輪（純 FIFA 排名）：AH={r1['ah_accuracy']*100:.1f}%（決勝 {r1['decisive_matches']}場/push {r1['push_matches']}場）  OU={r1['ou_accuracy']*100:.1f}%")
    print(f"  第 2 輪（+WC 實績加權）：AH={r2['ah_accuracy']*100:.1f}%（決勝 {r2['decisive_matches']}場/push {r2['push_matches']}場）  OU={r2['ou_accuracy']*100:.1f}%")
    print(f"\n{'─'*60}")
    print(f"  失準比賽（讓球盤預測錯誤，共 {len(report['failures'])} 場）：")
    for r in report["failures"]:
        print(f"  [{r['date']} 組{r['group']}] {r['home']} vs {r['away']}  {r['score']}")
        print(f"    AH線={r['ah_line']}  預測={r['ah_pred']}({r['ah_prob']*100:.0f}%)  實際={r['actual_ah']}")
    if report["pushes"]:
        print(f"\n  平局場次（push，共 {len(report['pushes'])} 場）：")
        for r in report["pushes"]:
            print(f"  [{r['date']} 組{r['group']}] {r['home']} vs {r['away']}  {r['score']}  AH線={r['ah_line']}")
    print(f"{'='*60}\n")


def save_validation(report: dict) -> None:
    out = DATA_DIR / "backtest" / "wc2026_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"[validate] 詳細結果已存至 {out}")


def refresh_validation() -> dict:
    """Run walk-forward validation, save results, re-run postmortem + model comparison."""
    report = run_validation()
    save_validation(report)
    from src.backtest import run_rich_postmortem, save_postmortem
    save_postmortem(run_rich_postmortem(report))
    compare_models(save=True)
    return report


def compare_models(rho_values: list = None, save: bool = True) -> dict:
    """
    A/B test: run walk-forward validation for plain Poisson (ρ=0) and DC variants.
    Saves results to data/backtest/model_comparison.json when save=True.
    Returns the comparison dict.
    """
    from datetime import datetime as _dt
    if rho_values is None:
        rho_values = [-0.05, -0.10, -0.13, -0.18]

    configs = [("plain_poisson", 0.0)] + [("dc_rho_%.2f" % r, r) for r in rho_values]
    rows = []
    for label, rho in configs:
        r = run_validation(rho=rho)
        rows.append({
            "label": label, "rho": rho,
            "ah_accuracy": round(r["ah_accuracy"], 4),
            "ou_accuracy": round(r["ou_accuracy"], 4),
            "ah_brier": round(r["ah_brier"], 4),
            "ou_brier": round(r["ou_brier"], 4),
            "total_matches": r["total_matches"],
        })

    base = rows[0]
    best_ah = max(rows, key=lambda x: x["ah_accuracy"])
    best_ou = max(rows, key=lambda x: x["ou_accuracy"])

    result = {
        "updated_at": _dt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_matches": base["total_matches"],
        "current_model": "plain_poisson",
        "current_ah_accuracy": base["ah_accuracy"],
        "current_ou_accuracy": base["ou_accuracy"],
        "best_ah_model": best_ah["label"],
        "best_ah_accuracy": best_ah["ah_accuracy"],
        "best_ou_model": best_ou["label"],
        "best_ou_accuracy": best_ou["ou_accuracy"],
        "adopt_dc_rho": None,  # filled below
        "rows": rows,
    }

    # Recommend adoption if any DC rho beats current by ≥2%
    for row in rows[1:]:
        d_ah = row["ah_accuracy"] - base["ah_accuracy"]
        d_ou = row["ou_accuracy"] - base["ou_accuracy"]
        if d_ah >= 0.02 or d_ou >= 0.02:
            result["adopt_dc_rho"] = row["rho"]
            break

    if save:
        out = DATA_DIR / "backtest" / "model_comparison.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print("[compare_models] 結果已存至 %s" % out)

    # Print summary
    print("\n%s" % ("=" * 72))
    print("  模型對比：Plain Poisson vs Dixon-Coles (%d 場回測)" % base["total_matches"])
    print("=" * 72)
    print("  %-26s  %6s  %6s  %7s  %7s" % ("版本", "AH準確", "OU準確", "AH Brier", "OU Brier"))
    print("  " + "-" * 66)
    for row in rows:
        ah_m = " ◀" if row["label"] == best_ah["label"] else ""
        ou_m = " ◀" if row["label"] == best_ou["label"] else ""
        print("  %-26s  %5.1f%%  %5.1f%%  %7.3f  %7.3f%s%s" % (
            row["label"], row["ah_accuracy"]*100, row["ou_accuracy"]*100,
            row["ah_brier"], row["ou_brier"], ah_m, ou_m))
    print("=" * 72)
    if result["adopt_dc_rho"] is not None:
        print("  ⚡ 建議採用 ρ=%.2f（AH 或 OU 改善 ≥2%%）" % result["adopt_dc_rho"])
    else:
        print("  ✓ 維持現有模型（無 DC 版本改善 ≥2%%）")
    print()
    return result


if __name__ == "__main__":
    import sys
    if "--compare" in sys.argv:
        compare_models(save=True)
    else:
        from src.backtest import run_rich_postmortem, save_postmortem
        report = run_validation()
        print_report(report)
        save_validation(report)
        save_postmortem(run_rich_postmortem(report))
        compare_models(save=True)
