#!/usr/bin/env python3
"""
wallet_monitor.py — Polygon 鏈上錢包 tx 監聽器

監聽策略：
  - 每 POLL_INTERVAL 秒輪詢一次 Polygon RPC
  - 掃描最新 N 個區塊的 USDC/USDC.e Transfer 事件（錢包為 from 或 to）
  - 也偵測 CTF ERC-1155 TransferSingle 事件（Polymarket 開/平倉）
  - 新 tx 發現時推送 Telegram

用法：
  python -m src.wallet_monitor              # 單次掃描
  python -m src.wallet_monitor --daemon     # 持續監聽（預設每 60 秒）
  python -m src.wallet_monitor --daemon --interval 30
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── 常數 ────────────────────────────────────────────────────────────────────
POLYGON_RPC      = "https://polygon.drpc.org"   # 免費，無速率限制問題
POLL_INTERVAL    = 60
BLOCK_LOOKBACK   = 120         # ~4 分鐘，drpc 無 50-block 限制
STATE_FILE       = Path("data/wallet_monitor_state.json")

# Polygon 合約地址（從實際 tx receipt 確認）
USDC_POS      = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"   # USDC (PoS)
USDC_E        = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"   # USDC.e (native)
CTF_CONTRACT  = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"  # Polymarket CTF tokens
CLOB_EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"   # Polymarket CLOB Exchange

# Event topic hashes
TRANSFER_TOPIC        = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # ERC-20 Transfer
TRANSFER_SINGLE_TOPIC = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"  # ERC-1155 TransferSingle
TRANSFER_BATCH_TOPIC  = "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"  # ERC-1155 TransferBatch

TOKEN_DECIMALS = {
    USDC_POS.lower(): 6,
    USDC_E.lower():   6,
}
TOKEN_NAME = {
    USDC_POS.lower(): "USDC(PoS)",
    USDC_E.lower():   "USDC.e",
    CTF_CONTRACT.lower(): "CTF",
}


# ── RPC 工具 ─────────────────────────────────────────────────────────────────
def rpc(method: str, params: list) -> dict:
    r = requests.post(
        POLYGON_RPC,
        json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
        timeout=12,
    )
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"RPC error: {d['error']}")
    return d.get("result")


def get_block_number() -> int:
    return int(rpc("eth_blockNumber", []), 16)


def pad_address(addr: str) -> str:
    """把 0x... 地址 pad 成 32-byte topic 格式。"""
    return "0x" + addr.lower().removeprefix("0x").zfill(64)


def get_logs(from_block: int, to_block: int, contracts: list, topics_filter: list) -> list:
    params = [{
        "fromBlock": hex(from_block),
        "toBlock":   hex(to_block),
        "address":   contracts,
        "topics":    topics_filter,
    }]
    result = rpc("eth_getLogs", params)
    return result if isinstance(result, list) else []


# ── 狀態管理 ─────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_block": 0, "seen_tx_hashes": []}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Telegram 推送 ────────────────────────────────────────────────────────────
def tg_notify(text: str):
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[wallet_monitor] Telegram 未設定，跳過推送")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=8,
        )
    except Exception as e:
        print(f"[wallet_monitor] Telegram 推送失敗：{e}")


# ── 解析 ERC-20 Transfer ─────────────────────────────────────────────────────
def parse_erc20_transfer(log: dict, wallet: str):
    topics = log.get("topics", [])
    if len(topics) < 3:
        return None
    from_addr = "0x" + topics[1][-40:]
    to_addr   = "0x" + topics[2][-40:]
    wallet_l  = wallet.lower()
    if from_addr != wallet_l and to_addr != wallet_l:
        return None

    contract  = log["address"].lower()
    decimals  = TOKEN_DECIMALS.get(contract, 6)
    raw_value = int(log.get("data", "0x0"), 16)
    amount    = raw_value / (10 ** decimals)
    direction = "OUT ↑" if from_addr == wallet_l else "IN ↓"
    counterparty = to_addr if from_addr == wallet_l else from_addr

    return {
        "type":         "ERC20",
        "token":        TOKEN_NAME.get(contract, contract[:10]),
        "direction":    direction,
        "amount":       amount,
        "from":         from_addr,
        "to":           to_addr,
        "counterparty": counterparty,
        "tx_hash":      log["transactionHash"],
        "block":        int(log["blockNumber"], 16),
    }


# ── 解析 ERC-1155 TransferSingle (CTF) ───────────────────────────────────────
def parse_ctf_transfer(log: dict, wallet: str):
    topics = log.get("topics", [])
    if len(topics) < 4:
        return None
    from_addr = "0x" + topics[2][-40:]
    to_addr   = "0x" + topics[3][-40:]
    wallet_l  = wallet.lower()
    if from_addr != wallet_l and to_addr != wallet_l:
        return None

    # data = abi.encode(id, value) = 32+32 bytes
    data      = log.get("data", "0x")
    raw       = bytes.fromhex(data.removeprefix("0x"))
    token_id  = int.from_bytes(raw[:32], "big") if len(raw) >= 32 else 0
    shares    = int.from_bytes(raw[32:64], "big") / 1e6 if len(raw) >= 64 else 0

    direction = "SELL (出倉)" if from_addr == wallet_l else "BUY (入倉)"

    return {
        "type":      "CTF",
        "direction": direction,
        "token_id":  str(token_id)[:12] + "...",
        "shares":    shares,
        "from":      from_addr,
        "to":        to_addr,
        "tx_hash":   log["transactionHash"],
        "block":     int(log["blockNumber"], 16),
    }


# ── 格式化 Telegram 訊息 ─────────────────────────────────────────────────────
def format_message(event: dict) -> str:
    tx_short = event["tx_hash"][:10] + "..."
    poly_link = f"https://polygonscan.com/tx/{event['tx_hash']}"
    block = event["block"]
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if event["type"] == "ERC20":
        emoji = "💸" if "OUT" in event["direction"] else "💰"
        return (
            f"{emoji} <b>錢包異動</b>  {ts}\n"
            f"方向：{event['direction']}  {event['token']}\n"
            f"金額：<b>${event['amount']:.2f}</b>\n"
            f"對方：<code>{event['counterparty'][:10]}…</code>\n"
            f"區塊：{block}\n"
            f"<a href=\"{poly_link}\">Polygonscan ↗</a>"
        )
    else:  # CTF
        emoji = "📤" if "SELL" in event["direction"] else "📥"
        return (
            f"{emoji} <b>CTF 倉位異動</b>  {ts}\n"
            f"方向：{event['direction']}\n"
            f"股數：<b>{event['shares']:.1f}</b> 股\n"
            f"TokenID：<code>{event['token_id']}</code>\n"
            f"區塊：{block}\n"
            f"<a href=\"{poly_link}\">Polygonscan ↗</a>"
        )


# ── 主掃描邏輯 ───────────────────────────────────────────────────────────────
def scan_once(wallet: str, state: dict) -> dict:
    try:
        current_block = get_block_number()
    except Exception as e:
        print(f"[wallet_monitor] RPC 取得區塊失敗：{e}")
        return state

    from_block = max(state.get("last_block", current_block - BLOCK_LOOKBACK),
                     current_block - BLOCK_LOOKBACK)
    if from_block >= current_block:
        return state

    wallet_padded = pad_address(wallet)
    seen = set(state.get("seen_tx_hashes", []))
    new_events = []

    # ── USDC 轉入 (to = wallet)
    try:
        logs = get_logs(from_block, current_block,
                        [USDC_POS, USDC_E],
                        [TRANSFER_TOPIC, None, wallet_padded])
        for log in logs:
            ev = parse_erc20_transfer(log, wallet)
            if ev and ev["tx_hash"] not in seen:
                new_events.append(ev)
                seen.add(ev["tx_hash"])
    except Exception as e:
        print(f"[wallet_monitor] USDC 轉入掃描失敗：{e}")

    # ── USDC 轉出 (from = wallet)
    try:
        logs = get_logs(from_block, current_block,
                        [USDC_POS, USDC_E],
                        [TRANSFER_TOPIC, wallet_padded, None])
        for log in logs:
            ev = parse_erc20_transfer(log, wallet)
            if ev and ev["tx_hash"] not in seen:
                new_events.append(ev)
                seen.add(ev["tx_hash"])
    except Exception as e:
        print(f"[wallet_monitor] USDC 轉出掃描失敗：{e}")

    # ── CTF 倉位：抓 CLOB Exchange 發出的所有 CTF 事件，再判斷 tx.from == wallet
    # Polymarket 以 operator 模式轉帳，from=wallet 是正確的 topic[2]，
    # 但為求完整也抓 CLOB Exchange 上的事件（tx.from = wallet）
    try:
        # topic[2]=wallet：直接轉出
        logs_direct = get_logs(from_block, current_block,
                               [CTF_CONTRACT],
                               [TRANSFER_SINGLE_TOPIC, None, wallet_padded, None])
        # topic[3]=wallet：收進
        logs_recv   = get_logs(from_block, current_block,
                               [CTF_CONTRACT],
                               [TRANSFER_SINGLE_TOPIC, None, None, wallet_padded])
        # CLOB Exchange 上所有 CTF 事件（TransferSingle + TransferBatch）→ 後查 tx.from
        logs_clob   = get_logs(from_block, current_block,
                               [CLOB_EXCHANGE],
                               [[TRANSFER_SINGLE_TOPIC, TRANSFER_BATCH_TOPIC]])
        # 對 CLOB logs 確認 tx.from == wallet
        clob_wallet_logs = []
        checked_txs = {}
        for log in logs_clob:
            tx_hash = log["transactionHash"]
            if tx_hash not in checked_txs:
                try:
                    tx = rpc("eth_getTransactionByHash", [tx_hash])
                    checked_txs[tx_hash] = (tx or {}).get("from", "").lower()
                except Exception:
                    checked_txs[tx_hash] = ""
            if checked_txs[tx_hash] == wallet.lower():
                clob_wallet_logs.append(log)

        for log in logs_direct + logs_recv + clob_wallet_logs:
            ev = parse_ctf_transfer(log, wallet)
            if ev and ev["tx_hash"] not in seen:
                new_events.append(ev)
                seen.add(ev["tx_hash"])
    except Exception as e:
        print(f"[wallet_monitor] CTF 掃描失敗：{e}")

    # ── 推送
    for ev in new_events:
        msg = format_message(ev)
        print(f"[wallet_monitor] 新 tx: {ev['type']} {ev['direction']} hash={ev['tx_hash'][:12]}")
        tg_notify(msg)

    # 只保留最近 500 筆 hash，避免無限增長
    state["last_block"]      = current_block
    state["seen_tx_hashes"]  = list(seen)[-500:]
    return state


# ── 入口 ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Polygon 錢包鏈上監聽器")
    parser.add_argument("--daemon",   action="store_true", help="持續監聽模式")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help="輪詢間隔（秒）")
    args = parser.parse_args()

    wallet = os.environ.get("WALLET_ADDRESS", "")
    if not wallet:
        raise SystemExit("ERROR: WALLET_ADDRESS 未設定")

    print(f"[wallet_monitor] 監聽錢包：{wallet[:8]}...{wallet[-6:]}")
    print(f"[wallet_monitor] RPC：{POLYGON_RPC}")
    print(f"[wallet_monitor] 模式：{'daemon' if args.daemon else '單次掃描'}")

    state = load_state()

    if args.daemon:
        tg_notify(f"👁️ <b>錢包監聽器啟動</b>\n"
                  f"地址：<code>{wallet[:8]}…{wallet[-6:]}</code>\n"
                  f"間隔：每 {args.interval} 秒掃描一次")
        while True:
            try:
                state = scan_once(wallet, state)
                save_state(state)
            except Exception as e:
                print(f"[wallet_monitor] 掃描異常：{e}")
            time.sleep(args.interval)
    else:
        state = scan_once(wallet, state)
        save_state(state)
        print("[wallet_monitor] 單次掃描完成")


if __name__ == "__main__":
    main()
