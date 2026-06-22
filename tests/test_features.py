from src.features import build_features, compute_incentive_score, compute_sharp_signal

SAMPLE_MATCHES = [
    {
        "id": 1,
        "homeTeam": {"name": "Spain", "id": 10},
        "awayTeam": {"name": "Cape Verde", "id": 999},
        "score": {"fullTime": {"home": None, "away": None}},
        "status": "SCHEDULED",
        "utcDate": "2026-06-22T18:00:00Z",
        "group": "Group H",
    }
]

SAMPLE_ODDS = {
    "match_1": {
        "home_team": "Spain",
        "away_team": "Cape Verde",
        "bookmakers": [
            {
                "markets": [
                    {
                        "key": "asian_handicap",
                        "outcomes": [
                            {"name": "Spain", "price": 1.72, "point": -1.5},
                            {"name": "Cape Verde", "price": 2.18, "point": 1.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.90, "point": 2.5},
                            {"name": "Under", "price": 1.90, "point": 2.5},
                        ],
                    },
                ]
            }
        ],
    }
}

DEFAULT_CALIBRATION = {
    "ah_weight": 1.0,
    "ou_weight": 1.0,
    "sharp_money_multiplier": 0.85,
    "incentive_boost": 0.15,
    "climate_penalty": 0.05,
    "age_decay_threshold": 29.5,
}


def test_build_features_returns_list():
    result = build_features(SAMPLE_MATCHES, SAMPLE_ODDS, DEFAULT_CALIBRATION)
    assert isinstance(result, list)
    assert len(result) == 1


def test_build_features_has_required_keys():
    result = build_features(SAMPLE_MATCHES, SAMPLE_ODDS, DEFAULT_CALIBRATION)
    required = {"match_id", "home_team", "away_team", "lambda_home", "lambda_away",
                "ah_line", "ou_line", "sharp_signal", "incentive_score"}
    assert required.issubset(result[0].keys())


def test_compute_incentive_score_must_win():
    score = compute_incentive_score(must_win=True, safe_draw=False, dead_rubber=False)
    assert score > 0.5


def test_compute_incentive_score_dead_rubber():
    score = compute_incentive_score(must_win=False, safe_draw=False, dead_rubber=True)
    assert score < 0.3


def test_compute_sharp_signal_line_moved_toward_underdog():
    signal = compute_sharp_signal(open_handicap=-1.5, current_handicap=-1.0)
    assert signal > 0
