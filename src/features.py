def compute_incentive_score(must_win: bool, safe_draw: bool, dead_rubber: bool) -> float:
    if dead_rubber:
        return 0.2
    if must_win:
        return 0.85
    if safe_draw:
        return 0.45
    return 0.6


def compute_sharp_signal(open_handicap: float, current_handicap: float) -> float:
    # positive = line moved toward away team; negative = toward home team
    return current_handicap - open_handicap


def _extract_ah_ou(bookmakers: list) -> tuple:
    ah_line = 0.0
    ou_line = 2.5
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market["key"] == "asian_handicap":
                for outcome in market.get("outcomes", []):
                    if outcome.get("point") is not None:
                        try:
                            ah_line = float(outcome["point"])
                            break
                        except (TypeError, ValueError):
                            pass
            if market["key"] == "totals":
                for outcome in market.get("outcomes", []):
                    if outcome.get("point") is not None:
                        try:
                            ou_line = float(outcome["point"])
                            break
                        except (TypeError, ValueError):
                            pass
    return ah_line, ou_line


def _base_lambda(ah_line: float) -> tuple:
    # seed expected goals from handicap line
    home_base = 1.3 - (ah_line * 0.25)
    away_base = 1.3 + (ah_line * 0.25)
    return max(0.5, home_base), max(0.3, away_base)


def build_features(matches: list, odds: dict, calibration: dict) -> list:
    results = []
    for match in matches:
        match_id = str(match.get("id", ""))
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]

        odds_entry = None
        for entry in odds.values():
            if entry.get("home_team") == home and entry.get("away_team") == away:
                odds_entry = entry
                break

        bookmakers = odds_entry.get("bookmakers", []) if odds_entry else []
        ah_line, ou_line = _extract_ah_ou(bookmakers)
        lambda_home, lambda_away = _base_lambda(ah_line)

        must_win_home = False
        must_win_away = False
        safe_draw = False
        dead_rubber = False

        incentive_home = compute_incentive_score(must_win_home, safe_draw, dead_rubber)
        incentive_away = compute_incentive_score(must_win_away, safe_draw, dead_rubber)
        incentive_score = max(incentive_home, incentive_away)

        boost = calibration.get("incentive_boost", 0.15)
        if must_win_home:
            lambda_home *= (1 + boost)
        if must_win_away:
            lambda_away *= (1 + boost)

        sharp_signal = compute_sharp_signal(ah_line, ah_line)

        results.append({
            "match_id": match_id,
            "home_team": home,
            "away_team": away,
            "lambda_home": round(lambda_home, 3),
            "lambda_away": round(lambda_away, 3),
            "ah_line": ah_line,
            "ou_line": ou_line,
            "sharp_signal": sharp_signal,
            "incentive_score": round(incentive_score, 3),
            "must_win_home": must_win_home,
            "must_win_away": must_win_away,
        })
    return results
