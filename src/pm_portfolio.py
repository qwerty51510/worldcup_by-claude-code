import fcntl
import json
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


def load():
    if not PORTFOLIO_PATH.exists():
        return {k: (v.copy() if isinstance(v, (dict, list)) else v)
                for k, v in _DEFAULT.items()}
    with open(PORTFOLIO_PATH) as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        data = json.load(f)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return data


def save(data):
    PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PORTFOLIO_PATH, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def get_bankroll():
    return load()["bankroll"]


def is_halted():
    data = load()
    today = date.today().isoformat()
    if data.get("daily_pnl_date") != today:
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
    today = date.today().isoformat()
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
