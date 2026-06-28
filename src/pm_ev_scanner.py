#!/usr/bin/env python3
"""
pm_ev_scanner.py  —  Polymarket World Cup EV Scanner

邏輯：
  1. 從 Gamma API 抓取四個晉級市場（八強/四強/決賽/奪冠）的即時賠率
  2. 計算每隊在各階段的「轉換率」（e.g. 八強→四強）
  3. 以同梯隊中位數轉換率為公允基準（避免弱隊拉低基準）
  4. 找出轉換率顯著偏離中位數的標的 → 正EV（低估）或負EV（高估）
  5. --watch 模式：持續輪詢，比對前次狀態，有新信號才通知

用法：
  python -m src.pm_ev_scanner                      # 掃一次
  python -m src.pm_ev_scanner --min-ev 0.05        # 只看 5%+ 的機會
  python -m src.pm_ev_scanner --watch              # 持續監聽（預設每 5 分鐘）
  python -m src.pm_ev_scanner --watch --interval 120  # 每 2 分鐘掃一次
  python -m src.pm_ev_scanner --watch --min-ev 0.08   # 只有 8%+ EV 才通知
"""

import argparse
import json
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"

STAGES = ["qf", "sf", "final", "winner"]

STAGE_SLUGS = {
    "qf":     "world-cup-nation-to-reach-quarterfinals",
    "sf":     "world-cup-nation-to-reach-semifinals",
    "final":  "world-cup-nation-to-reach-final",
    "winner": "world-cup-winner",
}

STAGE_ZH = {
    "qf":     "八強",
    "sf":     "四強",
    "final":  "決賽",
    "winner": "奪冠",
}

# 每個市場問題結尾的固定字串，用來解析球隊名稱
QUESTION_SUFFIX = {
    "qf":     " reach the Quarterfinals at the 2026 FIFA World Cup?",
    "sf":     " reach the Semifinals at the 2026 FIFA World Cup?",
    "final":  " reach the 2026 FIFA World Cup final?",
    "winner": " win the 2026 FIFA World Cup?",
}

TRANSITIONS = [
    ("qf",    "sf",     "qf→sf"),
    ("sf",    "final",  "sf→final"),
    ("final", "winner", "final→win"),
]

STAGE_URLS = {
    "qf":     "https://polymarket.com/event/world-cup-nation-to-reach-quarterfinals",
    "sf":     "https://polymarket.com/event/world-cup-nation-to-reach-semifinals",
    "final":  "https://polymarket.com/event/world-cup-nation-to-reach-final",
    "winner": "https://polymarket.com/event/world-cup-winner",
}

TEAM_ZH: dict[str, str] = {
    "Argentina":            "阿根廷",
    "Brazil":               "巴西",
    "France":               "法國",
    "England":              "英格蘭",
    "Germany":              "德國",
    "Spain":                "西班牙",
    "Portugal":             "葡萄牙",
    "Netherlands":          "荷蘭",
    "Belgium":              "比利時",
    "Uruguay":              "烏拉圭",
    "Colombia":             "哥倫比亞",
    "Mexico":               "墨西哥",
    "USA":                  "美國",
    "Canada":               "加拿大",
    "Japan":                "日本",
    "South Korea":          "南韓",
    "Australia":            "澳大利亞",
    "Morocco":              "摩洛哥",
    "Senegal":              "塞內加爾",
    "Nigeria":              "奈及利亞",
    "Egypt":                "埃及",
    "Saudi Arabia":         "沙烏地阿拉伯",
    "Iran":                 "伊朗",
    "Ecuador":              "厄瓜多",
    "Peru":                 "秘魯",
    "Chile":                "智利",
    "Switzerland":          "瑞士",
    "Croatia":              "克羅埃西亞",
    "Serbia":               "塞爾維亞",
    "Poland":               "波蘭",
    "Denmark":              "丹麥",
    "Sweden":               "瑞典",
    "Norway":               "挪威",
    "Austria":              "奧地利",
    "Turkey":               "土耳其",
    "Ukraine":              "烏克蘭",
    "Romania":              "羅馬尼亞",
    "Czech Republic":       "捷克",
    "Hungary":              "匈牙利",
    "Slovakia":             "斯洛伐克",
    "Slovenia":             "斯洛維尼亞",
    "Albania":              "阿爾巴尼亞",
    "Cape Verde":           "佛得角",
    "New Zealand":          "紐西蘭",
    "Panama":               "巴拿馬",
    "Costa Rica":           "哥斯大黎加",
    "Honduras":             "宏都拉斯",
    "El Salvador":          "薩爾瓦多",
    "Paraguay":             "巴拉圭",
    "Bolivia":              "玻利維亞",
    "Venezuela":            "委內瑞拉",
    "Qatar":                "卡達",
    "Jordan":               "約旦",
    "Iraq":                 "伊拉克",
    "Uzbekistan":           "烏茲別克",
    "Indonesia":            "印尼",
    "China":                "中國",
    "DR Congo":             "剛果民主共和國",
    "Cameroon":             "喀麥隆",
    "Algeria":              "阿爾及利亞",
    "Tunisia":              "突尼西亞",
    "Ghana":                "迦納",
    "Ivory Coast":          "象牙海岸",
    "Italy":                "義大利",
    "Greece":               "希臘",
    "Kenya":                "肯亞",
}

def _zh(team: str) -> str:
    return TEAM_ZH.get(team, team)


# ── 資料抓取 ────────────────────────────────────────────────────────────────

def _fetch_stage(stage: str) -> tuple:
    """回傳 (prices, token_ids)，prices: {team: float}，token_ids: {team: str}"""
    slug   = STAGE_SLUGS[stage]
    suffix = QUESTION_SUFFIX[stage]
    try:
        r = requests.get(f"{GAMMA_BASE}/events", params={"slug": slug}, timeout=15)
        r.raise_for_status()
        events = r.json()
    except Exception as e:
        print(f"  [warn] fetch {stage} failed: {e}")
        return {}, {}

    if not events:
        return {}, {}

    result: dict[str, float] = {}
    token_ids: dict[str, str] = {}
    for m in events[0].get("markets", []):
        q = m.get("question", "")
        if suffix not in q:
            continue
        prices = m.get("outcomePrices", "[]")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                continue
        try:
            yes_p = float(prices[0])
        except (ValueError, IndexError):
            continue
        team = q.replace("Will ", "").replace(suffix, "").strip()
        result[team] = yes_p
        clob_ids = m.get("clobTokenIds", [])
        if clob_ids:
            token_ids[team] = clob_ids[0]
    return result, token_ids


# 全域 token_id 快取：{stage: {team: token_id}}
_TOKEN_IDS: dict[str, dict[str, str]] = {}


def fetch_all() -> dict[str, dict[str, float]]:
    global _TOKEN_IDS
    data = {}
    for stage in STAGES:
        prices, token_ids = _fetch_stage(stage)
        data[stage] = prices
        _TOKEN_IDS[stage] = token_ids
        print(f"  {STAGE_ZH[stage]:>3}  {len(data[stage]):>2} 隊")
    return data


# ── 矩陣建構 ────────────────────────────────────────────────────────────────

def build_matrix(stage_data: dict) -> dict[str, dict]:
    all_teams: set[str] = set()
    for probs in stage_data.values():
        all_teams.update(probs.keys())

    matrix = {}
    for team in sorted(all_teams):
        row: dict = {s: stage_data[s].get(team) for s in STAGES}
        row["conv"] = {}
        for from_s, to_s, key in TRANSITIONS:
            p0 = row[from_s]
            p1 = row[to_s]
            if p0 and p1 and p0 > 0.001:
                row["conv"][key] = p1 / p0
        matrix[team] = row
    return matrix


# ── EV 計算 ─────────────────────────────────────────────────────────────────

@dataclass
class Opportunity:
    team:       str
    from_stage: str
    to_stage:   str
    p_from:     float
    p_to:       float
    actual_conv:  float
    median_conv:  float
    fair_value:   float
    ev:           float          # 正 = 低估（買）；負 = 高估（賣）
    ev_roi:       float          # EV / p_to
    reason:       str = ""       # 一句話說明 EV 來源
    suggested_price: float = 0.0 # 私人對賭建議出價（BUY 用）
    token_id:     str = ""       # Polymarket CLOB token ID (YES side)

    @property
    def direction(self) -> str:
        return "BUY " if self.ev > 0 else "SELL"

    @property
    def label(self) -> str:
        return f"{STAGE_ZH[self.from_stage]}→{STAGE_ZH[self.to_stage]}"


def _peer_median(matrix: dict, from_s: str, key: str, p_from: float) -> float:
    """
    同梯隊中位數：只取八強概率在 [p_from/3, p_from*3] 範圍內的隊伍計算中位數。
    避免弱隊拉低基準，讓強隊和弱隊分開比較。
    """
    lo, hi = p_from / 3.0, p_from * 3.0
    rates = [
        row["conv"][key]
        for row in matrix.values()
        if key in row["conv"]
        and row.get(from_s) is not None
        and lo <= row[from_s] <= hi
    ]
    if len(rates) < 3:
        # 梯隊內樣本不足時，退回全體中位數
        rates = [row["conv"][key] for row in matrix.values() if key in row["conv"]]
    return statistics.median(rates) if rates else 0.5


def _read_model_prob(team: str, stage: str):
    """從 portfolio.json 讀取我們的獨立模型機率。讀取失敗時返回 None。"""
    try:
        import src.pm_portfolio as pf
        return pf.load().get("model_probs", {}).get(team, {}).get(stage)
    except Exception:
        return None


def find_opportunities(matrix: dict, min_ev: float = 0.03) -> list[Opportunity]:
    opps = []

    for from_s, to_s, key in TRANSITIONS:
        for team, row in matrix.items():
            if key not in row["conv"]:
                continue
            p_from = row[from_s]
            p_to   = row[to_s]
            if not p_from or not p_to:
                continue

            actual_conv  = row["conv"][key]
            peer_med     = _peer_median(matrix, from_s, key, p_from)
            # 優先用我們的獨立模型機率；無資料時 fallback 到 peer_median
            _mp = _read_model_prob(team, to_s)
            fair_value   = _mp if _mp is not None else p_from * peer_med
            ev           = fair_value - p_to
            ev_roi       = ev / p_to

            if ev > 0:
                reason = (
                    f"市場轉換率 {actual_conv*100:.0f}%，同梯隊中位 {peer_med*100:.0f}%"
                    f"，市場低估{_zh(team)} {STAGE_ZH[from_s]}後晉級能力"
                )
                suggested_price = round((p_to + fair_value) / 2, 4)
            else:
                reason = (
                    f"市場轉換率 {actual_conv*100:.0f}%，同梯隊中位 {peer_med*100:.0f}%"
                    f"，市場高估{_zh(team)} {STAGE_ZH[from_s]}後晉級能力"
                )
                suggested_price = 0.0

            if abs(ev) >= min_ev:
                opps.append(Opportunity(
                    team=team,
                    from_stage=from_s,
                    to_stage=to_s,
                    p_from=p_from,
                    p_to=p_to,
                    actual_conv=actual_conv,
                    median_conv=peer_med,
                    fair_value=fair_value,
                    ev=ev,
                    ev_roi=ev_roi,
                    reason=reason,
                    suggested_price=suggested_price,
                    token_id=_TOKEN_IDS.get(to_s, {}).get(team, ""),
                ))

    opps.sort(key=lambda o: o.ev, reverse=True)
    return opps


# ── 報告輸出 ─────────────────────────────────────────────────────────────────

def _row(o: Opportunity) -> str:
    arrow = "↑" if o.ev > 0 else "↓"
    return (
        f"  {o.direction} {arrow}  "
        f"{_zh(o.team):<10}"
        f"[{o.label}]  "
        f"現價 {o.p_to*100:>5.1f}%  "
        f"公允 {o.fair_value*100:>5.1f}%  "
        f"EV {o.ev*100:>+5.1f}¢  "
        f"ROI {o.ev_roi*100:>+6.1f}%  "
        f"（轉換率 {o.actual_conv*100:.0f}% vs 中位 {o.median_conv*100:.0f}%）"
    )


def print_report(opps: list[Opportunity], min_ev: float) -> None:
    buys  = [o for o in opps if o.ev > 0]
    sells = [o for o in opps if o.ev < 0]

    print(f"\n{'═'*85}")
    print(f"  PM World Cup EV Scanner   共 {len(opps)} 個機會（|EV| ≥ {min_ev*100:.0f}¢）")
    print(f"{'═'*85}")

    if buys:
        print(f"\n  🟢 低估標的（BUY）— {len(buys)} 個")
        print(f"  {'─'*80}")
        for o in buys:
            print(_row(o))

    if sells:
        print(f"\n  🔴 高估標的（SELL）— {len(sells)} 個")
        print(f"  {'─'*80}")
        for o in sells:
            print(_row(o))

    # 精選前三名 + 對沖建議
    top3 = sorted(buys, key=lambda o: o.ev_roi, reverse=True)[:3]
    hedges = _find_hedges(opps)
    if top3:
        print(f"\n  ⭐ 最推薦（ROI 最高前三）")
        print(f"  {'─'*80}")
        for i, o in enumerate(top3, 1):
            print(f"  {i}. {_zh(o.team)} — {o.label}")
            print(f"     現價 {o.p_to*100:.1f}¢  公允 {o.fair_value*100:.1f}¢  ROI {o.ev_roi*100:+.1f}%")
            print(f"     原因：{o.reason}")
            if o.suggested_price:
                print(f"     私人對賭建議出價：{o.suggested_price*100:.1f}¢（對手覺得合理，你有 +{o.ev_roi*100/2:.0f}% 優勢）")
            sell_peers = hedges.get(_opp_key(o), [])
            if sell_peers:
                names = "、".join(_zh(s.team) for s in sell_peers[:3])
                print(f"     可對沖 SELL：{names}（同轉換、市場高估）")
            print()

    print()


# ── 對沖配對 ────────────────────────────────────────────────────────────────

def _find_hedges(opps: list[Opportunity]) -> dict[str, list]:
    """
    對每個 BUY 找同一轉換路線的 SELL 信號。
    例如：比利時 八強→四強 BUY，法國/英格蘭 八強→四強 SELL → 可做對沖
    回傳 {opp_key: [sell_opp, ...]}
    """
    transition_sells: dict[tuple, list] = {}
    for o in opps:
        if o.ev < 0:
            key = (o.from_stage, o.to_stage)
            transition_sells.setdefault(key, []).append(o)
    # 按 ev 最負排序（最高估的在前）
    for lst in transition_sells.values():
        lst.sort(key=lambda x: x.ev)

    result = {}
    for o in opps:
        if o.ev > 0:
            key = (o.from_stage, o.to_stage)
            sells = transition_sells.get(key, [])
            if sells:
                result[_opp_key(o)] = sells[:3]
    return result


# ── 狀態持久化 ───────────────────────────────────────────────────────────────

STATE_FILE = Path(__file__).parent.parent / "data" / "backtest" / "pm_ev_state.json"

def _opp_key(o: Opportunity) -> str:
    return f"{o.team}|{o.from_stage}|{o.to_stage}"

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}

def save_state(opps: list[Opportunity]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        _opp_key(o): {"ev": o.ev, "ev_roi": o.ev_roi, "p_to": o.p_to}
        for o in opps
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── 通知 ─────────────────────────────────────────────────────────────────────

ALERT_LOG = Path(__file__).parent.parent / "data" / "backtest" / "pm_ev_alerts.log"
TG_TOKEN   = "8542040709:AAGG_thtHtwPiLIgyYS3mby3sQEuZ-Q9Pjk"
TG_CHAT_ID = "-1003850051729"

def _payout_lines(p_to: float, suggested: float) -> list[str]:
    """生成對賭賠率說明（以 100 元為例）。"""
    if suggested <= 0 or suggested >= 1:
        return []
    win_amt  = round((1 - suggested) / suggested * 100)
    lose_amt = 100
    odds_str = f"1 : {round((1-suggested)/suggested, 2)}"
    return [
        f"💰 對賭說明（以 100 元為單位）",
        f"   你出價 {suggested*100:.1f}¢ 接 Yes",
        f"   → 贏：對方付你 {win_amt} 元（賠率 {odds_str}）",
        f"   → 輸：你付對方 {lose_amt} 元",
        f"   市場現價 {p_to*100:.1f}¢，你給 {suggested*100:.1f}¢，對手仍覺得划算",
    ]


STAGE_PATH = {
    "qf":     "進八強",
    "sf":     "進四強",
    "final":  "進決賽",
    "winner": "奪冠",
}

# ── 2026 WC 賽制與路線計算 ────────────────────────────────────────────────────

WC_RESULTS_FILE = Path(__file__).parent.parent / "data" / "wc2026_results.json"

# R32 相鄰組配對（已確認：南非=2A vs 加拿大=1B）
# 規則：1X vs 2(X+1)，2X vs 1(X+1)
# ⚠️ I-J 組已確認法國與阿根廷在不同半區，故 I-J 不採用 adjacent 模式
_ADJ = {"A":"B","B":"A","C":"D","D":"C","E":"F","F":"E",
        "G":"H","H":"G","K":"L","L":"K"}
# I、J 與 K/L 的 3rd-place 跨組配對，目前未知→設為 TBD
_ADJ_UNKNOWN = {"I", "J"}

# QF blocks（已知：G/H 在同一 QF block，與 E/F 搭配）
_QF_BLOCKS = [["A","B","C","D"], ["E","F","G","H"], ["I","J","K","L"]]

# 球隊名別名（PM 與 football-data 名稱對齊）
_TEAM_ALIASES = {
    "USA":                  "United States",
    "United States":        "United States",
    "Cabo Verde":           "Cape Verde",
    "Cape Verde Islands":   "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
}


def _group_standings() -> dict[str, list[str]]:
    """回傳 {group: [1st, 2nd, 3rd, 4th]} 順序排列（依積分/GD/GF）。"""
    try:
        data = json.loads(WC_RESULTS_FILE.read_text())
    except Exception:
        return {}

    from collections import defaultdict
    pts: dict[str, int]  = defaultdict(int)
    gf:  dict[str, int]  = defaultdict(int)
    ga:  dict[str, int]  = defaultdict(int)
    team_group: dict[str, str] = {}

    for m in data:
        grp = m.get("group", "")
        if not grp:
            continue
        h, a = m["home"], m["away"]
        hg, ag = m.get("home_goals"), m.get("away_goals")
        if hg is None or ag is None:
            continue
        team_group[h] = grp
        team_group[a] = grp
        gf[h] += hg; ga[h] += ag
        gf[a] += ag; ga[a] += hg
        if hg > ag:   pts[h] += 3
        elif ag > hg: pts[a] += 3
        else:         pts[h] += 1; pts[a] += 1

    groups: dict[str, list[str]] = defaultdict(list)
    for team, grp in team_group.items():
        groups[grp].append(team)

    return {
        grp: sorted(teams, key=lambda t: (-pts[t], -(gf[t]-ga[t]), -gf[t]))
        for grp, teams in groups.items()
    }


def _bracket_path(team: str) -> dict:
    """
    推算 team 從 R32 到 SF 的對手路線。
    回傳 {group, position, r32, r16_likely, qf_candidates, unknown}
    """
    standings = _group_standings()

    # 別名對齊
    canonical = _TEAM_ALIASES.get(team, team)

    # 找出球隊所在組別和名次（支援別名）
    group, position = None, None
    for grp, ranked in standings.items():
        for i, t in enumerate(ranked):
            if t == canonical or t == team:
                group, position = grp, i + 1
                break
        if group:
            break

    if not group:
        return {"unknown": True, "reason": "無法確定組別（資料不足）"}

    adj_group = _ADJ.get(group)
    if not adj_group or group in _ADJ_UNKNOWN:
        return {
            "group": group, "position": position,
            "unknown": True,
            "reason": f"組別 {group} 的 R32 配對結構尚未確認",
        }

    adj_ranked = standings.get(adj_group, [])
    ranked = standings.get(group, [])

    # R32：1名 → 鄰組 2nd；2名 → 鄰組 1st
    r32_opp = adj_ranked[1] if position == 1 and len(adj_ranked) > 1 else (
              adj_ranked[0] if position == 2 and adj_ranked else "TBD")

    # R16：鄰組另一側最強隊（1名 → 面對鄰組 1st；2名 → 面對鄰組 2nd）
    r16_likely = (adj_ranked[0] if position == 1 and adj_ranked else
                  adj_ranked[1] if position == 2 and len(adj_ranked) > 1 else "TBD")

    # QF：同 QF block 的其他組別代表
    qf_block = next((b for b in _QF_BLOCKS if group in b), [])
    other_grps = [g for g in qf_block if g not in (group, adj_group)]
    qf_candidates = []
    for g in other_grps:
        qf_candidates += standings.get(g, [])[:2]

    return {
        "group": group,
        "position": position,
        "r32": r32_opp,
        "r16_likely": r16_likely,
        "qf_candidates": qf_candidates[:4],
        "unknown": False,
    }


def _build_tg_message(o: Opportunity, tag: str, hedge_hint: str, url: str) -> str:
    label = "🆕 新信號" if tag == "NEW" else "📈 EV 上升"
    team_zh = _zh(o.team)
    stage_zh = STAGE_ZH[o.to_stage]

    lines = [
        f"{'🟢' if o.ev > 0 else '🔴'} Polymarket EV {label}",
        "",
        f"🎯 押注目標：{team_zh} 能否{stage_zh}",
        f"   Polymarket 現價：{o.p_to*100:.1f}¢  公允值：{o.fair_value*100:.1f}¢  ROI {o.ev_roi*100:+.0f}%",
        "",
    ]

    lines += _payout_lines(o.p_to, o.suggested_price)
    lines.append("")

    # 路線分析
    path = _bracket_path(o.team)
    if path and not path.get("unknown"):
        grp = path.get("group", "")
        pos = path.get("position", "?")
        r32 = _zh(path.get("r32", "TBD"))
        r16 = _zh(path.get("r16_likely", "TBD"))
        qf_names = "、".join(_zh(t) for t in path.get("qf_candidates", []))
        pos_zh = {1:"第一名",2:"第二名",3:"第三名"}.get(pos, f"第{pos}名")
        lines += [
            f"🗺 晉{stage_zh}前的對手路線",
            f"   組別 {grp} {pos_zh} 出線",
            f"   ▸ R32  vs {r32}",
            f"   ▸ R16  vs {r16}（最大概率）",
        ]
        if qf_names:
            lines.append(f"   ▸ QF   vs {qf_names}（其中之一）")
        lines.append("")
    elif path and path.get("unknown"):
        lines += [
            f"🗺 路線：{path.get('reason', 'TBD')}",
            "",
        ]

    lines += [
        f"📌 EV 來源",
        f"   市場給 {team_zh} 的 {STAGE_ZH[o.from_stage]}→{stage_zh} 轉換率：{o.actual_conv*100:.0f}%",
        f"   同梯隊中位：{o.median_conv*100:.0f}%（差 {abs(o.median_conv - o.actual_conv)*100:.0f}%）",
        f"   → 市場可能已把路線難度 price-in，請核對對手實力再決定是否投注",
        "",
        f"⚠️  私人對賭無法中途退場，{team_zh} 一旦在{stage_zh}前出局即全輸",
    ]

    if hedge_hint:
        lines += ["", f"🔀 {hedge_hint}"]

    if url:
        lines += ["", f"🔗 {url}"]

    return "\n".join(lines)


def _notify(title: str, body: str, url: str = "",
            reason: str = "", suggested_price: float = 0.0,
            hedge_hint: str = "", opp: Optional["Opportunity"] = None,
            tag: str = "NEW") -> None:
    """macOS 彈窗 + Telegram 頻道推播 + 寫入 log 留底。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 寫入 log 留底
    try:
        ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ALERT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {title} | {body}" + (f" | {url}" if url else "") + "\n")
    except Exception:
        pass
    # Telegram 推播（完整對賭說明書）
    if opp is not None:
        tg_text = _build_tg_message(opp, tag, hedge_hint, url)
    else:
        lines = [f"🔔 {title}", body]
        if reason:
            lines.append(f"📌 {reason}")
        if suggested_price > 0:
            lines.append(f"💰 建議出價：{suggested_price*100:.1f}¢")
        if hedge_hint:
            lines.append(f"🔀 {hedge_hint}")
        if url:
            lines.append(f"🔗 {url}")
        tg_text = "\n".join(lines)
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": tg_text},
            timeout=10,
        )
    except Exception:
        pass
    print(f"\n  🔔 [{ts}] {title}: {body}")


def detect_new_signals(
    opps: list[Opportunity],
    prev_state: dict,
    min_ev: float,
) -> list[Opportunity]:
    """
    回傳「新出現」或「EV 顯著增加（>2%）」的信號。
    只關注 BUY 方向。
    """
    alerts = []
    for o in opps:
        if o.ev <= 0:
            continue
        key = _opp_key(o)
        prev = prev_state.get(key)
        if prev is None:
            # 全新信號
            alerts.append(("NEW", o))
        elif o.ev - prev["ev"] >= 0.02:
            # EV 比上次增加超過 2¢
            alerts.append(("UP", o))
    return alerts


# ── 組別冠軍市場 ─────────────────────────────────────────────────────────────

PRED_DIR = Path(__file__).parent.parent / "data" / "predictions"


def _fetch_group_winner_markets() -> dict[str, dict[str, float]]:
    """抓取全部12組的組冠軍市場賠率。只回傳有活口的組別（非100%/0%）。"""
    result = {}
    for g in "ABCDEFGHIJKL":
        slug = f"world-cup-group-{g.lower()}-winner"
        try:
            r = requests.get(f"{GAMMA_BASE}/events", params={"slug": slug}, timeout=12)
            r.raise_for_status()
            events = r.json()
        except Exception:
            continue
        if not events:
            continue
        suffix = f" win Group {g} in the 2026 FIFA World Cup?"
        group_odds: dict[str, float] = {}
        for m in events[0].get("markets", []):
            q = m.get("question", "")
            if suffix not in q or "another team" in q.lower():
                continue
            team = q.replace("Will ", "").replace(suffix, "").strip()
            prices = m.get("outcomePrices", "[]")
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except Exception:
                    continue
            try:
                p = float(prices[0])
            except (ValueError, IndexError):
                continue
            group_odds[team] = p
        # 只保留有活口的（最高賠率 < 0.95）
        if group_odds and max(group_odds.values()) < 0.95:
            result[g] = group_odds
    return result


def _load_latest_predictions() -> list[dict]:
    """讀取最新的 predictions 檔，回傳預測列表。"""
    files = sorted(PRED_DIR.glob("*.json"), reverse=True)
    for f in files[:3]:
        try:
            preds = json.loads(f.read_text())
            if preds:
                return preds
        except Exception:
            continue
    return []


def _model_group_probs(group: str) -> dict[str, float]:
    """
    用當前積分 + 剩餘比賽的模型預測，計算各隊以第一名出線的概率。
    使用精確列舉所有剩餘賽事結果組合。
    """
    # 讀取已完成的比賽，建立積分/球差
    try:
        data = json.loads(WC_RESULTS_FILE.read_text())
    except Exception:
        return {}

    from collections import defaultdict
    pts: dict[str, int] = defaultdict(int)
    gf:  dict[str, int] = defaultdict(int)
    ga:  dict[str, int] = defaultdict(int)
    played: set[tuple] = set()
    group_teams: set[str] = set()

    for m in data:
        if m.get("group") != group:
            continue
        h, a = m["home"], m["away"]
        hg, ag = m.get("home_goals"), m.get("away_goals")
        if hg is None or ag is None:
            continue
        group_teams.update([h, a])
        gf[h] += hg; ga[h] += ag
        gf[a] += ag; ga[a] += hg
        if hg > ag:   pts[h] += 3
        elif ag > hg: pts[a] += 3
        else:         pts[h] += 1; pts[a] += 1
        played.add((h, a))

    if not group_teams:
        return {}

    # 確保每支隊都有初始值（防止 0 分隊伍不在 dict 裡）
    for t in group_teams:
        pts.setdefault(t, 0)
        gf.setdefault(t, 0)
        ga.setdefault(t, 0)

    # 找剩餘比賽（同組內兩隊尚未對陣）
    preds = _load_latest_predictions()
    remaining: list[dict] = []
    for p in preds:
        h, a = p.get("home_team", ""), p.get("away_team", "")
        # 嘗試別名對齊
        h = _TEAM_ALIASES.get(h, h)
        a = _TEAM_ALIASES.get(a, a)
        if h in group_teams and a in group_teams and (h, a) not in played:
            remaining.append({
                "home": h, "away": a,
                "ph": p.get("p_home_win", 0.33),
                "pd": p.get("p_draw", 0.33),
                "pa": p.get("p_away_win", 0.34),
            })

    # 精確列舉所有結果組合
    win_count: dict[str, float] = defaultdict(float)

    def simulate(idx: int, cur_pts: dict, cur_gd: dict, cur_gf: dict, weight: float) -> None:
        if idx == len(remaining):
            # 排名：積分 → GD → GF
            ranked = sorted(group_teams, key=lambda t: (-cur_pts[t], -cur_gd[t], -cur_gf[t]))
            win_count[ranked[0]] += weight
            return
        m = remaining[idx]
        h, a = m["home"], m["away"]
        for outcome, prob in [("H", m["ph"]), ("D", m["pd"]), ("A", m["pa"])]:
            np2 = dict(cur_pts); ng = dict(cur_gd); nf = dict(cur_gf)
            if outcome == "H":
                np2[h] += 3; ng[h] += 1; ng[a] -= 1; nf[h] += 1
            elif outcome == "D":
                np2[h] += 1; np2[a] += 1
            else:
                np2[a] += 3; ng[a] += 1; ng[h] -= 1; nf[a] += 1
            simulate(idx + 1, np2, ng, nf, weight * prob)

    init_gd = {t: gf[t] - ga[t] for t in group_teams}
    init_gf = dict(gf)
    simulate(0, dict(pts), init_gd, init_gf, 1.0)

    total = sum(win_count.values()) or 1.0
    return {t: win_count[t] / total for t in group_teams}


@dataclass
class GroupOpp:
    group:      str
    team:       str
    pm_price:   float          # PM 現價
    model_prob: float          # 模型公允值
    ev:         float          # model - pm（正 = 低估 = BUY）
    ev_roi:     float          # EV / pm_price

    @property
    def direction(self) -> str:
        return "BUY " if self.ev > 0 else "SELL"

    @property
    def suggested_price(self) -> float:
        return round((self.pm_price + self.model_prob) / 2, 4) if self.ev > 0 else 0.0

    def tg_message(self) -> str:
        tag = "BUY 低估" if self.ev > 0 else "SELL 高估"
        lines = [
            f"{'🟢' if self.ev > 0 else '🔴'} Polymarket EV 🆕 新信號",
            "",
            f"🎯 押注目標：{_zh(self.team)} 奪得 {self.group} 組冠軍",
            f"   PM 現價：{self.pm_price*100:.1f}¢  模型公允：{self.model_prob*100:.1f}¢  ROI {self.ev_roi*100:+.0f}%",
            "",
        ]
        if self.ev > 0:
            lines += _payout_lines(self.pm_price, self.suggested_price)
            lines.append("")
        lines += [
            f"📌 EV 來源：{tag}",
            f"   模型根據當前積分+剩餘賽程預測 {self.model_prob*100:.1f}%",
            f"   PM 卻給出 {self.pm_price*100:.1f}%，差距 {abs(self.ev)*100:.1f}%",
            "",
            f"⚠️  組冠為單次結果（今日賽後即確定），無法中途退場",
            "",
            f"🔗 https://polymarket.com/event/world-cup-group-{self.group.lower()}-winner",
        ]
        return "\n".join(lines)


def scan_group_winners(min_ev: float = 0.03) -> list[GroupOpp]:
    """掃描全部組別冠軍市場，找出模型 vs PM 的正負 EV 標的。"""
    print("  掃描組別冠軍市場...")
    pm_markets = _fetch_group_winner_markets()
    opps: list[GroupOpp] = []
    for group, odds in pm_markets.items():
        model_probs = _model_group_probs(group)
        if not model_probs:
            continue
        # 別名對齊：PM 用的隊名 vs 我們資料庫的隊名
        for pm_team, pm_p in odds.items():
            # 嘗試找對應的 model 隊名
            model_p = model_probs.get(pm_team, 0)
            if not model_p:
                # 試別名
                canonical = _TEAM_ALIASES.get(pm_team, pm_team)
                model_p = model_probs.get(canonical, 0)
            if not model_p or pm_p < 0.005:
                continue
            ev = model_p - pm_p
            ev_roi = ev / pm_p
            # BUY：模型概率需 ≥ 15%，否則信號通常依賴某個小概率前提（如強隊爆冷）
            if ev > 0 and model_p < 0.15:
                continue
            # SELL：PM 現價需 ≥ 10%，太低的已被市場認定不可能，無需再做空
            if ev < 0 and pm_p < 0.10:
                continue
            if abs(ev) >= min_ev:
                opps.append(GroupOpp(
                    group=group, team=pm_team,
                    pm_price=pm_p, model_prob=model_p,
                    ev=ev, ev_roi=ev_roi,
                ))
    opps.sort(key=lambda o: o.ev, reverse=True)
    return opps


def print_group_report(opps: list[GroupOpp]) -> None:
    if not opps:
        print("  （無組別冠軍 EV 機會）")
        return
    buys  = [o for o in opps if o.ev > 0]
    sells = [o for o in opps if o.ev < 0]
    print(f"\n  📋 組別冠軍 EV（模型 vs PM）")
    if buys:
        print(f"  🟢 低估（BUY）")
        for o in buys:
            print(f"     {_zh(o.team):<10} 組{o.group}冠  PM {o.pm_price*100:.1f}¢  模型 {o.model_prob*100:.1f}¢  ROI {o.ev_roi*100:+.0f}%  建議出價 {o.suggested_price*100:.1f}¢")
    if sells:
        print(f"  🔴 高估（SELL）")
        for o in sells:
            print(f"     {_zh(o.team):<10} 組{o.group}冠  PM {o.pm_price*100:.1f}¢  模型 {o.model_prob*100:.1f}¢  ROI {o.ev_roi*100:+.0f}%")


# ── 進入點 ──────────────────────────────────────────────────────────────────

def scan(min_ev: float = 0.03) -> tuple[list[Opportunity], list[GroupOpp]]:
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 抓取 Polymarket 即時賠率...")
    stage_data = fetch_all()
    matrix = build_matrix(stage_data)
    stage_opps = find_opportunities(matrix, min_ev=min_ev)
    print_report(stage_opps, min_ev)
    group_opps = scan_group_winners(min_ev=min_ev)
    print_group_report(group_opps)
    return stage_opps, group_opps


def watch(min_ev: float = 0.03, interval: int = 300) -> None:
    """
    持續輪詢模式。
    - 每隔 interval 秒掃描一次全部 PM 晉級市場
    - 比對上次結果，有新 BUY 信號或 EV 顯著上升才通知
    - 不管有沒有信號，每次都印出當前狀態
    """
    print(f"[pm_ev_scanner] 🚀 Watch 模式啟動")
    print(f"  輪詢間隔：{interval}s  EV 門檻：{min_ev*100:.0f}¢")
    print(f"  按 Ctrl+C 停止\n")

    prev_state = load_state()
    scan_count = 0

    while True:
        scan_count += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{'─'*60}")
        print(f"  掃描 #{scan_count}  {ts}")

        try:
            stage_data  = fetch_all()
            matrix      = build_matrix(stage_data)
            stage_opps  = find_opportunities(matrix, min_ev=min_ev)
            group_opps  = scan_group_winners(min_ev=min_ev)
        except Exception as e:
            print(f"  [error] 抓取失敗：{e}，{interval}s 後重試")
            time.sleep(interval)
            continue

        # ── 晉級市場信號 ──
        stage_alerts = detect_new_signals(stage_opps, prev_state, min_ev)
        if stage_alerts:
            print_report(stage_opps, min_ev)
            hedges = _find_hedges(stage_opps)
            for tag, o in stage_alerts:
                label = "🆕 新信號" if tag == "NEW" else "📈 EV 上升"
                sell_peers = hedges.get(_opp_key(o), [])
                hedge_hint = ""
                if sell_peers:
                    names = "、".join(_zh(s.team) for s in sell_peers[:2])
                    hedge_hint = f"可 SELL {names}（同路線高估，做反向對沖）"
                _notify(
                    f"Polymarket EV {label}",
                    f"{_zh(o.team)} {o.label}  ROI {o.ev_roi*100:+.1f}%  現價 {o.p_to*100:.1f}¢",
                    url=STAGE_URLS[o.to_stage],
                    suggested_price=o.suggested_price,
                    hedge_hint=hedge_hint,
                    opp=o,
                    tag=tag,
                )
        else:
            buys = [o for o in stage_opps if o.ev > 0]
            top  = buys[0] if buys else None
            print(f"  晉級：{'最佳 BUY ' + _zh(top.team) + f' [{top.label}] ROI {top.ev_roi*100:+.1f}%（無變化）' if top else '無機會'}")

        # ── 組別冠軍信號 ──
        prev_group_keys = prev_state.get("__group__", {})
        group_new = [o for o in group_opps
                     if f"grp:{o.group}:{o.team}" not in prev_group_keys
                     or abs(o.ev - prev_group_keys.get(f"grp:{o.group}:{o.team}", {}).get("ev", 0)) >= 0.02]
        if group_opps:
            print_group_report(group_opps)
        if group_new:
            for o in group_new:
                if o.ev > 0:
                    _notify(
                        f"Polymarket EV 🆕 組冠信號",
                        f"{_zh(o.team)} 奪{o.group}組冠  ROI {o.ev_roi*100:+.0f}%  PM {o.pm_price*100:.1f}¢  模型 {o.model_prob*100:.1f}¢",
                        url=f"https://polymarket.com/event/world-cup-group-{o.group.lower()}-winner",
                        reason=o.tg_message(),
                    )

        save_state(stage_opps)
        new_group_state = {f"grp:{o.group}:{o.team}": {"ev": o.ev, "ev_roi": o.ev_roi} for o in group_opps}
        prev_state = {_opp_key(o): {"ev": o.ev, "ev_roi": o.ev_roi, "p_to": o.p_to}
                      for o in stage_opps}
        prev_state["__group__"] = new_group_state

        print(f"  下次掃描：{interval}s 後（{datetime.now().strftime('%H:%M:%S')} + {interval//60}m{interval%60:02d}s）\n")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket WC EV Scanner")
    parser.add_argument("--min-ev",   type=float, default=0.03,
                        help="最小 EV 門檻（預設 0.03 = 3¢）")
    parser.add_argument("--watch",    action="store_true",
                        help="持續監聽模式")
    parser.add_argument("--interval", type=int, default=300,
                        help="Watch 模式輪詢間隔秒數（預設 300 = 5 分鐘）")
    args = parser.parse_args()

    if args.watch:
        watch(min_ev=args.min_ev, interval=args.interval)
    else:
        scan(min_ev=args.min_ev)
