"""
Tests for pm_ev_scanner: model_probs integration and fallback behavior.
"""
import json
import pytest
from unittest.mock import patch
from src.pm_ev_scanner import find_opportunities, build_matrix


SAMPLE_STAGE_DATA = {
    "qf": {"Switzerland": 0.50, "Argentina": 0.85, "Brazil": 0.80},
    "sf": {"Switzerland": 0.10, "Argentina": 0.60, "Brazil": 0.55},
    "final": {"Switzerland": 0.05, "Argentina": 0.35, "Brazil": 0.30},
    "winner": {"Switzerland": 0.02, "Argentina": 0.20, "Brazil": 0.18},
}

SAMPLE_MODEL_PROBS = {
    "Switzerland": {"qf": 0.50, "sf": 0.23, "final": 0.10, "winner": 0.04},
}


def test_find_opportunities_uses_model_probs_when_available(tmp_path, monkeypatch):
    import src.pm_portfolio as pf
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    data = pf.load()
    data["model_probs"] = SAMPLE_MODEL_PROBS
    pf.save(data)

    matrix = build_matrix(SAMPLE_STAGE_DATA)
    opps = find_opportunities(matrix, min_ev=0.0)
    swiss_sf = next((o for o in opps if o.team == "Switzerland" and o.to_stage == "sf"), None)
    # fair_value should be model prob 0.23, not peer_median * 0.50
    assert swiss_sf is not None
    assert abs(swiss_sf.fair_value - 0.23) < 0.01


def test_find_opportunities_falls_back_to_peer_median(tmp_path, monkeypatch):
    import src.pm_portfolio as pf
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    # No model_probs set → should still work with peer_median

    matrix = build_matrix(SAMPLE_STAGE_DATA)
    opps = find_opportunities(matrix, min_ev=0.0)
    assert len(opps) > 0
