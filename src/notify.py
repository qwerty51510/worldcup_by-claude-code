"""
Notification system: Telegram alerts for injury/lineup changes.
Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env
"""
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(message: str) -> bool:
    """Send plain text message to Telegram channel. Returns True on success."""
    token = _bot_token()
    chat = _chat_id()
    if not token or not chat:
        print(f"[notify] Telegram not configured — skipping: {message[:80]}")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat,
        "text": message,
        "parse_mode": "HTML",
    }).encode()
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
            return resp.get("ok", False)
    except Exception as e:
        print(f"[notify] Telegram error: {e}")
        return False


def alert_injury_update(match_label: str, changes: list[dict]) -> None:
    """
    Send a Telegram alert when injury/lineup changes are detected pre-kickoff.

    changes: [{"team": str, "player": str, "status": str, "impact": str}, ...]
    """
    if not changes:
        return

    now = datetime.utcnow().strftime("%H:%M UTC")
    lines = [f"⚠️ <b>傷兵/陣容更新</b> [{match_label}] @ {now}\n"]

    for c in changes:
        icon = "🔴" if "確定" in c.get("status", "") or "OUT" in c.get("status", "") else "🟡"
        lines.append(
            f"{icon} <b>{c['team']}</b> — {c['player']}\n"
            f"   狀態：{c['status']}\n"
            f"   影響：{c['impact']}"
        )

    message = "\n".join(lines)
    ok = send_telegram(message)
    if ok:
        print(f"[notify] Telegram alert sent for {match_label}")


def alert_pre_kickoff_summary(match_label: str, home: str, away: str,
                               lh: float, la: float,
                               home_win: float, draw: float, away_win: float,
                               ah_line: float, ou_line: float) -> None:
    """Send a pre-kickoff prediction summary to Telegram."""
    ah_str = f"{ah_line:+.1f}" if ah_line else "0"
    msg = (
        f"⚽ <b>開賽預告</b> [{match_label}]\n\n"
        f"<b>{home}</b> vs <b>{away}</b>\n"
        f"λ {lh:.2f} / {la:.2f}\n"
        f"勝率 {home_win:.0%} / {draw:.0%} / {away_win:.0%}\n"
        f"AH {ah_str}  OU {ou_line}\n"
    )
    send_telegram(msg)
