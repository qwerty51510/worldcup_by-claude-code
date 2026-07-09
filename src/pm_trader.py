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
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
import src.pm_portfolio as portfolio
import src.pm_auditor as auditor


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


def _append_creds_to_dotenv(api_key: str, secret: str, passphrase: str) -> None:
    try:
        env_path = Path(__file__).parent.parent / ".env"
        text = env_path.read_text() if env_path.exists() else ""
        additions = []
        if "CLOB_API_KEY" not in text:
            additions.append(f"CLOB_API_KEY={api_key}")
        if "CLOB_API_SECRET" not in text:
            additions.append(f"CLOB_API_SECRET={secret}")
        if "CLOB_API_PASSPHRASE" not in text:
            additions.append(f"CLOB_API_PASSPHRASE={passphrase}")
        if additions:
            env_path.write_text(text.rstrip() + "\n" + "\n".join(additions) + "\n")
            print("[pm_trader] Saved CLOB credentials to .env")
    except Exception as e:
        print(f"[pm_trader] Could not save credentials to .env: {e}")


def _build_client():
    """
    建立 Polymarket CLOB v2 client。
    若 .env 已有 CLOB_API_KEY，直接使用；
    否則自動向 CLOB 申請 API credentials（僅需 wallet 簽名，一次性）。
    """
    key = os.environ.get("POLY_PRIVATE_KEY", os.environ.get("WALLET_PRIVATE_KEY", ""))
    if not key:
        raise ValueError("POLY_PRIVATE_KEY not set in environment.")

    try:
        from py_clob_client_v2 import ClobClient, ApiCreds
    except ImportError:
        raise ImportError(
            "py-clob-client-v2 not installed. "
            "See: https://github.com/Polymarket/py-clob-client-v2"
        )

    api_key    = os.environ.get("POLY_API_KEY",    os.environ.get("CLOB_API_KEY", ""))
    api_secret = os.environ.get("POLY_SECRET",     os.environ.get("CLOB_API_SECRET", ""))
    api_pass   = os.environ.get("POLY_PASSPHRASE", os.environ.get("CLOB_API_PASSPHRASE", ""))

    if api_key and api_secret and api_pass:
        creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_pass)
        return ClobClient(host=CLOB_HOST, chain_id=POLYGON_CHAIN_ID, key=key, creds=creds)

    # 首次執行：自動 derive CLOB API credentials
    print("[pm_trader] No CLOB credentials found — deriving from wallet...")
    tmp = ClobClient(host=CLOB_HOST, chain_id=POLYGON_CHAIN_ID, key=key)
    creds_obj = tmp.create_api_key()
    # create_api_key() returns an ApiCreds dataclass object
    if hasattr(creds_obj, "api_key"):
        api_key    = creds_obj.api_key
        api_secret = creds_obj.api_secret
        api_pass   = creds_obj.api_passphrase
    elif isinstance(creds_obj, dict):
        api_key    = creds_obj.get("apiKey", creds_obj.get("api_key", ""))
        api_secret = creds_obj.get("secret", creds_obj.get("api_secret", ""))
        api_pass   = creds_obj.get("passPhrase", creds_obj.get("api_passphrase", ""))
    else:
        raise ValueError(f"Unexpected credential format: {creds_obj}")

    if not api_key:
        raise ValueError(f"Failed to derive CLOB credentials: {creds_obj}")

    os.environ["CLOB_API_KEY"]        = api_key
    os.environ["CLOB_API_SECRET"]     = api_secret
    os.environ["CLOB_API_PASSPHRASE"] = api_pass
    _append_creds_to_dotenv(api_key, api_secret, api_pass)
    print(f"[pm_trader] CLOB credentials obtained: key={api_key[:8]}...")

    creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_pass)
    return ClobClient(host=CLOB_HOST, chain_id=POLYGON_CHAIN_ID, key=key, creds=creds)


def place_limit_order(client, token_id: str, size_usd: float, limit_price: float) -> dict:
    """送出 GTC 限價買單，回傳包含 orderID 的 response dict。"""
    from py_clob_client_v2 import OrderArgs, OrderType, Side, PartialCreateOrderOptions
    resp = client.create_and_post_order(
        order_args=OrderArgs(token_id=token_id, price=limit_price, size=size_usd, side=Side.BUY),
        options=PartialCreateOrderOptions(tick_size="0.01"),
        order_type=OrderType.GTC,
    )
    return resp if isinstance(resp, dict) else {"orderID": str(resp)}


def market_sell(client, token_id: str, size_usd: float) -> dict:
    """送出 FOK 市價賣單（Fill-or-Kill，清倉用）。"""
    from py_clob_client_v2 import OrderArgs, OrderType, Side, PartialCreateOrderOptions
    resp = client.create_and_post_order(
        order_args=OrderArgs(token_id=token_id, price=0.01, size=size_usd, side=Side.SELL),
        options=PartialCreateOrderOptions(tick_size="0.01"),
        order_type=OrderType.FOK,
    )
    return resp if isinstance(resp, dict) else {}


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


def _try_place(client, token_id, size, limit_price, label, our_prob, market_price, ev, data, existing_keys, ts):
    """送出限價單並更新 portfolio，回傳是否成功。"""
    try:
        resp = place_limit_order(client, token_id=token_id, size_usd=size, limit_price=limit_price)
        order_id = resp.get("orderID", "")
        pos = {
            "market_id": f"{label}",
            "token_id": token_id,
            "team": label,
            "stage": "match",
            "size_usd": size,
            "entry_price": limit_price,
            "our_prob": our_prob,
            "entry_time": ts,
            "order_id": order_id,
            "fixture_id": None,
        }
        portfolio.add_position(pos)
        portfolio.log_trade({"type": "BUY", **pos})
        existing_keys.add(label)
        _tg_notify(
            f"🟢 <b>開倉</b>  {label}\n"
            f"限價：{limit_price:.3f}  倉位：${size:.2f}\n"
            f"我方機率：{our_prob*100:.1f}%  市場：{market_price*100:.1f}%  "
            f"EV：+{ev*100:.1f}¢\n"
            f"時間：{ts} UTC"
        )
        return True
    except Exception as e:
        print(f"[{ts}] ORDER FAILED {label}: {e}")
        return False


def scan_and_trade(client) -> None:
    """
    掃描 EV 機會並自動下注：
    1. 晉級市場（pm_ev_scanner）
    2. 單場勝負市場（pm_match_ev）
    """
    if portfolio.is_halted():
        print("[pm_trader] trading halted (daily loss limit)")
        return

    data = portfolio.load()
    if len(data["positions"]) >= MAX_POSITIONS:
        return

    bankroll = data["bankroll"]
    existing_keys = {p.get("market_id", "") for p in data["positions"]}
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

    # ── 1. 晉級市場 ──────────────────────────────────────────────
    try:
        from src.pm_ev_scanner import fetch_all, build_matrix, find_opportunities
        stage_data = fetch_all()
        matrix = build_matrix(stage_data)
        opps = find_opportunities(matrix, min_ev=MIN_EV)
    except Exception as e:
        print(f"[pm_trader] advancement scanner error: {e}")
        opps = []

    for opp in opps:
        if len(data["positions"]) >= MAX_POSITIONS:
            break
        if opp.ev < MIN_EV or opp.ev_roi < MIN_ROI:
            continue
        key = f"{opp.team}:{opp.to_stage}"
        if key in existing_keys:
            continue
        size = kelly_size(opp.fair_value, opp.p_to, bankroll)
        if size < 1.0:
            continue
        approved, reason = auditor.approve_advancement(opp)
        if not approved:
            print(f"[{ts}] AUDIT REJECT advancement {opp.team}: {reason}")
            continue
        limit_price = round((opp.p_to + opp.fair_value) / 2, 4)
        print(f"[{ts}] BUY advancement {opp.team} [{opp.label}] size=${size} limit={limit_price}")
        if _try_place(client, opp.token_id, size, limit_price, key, opp.fair_value, opp.p_to, opp.ev, data, existing_keys, ts):
            data = portfolio.load()

    # ── 2. 單場勝負市場 ──────────────────────────────────────────
    try:
        from src.pm_match_ev import scan as match_scan
        match_opps = match_scan(min_ev=MIN_EV)
    except Exception as e:
        print(f"[pm_trader] match scanner error: {e}")
        match_opps = []

    for opp in match_opps:
        if len(data["positions"]) >= MAX_POSITIONS:
            break
        for side in ("home_win", "away_win", "draw"):
            ev = opp["ev"][side]
            if ev < MIN_EV:
                continue
            market_price = opp["market"][side]
            our_prob = opp["model"][side]
            if kelly_size(our_prob, market_price, bankroll) < 1.0:
                continue
            token_id = opp["token_ids"].get(side, "")
            if not token_id:
                continue
            side_label = {"home_win": opp["home"], "away_win": opp["away"], "draw": "平局"}[side]
            key = f"{opp['home']}v{opp['away']}:{side}"
            if key in existing_keys:
                continue
            size = kelly_size(our_prob, market_price, bankroll)
            limit_price = round((market_price + our_prob) / 2, 4)
            approved, reason = auditor.approve_match(opp, side)
            if not approved:
                print(f"[{ts}] AUDIT REJECT match {key}: {reason}")
                continue
            label = f"{side_label} ({opp['home']} vs {opp['away']})"
            print(f"[{ts}] BUY match {label} size=${size} limit={limit_price} EV={ev*100:.1f}¢")
            if _try_place(client, token_id, size, limit_price, key, our_prob, market_price, ev, data, existing_keys, ts):
                data = portfolio.load()
            if len(data["positions"]) >= MAX_POSITIONS:
                break


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
