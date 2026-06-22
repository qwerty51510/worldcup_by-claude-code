import json
from math import exp, factorial
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * exp(-lam) / factorial(k)


def _poisson_ah_prob(lambda_home: float, lambda_away: float, handicap: float) -> float:
    """P(home covers AH): home_goals + handicap > away_goals."""
    max_goals = 10
    prob = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            if (h + handicap) > a:
                prob += _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
    return prob


def _poisson_ou_prob(lambda_home: float, lambda_away: float, line: float) -> float:
    """P(total goals > line) — probability of Over."""
    max_goals = 10
    prob_over = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            if (h + a) > line:
                prob_over += _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
    return prob_over


def _prob_to_confidence(prob: float) -> int:
    return min(100, max(0, int(abs(prob - 0.5) * 200)))


def _predict_score(lambda_home: float, lambda_away: float) -> dict:
    """
    Compute most likely exact score and 1X2 probabilities from Poisson model.
    Returns predicted_score, p_home_win, p_draw, p_away_win.
    """
    max_goals = 8
    best_prob = 0.0
    best_h, best_a = 0, 0
    p_home, p_draw, p_away = 0.0, 0.0, 0.0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
            if p > best_prob:
                best_prob = p
                best_h, best_a = h, a
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p

    return {
        "predicted_score": f"{best_h}-{best_a}",
        "p_home_win": round(p_home, 3),
        "p_draw": round(p_draw, 3),
        "p_away_win": round(p_away, 3),
    }


def predict_match(feature: dict, calibration: dict) -> dict:
    lh = feature["lambda_home"]
    la = feature["lambda_away"]
    ah_line = feature["ah_line"]
    ou_line = feature["ou_line"]
    sharp = feature["sharp_signal"]
    mul = calibration.get("sharp_money_multiplier", 0.85)

    if sharp > 0.25:
        lh *= mul
    elif sharp < -0.25:
        la *= mul

    ah_prob_home = _poisson_ah_prob(lh, la, ah_line)
    ah_prob_home = min(0.95, max(0.05, ah_prob_home))

    ah_prediction = "home" if ah_prob_home > 0.5 else "away"
    ah_confidence = _prob_to_confidence(ah_prob_home)

    ou_prob_over = _poisson_ou_prob(lh, la, ou_line)
    ou_prediction = "over" if ou_prob_over > 0.5 else "under"
    ou_confidence = _prob_to_confidence(ou_prob_over)

    key_factors = []
    data_source = feature.get("data_source", "")
    if data_source:
        key_factors.append(f"強度來源：{data_source}")
    if feature.get("must_win_home"):
        key_factors.append("主隊必贏場")
    if feature.get("must_win_away"):
        key_factors.append("客隊必贏場")
    if abs(sharp) > 0.25:
        key_factors.append(f"盤口明顯移動 {sharp:+.2f}")
    if not key_factors:
        key_factors.append("Poisson 標準預測")

    score_info = _predict_score(lh, la)

    return {
        "match_id": feature["match_id"],
        "home_team": feature["home_team"],
        "away_team": feature["away_team"],
        "ah_prediction": ah_prediction,
        "ah_confidence": ah_confidence,
        "ou_prediction": ou_prediction,
        "ou_confidence": ou_confidence,
        "predicted_score": score_info["predicted_score"],
        "p_home_win": score_info["p_home_win"],
        "p_draw": score_info["p_draw"],
        "p_away_win": score_info["p_away_win"],
        "key_factors": key_factors,
        "lambda_home": round(lh, 3),
        "lambda_away": round(la, 3),
    }


def predict_all(features: list, calibration: dict) -> list:
    return [predict_match(f, calibration) for f in features]


def save_predictions(date: str, predictions: list) -> None:
    out_dir = DATA_DIR / "predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{date}.json").write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2)
    )


def _load_predictions(date: str) -> list:
    path = DATA_DIR / "predictions" / f"{date}.json"
    if path.exists():
        return json.loads(path.read_text())
    return []
