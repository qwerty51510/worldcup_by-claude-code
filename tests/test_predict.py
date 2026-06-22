from src.predict import predict_match, predict_all, _poisson_ah_prob, _poisson_ou_prob

SAMPLE_FEATURE = {
    "match_id": "1",
    "home_team": "Brazil",
    "away_team": "Morocco",
    "lambda_home": 1.6,
    "lambda_away": 0.9,
    "ah_line": -0.5,
    "ou_line": 2.5,
    "sharp_signal": 0.0,
    "incentive_score": 0.6,
    "must_win_home": False,
    "must_win_away": False,
}

DEFAULT_CAL = {
    "ah_weight": 1.0,
    "ou_weight": 1.0,
    "sharp_money_multiplier": 0.85,
    "incentive_boost": 0.15,
    "climate_penalty": 0.05,
    "age_decay_threshold": 29.5,
}


def test_predict_match_returns_required_keys():
    result = predict_match(SAMPLE_FEATURE, DEFAULT_CAL)
    required = {"match_id", "home_team", "away_team", "ah_prediction", "ah_confidence",
                "ou_prediction", "ou_confidence", "key_factors"}
    assert required.issubset(result.keys())


def test_ah_confidence_is_between_0_and_100():
    result = predict_match(SAMPLE_FEATURE, DEFAULT_CAL)
    assert 0 <= result["ah_confidence"] <= 100


def test_ou_confidence_is_between_0_and_100():
    result = predict_match(SAMPLE_FEATURE, DEFAULT_CAL)
    assert 0 <= result["ou_confidence"] <= 100


def test_ah_prediction_is_home_or_away():
    result = predict_match(SAMPLE_FEATURE, DEFAULT_CAL)
    assert result["ah_prediction"] in ("home", "away")


def test_ou_prediction_is_over_or_under():
    result = predict_match(SAMPLE_FEATURE, DEFAULT_CAL)
    assert result["ou_prediction"] in ("over", "under")


def test_poisson_ah_prob_strong_home_favored():
    prob = _poisson_ah_prob(lambda_home=2.0, lambda_away=0.5, handicap=-0.5)
    assert prob > 0.6


def test_predict_all_returns_list_same_length():
    result = predict_all([SAMPLE_FEATURE, SAMPLE_FEATURE], DEFAULT_CAL)
    assert len(result) == 2
