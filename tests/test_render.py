from src.render import render_index, render_postmortem, render_calibration

SAMPLE_PREDICTIONS = [
    {
        "match_id": "1", "home_team": "Brazil", "away_team": "Morocco",
        "ah_prediction": "home", "ah_confidence": 65,
        "ou_prediction": "under", "ou_confidence": 58,
        "key_factors": ["sharp line move: +0.30"],
    }
]

SAMPLE_POSTMORTEM = [
    {
        "match_id": "2", "home_team": "Spain", "away_team": "Cape Verde",
        "predicted": "home", "confidence": 85, "actual_score": "0-0",
        "error": 0.72, "key_factors": ["standard Poisson projection"],
    }
]

SAMPLE_CALIBRATION = {
    "ah_weight": 1.0, "ou_weight": 1.0, "sharp_money_multiplier": 0.85,
    "incentive_boost": 0.15, "climate_penalty": 0.05,
    "age_decay_threshold": 29.5, "version": "1.0", "last_updated": "2026-06-22",
}


def test_render_index_produces_html(tmp_path):
    out = tmp_path / "index.html"
    render_index(SAMPLE_PREDICTIONS, "2026-06-22", str(out))
    assert out.exists()
    content = out.read_text()
    assert "巴西" in content   # Brazil → 巴西 after Chinese translation
    assert "摩洛哥" in content  # Morocco → 摩洛哥
    assert "65" in content


def test_render_postmortem_highlights_error(tmp_path):
    out = tmp_path / "postmortem.html"
    render_postmortem(SAMPLE_POSTMORTEM, str(out))
    content = out.read_text()
    assert "Spain" in content
    assert "0-0" in content


def test_render_calibration_includes_version(tmp_path):
    out = tmp_path / "calibration.html"
    render_calibration(SAMPLE_CALIBRATION, brier_history=[0.22, 0.19, 0.17], out_path=str(out))
    content = out.read_text()
    assert "1.0" in content
