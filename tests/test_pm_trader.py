"""
tests/test_pm_trader.py — Kelly Sizing + CLOB Execution Engine 測試

所有 ClobClient 呼叫均使用 MagicMock，不發出真實網路請求。
"""
import pytest
from unittest.mock import MagicMock, patch

from src.pm_trader import kelly_size, _ev, _build_client, place_limit_order, market_sell


# ── _ev ─────────────────────────────────────────────────────────────────────

def test_ev_calculation():
    assert _ev(our_prob=0.60, market_price=0.50) == pytest.approx(0.10)


def test_ev_negative():
    assert _ev(our_prob=0.30, market_price=0.50) == pytest.approx(-0.20)


def test_ev_zero():
    assert _ev(our_prob=0.50, market_price=0.50) == pytest.approx(0.0)


# ── kelly_size ───────────────────────────────────────────────────────────────

def test_kelly_zero_ev_returns_zero():
    assert kelly_size(our_prob=0.50, market_price=0.50, bankroll=500.0) == 0.0


def test_kelly_negative_ev_returns_zero():
    size = kelly_size(our_prob=0.30, market_price=0.50, bankroll=500.0)
    assert size == 0.0


def test_kelly_positive_ev():
    size = kelly_size(our_prob=0.65, market_price=0.50, bankroll=500.0)
    assert 0 < size <= 25.0


def test_kelly_respects_max_bet():
    # 即使有巨大優勢，下注上限仍為 $25
    size = kelly_size(our_prob=0.99, market_price=0.10, bankroll=500.0)
    assert size <= 25.0


def test_kelly_respects_bankroll_pct():
    # 5% bankroll cap：bankroll=100 → 上限 $5，MAX_BET=$25 不生效
    size = kelly_size(our_prob=0.99, market_price=0.10, bankroll=100.0)
    assert size <= 5.0


def test_kelly_returns_float():
    size = kelly_size(our_prob=0.65, market_price=0.50, bankroll=500.0)
    assert isinstance(size, float)


# ── _build_client ────────────────────────────────────────────────────────────

def test_build_client_requires_key(monkeypatch):
    monkeypatch.delenv("WALLET_PRIVATE_KEY", raising=False)
    with pytest.raises(ValueError, match="WALLET_PRIVATE_KEY"):
        _build_client()


def test_build_client_import_error(monkeypatch):
    monkeypatch.setenv("WALLET_PRIVATE_KEY", "0xdeadbeef")
    with patch.dict("sys.modules", {"py_clob_client": None, "py_clob_client.client": None}):
        with pytest.raises((ImportError, Exception)):
            _build_client()


# ── place_limit_order ────────────────────────────────────────────────────────

def test_place_limit_order_calls_post_order():
    mock_client = MagicMock()
    mock_client.post_order.return_value = {"orderID": "test-123"}

    with patch.dict("sys.modules", {
        "py_clob_client": MagicMock(),
        "py_clob_client.client": MagicMock(),
        "py_clob_client.clob_types": MagicMock(
            OrderArgs=MagicMock(),
            OrderType=MagicMock(GTC="GTC"),
            Side=MagicMock(BUY="BUY"),
        ),
    }):
        result = place_limit_order(mock_client, "token-abc", 10.0, 0.55)

    assert mock_client.post_order.called
    assert result == {"orderID": "test-123"}


def test_place_limit_order_returns_dict():
    mock_client = MagicMock()
    mock_client.post_order.return_value = {"orderID": "ord-999", "status": "LIVE"}

    with patch.dict("sys.modules", {
        "py_clob_client": MagicMock(),
        "py_clob_client.client": MagicMock(),
        "py_clob_client.clob_types": MagicMock(
            OrderArgs=MagicMock(),
            OrderType=MagicMock(GTC="GTC"),
            Side=MagicMock(BUY="BUY"),
        ),
    }):
        result = place_limit_order(mock_client, "token-xyz", 5.0, 0.40)

    assert isinstance(result, dict)
    assert "orderID" in result


# ── market_sell ──────────────────────────────────────────────────────────────

def test_market_sell_calls_fok():
    mock_client = MagicMock()
    mock_client.post_order.return_value = {"orderID": "sell-456"}

    with patch.dict("sys.modules", {
        "py_clob_client": MagicMock(),
        "py_clob_client.client": MagicMock(),
        "py_clob_client.clob_types": MagicMock(
            OrderArgs=MagicMock(),
            OrderType=MagicMock(FOK="FOK"),
            Side=MagicMock(SELL="SELL"),
        ),
    }):
        result = market_sell(mock_client, "token-abc", 10.0)

    assert mock_client.post_order.called
    # 確認使用 FOK
    call_args = mock_client.post_order.call_args
    assert call_args[0][1] == "FOK" or "FOK" in str(call_args)


def test_market_sell_returns_dict():
    mock_client = MagicMock()
    mock_client.post_order.return_value = {"orderID": "sell-789", "status": "MATCHED"}

    with patch.dict("sys.modules", {
        "py_clob_client": MagicMock(),
        "py_clob_client.client": MagicMock(),
        "py_clob_client.clob_types": MagicMock(
            OrderArgs=MagicMock(),
            OrderType=MagicMock(FOK="FOK"),
            Side=MagicMock(SELL="SELL"),
        ),
    }):
        result = market_sell(mock_client, "token-xyz", 15.0)

    assert isinstance(result, dict)
