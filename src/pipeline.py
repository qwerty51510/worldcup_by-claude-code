import sys
from datetime import date as dt_date

from src.backtest import compute_brier_score, generate_postmortem, load_calibration, save_calibration, update_calibration
from src.features import build_features
from src.features import clear_caches
from src.fetch_data import fetch_matches, fetch_odds, fetch_espn_odds, fetch_polymarket, save_match_day, update_wc_results, update_team_history, update_pm_actuals
from src.predict import predict_all, save_predictions
from src.render import render_all
from src.tuner import tune_params, save_tuned_params
from src.validate import refresh_validation


def run(date: str) -> None:
    print(f"[pipeline] Running for date: {date}")

    calibration = load_calibration()

    # ── 0. Ensure pre-tournament team history is cached ──────────────────────
    update_team_history()

    # ── 1. Pull latest completed match results into wc2026_results.json ──────
    print("[pipeline] Updating completed WC results...")
    new_results = update_wc_results()
    if new_results > 0:
        print(f"[pipeline] {new_results} new result(s) — refreshing walk-forward validation...")
        update_pm_actuals()
        clear_caches()  # reset stale in-memory data after file update
        refresh_validation()

        # Auto-tune params after each new batch of results
        print("[pipeline] Running parameter tuning...")
        best = tune_params()
        save_tuned_params(best)
        clear_caches()  # force features.py to reload new tuned params

    # ── 2. Fetch today's matches, odds, Polymarket ───────────────────────────
    print("[pipeline] Fetching matches...")
    matches = fetch_matches(date)
    print(f"[pipeline] Found {len(matches)} matches")

    print("[pipeline] Fetching odds (Odds API)...")
    odds = fetch_odds([str(m["id"]) for m in matches])

    print("[pipeline] Fetching DraftKings lines (ESPN)...")
    espn_odds = fetch_espn_odds(date)

    print("[pipeline] Fetching Polymarket...")
    polymarket = fetch_polymarket()

    # only persist match data when we actually fetched something — avoids
    # overwriting real data during local runs without API keys
    if matches or odds or espn_odds or polymarket:
        save_match_day(date, {
            "matches": matches,
            "odds": odds,
            "espn_odds": {f"{k[0]}|{k[1]}": v for k, v in espn_odds.items()},
            "polymarket": polymarket,
        })

    finished = [m for m in matches if m.get("status") == "FINISHED"]
    upcoming = [m for m in matches if m.get("status") in ("TIMED", "SCHEDULED", "IN_PLAY", "PAUSED")]
    print(f"[pipeline] {len(upcoming)} upcoming, {len(finished)} finished")

    # ── 3. Predict upcoming matches ──────────────────────────────────────────
    print("[pipeline] Building features...")
    features = build_features(upcoming, odds, calibration, pm_strengths=polymarket)

    print("[pipeline] Predicting...")
    predictions = predict_all(features, calibration)
    save_predictions(date, predictions)
    if finished:
        brier = compute_brier_score(predictions, finished)
        print(f"[pipeline] Brier Score: {brier:.4f}")
        calibration = update_calibration(calibration, brier, predictions, finished)
        save_calibration(calibration)

    # ── 4. Render all HTML pages ─────────────────────────────────────────────
    print("[pipeline] Rendering HTML...")
    render_all(date)
    print("[pipeline] Done.")


if __name__ == "__main__":
    target_date = sys.argv[1] if len(sys.argv) > 1 else str(dt_date.today())
    run(target_date)
