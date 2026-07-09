"""
持倉監控員：掃描現有持倉，依規則執行止損、EV 翻轉、止盈
用法：
  python -m src.position_monitor          # dry-run
  python -m src.position_monitor --live   # 真實平倉
"""

import argparse
import os
from pathlib import Path

import requests

DATA_API = "https://data-api.polymarket.com"


def _load_env() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _fetch_positions() -> list[dict]:
    _load_env()
    maker = os.environ.get("POLY_MAKER", "")
    try:
        r = requests.get(f"{DATA_API}/positions?user={maker}", timeout=8)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return []


def _fetch_fair_values() -> dict[str, float]:
    """token_id → fair_value，來源 pm_ev_scanner（允許負 EV 以取得全部）"""
    try:
        from src.pm_ev_scanner import scan
        stage_opps, _ = scan(min_ev=-1.0)
        return {o.token_id: o.fair_value for o in stage_opps if o.token_id}
    except Exception:
        return {}


def check_and_execute(dry_run: bool = True) -> list[str]:
    """
    掃描所有開倉，依以下規則決定是否平倉：
      止損：percentPnl ≤ -35%  → 全賣
      EV翻轉：fair_value < curPrice → 全賣
      止盈：percentPnl ≥ 80%  → 賣一半
    回傳操作日誌（list[str]）。
    """
    from src.execution_agent import place_sell_order
    from src import pm_portfolio

    positions    = _fetch_positions()
    fair_values  = _fetch_fair_values()
    logs: list[str] = []

    for p in positions:
        token_id  = p.get("asset", "")
        title     = p.get("title", token_id[:16] if token_id else "?")
        cur_price = float(p.get("curPrice", 0) or 0)
        pct_pnl   = float(p.get("percentPnl", 0) or 0)   # data-api 已是百分比單位
        size      = float(p.get("size", 0) or 0)
        fair_val  = fair_values.get(token_id)

        action = None
        reason = ""

        if pct_pnl <= -35:
            action = "SELL_ALL"
            reason = f"止損 P&L={pct_pnl:.1f}%"
        elif fair_val is not None and fair_val < cur_price:
            action = "SELL_ALL"
            reason = f"EV翻轉 模型={fair_val*100:.1f}¢ < 現價={cur_price*100:.1f}¢"
        elif pct_pnl >= 80:
            action = "SELL_HALF"
            reason = f"止盈 P&L={pct_pnl:.1f}%"

        if action is None:
            continue

        shares_to_sell = size if action == "SELL_ALL" else round(size / 2, 2)
        tag = "[DRY] " if dry_run else ""
        logs.append(f"  {tag}{title[:24]}  {reason}  → 賣 {shares_to_sell:.2f} 股 @ ≥{cur_price*100:.1f}¢")

        if not dry_run and token_id and shares_to_sell > 0:
            floor_price = max(cur_price * 0.95, 0.001)
            ok, msg = place_sell_order(token_id, shares_to_sell, floor_price)
            logs.append(f"    {'✓' if ok else '✗'} {msg}")
            if ok and action == "SELL_ALL":
                pm_portfolio.close_position(token_id)
                pm_portfolio.log_trade({
                    "team":     title,
                    "action":   "SELL",
                    "reason":   reason,
                    "shares":   shares_to_sell,
                    "price":    cur_price,
                    "size_usd": round(shares_to_sell * cur_price, 2),
                    "pnl":      float(p.get("cashPnl", 0) or 0),
                })

    if not logs:
        logs.append("  ── 無需調整的持倉 ──")

    return logs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="真實平倉（預設 dry-run）")
    args = parser.parse_args()

    results = check_and_execute(dry_run=not args.live)
    for line in results:
        print(line)
