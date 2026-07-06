"""
kickoff_watch.py — persistent background monitor for WC 2026 matches.

Actions:
  T-65 min  fetch confirmed lineup → update injuries → re-predict → Telegram alert
  T+90 min  check for results → update wc2026_results → Telegram final score
  Daily 06:00 UTC  full pipeline refresh (odds, Polymarket, HTML)

Run:
  python3 -m src.kickoff_watch
  # or: python3 src/kickoff_watch.py
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATA_DIR = Path(__file__).parent.parent / "data"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _load_upcoming_matches(lookahead_hours: int = 48) -> list:
    """Scan match files for upcoming matches within lookahead_hours."""
    cutoff = _now() + timedelta(hours=lookahead_hours)
    seen_ids: set = set()
    matches = []
    for path in sorted(DATA_DIR.glob("matches/2026-*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        for m in data.get("matches", []):
            mid = m.get("id")
            if mid in seen_ids:
                continue
            utc_str = m.get("utcDate", "")
            if not utc_str:
                continue
            try:
                kickoff = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if kickoff < _now() - timedelta(hours=3):
                continue   # already finished (with buffer)
            if kickoff > cutoff:
                continue
            status = m.get("status", "")
            if status == "FINISHED":
                continue
            seen_ids.add(mid)
            matches.append({**m, "_kickoff": kickoff})
    return sorted(matches, key=lambda x: x["_kickoff"])


def _match_label(m: dict) -> str:
    h = m.get("homeTeam", {}).get("name", "?")
    a = m.get("awayTeam", {}).get("name", "?")
    return f"{h} vs {a}"


# ── Pipeline wrappers ─────────────────────────────────────────────────────────

def _run_daily_pipeline(date: str) -> None:
    print(f"\n[watch] ── 日常更新 {date} ──────────────────")
    try:
        from src.features import clear_caches
        clear_caches()
        from src.pipeline import run
        run(date)
    except Exception as e:
        print(f"[watch] pipeline error: {e}")


def _run_pre_kickoff(match: dict) -> None:
    label = _match_label(match)
    print(f"\n[watch] ── 開賽前更新：{label} ──────────────")
    try:
        from src.fetch_data import fetch_pre_kickoff_lineups, detect_and_notify_lineup_changes
        from src.features import clear_caches

        lineups = fetch_pre_kickoff_lineups([match])
        if lineups:
            changes = detect_and_notify_lineup_changes([match], lineups)
            if changes:
                clear_caches()
                print(f"[watch] {len(changes)} 傷兵/陣容變化，重新預測中…")
                _re_predict(match)
        else:
            print(f"[watch] {label} 首發名單尚未公布")
            from src.notify import send_telegram
            send_telegram(f"⏳ <b>{label}</b>\n首發名單尚未公布（距開賽 ~65 分鐘）")
    except Exception as e:
        print(f"[watch] pre_kickoff error: {e}")


def _re_predict(match: dict) -> None:
    """Re-run features + predict + render for a single match day."""
    try:
        kickoff: datetime = match["_kickoff"]
        date_str = kickoff.strftime("%Y-%m-%d")
        from src.features import clear_caches, build_features
        from src.predict import predict_all, save_predictions
        from src.render import render_all
        from src.backtest import load_calibration
        import json as _json

        clear_caches()
        data = _json.loads((DATA_DIR / f"matches/{date_str}.json").read_text())
        odds = data.get("odds", {})
        espn_odds_raw = data.get("espn_odds", {})
        espn_odds = {}
        for k, v in espn_odds_raw.items():
            parts = k.split("|")
            if len(parts) == 2:
                espn_odds[tuple(parts)] = v
        pm = data.get("polymarket", {})
        upcoming = [m for m in data.get("matches", [])
                    if m.get("status") in ("TIMED", "SCHEDULED", "IN_PLAY")]
        calibration = load_calibration()
        features = build_features(upcoming, odds, calibration, pm_strengths=pm, espn_odds=espn_odds)
        predictions = predict_all(features, calibration)
        save_predictions(date_str, predictions)
        render_all(date_str)
        print(f"[watch] Re-predicted + rendered for {date_str}")
    except Exception as e:
        print(f"[watch] re_predict error: {e}")


def _check_result(match: dict) -> None:
    """After match should be finished, fetch result and notify."""
    label = _match_label(match)
    print(f"\n[watch] ── 結果檢查：{label} ──────────────")
    try:
        from src.fetch_data import update_wc_results, update_pm_actuals
        from src.features import clear_caches
        from src.notify import send_telegram
        from src.validate import refresh_validation

        new = update_wc_results()
        if new > 0:
            update_pm_actuals()
            clear_caches()
            refresh_validation()
            print(f"[watch] {new} 新結果已更新")
            # Find the result for this specific match
            results = json.loads((DATA_DIR / "wc2026_results.json").read_text())
            h_name = match.get("homeTeam", {}).get("name", "")
            a_name = match.get("awayTeam", {}).get("name", "")
            for r in reversed(results):
                if r.get("home") == h_name and r.get("away") == a_name:
                    hg, ag = r.get("home_goals", "?"), r.get("away_goals", "?")
                    send_telegram(
                        f"🏁 <b>最終比分</b>\n{h_name} <b>{hg} - {ag}</b> {a_name}"
                    )
                    break
        else:
            print(f"[watch] 尚無新結果（可能仍在比賽中）")
    except Exception as e:
        print(f"[watch] check_result error: {e}")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _next_daily_refresh() -> datetime:
    """Next 06:00 UTC."""
    now = _now()
    candidate = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def run_forever() -> None:
    print(f"[watch] 監測腳本啟動 {_fmt(_now())}")

    # Track which actions have fired for each match
    fired_pre: set = set()    # match ids where pre-kickoff ran
    fired_result: set = set() # match ids where result check ran

    # Run initial daily pipeline
    _run_daily_pipeline(_now().strftime("%Y-%m-%d"))

    next_daily = _next_daily_refresh()
    print(f"[watch] 下次日常更新：{_fmt(next_daily)}")

    while True:
        now = _now()

        # ── Daily refresh ───────────────────────────────────────────────
        if now >= next_daily:
            _run_daily_pipeline(now.strftime("%Y-%m-%d"))
            next_daily = _next_daily_refresh()
            print(f"[watch] 下次日常更新：{_fmt(next_daily)}")

        # ── Load upcoming matches and fire actions ──────────────────────
        matches = _load_upcoming_matches(lookahead_hours=48)

        wake_times = [next_daily]  # always wake for daily refresh

        for m in matches:
            mid = m.get("id")
            kickoff: datetime = m["_kickoff"]
            label = _match_label(m)

            t_pre = kickoff - timedelta(minutes=65)
            t_result = kickoff + timedelta(minutes=110)  # ~T+110 min

            # Pre-kickoff action
            if now >= t_pre and mid not in fired_pre:
                fired_pre.add(mid)
                _run_pre_kickoff(m)
            elif now < t_pre:
                wake_times.append(t_pre)

            # Result check action
            if now >= t_result and mid not in fired_result:
                fired_result.add(mid)
                _check_result(m)
            elif now < t_result:
                wake_times.append(t_result)

            # Print upcoming schedule summary once
            if now < t_pre:
                mins_to_pre = int((t_pre - now).total_seconds() / 60)
                print(f"[watch] {label} — 開賽前更新在 {_fmt(t_pre)} ({mins_to_pre} 分鐘後)")

        # ── Sleep until next action ─────────────────────────────────────
        if wake_times:
            next_wake = min(t for t in wake_times if t > now)
            sleep_secs = max(30, (next_wake - now).total_seconds())
            # Cap at 10 min to allow reloading match schedule
            sleep_secs = min(sleep_secs, 600)
            print(f"[watch] 休眠 {int(sleep_secs/60)}m {int(sleep_secs%60)}s → 下次檢查 {_fmt(now + timedelta(seconds=sleep_secs))}")
            time.sleep(sleep_secs)
        else:
            print(f"[watch] 無待處理比賽，休眠 10 分鐘")
            time.sleep(600)


if __name__ == "__main__":
    run_forever()
