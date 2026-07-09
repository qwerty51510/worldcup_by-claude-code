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
                               ah_line: float, ou_line: float,
                               injuries_json_path: str = "data/injuries.json") -> None:
    """Send pre-kickoff prediction + known injuries + impact scores to Telegram."""
    from pathlib import Path

    ah_str = f"{ah_line:+.1f}" if ah_line else "0"
    lines = [
        f"⚽ <b>開賽預告</b>  {match_label}",
        f"",
        f"<b>{home}</b> vs <b>{away}</b>",
        f"λ {lh:.2f} / {la:.2f}",
        f"勝率 {home_win:.0%} / {draw:.0%} / {away_win:.0%}",
        f"AH {ah_str}  OU {ou_line}",
    ]

    # 讀 injuries.json，分「新缺陣（影響模型）」與「既有缺陣（已反映在近期表現）」
    inj_path = Path(injuries_json_path)
    if inj_path.exists():
        try:
            injuries = json.loads(inj_path.read_text())
        except Exception:
            injuries = {}

        new_lines = []      # already_absent=False — 新傷，影響預測
        old_lines = []      # already_absent=True  — 既有缺陣，僅供參考

        for team in (home, away):
            all_inj = injuries.get(team, {}).get("injuries", [])
            for inj in all_inj:
                player  = inj.get("player", "")
                note    = inj.get("note", "")
                atk     = inj.get("attack_mult", 1.0)
                dfd     = inj.get("defense_mult", 1.0)
                excl    = inj.get("exclude", False)
                absent  = inj.get("already_absent", False)

                icon = "🔴" if excl else ("🟡" if atk < 1.0 or dfd < 1.0 else "⚪")
                if excl:
                    impact_str = " | 缺陣"
                elif atk != 1.0 or dfd != 1.0:
                    parts = []
                    if atk != 1.0:
                        parts.append(f"攻擊×{atk:.2f}")
                    if dfd != 1.0:
                        parts.append(f"防守×{dfd:.2f}")
                    impact_str = f" | {', '.join(parts)}"
                else:
                    impact_str = ""

                line = f"  {icon} <b>{team}</b> {player}{impact_str} — {note}"
                if absent:
                    old_lines.append(line)
                else:
                    new_lines.append(line)

        if new_lines:
            lines.append("")
            lines.append("🆕 <b>新缺陣（已納入預測）</b>")
            lines.extend(new_lines)
        if old_lines:
            lines.append("")
            lines.append("📋 <b>既有缺陣（已反映在近期表現，不重複計算）</b>")
            lines.extend(old_lines)
        if not new_lines and not old_lines:
            lines.append("")
            lines.append("🏥 傷兵：無已知傷情")

    send_telegram("\n".join(lines))
