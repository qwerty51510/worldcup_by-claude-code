import pytest
from unittest.mock import patch
from src.pm_predict import match_win_probs, _elo_lambdas, _poisson_match_probs


def test_probs_sum_to_one():
    with patch("src.pm_predict.player_lambdas", return_value=(1.5, 1.2)):
        p_h, p_d, p_a = match_win_probs("Brazil", "Germany")
    assert abs(p_h + p_d + p_a - 1.0) < 1e-6


def test_stronger_team_wins_more():
    # Brazil ELO >> Haiti ELO → Brazil should win more
    p_h, _, p_a = match_win_probs("Brazil", "Haiti")
    assert p_h > p_a


def test_elo_lambdas_favors_higher_elo():
    lh, la = _elo_lambdas("Brazil", "Haiti")
    assert lh > la


def test_poisson_probs_sum_to_one():
    p_h, p_d, p_a = _poisson_match_probs(1.5, 0.8)
    assert abs(p_h + p_d + p_a - 1.0) < 1e-6


def test_player_lambda_fallback():
    # When player data unavailable, falls back to ELO
    with patch("src.pm_predict.player_lambdas", return_value=(None, None)):
        p_h, p_d, p_a = match_win_probs("Brazil", "Germany")
    assert abs(p_h + p_d + p_a - 1.0) < 1e-6
