from src.backtest import compute_brier_score, update_calibration, generate_postmortem
from src.config import DEFAULT_CALIBRATION, BRIER_RESET_THRESHOLD

PREDICTIONS = [
    {"match_id": "1", "home_team": "Brazil", "away_team": "Morocco",
     "ah_prediction": "home", "ah_confidence": 70, "ou_prediction": "over", "ou_confidence": 60,
     "key_factors": []},
    {"match_id": "2", "home_team": "Spain", "away_team": "Cape Verde",
     "ah_prediction": "home", "ah_confidence": 85, "ou_prediction": "over", "ou_confidence": 65,
     "key_factors": ["standard Poisson projection"]},
]

ACTUALS = [
    {"id": 1, "homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Morocco"},
     "score": {"fullTime": {"home": 1, "away": 1}}, "status": "FINISHED"},
    {"id": 2, "homeTeam": {"name": "Spain"}, "awayTeam": {"name": "Cape Verde"},
     "score": {"fullTime": {"home": 0, "away": 0}}, "status": "FINISHED"},
]


def test_brier_score_returns_float():
    score = compute_brier_score(PREDICTIONS, ACTUALS)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_brier_score_perfect_prediction_is_zero():
    preds = [{"match_id": "1", "home_team": "X", "away_team": "Y",
              "ah_prediction": "home", "ah_confidence": 100,
              "ou_prediction": "under", "ou_confidence": 100, "key_factors": []}]
    acts = [{"id": 1, "homeTeam": {"name": "X"}, "awayTeam": {"name": "Y"},
             "score": {"fullTime": {"home": 2, "away": 0}}, "status": "FINISHED"}]
    score = compute_brier_score(preds, acts)
    assert score == 0.0


def test_update_calibration_resets_on_high_brier():
    cal = dict(DEFAULT_CALIBRATION)
    cal["ah_weight"] = 1.5
    updated = update_calibration(cal, BRIER_RESET_THRESHOLD + 0.01, PREDICTIONS, ACTUALS)
    assert updated["ah_weight"] == 1.0


def test_generate_postmortem_returns_high_error_matches():
    result = generate_postmortem(PREDICTIONS, ACTUALS)
    spain_match = next((r for r in result if "Spain" in r.get("home_team", "")), None)
    assert spain_match is not None
    assert spain_match["error"] > 0.5
