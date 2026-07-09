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
    """Scan match files for upcoming matches within lookahead_hours.

    Includes matches up to T+150 min past kickoff so result checks are not
    missed when the script restarts after a match has already kicked off.
    Excludes matches with null team names (bracket slots not yet determined).
    """
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
            # Skip TBD bracket slots (teams not yet determined)
            home_name = m.get("homeTeam", {}).get("name")
            away_name = m.get("awayTeam", {}).get("name")
            if not home_name or not away_name:
                continue
            utc_str = m.get("utcDate", "")
            if not utc_str:
                continue
            try:
                kickoff = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            # Keep matches up to T+150 min so result check fires even after restart
            if kickoff < _now() - timedelta(minutes=150):
                continue
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


def _run_pre_kickoff(match: dict) -> bool:
    """Fetch confirmed lineup, send injury brief + prediction summary. Returns True if lineup obtained."""
    label = _match_label(match)
    home = match.get("homeTeam", {}).get("name", "?")
    away = match.get("awayTeam", {}).get("name", "?")
    print(f"\n[watch] ── 開賽前更新：{label} ──────────────")
    try:
        from src.fetch_data import fetch_pre_kickoff_lineups, detect_and_notify_lineup_changes
        from src.features import clear_caches, build_features
        from src.predict import predict_all
        from src.backtest import load_calibration
        from src.notify import alert_pre_kickoff_summary
        import json as _json

        # ── 1. 嘗試抓首發名單 ─────────────────────────────────────────
        lineups = fetch_pre_kickoff_lineups([match])
        lineup_confirmed = bool(lineups)

        if lineup_confirmed:
            changes = detect_and_notify_lineup_changes([match], lineups)
            if changes:
                clear_caches()
                print(f"[watch] {len(changes)} 傷兵/陣容變化，重新預測中…")
                _re_predict(match)
        else:
            kickoff: datetime = match["_kickoff"]
            mins_left = int((kickoff - _now()).total_seconds() / 60)
            print(f"[watch] {label} 首發名單尚未公布（距開賽 {mins_left} 分鐘）")

        # ── 2. 無論名單是否確認，主動推送傷兵+預測摘要 ──────────────
        try:
            kickoff_dt: datetime = match["_kickoff"]
            date_str = kickoff_dt.strftime("%Y-%m-%d")
            match_file = DATA_DIR / f"matches/{date_str}.json"
            if match_file.exists():
                data = _json.loads(match_file.read_text())
                odds = data.get("odds", {})
                pm = data.get("polymarket", {})
                espn_odds_raw = data.get("espn_odds", {})
                espn_odds = {tuple(k.split("|")): v for k, v in espn_odds_raw.items() if "|" in k}
                upcoming = [m for m in data.get("matches", [])
                            if m.get("id") == match.get("id")]
                if upcoming:
                    calibration = load_calibration()
                    features = build_features(upcoming, odds, calibration,
                                              pm_strengths=pm, espn_odds=espn_odds)
                    preds = predict_all(features, calibration)
                    if preds:
                        p = preds[0]
                        alert_pre_kickoff_summary(
                            match_label=label,
                            home=home, away=away,
                            lh=p.get("lambda_home", 0),
                            la=p.get("lambda_away", 0),
                            home_win=p.get("p_home_win", 0),
                            draw=p.get("p_draw", 0),
                            away_win=p.get("p_away_win", 0),
                            ah_line=p.get("ah_line", 0),
                            ou_line=p.get("ou_line", 2.5),
                        )
                        print(f"[watch] 傷兵+預測摘要已推送 Telegram")
        except Exception as e:
            print(f"[watch] summary alert error: {e}")

        return lineup_confirmed
    except Exception as e:
        print(f"[watch] pre_kickoff error: {e}")
        return False


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
    h_name = match.get("homeTeam", {}).get("name", "")
    a_name = match.get("awayTeam", {}).get("name", "")
    kickoff: datetime = match["_kickoff"]
    date_str = kickoff.strftime("%Y-%m-%d")
    print(f"\n[watch] ── 結果檢查：{label} ──────────────")
    try:
        from src.fetch_data import update_wc_results, update_pm_actuals
        from src.features import clear_caches
        from src.notify import send_telegram
        from src.validate import refresh_validation
        from src.render import render_all

        new = update_wc_results()
        if new > 0:
            update_pm_actuals()
            clear_caches()
            refresh_validation()
            print(f"[watch] {new} 新結果已更新")
        else:
            print(f"[watch] 結果已在庫中，重新整理 dashboard")

        # Always re-render and notify — results may have been added by pipeline
        clear_caches()
        refresh_validation()
        render_all(date_str)
        print(f"[watch] Dashboard 已更新 ({date_str})")

        # Find and send result notification
        results = json.loads((DATA_DIR / "wc2026_results.json").read_text())
        for r in reversed(results):
            rh = r.get("home", "")
            ra = r.get("away", "")
            if rh == h_name and ra == a_name:
                hg = r.get("home_goals", "?")
                ag = r.get("away_goals", "?")
                hgf = r.get("home_goals_final", hg)
                agf = r.get("away_goals_final", ag)
                duration = r.get("duration", "REGULAR")
                extra = ""
                if duration == "EXTRA_TIME":
                    extra = f"（加時 {hgf}-{agf}）"
                elif duration == "PENALTY_SHOOTOUT":
                    extra = f"（加時平手，罰球 {hgf}-{agf}）"
                send_telegram(
                    f"🏁 <b>最終比分</b>\n{h_name} <b>{hg} - {ag}</b> {a_name}{extra}"
                )
                break
        else:
            send_telegram(f"⏳ <b>{label}</b>\n結果尚未更新，請稍後查看")

        # Run injury multiplier post-match validation
        try:
            from src.injury_validator import validate_all
            validate_all(match_filter=f"{h_name} vs {a_name}")
        except Exception as ve:
            print(f"[watch] injury_validator error: {ve}")
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
    fired_pre: set = set()       # match ids where lineup was successfully fetched
    fired_pre_attempt: set = set()  # match ids where pre-kickoff window opened (may retry)
    fired_result: set = set()    # match ids where result check ran

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

            # Pre-kickoff action: retry every loop until lineup confirmed or kickoff passed
            in_window = t_pre <= now < kickoff
            if in_window and mid not in fired_pre:
                fired_pre_attempt.add(mid)
                got_lineup = _run_pre_kickoff(m)
                if got_lineup:
                    fired_pre.add(mid)  # stop retrying once lineup is confirmed
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
