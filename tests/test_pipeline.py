from src.pipeline import run


def test_run_calls_all_stages(monkeypatch):
    calls = []
    monkeypatch.setattr("src.pipeline.fetch_matches", lambda d: [])
    monkeypatch.setattr("src.pipeline.fetch_odds", lambda ids: {})
    monkeypatch.setattr("src.pipeline.fetch_polymarket", lambda: {})
    monkeypatch.setattr("src.pipeline.save_match_day", lambda d, data: None)
    monkeypatch.setattr("src.pipeline.build_features", lambda m, o, c, pm_strengths=None: [])
    monkeypatch.setattr("src.pipeline.predict_all", lambda f, c: [])
    monkeypatch.setattr("src.pipeline.save_predictions", lambda d, p: calls.append("save_pred"))
    monkeypatch.setattr("src.pipeline.load_calibration", lambda: {})
    monkeypatch.setattr("src.pipeline.compute_brier_score", lambda p, a: 0.18)
    monkeypatch.setattr("src.pipeline.update_calibration", lambda c, b, p, a: c)
    monkeypatch.setattr("src.pipeline.save_calibration", lambda c: calls.append("save_cal"))
    monkeypatch.setattr("src.pipeline.render_all", lambda d: calls.append("render"))
    run("2026-06-22")
    assert "render" in calls
    assert "save_pred" in calls
