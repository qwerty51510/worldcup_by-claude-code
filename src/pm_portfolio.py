import copy
import fcntl
import json
import os
from datetime import date
from pathlib import Path

PORTFOLIO_PATH = Path(__file__).parent.parent / "data" / "portfolio.json"

_DEFAULT = {
    "bankroll": 500.0,
    "daily_pnl": 0.0,
    "daily_pnl_date": "",
    "daily_loss_limit": 75.0,
    "trading_halted": False,
    "positions": [],
    "model_probs": {},
    "match_probs": {},
    "live_events": {},
    "exit_signals": [],
    "trade_log": [],
    "calibration": {"n_settled": 0, "factor": 1.0, "history": []},
}


def _today():
    """Return today's ISO date string. Extracted so tests can monkeypatch it."""
    return date.today().isoformat()


def _default_state():
    return copy.deepcopy(_DEFAULT)


def load():
    if not PORTFOLIO_PATH.exists():
        return _default_state()
    with open(PORTFOLIO_PATH) as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        data = json.load(f)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    # Backfill missing keys introduced by schema upgrades
    defaults = _default_state()
    for key, val in defaults.items():
        if key not in data:
            data[key] = val
    return data


def save(data):
    PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, indent=2, ensure_ascii=False).encode()
    # Open for read+write so the lock is taken before any truncation.
    # If the file doesn't exist yet, create it cleanly (no race on creation).
    if PORTFOLIO_PATH.exists():
        fd = os.open(str(PORTFOLIO_PATH), os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, encoded)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    else:
        # File absent: write atomically via a temp file + rename
        tmp = str(PORTFOLIO_PATH) + ".tmp"
        with open(tmp, "w") as f:
            f.write(encoded.decode())
        os.replace(tmp, str(PORTFOLIO_PATH))


def get_bankroll():
    return load()["bankroll"]


def is_halted():
    data = load()
    if data.get("daily_pnl_date") != _today():
        return False
    return data.get("trading_halted", False)


def add_position(pos):
    data = load()
    data["positions"].append(pos)
    save(data)


def remove_position(market_id):
    data = load()
    for i, p in enumerate(data["positions"]):
        if p["market_id"] == market_id:
            removed = data["positions"].pop(i)
            save(data)
            return removed
    return None


def update_pnl(delta):
    data = load()
    today = _today()
    if data.get("daily_pnl_date") != today:
        data["daily_pnl"] = 0.0
        data["daily_pnl_date"] = today
        data["trading_halted"] = False
    data["daily_pnl"] = round(data["daily_pnl"] + delta, 4)
    data["bankroll"] = round(data["bankroll"] + delta, 4)
    if data["daily_pnl"] <= -data["daily_loss_limit"]:
        data["trading_halted"] = True
    save(data)


def push_exit_signal(market_id, reason):
    data = load()
    data["exit_signals"].append({"market_id": market_id, "reason": reason})
    save(data)


def pop_exit_signals():
    data = load()
    signals = data.get("exit_signals", [])
    data["exit_signals"] = []
    save(data)
    return signals


def log_trade(entry):
    data = load()
    data["trade_log"].append(entry)
    save(data)


def record_settled_trade(predicted_prob: float, actual_outcome: int) -> None:
    """Record a settled trade for calibration.

    Args:
        predicted_prob: The predicted probability (0.0 to 1.0)
        actual_outcome: 1=won, 0=lost
    """
    data = load()
    cal = data["calibration"]
    cal["history"].append({"pred": predicted_prob, "actual": actual_outcome})
    cal["n_settled"] += 1
    if cal["n_settled"] % 10 == 0:
        _refit_calibration(data)
    else:
        save(data)


def _refit_calibration(data: dict) -> None:
    """Refit calibration factor using linear regression on prediction history."""
    import numpy as np
    history = data["calibration"]["history"]
    if len(history) < 5:
        save(data)
        return
    preds = np.array([h["pred"] for h in history])
    actuals = np.array([h["actual"] for h in history], dtype=float)
    pred_std = preds.std()

    if pred_std < 1e-6:
        # Low variance in predictions: use mean ratio instead
        pred_mean = preds.mean()
        actual_mean = actuals.mean()
        if pred_mean > 1e-6:
            slope = actual_mean / pred_mean
        else:
            slope = 1.0
    else:
        slope = float(np.cov(preds, actuals)[0, 1] / np.var(preds))

    data["calibration"]["factor"] = round(max(0.5, min(1.5, slope)), 4)
    save(data)


def get_calibration_factor() -> float:
    """Get the current calibration factor."""
    return load()["calibration"]["factor"]
