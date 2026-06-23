import json
from datetime import datetime, timezone, timedelta
from math import exp, factorial
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
_UTC8 = timezone(timedelta(hours=8))


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * exp(-lam) / factorial(k)


def _dc_tau(h: int, a: int, lh: float, la: float, rho: float) -> float:
    """
    Dixon-Coles (1997) low-score correction factor τ.
    rho < 0 boosts 0-0 and 1-1 probabilities (more common in football than
    independent Poisson predicts).  Typical value for international football: -0.13.
    τ = 1 for all scores with h≥2 or a≥2 (no correction needed there).
    """
    if h == 0 and a == 0:
        return 1.0 - lh * la * rho
    if h == 0 and a == 1:
        return 1.0 + lh * rho
    if h == 1 and a == 0:
        return 1.0 + la * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def _poisson_ah_prob(lambda_home: float, lambda_away: float, handicap: float,
                     rho: float = 0.0) -> float:
    """P(home covers AH). rho=0 → standard Poisson; rho<0 → Dixon-Coles correction."""
    max_goals = 10
    prob = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
            if rho != 0.0:
                p *= _dc_tau(h, a, lambda_home, lambda_away, rho)
            if (h + handicap) > a:
                prob += p
    return prob


def _poisson_ou_prob(lambda_home: float, lambda_away: float, line: float,
                     rho: float = 0.0) -> float:
    """P(total goals > line). rho=0 → standard Poisson; rho<0 → Dixon-Coles correction."""
    max_goals = 10
    prob_over = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
            if rho != 0.0:
                p *= _dc_tau(h, a, lambda_home, lambda_away, rho)
            if (h + a) > line:
                prob_over += p
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
                         ou_pred: str, ou_conf: int,
                         feature: dict = None) -> str:
    from src.features import _load_elo, _load_wc_team_stats, _WC_LEAGUE_AVG, STYLE_ZH
    from src.config import team_zh
    elo = _load_elo()
    stats = _load_wc_team_stats()

    h_zh, a_zh = team_zh(home), team_zh(away)
    h_elo = elo.get(home, 1500)
    a_elo = elo.get(away, 1500)
    diff = h_elo - a_elo

    if abs(diff) >= 400:
        str_text = "實力差距懸殊（ELO %+d）" % diff
    elif abs(diff) >= 200:
        str_text = "實力有明顯優勢（ELO %+d）" % diff
    elif abs(diff) >= 80:
        str_text = "實力略佔優勢（ELO %+d）" % diff
    else:
        str_text = "實力相當（ELO %+d）" % diff

    lines = ["【強度】%s（ELO %d）vs %s（ELO %d），%s" % (h_zh, h_elo, a_zh, a_elo, str_text)]

    form_parts = []
    for team, zh in [(home, h_zh), (away, a_zh)]:
        s = stats.get(team)
        if s and s["played"] > 0:
            form_parts.append("%s %d場 進%d 失%d" % (zh, s["played"], s["scored"], s["conceded"]))
    if form_parts:
        lines.append("【近況】" + "；".join(form_parts))

    # Formation + tactics + style matchup insight
    if feature:
        from src.features import _STYLE_MATCHUP
        h_form = feature.get("formation_home", "4-4-2")
        a_form = feature.get("formation_away", "4-4-2")
        h_skey = feature.get("style_home", "balanced")
        a_skey = feature.get("style_away", "balanced")
        h_style = STYLE_ZH.get(h_skey, "均衡")
        a_style = STYLE_ZH.get(a_skey, "均衡")
        h_sm, a_sm = _STYLE_MATCHUP.get((h_skey, a_skey), (1.0, 1.0))

        matchup_note = ""
        if h_skey == "counter" and a_skey in ("attacking", "possession"):
            matchup_note = "，客隊進攻留縫隙，主隊反擊空間大"
        elif a_skey == "counter" and h_skey in ("attacking", "possession"):
            matchup_note = "，主隊進攻留縫隙，客隊反擊空間大"
        elif h_skey == "attacking" and a_skey == "defensive":
            matchup_note = "，主隊難以打開密集防守"
        elif a_skey == "attacking" and h_skey == "defensive":
            matchup_note = "，客隊難以打開密集防守"
        elif h_skey == "attacking" and a_skey == "attacking":
            matchup_note = "，雙方均主動進攻，預計開放式打法"
        elif h_skey == "possession" and a_skey == "counter":
            matchup_note = "，控球被針對，反擊威脅大"
        elif a_skey == "possession" and h_skey == "counter":
            matchup_note = "，客隊控球被針對，反擊威脅大"

        lines.append("【陣型戰術】%s %s（%s）vs %s %s（%s）%s" % (
            h_zh, h_form, h_style, a_zh, a_form, a_style, matchup_note))

        # Stamina
        h_rest = feature.get("rest_days_home", 999)
        a_rest = feature.get("rest_days_away", 999)

        def _rest_desc(days):
            if days >= 999:
                return "首場出賽"
            if days <= 3:
                return "%d天（疲態明顯）" % days
            if days <= 4:
                return "%d天（略有疲態）" % days
            return "%d天（體力充足）" % days

        lines.append("【體力】%s 休息%s；%s 休息%s" % (
            h_zh, _rest_desc(h_rest), a_zh, _rest_desc(a_rest)))

    total = lh + la
    ou_label = "大球" if ou_pred == "over" else "小球"
    lines.append("【進球預期】主 %.1f + 客 %.1f = %.1f，傾向%s（信心 %d%%）" % (
        lh, la, total, ou_label, ou_conf))

    fav_zh = h_zh if p_home > p_away else a_zh
    fav_p = max(p_home, p_away)
    if fav_p >= 0.65:
        lines.append("【勝負】%s 明顯佔優（勝率 %d%%），平局機率 %d%%" % (fav_zh, int(fav_p*100), int(p_draw*100)))
    elif fav_p >= 0.50:
        lines.append("【勝負】%s 略佔優（勝率 %d%%），平局機率 %d%%" % (fav_zh, int(fav_p*100), int(p_draw*100)))
    else:
        lines.append("【勝負】雙方勢均力敵，平局機率 %d%% 不低" % int(p_draw*100))

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
    pm_gap = feature.get("pm_ah_gap")
    if pm_gap is not None:
        direction = "主" if pm_gap > 0 else "客"
        key_factors.append(f"⚠️ PM盤口落差 {pm_gap:+.2f}（PM偏向{direction}隊）")
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
        feature=feature,
    )

    return {
        "match_id": feature["match_id"],
        "home_team": home,
        "away_team": away,
        "kickoff": _format_kickoff(feature.get("kickoff_utc", "")),
        "kickoff_utc": feature.get("kickoff_utc", ""),
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
        "ah_line": ah_line,
        "ou_line": ou_line,
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
