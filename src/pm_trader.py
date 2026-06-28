"""
pm_trader.py — Kelly Sizing + CLOB Execution Engine

功能：
  1. _ev() / kelly_size() — 計算期望值與下注規模
  2. _build_client()      — 建立 Polymarket CLOB 連線
  3. place_limit_order()  — 送出 GTC 限價買單
  4. market_sell()        — 送出 FOK 市價賣單（清倉用）
  5. handle_exits()       — 處理 portfolio exit signals
  6. scan_and_trade()     — 掃描 EV 機會並自動下注
  7. run_daemon()         — 定時循環執行
"""

import os
import time
from datetime import datetime, timezone
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
import src.pm_portfolio as portfolio


def _tg_notify(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception:
        pass

MAX_BET = 25.0
MAX_POSITIONS = 4
MIN_EV = 0.05
MIN_ROI = 0.20
CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137


def _ev(our_prob: float, market_price: float) -> float:
    """期望值 = 我方估算概率 - 市場價格。"""
    return our_prob - market_price


def kelly_size(our_prob: float, market_price: float, bankroll: float) -> float:
    """
    Half-Kelly 下注規模，上限為 min(half_kelly * bankroll, 5% bankroll, $25)。
    EV <= 0 時回傳 0.0。
    """
    ev = _ev(our_prob, market_price)
    if ev <= 0:
        return 0.0
    if market_price <= 0 or market_price >= 1:
        return 0.0
    b = (1.0 / market_price) - 1.0
    q = 1.0 - our_prob
    kelly = (our_prob * b - q) / b
    half_kelly = kelly * 0.5
    return round(min(half_kelly * bankroll, bankroll * 0.05, MAX_BET), 2)


def _build_client():
    """
    建立 Polymarket CLOB client。
    - 若缺少 WALLET_PRIVATE_KEY，拋出 ValueError
    - 若 py-clob-client 未安裝，拋出 ImportError
    """
    key = os.environ.get("WALLET_PRIVATE_KEY", "")
    if not key:
        raise ValueError(
            "WALLET_PRIVATE_KEY not set in environment. "
            "Export it before running: export WALLET_PRIVATE_KEY=0x..."
        )
    try:
        from py_clob_client.client import ClobClient
        return ClobClient(host=CLOB_HOST, key=key, chain_id=POLYGON_CHAIN_ID)
    except ImportError:
        raise ImportError(
            "py-clob-client-v2 not installed. "
            "Run: pip install git+https://github.com/Polymarket/py-clob-client-v2"
        )


def place_limit_order(client, token_id: str, size_usd: float, limit_price: float) -> dict:
    """
    送出 GTC 限價買單。
    回傳 Polymarket API response dict（含 orderID）。
    """
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType, Side
    except ImportError:
        raise ImportError(
            "py-clob-client-v2 not installed. "
            "Run: pip install git+https://github.com/Polymarket/py-clob-client-v2"
        )
    order = client.create_order(OrderArgs(
        token_id=token_id,
        price=limit_price,
        size=size_usd,
        side=Side.BUY,
    ))
    return client.post_order(order, OrderType.GTC)


def market_sell(client, token_id: str, size_usd: float) -> dict:
    """
    送出 FOK 市價賣單（Fill-or-Kill，清倉用）。
    以極低限價模擬市價賣出。
    """
    try:
        from py_clob_client.clob_types import OrderArgs, OrderType, Side
    except ImportError:
        raise ImportError(
            "py-clob-client-v2 not installed. "
            "Run: pip install git+https://github.com/Polymarket/py-clob-client-v2"
        )
    order = client.create_order(OrderArgs(
        token_id=token_id,
        price=0.01,   # 極低限價 = 實際上的市價賣出
        size=size_usd,
        side=Side.SELL,
    ))
    return client.post_order(order, OrderType.FOK)


def handle_exits(client) -> None:
    """
    處理所有 exit signals：
    1. pop_exit_signals() 取出所有待退出信號
    2. 對每個信號執行 market_sell
    3. 失敗時把 position 放回去
    """
    signals = portfolio.pop_exit_signals()
    for sig in signals:
        pos = portfolio.remove_position(sig["market_id"])
        if not pos:
            continue
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] EXIT {pos['team']} reason={sig['reason']} size=${pos['size_usd']}")
        try:
            market_sell(client, pos["token_id"], pos["size_usd"])
            portfolio.update_pnl(0.0)  # PnL 在 Polymarket 結算後確認
            portfolio.log_trade({
                "type": "EXIT",
                "team": pos["team"],
                "reason": sig["reason"],
                "time": ts,
            })
            _tg_notify(
                f"🔴 <b>平倉</b>  {pos['team']}\n"
                f"原因：{sig['reason']}\n"
                f"倉位：${pos['size_usd']:.2f}  進場價：{pos['entry_price']:.3f}\n"
                f"時間：{ts} UTC"
            )
        except Exception as e:
            print(f"[{ts}] EXIT FAILED for {pos['team']}: {e}")
            portfolio.add_position(pos)  # 放回去


def scan_and_trade(client) -> None:
    """
    掃描 EV 機會並自動下注：
    1. 檢查 is_halted()（日損限制）
    2. 檢查現有持倉數量上限
    3. 呼叫 pm_ev_scanner.find_opportunities()
    4. 對符合條件的機會送出限價單
    """
    if portfolio.is_halted():
        print("[pm_trader] trading halted (daily loss limit)")
        return

    data = portfolio.load()
    if len(data["positions"]) >= MAX_POSITIONS:
        return

    bankroll = data["bankroll"]

    try:
        from src.pm_ev_scanner import fetch_all, build_matrix, find_opportunities
        stage_data = fetch_all()
        matrix = build_matrix(stage_data)
        opps = find_opportunities(matrix, min_ev=MIN_EV)
    except Exception as e:
        print(f"[pm_trader] scanner error: {e}")
        return

    existing_keys = {(p["team"], p.get("stage")) for p in data["positions"]}
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

    for opp in opps:
        if opp.ev < MIN_EV:
            continue
        if opp.ev_roi < MIN_ROI:
            continue
        if (opp.team, opp.to_stage) in existing_keys:
            continue
        if len(data["positions"]) >= MAX_POSITIONS:
            break

        size = kelly_size(opp.fair_value, opp.p_to, bankroll)
        if size < 1.0:
            continue

        limit_price = round((opp.p_to + opp.fair_value) / 2, 4)
        print(f"[{ts}] BUY {opp.team} [{opp.label}] size=${size} limit={limit_price}")

        try:
            resp = place_limit_order(
                client,
                token_id=opp.token_id,
                size_usd=size,
                limit_price=limit_price,
            )
            order_id = resp.get("orderID", "")
            pos = {
                "market_id": f"{opp.team}:{opp.to_stage}",
                "token_id": opp.token_id,
                "team": opp.team,
                "stage": opp.to_stage,
                "size_usd": size,
                "entry_price": limit_price,
                "our_prob": opp.fair_value,
                "entry_time": ts,
                "order_id": order_id,
                "fixture_id": None,
            }
            portfolio.add_position(pos)
            portfolio.log_trade({"type": "BUY", **pos})
            existing_keys.add((opp.team, opp.to_stage))
            _tg_notify(
                f"🟢 <b>開倉</b>  {opp.team}  [{opp.label}]\n"
                f"限價：{limit_price:.3f}  倉位：${size:.2f}\n"
                f"我方機率：{opp.fair_value*100:.1f}%  市場：{opp.p_to*100:.1f}%  "
                f"EV：+{opp.ev*100:.1f}¢\n"
                f"時間：{ts} UTC"
            )
            # 重新讀取以取得最新持倉數量
            data = portfolio.load()
        except Exception as e:
            print(f"[{ts}] ORDER FAILED {opp.team}: {e}")


def run_daemon(interval: int = 300) -> None:
    """
    定時循環：每隔 interval 秒執行一次 handle_exits + scan_and_trade。
    """
    print(f"[pm_trader] daemon started, interval={interval}s")
    _tg_notify("🤖 <b>交易機器人啟動</b>\n本金：$500 USDC  半Kelly  最大單筆 $25")
    client = _build_client()
    _last_halted = False
    while True:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        try:
            handle_exits(client)
            scan_and_trade(client)
        except Exception as e:
            print(f"[{ts}] pm_trader loop error: {e}")

        data = portfolio.load()
        bankroll = data["bankroll"]
        daily_pnl = data.get("daily_pnl", 0.0)
        halted = data.get("trading_halted", False)
        n_pos = len(data.get("positions", []))

        if halted and not _last_halted:
            _tg_notify(
                f"🚨 <b>交易暫停</b> — 日損達上限\n"
                f"今日 PnL：${daily_pnl:.2f}  本金：${bankroll:.2f}"
            )
        _last_halted = halted

        print(f"[{ts}] bankroll=${bankroll:.2f}  daily={daily_pnl:+.2f}  pos={n_pos}  next in {interval}s")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Polymarket Trader")
    ap.add_argument("--daemon", action="store_true", help="持續循環模式")
    ap.add_argument("--interval", type=int, default=300, help="循環間隔秒數")
    args = ap.parse_args()
    if args.daemon:
        run_daemon(args.interval)
    else:
        client = _build_client()
        handle_exits(client)
        scan_and_trade(client)
