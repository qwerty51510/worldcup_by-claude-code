import sys
from datetime import date as dt_date

from src.backtest import compute_brier_score, generate_postmortem, load_calibration, save_calibration, update_calibration
from src.features import build_features
from src.fetch_data import fetch_matches, fetch_odds, fetch_polymarket, save_match_day
from src.predict import predict_all, save_predictions
from src.render import render_all


def run(date: str) -> None:
    print(f"[pipeline] Running for date: {date}")

    calibration = load_calibration()

    print("[pipeline] Fetching matches...")
    matches = fetch_matches(date)
    print(f"[pipeline] Found {len(matches)} matches")

    print("[pipeline] Fetching odds...")
    odds = fetch_odds([str(m["id"]) for m in matches])

    print("[pipeline] Fetching Polymarket...")
    polymarket = fetch_polymarket()

    save_match_day(date, {"matches": matches, "odds": odds, "polymarket": polymarket})

    print("[pipeline] Building features...")
    features = build_features(matches, odds, calibration)

    print("[pipeline] Predicting...")
    predictions = predict_all(features, calibration)
    save_predictions(date, predictions)

    finished = [m for m in matches if m.get("status") == "FINISHED"]
    if finished:
        brier = compute_brier_score(predictions, finished)
        print(f"[pipeline] Brier Score: {brier:.4f}")
        calibration = update_calibration(calibration, brier, predictions, finished)
        save_calibration(calibration)

    print("[pipeline] Rendering HTML...")
    render_all(date)
    print("[pipeline] Done.")


if __name__ == "__main__":
    target_date = sys.argv[1] if len(sys.argv) > 1 else str(dt_date.today())
    run(target_date)
