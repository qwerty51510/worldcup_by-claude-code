import json
from datetime import datetime, timezone, timedelta
from math import exp, factorial
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
_UTC8 = timezone(timedelta(hours=8))


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * exp(-lam) / factorial(k)


def _poisson_ah_prob(lambda_home: float, lambda_away: float, handicap: float) -> float:
    """P(home covers AH): home_goals + handicap > away_goals."""
    max_goals = 10
    prob = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            if (h + handicap) > a:
                prob += _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
    return prob


def _poisson_ou_prob(lambda_home: float, lambda_away: float, line: float) -> float:
    """P(total goals > line) — probability of Over."""
    max_goals = 10
    prob_over = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            if (h + a) > line:
                prob_over += _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
    return prob_over


def _prob_to_confidence(prob: float) -> int:
    return min(100, max(0, int(abs(prob - 0.5) * 200)))


def _predict_score(lambda_home: float, lambda_away: float) -> dict:
    """
    Compute most likely exact score and 1X2 probabilities from Poisson model.
    Returns predicted_score, p_home_win, p_draw, p_away_win.
    """
    max_goals = 8
    best_prob = 0.0
    best_h, best_a = 0, 0
    p_home, p_draw, p_away = 0.0, 0.0, 0.0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
            if p > best_prob:
                best_prob = p
                best_h, best_a = h, a
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p

    return {
        "predicted_score": f"{best_h}-{best_a}",
        "p_home_win": round(p_home, 3),
        "p_draw": round(p_draw, 3),
        "p_away_win": round(p_away, 3),
    }


def _format_kickoff(utc_str: str) -> str:
    """Convert UTC ISO string to UTC+8 display string."""
    if not utc_str:
        return ""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        local = dt.astimezone(_UTC8)
        return local.strftime("%m/%d %H:%M")
    except Exception:
        return utc_str


def _load_injuries() -> dict:
    path = DATA_DIR / "injuries.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _generate_reasoning(home: str, away: str, lh: float, la: float,
                         p_home: float, p_draw: float, p_away: float,
                         ou_pred: str, ou_conf: int) -> str:
    from src.features import _load_elo, _load_wc_team_stats, _WC_LEAGUE_AVG
    from src.config import team_zh
    elo = _load_elo()
    stats = _load_wc_team_stats()

    h_zh, a_zh = team_zh(home), team_zh(away)
    h_elo = elo.get(home, 1500)
    a_elo = elo.get(away, 1500)
    diff = h_elo - a_elo

    if abs(diff) >= 400:
        str_text = f"實力差距懸殊（ELO {diff:+d}）"
    elif abs(diff) >= 200:
        str_text = f"實力有明顯優勢（ELO {diff:+d}）"
    elif abs(diff) >= 80:
        str_text = f"實力略佔優勢（ELO {diff:+d}）"
    else:
        str_text = f"實力相當（ELO {diff:+d}）"

    lines = [f"【強度】{h_zh}（ELO {h_elo}）vs {a_zh}（ELO {a_elo}），{str_text}"]

    form_parts = []
    for team, zh in [(home, h_zh), (away, a_zh)]:
        s = stats.get(team)
        if s and s["played"] > 0:
            form_parts.append(f"{zh} {s['played']}場 進{s['scored']} 失{s['conceded']}")
    if form_parts:
        lines.append("【近況】" + "；".join(form_parts))

    total = lh + la
    ou_label = "大球" if ou_pred == "over" else "小球"
    lines.append(f"【進球預期】主 {lh:.1f} + 客 {la:.1f} = {total:.1f}，傾向{ou_label}（信心 {ou_conf}%）")

    fav_zh = h_zh if p_home > p_away else a_zh
    fav_p = max(p_home, p_away)
    if fav_p >= 0.65:
        lines.append(f"【勝負】{fav_zh} 明顯佔優（勝率 {int(fav_p*100)}%），平局機率 {int(p_draw*100)}%")
    elif fav_p >= 0.50:
        lines.append(f"【勝負】{fav_zh} 略佔優（勝率 {int(fav_p*100)}%），平局機率 {int(p_draw*100)}%")
    else:
        lines.append(f"【勝負】雙方勢均力敵，平局機率 {int(p_draw*100)}% 不低")

    return "\n".join(lines)


def predict_match(feature: dict, calibration: dict) -> dict:
    lh = feature["lambda_home"]
    la = feature["lambda_away"]
    ah_line = feature["ah_line"]
    ou_line = feature["ou_line"]
    sharp = feature["sharp_signal"]
    mul = calibration.get("sharp_money_multiplier", 0.85)

    if sharp > 0.25:
        lh *= mul
    elif sharp < -0.25:
        la *= mul

    ah_prob_home = _poisson_ah_prob(lh, la, ah_line)
    ah_prob_home = min(0.95, max(0.05, ah_prob_home))

    ah_prediction = "home" if ah_prob_home > 0.5 else "away"
    ah_confidence = _prob_to_confidence(ah_prob_home)

    ou_prob_over = _poisson_ou_prob(lh, la, ou_line)
    ou_prediction = "over" if ou_prob_over > 0.5 else "under"
    ou_confidence = _prob_to_confidence(ou_prob_over)

    key_factors = []
    data_source = feature.get("data_source", "")
    if data_source:
        key_factors.append(f"強度來源：{data_source}")
    if feature.get("must_win_home"):
        key_factors.append("主隊必贏場")
    if feature.get("must_win_away"):
        key_factors.append("客隊必贏場")
    if abs(sharp) > 0.25:
        key_factors.append(f"盤口明顯移動 {sharp:+.2f}")
    if not key_factors:
        key_factors.append("Poisson 標準預測")

    score_info = _predict_score(lh, la)
    home = feature["home_team"]
    away = feature["away_team"]

    injuries = _load_injuries()
    injury_notes = []
    for team in [home, away]:
        team_injuries = injuries.get(team, [])
        if team_injuries:
            injury_notes.append(f"{team}：" + "、".join(team_injuries))

    reasoning = _generate_reasoning(
        home, away, lh, la,
        score_info["p_home_win"], score_info["p_draw"], score_info["p_away_win"],
        ou_prediction, ou_confidence,
    )

    return {
        "match_id": feature["match_id"],
        "home_team": home,
        "away_team": away,
        "kickoff": _format_kickoff(feature.get("kickoff_utc", "")),
        "ah_prediction": ah_prediction,
        "ah_confidence": ah_confidence,
        "ou_prediction": ou_prediction,
        "ou_confidence": ou_confidence,
        "predicted_score": score_info["predicted_score"],
        "p_home_win": score_info["p_home_win"],
        "p_draw": score_info["p_draw"],
        "p_away_win": score_info["p_away_win"],
        "key_factors": key_factors,
        "lambda_home": round(lh, 3),
        "lambda_away": round(la, 3),
        "reasoning": reasoning,
        "injury_notes": injury_notes,
    }


def predict_all(features: list, calibration: dict) -> list:
    return [predict_match(f, calibration) for f in features]


def save_predictions(date: str, predictions: list) -> None:
    out_dir = DATA_DIR / "predictions"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{date}.json").write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2)
    )


def _load_predictions(date: str) -> list:
    path = DATA_DIR / "predictions" / f"{date}.json"
    if path.exists():
        return json.loads(path.read_text())
    return []
