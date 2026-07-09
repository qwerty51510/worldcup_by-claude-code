"""
執行員：透過 Polymarket CLOB API 連線與下單
V2 EIP-712 DEPOSIT_WALLET（ERC-7739 TypedDataSign）簽章
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from pathlib import Path

import requests
from eth_abi.abi import encode as abi_encode
from eth_account import Account
from eth_utils.crypto import keccak

CLOB_BASE         = "https://clob.polymarket.com"
STANDARD_EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59"
CHAIN_ID          = 137
BYTES32_ZERO      = "0x" + "0" * 64
SIG_TYPE          = 3  # DEPOSIT_WALLET

# tick → amount decimal places (matches py-sdk context.py)
_TICK_AMOUNT_DEC: dict[Decimal, int] = {
    Decimal("0.1"):    3,
    Decimal("0.01"):   4,
    Decimal("0.001"):  5,
    Decimal("0.0001"): 6,
}

_ORDER_TYPE_STRING = (
    "Order("
    "uint256 salt,"
    "address maker,"
    "address signer,"
    "uint256 tokenId,"
    "uint256 makerAmount,"
    "uint256 takerAmount,"
    "uint8 side,"
    "uint8 signatureType,"
    "uint256 timestamp,"
    "bytes32 metadata,"
    "bytes32 builder"
    ")"
)
_TYPED_DATA_SIGN_TYPE_STRING = (
    "TypedDataSign("
    "Order contents,"
    "string name,"
    "string version,"
    "uint256 chainId,"
    "address verifyingContract,"
    "bytes32 salt"
    ")" + _ORDER_TYPE_STRING
)
_DOMAIN_TYPE_STRING = (
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)
_ORDER_TYPE_HASH     = keccak(_ORDER_TYPE_STRING.encode())
_TDS_TYPE_HASH       = keccak(_TYPED_DATA_SIGN_TYPE_STRING.encode())
_DOMAIN_TYPE_HASH    = keccak(_DOMAIN_TYPE_STRING.encode())
_PROTOCOL_NAME_HASH  = keccak(b"Polymarket CTF Exchange")
_PROTOCOL_VER_HASH   = keccak(b"2")

_exchange_cache: dict[str, str] = {}
_tick_cache:     dict[str, Decimal] = {}


def _load_env() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _pad_b64(value: str) -> str:
    return value + "=" * ((-len(value)) % 4)


def _signer() -> tuple[str, bytes]:
    """回傳 (eoa_address, private_key_bytes)，從 POLY_PRIVATE_KEY 讀取"""
    _load_env()
    priv = bytes.fromhex(os.environ["POLY_PRIVATE_KEY"].lstrip("0x"))
    addr = Account.from_key(priv).address
    return addr, priv


def _headers(method: str, path: str, body: str = "") -> dict:
    """L2 auth headers（urlsafe base64 HMAC，POLY_ADDRESS = EOA 地址）"""
    _load_env()
    ts   = str(int(time.time()))
    base = path.split("?")[0]
    msg  = ts + method.upper() + base
    if body:
        msg += body
    key = base64.urlsafe_b64decode(_pad_b64(os.environ["POLY_SECRET"]))
    sig = base64.urlsafe_b64encode(
        hmac.new(key, msg.encode("utf-8"), digestmod=hashlib.sha256).digest()
    ).decode()
    signer_addr, _ = _signer()
    return {
        "POLY_ADDRESS":    signer_addr,
        "POLY_API_KEY":    os.environ["POLY_API_KEY"],
        "POLY_PASSPHRASE": os.environ["POLY_PASSPHRASE"],
        "POLY_TIMESTAMP":  ts,
        "POLY_SIGNATURE":  sig,
        "Content-Type":    "application/json",
    }


def _get_tick_size(token_id: str) -> Decimal:
    """從 CLOB API 取得 token minimum tick size，結果快取"""
    if token_id in _tick_cache:
        return _tick_cache[token_id]
    try:
        r = requests.get(
            f"{CLOB_BASE}/tick-size",
            params={"token_id": token_id},
            timeout=8,
        )
        if r.ok:
            tick = Decimal(str(r.json().get("minimum_tick_size", "0.001")))
            _tick_cache[token_id] = tick
            return tick
    except Exception:
        pass
    return Decimal("0.001")


def _get_exchange(token_id: str) -> str:
    """偵測 token 使用 standard 或 neg-risk exchange，結果快取"""
    if token_id in _exchange_cache:
        return _exchange_cache[token_id]
    try:
        r = requests.get(
            f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}",
            timeout=8,
        )
        if r.ok:
            markets = r.json()
            if markets and markets[0].get("negRisk"):
                _exchange_cache[token_id] = NEG_RISK_EXCHANGE
                return NEG_RISK_EXCHANGE
    except Exception:
        pass
    _exchange_cache[token_id] = STANDARD_EXCHANGE
    return STANDARD_EXCHANGE


def _domain_sep(exchange: str) -> bytes:
    """計算 EIP-712 domain separator（bytes）"""
    encoded = abi_encode(
        ["bytes32", "bytes32", "bytes32", "uint256", "address"],
        [_DOMAIN_TYPE_HASH, _PROTOCOL_NAME_HASH, _PROTOCOL_VER_HASH, CHAIN_ID, exchange],
    )
    return keccak(encoded)


def _sign_order(token_id: str, price: float, size_usdc: float) -> dict:
    """建構並 EIP-712 V2 DEPOSIT_WALLET 簽署 BUY limit order，回傳 order dict"""
    _load_env()
    wallet       = os.environ["POLY_MAKER"]
    _, priv      = _signer()

    # 1. 取得 tick 並將價格 snap DOWN 到最近的 tick 倍數
    tick  = _get_tick_size(token_id)
    a_dec = _TICK_AMOUNT_DEC.get(tick, 5)
    _p    = (Decimal(str(price)) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    _s    = Decimal(str(size_usdc))

    # 2. 計算股數與金額（對齊 py-sdk _compute_limit_order_amounts BUY 邏輯）
    _shares   = (_s / _p).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    _maker_d  = _shares * _p                          # USDC，小數位 = shares_dec + tick_dec
    q_amt     = Decimal(10) ** -a_dec
    # 先 round_up 再 round_down，確保不超出 amount_decimals
    _maker_d  = _maker_d.quantize(Decimal(10) ** -(a_dec + 4), rounding=ROUND_CEILING)
    _maker_d  = _maker_d.quantize(q_amt, rounding=ROUND_DOWN)
    maker_amt = int((_maker_d  * 1_000_000).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    taker_amt = int((_shares   * 1_000_000).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    salt         = secrets.randbits(53)
    timestamp_ms = int(time.time() * 1000)
    exchange     = _get_exchange(token_id)

    # Order struct hash（= contents_hash for trailer）
    contents_hash = keccak(abi_encode(
        ["bytes32", "uint256", "address", "address", "uint256",
         "uint256", "uint256", "uint8", "uint8", "uint256", "bytes32", "bytes32"],
        [_ORDER_TYPE_HASH, salt, wallet, wallet, int(token_id),
         maker_amt, taker_amt, 0, SIG_TYPE, timestamp_ms, bytes(32), bytes(32)],
    ))

    # TypedDataSign struct hash
    app_sep_bytes = _domain_sep(exchange)
    tds_struct_hash = keccak(abi_encode(
        ["bytes32", "bytes32", "bytes32", "bytes32", "uint256", "address", "bytes32"],
        [_TDS_TYPE_HASH, contents_hash, keccak(b"DepositWallet"),
         keccak(b"1"), CHAIN_ID, wallet, bytes(32)],
    ))
    tds_full_hash = keccak(b"\x19\x01" + app_sep_bytes + tds_struct_hash)

    inner_sig = Account._sign_hash(tds_full_hash, priv).signature

    # 追加 DEPOSIT_WALLET trailer
    trailer = (
        app_sep_bytes.hex()
        + contents_hash.hex()
        + _ORDER_TYPE_STRING.encode().hex()
        + f"{len(_ORDER_TYPE_STRING):04x}"
    )
    final_sig = "0x" + inner_sig.hex() + trailer

    return {
        "builder":       BYTES32_ZERO,
        "expiration":    "0",
        "maker":         wallet,
        "makerAmount":   str(maker_amt),
        "metadata":      BYTES32_ZERO,
        "salt":          salt,
        "side":          "BUY",
        "signature":     final_sig,
        "signatureType": SIG_TYPE,
        "signer":        wallet,
        "takerAmount":   str(taker_amt),
        "timestamp":     str(timestamp_ms),
        "tokenId":       str(int(token_id)),
    }


def _sign_sell_order(token_id: str, shares: float, min_price: float) -> dict:
    """建構並 EIP-712 V2 DEPOSIT_WALLET 簽署 SELL limit order，回傳 order dict"""
    _load_env()
    wallet       = os.environ["POLY_MAKER"]
    _, priv      = _signer()

    # 1. 取得 tick，價格 snap UP（賣單不接受低於底價）
    tick  = _get_tick_size(token_id)
    a_dec = _TICK_AMOUNT_DEC.get(tick, 5)
    _p    = (Decimal(str(min_price)) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    _shares_d = Decimal(str(shares)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    # 2. SELL: makerAmt = shares（你給出）, takerAmt = shares × price（你收取 USDC）
    _taker_d = _shares_d * _p
    q_amt    = Decimal(10) ** -a_dec
    _taker_d = _taker_d.quantize(Decimal(10) ** -(a_dec + 4), rounding=ROUND_CEILING)
    _taker_d = _taker_d.quantize(q_amt, rounding=ROUND_DOWN)
    maker_amt = int((_shares_d * 1_000_000).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
    taker_amt = int((_taker_d  * 1_000_000).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))

    salt         = secrets.randbits(53)
    timestamp_ms = int(time.time() * 1000)
    exchange     = _get_exchange(token_id)

    contents_hash = keccak(abi_encode(
        ["bytes32", "uint256", "address", "address", "uint256",
         "uint256", "uint256", "uint8", "uint8", "uint256", "bytes32", "bytes32"],
        [_ORDER_TYPE_HASH, salt, wallet, wallet, int(token_id),
         maker_amt, taker_amt, 1, SIG_TYPE, timestamp_ms, bytes(32), bytes(32)],
    ))

    app_sep_bytes   = _domain_sep(exchange)
    tds_struct_hash = keccak(abi_encode(
        ["bytes32", "bytes32", "bytes32", "bytes32", "uint256", "address", "bytes32"],
        [_TDS_TYPE_HASH, contents_hash, keccak(b"DepositWallet"),
         keccak(b"1"), CHAIN_ID, wallet, bytes(32)],
    ))
    tds_full_hash = keccak(b"\x19\x01" + app_sep_bytes + tds_struct_hash)
    inner_sig     = Account._sign_hash(tds_full_hash, priv).signature

    trailer = (
        app_sep_bytes.hex()
        + contents_hash.hex()
        + _ORDER_TYPE_STRING.encode().hex()
        + f"{len(_ORDER_TYPE_STRING):04x}"
    )
    final_sig = "0x" + inner_sig.hex() + trailer

    return {
        "builder":       BYTES32_ZERO,
        "expiration":    "0",
        "maker":         wallet,
        "makerAmount":   str(maker_amt),
        "metadata":      BYTES32_ZERO,
        "salt":          salt,
        "side":          "SELL",
        "signature":     final_sig,
        "signatureType": SIG_TYPE,
        "signer":        wallet,
        "takerAmount":   str(taker_amt),
        "timestamp":     str(timestamp_ms),
        "tokenId":       str(int(token_id)),
    }


def place_sell_order(token_id: str, shares: float, min_price: float) -> tuple[bool, str]:
    """送出真實 V2 CLOB SELL limit order，回傳 (success, message)"""
    if not token_id:
        return False, "無 token_id"
    try:
        order = _sign_sell_order(token_id, shares, min_price)
        body  = json.dumps(
            {
                "deferExec": False,
                "order":     order,
                "orderType": "GTC",
                "owner":     os.environ["POLY_API_KEY"],
            },
            separators=(",", ":"), ensure_ascii=False,
        )
        r    = requests.post(
            f"{CLOB_BASE}/order",
            headers=_headers("POST", "/order", body),
            data=body,
            timeout=15,
        )
        data = r.json()
        if r.status_code == 200 and data.get("success"):
            return True, f"已成交 order_id={data.get('orderID', '?')}"
        return False, f"HTTP {r.status_code} — {data.get('error', r.text[:200])}"
    except Exception as e:
        return False, str(e)


def cancel_order(order_id: str) -> tuple[bool, str]:
    """取消 CLOB GTC 掛單，回傳 (success, message)"""
    if not order_id:
        return False, "無 order_id"
    try:
        path = f"/order/{order_id}"
        r = requests.delete(
            f"{CLOB_BASE}{path}",
            headers=_headers("DELETE", path),
            timeout=10,
        )
        if r.status_code == 200:
            return True, f"已取消 {order_id}"
        return False, f"HTTP {r.status_code} — {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def test_connection() -> tuple[bool, str]:
    try:
        r = requests.get(f"{CLOB_BASE}/time", headers=_headers("GET", "/time"), timeout=10)
        if r.status_code == 200:
            return True, f"server time={r.json()}"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


def preview_order(bet) -> str:
    shares = bet.size_usdc / bet.price
    payout = shares * 1.0
    profit = payout - bet.size_usdc
    return (
        f"  LIMIT BUY  {bet.team} {bet.label}\n"
        f"    出價 {bet.price*100:.1f}¢  投入 ${bet.size_usdc:.0f} USDC"
        f"  → {shares:.0f} 股  中獎 ${payout:.0f}（利潤 +${profit:.0f}）"
    )


def place_order(bet) -> tuple[bool, str]:
    """送出真實 V2 CLOB limit order，回傳 (success, message)"""
    if not bet.token_id:
        return False, f"無 token_id（{bet.team} {bet.label}）"
    try:
        order = _sign_order(bet.token_id, bet.price, bet.size_usdc)
        body  = json.dumps(
            {
                "deferExec": False,
                "order":     order,
                "orderType": "GTC",
                "owner":     os.environ["POLY_API_KEY"],
            },
            separators=(",", ":"), ensure_ascii=False,
        )
        r    = requests.post(
            f"{CLOB_BASE}/order",
            headers=_headers("POST", "/order", body),
            data=body,
            timeout=15,
        )
        data = r.json()
        if r.status_code == 200 and data.get("success"):
            return True, f"已成交 order_id={data.get('orderID', '?')}"
        return False, f"HTTP {r.status_code} — {data.get('error', r.text[:200])}"
    except Exception as e:
        return False, str(e)


def execute(bets: list, dry_run: bool = True) -> tuple[list[str], list[dict]]:
    """回傳 (log_lines, placed_bets)；placed_bets 在 live 模式下含成功下單資訊"""
    logs, placed = [], []
    for bet in bets:
        if dry_run:
            logs.append(preview_order(bet))
        else:
            ok, msg = place_order(bet)
            status = "✓" if ok else "✗"
            logs.append(f"  {status} {bet.team} {bet.label}  ${bet.size_usdc:.0f} @ {bet.price*100:.1f}¢  → {msg}")
            if ok:
                # 取出 order_id 供持倉追蹤
                oid = msg.split("order_id=")[-1] if "order_id=" in msg else ""
                placed.append({
                    "team":        bet.team,
                    "label":       bet.label,
                    "token_id":    bet.token_id,
                    "price":       bet.price,
                    "size_usdc":   bet.size_usdc,
                    "fair_value":  getattr(bet, "fair_value", 0.0),
                    "order_id":    oid,
                })
    return logs, placed


def fetch_user_trades() -> list[dict]:
    """從 CLOB /data/trades 取得使用者所有已成交交易"""
    _load_env()
    maker = os.environ["POLY_MAKER"]
    qs    = f"?user={maker}"
    try:
        r = requests.get(
            f"{CLOB_BASE}/data/trades{qs}",
            headers=_headers("GET", f"/data/trades{qs}"),
            timeout=10,
        )
        if r.ok:
            return r.json().get("data", [])
    except Exception:
        pass
    return []
