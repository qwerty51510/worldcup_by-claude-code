"""
injury_validator.py — 賽後傷兵乘數驗證

用法：
  python3 -m src.injury_validator
  python3 -m src.injury_validator --match "Switzerland vs Colombia"

比對 data/backtest/injury_validation_log.json 中的賽前預測
與 data/wc2026_results.json 中的實際比分，
輸出每個情境的準確度，並推送 Telegram 摘要。
"""
import argparse
import json
import math
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "data"


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(min(k, 20))


def log_loss(p_correct: float) -> float:
    return -math.log(max(1e-6, min(1 - 1e-6, p_correct)))


def validate_all(match_filter: str = "") -> None:
    log_path = DATA_DIR / "backtest" / "injury_validation_log.json"
    results_path = DATA_DIR / "wc2026_results.json"

    if not log_path.exists():
        print("[validator] No injury_validation_log.json found")
        return
    if not results_path.exists():
        print("[validator] No wc2026_results.json found")
        return

    entries = json.loads(log_path.read_text())
    results = json.loads(results_path.read_text())

    results_by_key = {}
    for r in results:
        results_by_key[(r["home"], r["away"])] = r

    updated = []
    summary_lines = []

    for entry in entries:
        match_label = entry.get("match", "")
        if match_filter and match_filter.lower() not in match_label.lower():
            updated.append(entry)
            continue

        # Already validated
        if entry.get("result") is not None:
            updated.append(entry)
            continue

        # Try to find result
        home, away = match_label.split(" vs ", 1) if " vs " in match_label else ("", "")
        result = results_by_key.get((home, away))
        if result is None:
            print(f"[validator] No result yet for {match_label}")
            updated.append(entry)
            continue

        hg = result["home_goals"]
        ag = result["away_goals"]
        entry["result"] = {"home_goals": hg, "away_goals": ag}

        # Determine actual outcome
        if hg > ag:
            actual_winner = "home"
        elif ag > hg:
            actual_winner = "away"
        else:
            actual_winner = "draw_90min"

        # Evaluate each scenario
        scenario_evals = {}
        for s_name, s_data in entry.get("scenarios", {}).items():
            lh = s_data["lh"]
            la = s_data["la"]

            # Compute predicted prob for each outcome (90min)
            p_h = p_d = p_a = 0.0
            for h in range(11):
                for a in range(11):
                    p = _poisson_pmf(h, lh) * _poisson_pmf(a, la)
                    if h > a:
                        p_h += p
                    elif h == a:
                        p_d += p
                    else:
                        p_a += p

            if actual_winner == "home":
                p_correct = p_h
                direction_ok = p_h > 0.5
            elif actual_winner == "away":
                p_correct = p_a
                direction_ok = p_a > 0.5
            else:
                p_correct = p_d
                direction_ok = p_d > p_h and p_d > p_a

            brier = (p_correct - 1.0) ** 2
            scenario_evals[s_name] = {
                "p_home_90": round(p_h, 3),
                "p_draw_90": round(p_d, 3),
                "p_away_90": round(p_a, 3),
                "p_correct_outcome": round(p_correct, 3),
                "brier": round(brier, 4),
                "direction_correct": direction_ok,
            }

        entry["scenario_evals"] = scenario_evals
        entry["actual_result"] = f"{home} {hg}-{ag} {away}"

        # Determine verdict on injury_scale
        # Compare scenario C (current model with all injuries) vs scenario A (minimal injuries)
        brier_A = scenario_evals.get("A", {}).get("brier", 1.0)
        brier_C = scenario_evals.get("C", {}).get("brier", 1.0)
        if brier_C < brier_A:
            verdict = f"more_injuries_better (C Brier {brier_C} < A Brier {brier_A})"
        elif brier_A < brier_C:
            verdict = f"fewer_injuries_better (A Brier {brier_A} < C Brier {brier_C})"
        else:
            verdict = "neutral"
        entry["injury_scale_verdict"] = verdict

        summary_lines.append(
            f"✅ <b>{match_label}</b>  {hg}:{ag}\n"
            f"   情境A(輕) Brier={brier_A} | 情境C(當前) Brier={brier_C}\n"
            f"   裁定：{verdict}"
        )

        print(f"[validator] {match_label}: {hg}-{ag}")
        for s_name, ev in scenario_evals.items():
            print(f"  Scenario {s_name}: p_correct={ev['p_correct_outcome']:.3f} brier={ev['brier']:.4f} dir={ev['direction_correct']}")
        print(f"  verdict: {verdict}")

        updated.append(entry)

    log_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2))

    if summary_lines:
        from src.notify import send_telegram
        msg = "🔬 <b>傷兵乘數賽後驗證</b>\n\n" + "\n\n".join(summary_lines)
        send_telegram(msg)
        print("[validator] Telegram sent")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--match", default="", help="Filter by match label")
    args = parser.parse_args()
    validate_all(args.match)
