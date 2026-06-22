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


def load_calibration() -> dict:
    if CALIBRATION_PATH.exists():
        return json.loads(CALIBRATION_PATH.read_text())
    return dict(DEFAULT_CALIBRATION)


def save_calibration(calibration: dict) -> None:
    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(json.dumps(calibration, ensure_ascii=False, indent=2))
