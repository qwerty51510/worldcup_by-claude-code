import json
import pytest
from pathlib import Path
import src.pm_portfolio as pf


@pytest.fixture(autouse=True)
def tmp_portfolio(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", tmp_path / "portfolio.json")


def test_load_creates_default():
    data = pf.load()
    assert data["bankroll"] == 500.0
    assert data["positions"] == []
    assert data["trading_halted"] is False


def test_save_and_load_roundtrip():
    data = pf.load()
    data["bankroll"] = 480.0
    pf.save(data)
    assert pf.load()["bankroll"] == 480.0


def test_add_and_remove_position():
    pos = {"market_id": "abc", "team": "Switzerland", "size_usd": 20.0}
    pf.add_position(pos)
    assert len(pf.load()["positions"]) == 1
    removed = pf.remove_position("abc")
    assert removed["team"] == "Switzerland"
    assert pf.load()["positions"] == []


def test_update_pnl_halts_on_limit():
    pf.update_pnl(-80.0)
    assert pf.is_halted() is True


def test_exit_signals_push_pop():
    pf.push_exit_signal("abc", "RED_CARD")
    signals = pf.pop_exit_signals()
    assert signals[0]["market_id"] == "abc"
    assert pf.pop_exit_signals() == []


def test_bankroll_persists_across_day_boundary(monkeypatch):
    """Bankroll reflects cumulative P&L; daily_pnl resets on a new date."""
    monkeypatch.setattr(pf, "_today", lambda: "2026-06-27")
    pf.update_pnl(-80.0)
    assert pf.load()["bankroll"] == 420.0
    assert pf.load()["trading_halted"] is True

    # Simulate next day
    monkeypatch.setattr(pf, "_today", lambda: "2026-06-28")
    assert pf.is_halted() is False          # halt cleared for new day
    # Explicitly reset daily state (would happen when first trade of the day is made)
    pf.update_pnl(0.0)
    data = pf.load()
    assert data["bankroll"] == 420.0        # bankroll unchanged
    assert data["daily_pnl"] == 0.0        # only daily_pnl reset


def test_load_default_no_shared_state_between_calls():
    """Multiple load() calls when file absent must not share _DEFAULT references."""
    d1 = pf.load()
    d2 = pf.load()
    d1["calibration"]["history"].append("x")
    assert d2["calibration"]["history"] == [], "deepcopy failed: _DEFAULT was mutated"


def test_schema_backfill_on_load(tmp_path, monkeypatch):
    """Old portfolio.json missing new fields should be backfilled after load()."""
    path = tmp_path / "portfolio.json"
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", path)
    # Write a minimal portfolio without 'calibration'
    path.write_text('{"bankroll": 450.0, "positions": [], "trading_halted": false}')
    data = pf.load()
    assert "calibration" in data
    assert data["bankroll"] == 450.0


def test_calibration_factor_default_is_one(tmp_path, monkeypatch):
    import src.pm_portfolio as pf2
    monkeypatch.setattr(pf2, "PORTFOLIO_PATH", tmp_path / "p2.json")
    assert pf2.get_calibration_factor() == pytest.approx(1.0)


def test_calibration_updates_after_ten_trades(tmp_path, monkeypatch):
    import src.pm_portfolio as pf2
    monkeypatch.setattr(pf2, "PORTFOLIO_PATH", tmp_path / "p3.json")
    for _ in range(10):
        pf2.record_settled_trade(predicted_prob=0.7, actual_outcome=0)
    assert pf2.get_calibration_factor() < 1.0
