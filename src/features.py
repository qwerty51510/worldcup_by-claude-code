import math
from src.config import FIFA_RANKINGS, BASE_LAMBDA, RANK_DECAY, AH_LINE_MULTIPLIER

# Log-linear mapping: P(win WC) → strength in range [0.5, 2.0]
# Calibrated so France(19.75%) → 2.0, Qatar(0.05%) → 0.5
_PM_LOG_A = 2.406
_PM_LOG_B = 0.2508


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


def _rank_to_strength(rank: int) -> float:
    return 2.0 * (1.0 / (1.0 + (rank - 1) * RANK_DECAY))


def _pm_to_strength(p_win_wc: float) -> float:
    """Convert Polymarket WC winner probability to team strength (0.5–2.0 range)."""
    p = max(p_win_wc, 0.0005)  # floor at 0.05% to avoid log(0)
    return max(0.5, min(2.0, _PM_LOG_A + _PM_LOG_B * math.log(p)))


def _round_ah(line: float) -> float:
    return round(line * 4) / 4


def _strengths_to_lambdas(home_str: float, away_str: float) -> tuple:
    total = home_str + away_str
    lh = round(max(0.4, BASE_LAMBDA * (home_str / total) * 2.0 + 0.1), 3)
    la = round(max(0.3, BASE_LAMBDA * (away_str / total) * 2.0), 3)
    implied_ah = _round_ah(-(lh - la) * AH_LINE_MULTIPLIER)
    implied_ou = round((lh + la) * 2) / 2
    return lh, la, implied_ah, implied_ou


def _lambda_from_pm(home: str, away: str, pm_strengths: dict) -> tuple:
    """Use Polymarket WC winner probabilities as team strength signal."""
    h_str = _pm_to_strength(pm_strengths[home]) if home in pm_strengths else None
    a_str = _pm_to_strength(pm_strengths[away]) if away in pm_strengths else None

    # fall back to FIFA for teams not in PM market
    if h_str is None:
        h_str = _rank_to_strength(FIFA_RANKINGS.get(home, 40))
    if a_str is None:
        a_str = _rank_to_strength(FIFA_RANKINGS.get(away, 40))

    return _strengths_to_lambdas(h_str, a_str)


def _lambda_from_rankings(home: str, away: str) -> tuple:
    home_str = _rank_to_strength(FIFA_RANKINGS.get(home, 40))
    away_str = _rank_to_strength(FIFA_RANKINGS.get(away, 40))
    return _strengths_to_lambdas(home_str, away_str)


def _extract_ah_ou(bookmakers: list) -> tuple:
    ah_line = None  # None = no odds data
    ou_line = 2.5
    for bm in bookmakers:
        for market in bm.get("markets", []):
            if market["key"] in ("asian_handicap", "spreads"):
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


def _lambda_from_ah_line(ah_line: float) -> tuple:
    home_base = 1.3 - (ah_line * 0.25)
    away_base = 1.3 + (ah_line * 0.25)
    return max(0.5, home_base), max(0.3, away_base)


def build_features(matches: list, odds: dict, calibration: dict, pm_strengths: dict = None) -> list:
    if pm_strengths is None:
        pm_strengths = {}
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

        has_odds = ah_line is not None
        if has_odds:
            lambda_home, lambda_away = _lambda_from_ah_line(ah_line)
            data_source = "盤口線"
        elif pm_strengths and (home in pm_strengths or away in pm_strengths):
            lambda_home, lambda_away, ah_line, ou_line = _lambda_from_pm(home, away, pm_strengths)
            data_source = "Polymarket 實力評估"
        else:
            lambda_home, lambda_away, ah_line, ou_line = _lambda_from_rankings(home, away)
            data_source = "FIFA排名（推算盤口）"

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

        results.append({
            "match_id": match_id,
            "home_team": home,
            "away_team": away,
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "ah_line": ah_line,
            "ou_line": ou_line,
            "sharp_signal": compute_sharp_signal(ah_line, ah_line),
            "incentive_score": round(incentive_score, 3),
            "must_win_home": must_win_home,
            "must_win_away": must_win_away,
            "data_source": data_source,
        })
    return results
