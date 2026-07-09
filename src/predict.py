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


def ko_outcome_probs(lh: float, la: float) -> dict:
    """
    Full knockout probability tree: 90min → ET → penalties.
    Returns dict with probabilities for each path.
    ET lambda = 90min lambda * (30/90) * 0.85 (fatigue reduces scoring rate).
    Penalty shootout: 50/50 base (historical edge negligible).
    """
    max_g = 10

    def pmf(k, lam):
        return _poisson_pmf(k, lam)

    # 90-minute outcomes
    p_h90 = p_d90 = p_a90 = 0.0
    for h in range(max_g + 1):
        for a in range(max_g + 1):
            p = pmf(h, lh) * pmf(a, la)
            if h > a:
                p_h90 += p
            elif h == a:
                p_d90 += p
            else:
                p_a90 += p

    # ET lambdas: 30/90 of 90min rate, further reduced by fatigue factor
    lh_et = lh * (30 / 90) * 0.85
    la_et = la * (30 / 90) * 0.85

    # ET outcomes (conditional on draw at 90')
    p_h_et = p_d_et = p_a_et = 0.0
    for h in range(max_g + 1):
        for a in range(max_g + 1):
            p = pmf(h, lh_et) * pmf(a, la_et)
            if h > a:
                p_h_et += p
            elif h == a:
                p_d_et += p
            else:
                p_a_et += p

    # Penalty shootout: roughly 50/50
    p_pens = p_d90 * p_d_et

    # Overall win probabilities
    p_home_wins = p_h90 + p_d90 * (p_h_et + p_d_et * 0.50)
    p_away_wins = p_a90 + p_d90 * (p_a_et + p_d_et * 0.50)

    return {
        "p_home_90": round(p_h90, 4),
        "p_draw_90": round(p_d90, 4),
        "p_away_90": round(p_a90, 4),
        "p_et": round(p_d90, 4),
        "p_penalties": round(p_pens, 4),
        "p_home_wins": round(p_home_wins, 4),
        "p_away_wins": round(p_away_wins, 4),
    }


def _prob_to_confidence(prob: float) -> int:
    return min(100, max(0, int(abs(prob - 0.5) * 200)))


def _predict_score(lambda_home: float, lambda_away: float,
                   ou_line: float = None, ou_over: bool = None) -> dict:
    """
    Compute 1X2 probabilities and the joint-mode exact score (highest single probability).
    The mode score is the most likely single outcome — it may differ from the OU call
    direction because many low-probability Over scores can still sum to >50%.
    """
    max_goals = 8
    best_prob = 0.0
    best_h = best_a = 0
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
        "predicted_score_prob": round(best_prob * 100, 1),
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
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    result = {}
    for team, val in raw.items():
        if team.startswith("_"):
            continue
        if isinstance(val, list):
            result[team] = val
        elif isinstance(val, dict):
            injuries = val.get("injuries", [])
            if injuries:
                result[team] = [f"{inj['player']}（{inj['note']}）" for inj in injuries]
    return result


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

    # Group context: standings + motivation
    group_ctx = feature.get("group_context", {}) if feature else {}
    if group_ctx:
        grp = group_ctx.get("group", "")
        h_st = group_ctx.get("home_standing", {})
        a_st = group_ctx.get("away_standing", {})
        dead_rubber = group_ctx.get("dead_rubber", False)
        must_win_home = group_ctx.get("must_win_home", False)
        must_win_away = group_ctx.get("must_win_away", False)
        safe_draw_home = group_ctx.get("safe_draw_home", False)
        safe_draw_away = group_ctx.get("safe_draw_away", False)

        if h_st and a_st:
            h_pts, h_gd = h_st.get("pts", 0), h_st.get("gd", 0)
            a_pts, a_gd = a_st.get("pts", 0), a_st.get("gd", 0)
            bg = "%s組第%d輪" % (grp, h_st.get("played", 0) + 1) if grp else ""
            bg += "，%s（%d分 淨%+d）vs %s（%d分 淨%+d）" % (
                h_zh, h_pts, h_gd, a_zh, a_pts, a_gd)
            motives = []
            if dead_rubber:
                home_elim = group_ctx.get("home_eliminated", False)
                away_elim = group_ctx.get("away_eliminated", False)
                if home_elim and away_elim:
                    motives.append("雙方均已出局，可能輪換主力")
                elif home_elim:
                    motives.append("%s已出局，客隊保平可出線" % h_zh)
                elif away_elim:
                    motives.append("%s已出局，主隊保平可出線" % a_zh)
                else:
                    motives.append("雙方均已確保出線，可能輪換主力")
            else:
                if safe_draw_home and not must_win_home:
                    motives.append("%s平局即可確保前2" % h_zh)
                elif must_win_home:
                    motives.append("%s必須取勝才有出線機會" % h_zh)
                if safe_draw_away and not must_win_away:
                    motives.append("%s平局即可確保前2" % a_zh)
                elif must_win_away:
                    motives.append("%s必須取勝才有出線機會" % a_zh)
            if motives:
                bg += "；" + "，".join(motives)
            lines.insert(0, "【賽事背景】" + bg)

    # Recent form: show last match score + overall stats
    form_parts = []
    for team, zh in [(home, h_zh), (away, a_zh)]:
        s = stats.get(team)
        ctx_st = (group_ctx.get("home_standing") if team == home else group_ctx.get("away_standing")) or {}
        last = ctx_st.get("last")
        if s and s["played"] > 0:
            part = "%s %d場 進%d 失%d" % (zh, s["played"], s["scored"], s["conceded"])
            if last:
                opp_zh = team_zh(last["opp"])
                if last["home"]:
                    score_str = "%d-%d" % (last["hg"], last["ag"])
                    result = "勝" if last["hg"] > last["ag"] else ("平" if last["hg"] == last["ag"] else "敗")
                else:
                    score_str = "%d-%d" % (last["ag"], last["hg"])
                    result = "勝" if last["ag"] > last["hg"] else ("平" if last["ag"] == last["hg"] else "敗")
                part += "（上場%s%s %s）" % (result, opp_zh, score_str)
            form_parts.append(part)
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

    # Whole-ball lines (0, 1, 2, …) allow draws which are a push; compare each side directly
    if abs(ah_line - round(ah_line)) < 0.01:
        ah_prob_away = _poisson_ah_prob(la, lh, -ah_line)
        ah_prob_away = min(0.95, max(0.05, ah_prob_away))
        ah_prediction = "home" if ah_prob_home >= ah_prob_away else "away"
        ah_confidence = _prob_to_confidence(ah_prob_home / (ah_prob_home + ah_prob_away))
    else:
        ah_prediction = "home" if ah_prob_home > 0.5 else "away"
        ah_confidence = _prob_to_confidence(ah_prob_home)

    # Use OU-scaled lambdas when available (WC form paths have inflated league_avg)
    ou_lh = feature.get("ou_lambda_home", lh)
    ou_la = feature.get("ou_lambda_away", la)
    ou_prob_over = _poisson_ou_prob(ou_lh, ou_la, ou_line)
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
    if feature.get("dead_rubber"):
        _gctx = feature.get("group_context", {})
        _h_elim = _gctx.get("home_eliminated", False)
        _a_elim = _gctx.get("away_eliminated", False)
        if _h_elim and _a_elim:
            key_factors.append("雙方均已出局（死局場）")
        else:
            key_factors.append("雙方已確保出線（輪換效應）")
    if abs(sharp) > 0.25:
        key_factors.append(f"盤口明顯移動 {sharp:+.2f}")
    pm_gap = feature.get("pm_ah_gap")
    if pm_gap is not None:
        # gap = pm_ah - ah_line; gap > 0 → pm_ah less negative → PM values AWAY more
        direction = "客" if pm_gap > 0 else "主"
        key_factors.append(f"⚠️ PM盤口落差 {pm_gap:+.2f}（PM偏向{direction}隊）")
    if not key_factors:
        key_factors.append("Poisson 標準預測")

    score_info = _predict_score(lh, la, ou_line=ou_line, ou_over=(ou_prediction == "over"))
    home = feature["home_team"]
    away = feature["away_team"]

    from src.config import team_zh as _team_zh
    injuries = _load_injuries()
    injury_notes = []
    for team in [home, away]:
        team_injuries = injuries.get(team, [])
        if team_injuries:
            injury_notes.append(f"{_team_zh(team)}：" + "、".join(team_injuries))

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
        "predicted_score_prob": score_info.get("predicted_score_prob"),
        "p_home_win": score_info["p_home_win"],
        "p_draw": score_info["p_draw"],
        "p_away_win": score_info["p_away_win"],
        "key_factors": key_factors,
        "lambda_home": round(lh, 3),
        "lambda_away": round(la, 3),
        "ou_lambda_home": round(ou_lh, 3),
        "ou_lambda_away": round(ou_la, 3),
        "ah_line": ah_line,
        "ou_line": ou_line,
        "reasoning": reasoning,
        "injury_notes": injury_notes,
        "stage": feature.get("stage", "GROUP_STAGE"),
        "dk_ml_home": feature.get("dk_ml_home"),
        "dk_ml_draw": feature.get("dk_ml_draw"),
        "dk_ml_away": feature.get("dk_ml_away"),
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
