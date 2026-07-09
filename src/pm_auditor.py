"""
pm_auditor.py — Signal audit gate between EV scanners and pm_trader

每個 EV 信號進入 pm_trader 前必須通過此稽核。
Rules:
  1. EV + ROI 安全緩衝（比掃描器門檻更嚴）
  2. 模型最低可信度（禁止對 < 12% 機率投注）
  3. 跨市場一致性（晉級倉位 vs 單場勝負矛盾偵測）
  4. 所有決策寫入 data/audit_log.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import src.pm_portfolio as portfolio

AUDIT_LOG = Path(__file__).parent.parent / "data" / "audit_log.json"

# 比 pm_trader 的 MIN_EV=0.05 / MIN_ROI=0.20 更嚴
AUDITOR_MIN_EV  = 0.07
AUDITOR_MIN_ROI = 0.25
MIN_MODEL_PROB  = 0.12   # 低於此機率不下注，無論 EV 多高


# ── Helpers ──────────────────────────────────────────────────────────────────

def _log(entry: dict) -> None:
    try:
        if AUDIT_LOG.exists():
            data = json.loads(AUDIT_LOG.read_text())
        else:
            data = []
        data.append(entry)
        AUDIT_LOG.write_text(json.dumps(data[-500:], indent=2))
    except Exception:
        pass


def _advancement_positions() -> set:
    """
    回傳所有已開倉的晉級市場隊伍名稱 (lower case)。
    晉級倉位的 market_id 格式："{TeamName}:{Stage}"，例如 "France:R16"。
    單場倉位的 market_id 格式："{HomeTeam}v{AwayTeam}:{side}"。
    """
    data = portfolio.load()
    adv = set()
    for pos in data.get("positions", []):
        mid = pos.get("market_id", "")
        # 晉級倉位：有 ":" 但沒有 "v" 在冒號前
        if ":" in mid:
            before_colon = mid.split(":")[0]
            if "v" not in before_colon.lower():
                adv.add(before_colon.lower())
    return adv


# ── Public API ────────────────────────────────────────────────────────────────

def approve_advancement(opp) -> tuple:
    """
    稽核晉級市場信號。
    opp 欄位：.team, .to_stage, .fair_value (我方概率), .p_to (市場價格),
              .ev, .ev_roi, .token_id, .label
    回傳 (approved: bool, reason: str)
    """
    ts = datetime.now(timezone.utc).isoformat()

    def _reject(reason: str):
        _log({
            "ts": ts, "type": "advancement",
            "team": opp.team, "stage": opp.to_stage,
            "ev": round(opp.ev, 4), "roi": round(opp.ev_roi, 4),
            "our_prob": round(opp.fair_value, 4), "market": round(opp.p_to, 4),
            "approved": False, "reason": reason,
        })
        return False, reason

    def _accept():
        _log({
            "ts": ts, "type": "advancement",
            "team": opp.team, "stage": opp.to_stage,
            "ev": round(opp.ev, 4), "roi": round(opp.ev_roi, 4),
            "our_prob": round(opp.fair_value, 4), "market": round(opp.p_to, 4),
            "approved": True, "reason": "ok",
        })
        return True, "ok"

    if opp.ev < AUDITOR_MIN_EV:
        return _reject(f"ev {opp.ev:.4f} < floor {AUDITOR_MIN_EV}")

    if opp.ev_roi < AUDITOR_MIN_ROI:
        return _reject(f"roi {opp.ev_roi:.4f} < floor {AUDITOR_MIN_ROI}")

    if opp.fair_value < MIN_MODEL_PROB:
        return _reject(f"model_prob {opp.fair_value:.4f} < min {MIN_MODEL_PROB}")

    return _accept()


def approve_match(opp: dict, side: str) -> tuple:
    """
    稽核單場勝負市場信號。
    opp 欄位：home, away, date, market (dict), model (dict), ev (dict), token_ids (dict)
    side：'home_win' | 'draw' | 'away_win'
    回傳 (approved: bool, reason: str)
    """
    ts = datetime.now(timezone.utc).isoformat()
    ev         = opp["ev"][side]
    our_prob   = opp["model"][side]
    mkt_price  = opp["market"][side]
    match_key  = f"{opp['home']}v{opp['away']}"

    def _reject(reason: str):
        _log({
            "ts": ts, "type": "match",
            "match": match_key, "side": side,
            "ev": round(ev, 4), "our_prob": round(our_prob, 4),
            "market": round(mkt_price, 4),
            "approved": False, "reason": reason,
        })
        return False, reason

    def _accept():
        _log({
            "ts": ts, "type": "match",
            "match": match_key, "side": side,
            "ev": round(ev, 4), "our_prob": round(our_prob, 4),
            "market": round(mkt_price, 4),
            "approved": True, "reason": "ok",
        })
        return True, "ok"

    # Rule 1: EV floor
    if ev < AUDITOR_MIN_EV:
        return _reject(f"ev {ev:.4f} < floor {AUDITOR_MIN_EV}")

    # Rule 2: Model minimum probability
    if our_prob < MIN_MODEL_PROB:
        return _reject(f"model_prob {our_prob:.4f} < min {MIN_MODEL_PROB}")

    # Rule 3: Cross-market consistency
    # 若持有主隊晉級倉位，不可下注客隊獲勝（矛盾：主隊晉級需先在此場獲勝/晉級）
    # 若持有客隊晉級倉位，不可下注主隊獲勝（同上）
    adv_teams = _advancement_positions()
    home_lower = opp["home"].lower()
    away_lower = opp["away"].lower()

    if side == "away_win" and home_lower in adv_teams:
        return _reject(f"contradicts open advancement position on {opp['home']}")

    if side == "home_win" and away_lower in adv_teams:
        return _reject(f"contradicts open advancement position on {opp['away']}")

    return _accept()


def recent_decisions(n: int = 20) -> list:
    """回傳最近 n 筆稽核記錄（供 dashboard 使用）。"""
    try:
        if not AUDIT_LOG.exists():
            return []
        data = json.loads(AUDIT_LOG.read_text())
        return data[-n:]
    except Exception:
        return []
