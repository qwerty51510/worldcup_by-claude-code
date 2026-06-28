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
