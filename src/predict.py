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

    return {
        "match_id": feature["match_id"],
        "home_team": feature["home_team"],
        "away_team": feature["away_team"],
        "ah_prediction": ah_prediction,
        "ah_confidence": ah_confidence,
        "ou_prediction": ou_prediction,
        "ou_confidence": ou_confidence,
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
