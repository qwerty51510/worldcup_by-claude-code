import json
from pathlib import Path

from src.config import DEFAULT_CALIBRATION, BRIER_RESET_THRESHOLD

DATA_DIR = Path(__file__).parent.parent / "data"
CALIBRATION_PATH = DATA_DIR / "backtest" / "calibration.json"


def _ah_covered(prediction: dict, actual: dict):
    if actual.get("status") != "FINISHED":
        return None
    score = actual["score"]["fullTime"]
    if score["home"] is None or score["away"] is None:
        return None
    home_goals = score["home"]
    away_goals = score["away"]
    return (home_goals > away_goals) == (prediction.get("ah_prediction") == "home")


def compute_brier_score(predictions: list, actuals: list) -> float:
    actual_map = {str(a["id"]): a for a in actuals}
    errors = []
    for pred in predictions:
        actual = actual_map.get(str(pred["match_id"]))
        if not actual:
            continue
        ah_hit = _ah_covered(pred, actual)
        if ah_hit is not None:
            p = pred["ah_confidence"] / 100.0
            outcome = 1.0 if ah_hit else 0.0
            errors.append((p - outcome) ** 2)
    return sum(errors) / len(errors) if errors else 0.0


def update_calibration(calibration: dict, brier: float, predictions: list, actuals: list) -> dict:
    if brier > BRIER_RESET_THRESHOLD:
        cal = dict(DEFAULT_CALIBRATION)
        cal["last_updated"] = calibration.get("last_updated", "")
        return cal
    cal = dict(calibration)
    if brier < 0.15:
        cal["ah_weight"] = min(1.3, cal.get("ah_weight", 1.0) * 1.02)
    elif brier > 0.20:
        cal["ah_weight"] = max(0.7, cal.get("ah_weight", 1.0) * 0.98)
    return cal


def generate_postmortem(predictions: list, actuals: list) -> list:
    actual_map = {str(a["id"]): a for a in actuals}
    postmortem = []
    for pred in predictions:
        actual = actual_map.get(str(pred["match_id"]))
        if not actual:
            continue
        ah_hit = _ah_covered(pred, actual)
        if ah_hit is None:
            continue
        confidence = pred["ah_confidence"] / 100.0
        error = (confidence - (1.0 if ah_hit else 0.0)) ** 2
        if error > 0.25:
            score = actual["score"]["fullTime"]
            postmortem.append({
                "match_id": pred["match_id"],
                "home_team": pred["home_team"],
                "away_team": pred["away_team"],
                "predicted": pred["ah_prediction"],
                "confidence": pred["ah_confidence"],
                "actual_score": f"{score['home']}-{score['away']}",
                "error": round(error, 3),
                "key_factors": pred.get("key_factors", []),
            })
    return sorted(postmortem, key=lambda x: x["error"], reverse=True)


def run_rich_postmortem(report: dict) -> dict:
    """Generate structured postmortem: per-match analysis + team goal bias."""
    from datetime import datetime as _dt
    all_results = report.get("all_results", [])
    if not all_results:
        return {}

    matches_analysis = []
    for r in all_results:
        try:
            pred_h, pred_a = map(int, r.get("predicted_score", "0-0").split("-"))
            actual_h, actual_a = map(int, r["score"].split("-"))
        except (ValueError, AttributeError):
            continue
        matches_analysis.append({
            "date": r["date"], "group": r["group"], "round": r["round"],
            "home": r["home"], "away": r["away"],
            "predicted_score": r.get("predicted_score", "?-?"),
            "actual_score": r["score"],
            "score_correct": r.get("predicted_score") == r["score"],
            "goal_total_error": abs((pred_h + pred_a) - (actual_h + actual_a)),
            "lambda_home": r["lambda_home"], "lambda_away": r["lambda_away"],
            "ah_pred": r["ah_pred"], "actual_ah": r.get("actual_ah"),
            "ah_correct": r["ah_correct"], "ah_is_push": r["ah_is_push"],
            "ou_pred": r["ou_pred"], "ou_correct": r["ou_correct"],
        })

    # Per-team goal bias
    team_stats: dict = {}
    for m in matches_analysis:
        try:
            pred_h, pred_a = map(int, m["predicted_score"].split("-"))
            actual_h, actual_a = map(int, m["actual_score"].split("-"))
        except (ValueError, AttributeError):
            continue
        for team, pg, ag in [(m["home"], pred_h, actual_h), (m["away"], pred_a, actual_a)]:
            s = team_stats.setdefault(team, {
                "matches": 0, "pred_goals": 0, "actual_goals": 0,
                "ah_correct": 0, "ah_decisive": 0,
            })
            s["matches"] += 1
            s["pred_goals"] += pg
            s["actual_goals"] += ag
            if not m["ah_is_push"]:
                s["ah_decisive"] += 1
                if m["ah_correct"]:
                    s["ah_correct"] += 1

    team_analysis = []
    for team, s in team_stats.items():
        n = s["matches"]
        team_analysis.append({
            "team": team, "matches": n,
            "pred_goals_avg": round(s["pred_goals"] / n, 2),
            "actual_goals_avg": round(s["actual_goals"] / n, 2),
            "goal_bias": round((s["pred_goals"] - s["actual_goals"]) / n, 2),
            "ah_accuracy": round(s["ah_correct"] / s["ah_decisive"], 3) if s["ah_decisive"] > 0 else None,
        })
    team_analysis.sort(key=lambda x: abs(x["goal_bias"]), reverse=True)

    missed_ah = [m for m in matches_analysis if not m["ah_is_push"] and not m["ah_correct"]]
    avg_goal_err = round(sum(m["goal_total_error"] for m in matches_analysis) / len(matches_analysis), 2) if matches_analysis else 0

    return {
        "generated_at": _dt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_matches": len(matches_analysis),
        "summary": {
            "ah_accuracy": report.get("ah_accuracy", 0),
            "ou_accuracy": report.get("ou_accuracy", 0),
            "score_exact_match": sum(1 for m in matches_analysis if m["score_correct"]),
            "avg_goal_total_error": avg_goal_err,
        },
        "matches": matches_analysis,
        "team_analysis": team_analysis,
        "missed_ah_matches": missed_ah,
    }


def save_postmortem(postmortem: dict) -> None:
    path = DATA_DIR / "backtest" / "postmortem.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(postmortem, ensure_ascii=False, indent=2))
    print("[postmortem] 復盤報告已存至 %s" % path)


def load_calibration() -> dict:
    if CALIBRATION_PATH.exists():
        return json.loads(CALIBRATION_PATH.read_text())
    return dict(DEFAULT_CALIBRATION)


def save_calibration(calibration: dict) -> None:
    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(json.dumps(calibration, ensure_ascii=False, indent=2))


BRIER_HISTORY_PATH = DATA_DIR / "backtest" / "brier_history.json"


def load_brier_history() -> list:
    if BRIER_HISTORY_PATH.exists():
        return json.loads(BRIER_HISTORY_PATH.read_text())
    return []


def save_brier_history(score: float) -> None:
    history = load_brier_history()
    history.append(round(score, 4))
    BRIER_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRIER_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2))
