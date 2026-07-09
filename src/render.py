import json
import math
from pathlib import Path

import plotly.graph_objects as go
from src.config import team_zh

DOCS_DIR = Path(__file__).parent.parent / "docs"
_DATA_DIR = Path(__file__).parent.parent / "data"


# ── Formation analysis helpers ───────────────────────────────────────────────

_STYLE_ZH = {
    "attacking":  "主動進攻",
    "possession": "控球打法",
    "counter":    "防守反擊",
    "balanced":   "攻守均衡",
    "defensive":  "穩守為主",
    "pressing":   "高位逼搶",
}

_STYLE_PROFILE = {
    "attacking": {
        "thrives": "邊路高速突破＋前場高壓持續施壓；對手防線出現失誤或體能下滑後半段得分率高",
        "weakness": "邊後衛大量壓上後身後留有大片空間，中場回防覆蓋速度是關鍵",
        "threat":  "速度型反擊前鋒（直接衝擊身後空間）、高球頭球中鋒（定位球近角威脅）",
    },
    "possession": {
        "thrives": "中場技術明顯佔優時可完全掌控節奏；對手越著急追球，給出的空間就越大",
        "weakness": "遇高強度逼搶時後場出球失誤率升高；速度不足的後衛難應對越過逼搶線的長傳球",
        "threat":  "強力逼搶型中場（在後場截球直接威脅）、速度身後球型前鋒（搶在防線重組前先一步）",
    },
    "counter": {
        "thrives": "對手全線壓上時身後空間充足；己方速度型前鋒狀態好時一擊即中效率高",
        "weakness": "對手耐心控球、不輕易壓上時，缺乏主動進攻組織能力，前場支撐點少",
        "threat":  "耐心型控球中場（消除身後空間、不給快攻機會）、高球強力中鋒（低位防守定位球時暴露）",
    },
    "balanced": {
        "thrives": "陣容深度足夠時可依場情靈活調度攻守比例；體能管理得當則下半場仍有餘力",
        "weakness": "風格不鮮明，在極端高壓或極端防守的對手面前較難取得壓倒性優勢",
        "threat":  "技術明顯佔優的高壓型隊伍（強迫進入節奏快的對抗）、定位球精準的防守型隊伍",
    },
    "defensive": {
        "thrives": "對手缺乏耐心時可靠守引誘失誤反擊；己方鋒線有個人突破能力或定位球專項威脅",
        "weakness": "長時間低位防守體能集中消耗在少數失誤節點，無法主動製造持續進攻壓力",
        "threat":  "耐心控球型隊伍（持續施壓直到防守疲軟）、高球強力中鋒（低位密集時頂角球危險）",
    },
    "pressing": {
        "thrives": "對手後場技術不穩定時強逼出失誤效果顯著；全隊體能充足下半場前維持全場壓制",
        "weakness": "體能消耗極快，下半場逼搶線被迫下降後身後大量空間暴露，容易被長傳打穿",
        "threat":  "長傳越線型後腰（一腳直接越過逼搶陣線）、速度型邊鋒（反跑利用收縮後的大空間）",
    },
}

_MATCHUP_KEY_NOTES = {
    "attacking_counter":     ("⚠️ 主隊需注意", "主隊主動壓上正好為對手創造身後空間，客隊速度型前鋒反擊威脅大；若主隊能快速多線壓制不讓客隊出球，優勢可轉化"),
    "counter_attacking":     ("⚠️ 客隊需注意", "客隊全線進攻留下身後空間，主隊快攻威脅極大；客隊若能快速進球讓主隊被迫追分，才能掌握主動"),
    "possession_counter":    ("⚠️ 主隊需注意", "主隊每次失球即面臨閃電反擊，逼搶失誤代價高；關鍵是能否在客隊出球前完成截斷，消除快攻威脅"),
    "counter_possession":    ("⚠️ 主隊被動", "主隊所需的身後空間被客隊耐心控球消除；主隊若無法逼迫客隊犯錯，將長期低位防守消耗體能"),
    "pressing_counter":      ("🚨 極危險組合", "高位逼搶正面對反擊型對手是最高風險組合：逼搶失敗瞬間暴露大量身後空間給速度型前鋒直搗"),
    "counter_pressing":      ("🚨 主隊生存難", "主隊反擊依賴的身後空間被高位逼搶徹底封鎖，出球受阻則失去反擊能力，淪為完全被動"),
    "attacking_attacking":   ("🔥 進攻對決", "雙方均主動壓上，身後空間大，進球數預計偏多；任何一次失誤都可能被對手即時懲罰"),
    "possession_possession": ("🎯 中場拉鋸", "控球鬥控球，中場技術質量與體能是核心差異；定位球往往是這類拉鋸戰的最終決定手段"),
    "defensive_defensive":   ("😴 低分博弈", "雙方均收縮不冒進，進球機會極少；定位球或個人突破是主要得分來源，加時賽或PK機率高"),
    "attacking_possession":  ("🎯 節奏之爭", "進攻方持續施壓，控球方耐心拆解等失誤；誰先破門將改變雙方節奏選擇"),
    "possession_attacking":  ("🎯 節奏之爭", "主隊控球等機會，客隊高壓逼求快速進球；主隊若能守住前30分鐘，體能差異將在後半段體現"),
    "counter_counter":       ("😐 雙低位僵局", "雙方均等待對方先壓，比賽空間緊縮；定位球或個人技術突破才能打破僵局"),
    "balanced_balanced":     ("⚖️ 均勢對決", "雙方攻守均衡風格相近，個人質量差異與臨場調度是勝負關鍵"),
    "attacking_defensive":   ("💪 強攻對穩守", "進攻方主導場面，但需突破密集低位防線；若守方鋒線有威脅，一次精準反擊即可改變局面"),
    "defensive_attacking":   ("💪 強攻對穩守", "客隊主導進攻，主隊低位等機會；主隊若能撐過前45分鐘，客隊體能消耗後可能出現機會"),
    "balanced_attacking":    ("📊 均衡迎強攻", "客隊積極施壓，主隊均衡應對需快速找到節奏；主隊中場覆蓋能力是抵擋對手進攻的關鍵"),
    "attacking_balanced":    ("📊 強攻對均衡", "主隊全力施壓，客隊攻守均衡靠調度應對；若主隊前30分鐘無法破門，客隊會逐漸找到防守節奏"),
    "balanced_counter":      ("⚠️ 主隊注意", "主隊均衡打法一旦壓上，即為客隊反擊創造機會；主隊需控制壓上節奏，不過度冒進"),
    "counter_balanced":      ("📊 快攻對均衡", "主隊伺機快攻，客隊均衡應對；客隊若能穩住防線，主隊身後空間將逐漸縮小"),
    "possession_balanced":   ("🎯 控球對均衡", "主隊靠技術掌控節奏，客隊均衡消化；主隊若能在前場維持控球，客隊體能消耗後空間會增加"),
    "balanced_possession":   ("🎯 均衡對控球", "客隊耐心控球，主隊均衡應對；主隊需在高強度前壓中找到截球機會，不能讓客隊長期壓制"),
    "defensive_counter":     ("🏰 雙防僵局", "雙方均不願主動暴露，都在等待對手失誤；定位球是最可能的進球方式"),
    "counter_defensive":     ("🏰 雙防僵局", "雙方均保守低位，比賽節奏極慢；個人閃光或定位球是打破僵局的主要手段"),
    "possession_defensive":  ("💪 控球破密集", "主隊耐心製造空隙，客隊密集低位；關鍵是主隊能否在客隊體能下滑前找到穿透防線的機會"),
    "defensive_possession":  ("💪 密集對控球", "客隊控球，主隊密集防守等機會；主隊需注意長時間防守體能消耗，避免後半段出現失誤"),
    "pressing_attacking":    ("🔥 極高壓對決", "雙方均積極向前，強度極高；體能管理差的一方在後半段將付出代價"),
    "attacking_pressing":    ("🔥 極高壓對決", "客隊逼搶，主隊反壓；誰先在對方高壓下失誤，比賽節奏就向另一方傾斜"),
    "pressing_possession":   ("⚠️ 逼搶破控球", "主隊高位逼搶恰好針對控球方的弱點；若逼搶成功率高，客隊後場出球將極為困難"),
    "possession_pressing":   ("⚠️ 控球破逼搶", "客隊逼搶針對主隊控球；主隊需要技術穩定的後場出球人，若逼搶成功率高，主隊要付出代價"),
    "pressing_balanced":     ("📊 逼搶對均衡", "主隊高強度逼搶，客隊均衡應對；客隊若後場出球穩定，可靠長傳越過主隊逼搶線"),
    "balanced_pressing":     ("📊 均衡對逼搶", "客隊強力逼搶，主隊均衡消化；主隊需快速出球破解逼搶，長傳是有效選項"),
    "pressing_defensive":    ("🏰 逼搶對密集", "主隊高壓進攻，客隊密集低位防守；主隊需要耐心突破，避免因逼搶失敗暴露身後"),
    "defensive_pressing":    ("🏰 密集對逼搶", "客隊高壓，主隊低位；主隊若能承受高壓並找到精準反擊機會，可靠定位球或個人突破制勝"),
}

_FORMATION_DESC = {
    "4-3-3":   ("4-3-3", 4, 3, 3),
    "4-2-3-1": ("4-2-3-1", 4, 5, 1),   # treat 2+3 as 5 mid
    "4-4-2":   ("4-4-2", 4, 4, 2),
    "4-1-4-1": ("4-1-4-1", 5, 4, 1),   # 4+1 back
    "5-3-2":   ("5-3-2", 5, 3, 2),
    "5-4-1":   ("5-4-1", 5, 4, 1),
    "3-5-2":   ("3-5-2", 3, 5, 2),
    "3-4-3":   ("3-4-3", 3, 4, 3),
    "4-5-1":   ("4-5-1", 4, 5, 1),
}

def _get_team_formation(team_en: str):
    """Return (formation, style) for a team.
    Priority: most recent ESPN match → formations.json → default.
    """
    # 1. Look through recent stored match goal_events
    matches_dir = _DATA_DIR / "matches"
    best_form = ""
    for f in sorted(matches_dir.glob("2026-06-*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            ge = data.get("goal_events", {})
            if not isinstance(ge, dict):
                continue
            for key, v in ge.items():
                if not isinstance(v, dict):
                    continue
                parts = key.split("|")
                if len(parts) != 2:
                    continue
                h, a = parts
                forms = v.get("formations", {})
                if h.lower() == team_en.lower() and forms.get("home"):
                    best_form = forms["home"]
                    break
                if a.lower() == team_en.lower() and forms.get("away"):
                    best_form = forms["away"]
                    break
            if best_form:
                break
        except Exception:
            continue

    # 2. Fallback to formations.json
    try:
        fdb = json.loads((_DATA_DIR / "formations.json").read_text())
        entry = fdb.get(team_en, {})
        if isinstance(entry, dict):
            static_form = entry.get("formation", "")
            style = entry.get("style", "balanced")
            return (best_form or static_form or "?"), style
    except Exception:
        pass
    return best_form or "?", "balanced"


def _midfield_count(formation: str) -> int:
    """Rough midfield player count from formation string."""
    parts = [int(x) for x in formation.split("-") if x.isdigit()]
    if len(parts) == 3:
        return parts[1]
    if len(parts) == 4:
        return parts[1] + parts[2]
    return 3


def _discipline_stats_html(home_en: str, away_en: str, home_zh: str, away_zh: str) -> str:
    """Show per-team discipline stats: WC 2026 avg (all teams) + historical avg (where available)."""
    try:
        from src.features import load_team_discipline_stats
        all_stats = load_team_discipline_stats()
    except Exception:
        return ""
    wc_stats   = all_stats.get("wc", {})
    hist_stats = all_stats.get("hist", {})
    if not wc_stats and not hist_stats:
        return ""

    _ESPN_NAME_MAP = {
        "United States": "USA",
        "South Korea": "South Korea",
        "Ivory Coast": "Ivory Coast",
        "DR Congo": "Congo DR",
        "Cabo Verde": "Cape Verde",
    }

    def _lookup(pool, team_en: str):
        key = _ESPN_NAME_MAP.get(team_en, team_en)
        if key in pool:
            return pool[key]
        if team_en in pool:
            return pool[team_en]
        tl = team_en.lower()
        for k, v in pool.items():
            if k.lower() == tl or tl in k.lower() or k.lower() in tl:
                return v
        return None

    hw = _lookup(wc_stats, home_en)
    aw = _lookup(wc_stats, away_en)
    hh = _lookup(hist_stats, home_en)
    ah = _lookup(hist_stats, away_en)
    if not hw and not aw:
        return ""

    def _v(d, key):
        return str(d[key]) if d and key in d else "—"

    metrics = [
        ("⚽ 角球/場", "corners_pg"),
        ("🟨 黃牌/場", "yellow_pg"),
        ("🟥 紅牌/場", "red_pg"),
    ]

    has_hist = hh or ah
    hw_games = hw["games"] if hw else 0
    aw_games = aw["games"] if aw else 0
    hh_games = hh["games"] if hh else 0
    ah_games = ah["games"] if ah else 0

    # Header
    header = (
        f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:10px'>"
        f"<span style='font-size:0.72rem;color:var(--muted);font-weight:600'>紀律統計</span>"
        f"<span style='font-size:0.75rem'>"
        f"<span style='color:var(--accent);font-weight:700'>{home_zh}</span>"
        f"<span style='color:var(--muted);margin:0 6px'>/</span>"
        f"<span style='color:var(--gold);font-weight:700'>{away_zh}</span>"
        f"</span>"
        f"</div>"
    )

    # WC section
    wc_cells = ""
    for label, key in metrics:
        hwv = _v(hw, key)
        awv = _v(aw, key)
        wc_cells += (
            f"<div style='display:flex;flex-direction:column;align-items:center;flex:1;gap:3px'>"
            f"<div style='font-size:0.68rem;color:var(--muted)'>{label}</div>"
            f"<div style='display:flex;gap:8px;align-items:baseline'>"
            f"<span style='font-size:1.05rem;font-weight:700;color:var(--accent)'>{hwv}</span>"
            f"<span style='font-size:0.65rem;color:var(--muted)'>vs</span>"
            f"<span style='font-size:1.05rem;font-weight:700;color:var(--gold)'>{awv}</span>"
            f"</div>"
            f"</div>"
        )
    wc_label = f"本屆 WC（主{hw_games}場 / 客{aw_games}場）"
    wc_block = (
        f"<div style='background:rgba(255,255,255,0.04);border-radius:6px;padding:8px 10px;margin-bottom:6px'>"
        f"<div style='font-size:0.62rem;color:var(--muted);margin-bottom:6px'>{wc_label}</div>"
        f"<div style='display:flex;gap:6px'>{wc_cells}</div>"
        f"</div>"
    )

    # Historical section (only if data exists)
    hist_block = ""
    if has_hist:
        hist_cells = ""
        for label, key in metrics:
            hhv = _v(hh, key)
            ahv = _v(ah, key)
            hist_cells += (
                f"<div style='display:flex;flex-direction:column;align-items:center;flex:1;gap:3px'>"
                f"<div style='font-size:0.68rem;color:var(--muted)'>{label}</div>"
                f"<div style='display:flex;gap:8px;align-items:baseline'>"
                f"<span style='font-size:0.92rem;font-weight:600;color:rgba(255,255,255,0.6)'>{hhv}</span>"
                f"<span style='font-size:0.65rem;color:var(--muted)'>vs</span>"
                f"<span style='font-size:0.92rem;font-weight:600;color:rgba(212,175,55,0.6)'>{ahv}</span>"
                f"</div>"
                f"</div>"
            )
        hi_label = f"近1年歷史（主{hh_games}場 / 客{ah_games}場）"
        hist_block = (
            f"<div style='background:rgba(255,255,255,0.02);border-radius:6px;padding:8px 10px;"
            f"border:1px solid rgba(255,255,255,0.06)'>"
            f"<div style='font-size:0.62rem;color:var(--muted);margin-bottom:6px'>{hi_label}</div>"
            f"<div style='display:flex;gap:6px'>{hist_cells}</div>"
            f"</div>"
        )

    return (
        f"<div style='margin-top:12px;padding:12px 14px;background:rgba(255,255,255,0.03);"
        f"border:1px solid var(--border);border-radius:8px'>"
        f"{header}"
        f"{wc_block}"
        f"{hist_block}"
        f"</div>"
    )


def _formation_analysis_html(home_en: str, away_en: str, home_zh_name: str, away_zh_name: str) -> str:
    """Generate detailed formation + tactical analysis HTML block."""
    h_form, h_style = _get_team_formation(home_en)
    a_form, a_style = _get_team_formation(away_en)

    h_style_zh = _STYLE_ZH.get(h_style, h_style)
    a_style_zh = _STYLE_ZH.get(a_style, a_style)
    h_profile   = _STYLE_PROFILE.get(h_style, {})
    a_profile   = _STYLE_PROFILE.get(a_style, {})

    matchup_key = f"{h_style}_{a_style}"
    matchup_tag, matchup_note = _MATCHUP_KEY_NOTES.get(
        matchup_key, ("📊 戰術對決", "雙方陣型風格相近，個人質量差異與臨場調度將是勝負關鍵")
    )

    h_mid = _midfield_count(h_form) if h_form != "?" else 3
    a_mid = _midfield_count(a_form) if a_form != "?" else 3
    if h_mid > a_mid:
        mid_note = f"中場人數：{home_zh_name} {h_mid}v{a_mid} 數量佔優"
    elif a_mid > h_mid:
        mid_note = f"中場人數：{away_zh_name} {a_mid}v{h_mid} 數量佔優"
    else:
        mid_note = f"中場人數持平（各 {h_mid} 人），需靠技術與跑動製造優勢"

    return f"""<div style='margin-top:10px;padding:12px 14px;background:rgba(255,255,255,0.03);
border:1px solid var(--border);border-radius:8px;font-size:0.8rem'>
  <div style='font-size:0.7rem;font-weight:600;color:var(--muted);text-transform:uppercase;
  letter-spacing:0.5px;margin-bottom:10px'>⚽ 陣型戰術分析</div>

  <div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;
  padding-bottom:8px;border-bottom:1px solid var(--border)'>
    <div style='text-align:center;flex:1'>
      <div style='font-size:1.05rem;font-weight:700;color:var(--accent)'>{h_form}</div>
      <div style='font-size:0.68rem;color:var(--muted);margin-top:2px'>{h_style_zh}</div>
    </div>
    <div style='color:var(--muted);font-size:0.72rem;padding:0 10px'>VS</div>
    <div style='text-align:center;flex:1'>
      <div style='font-size:1.05rem;font-weight:700;color:var(--gold)'>{a_form}</div>
      <div style='font-size:0.68rem;color:var(--muted);margin-top:2px'>{a_style_zh}</div>
    </div>
  </div>

  <div style='margin-bottom:8px;padding:8px 10px;background:rgba(59,130,246,0.06);border-radius:6px;
  border-left:3px solid var(--accent)'>
    <div style='font-size:0.68rem;font-weight:700;color:var(--accent);margin-bottom:5px'>
      {home_zh_name} · {h_style_zh}
    </div>
    <div style='font-size:0.71rem;color:var(--text);line-height:1.7'>
      <span style='color:#34d399;font-weight:600'>✓ 優勢條件：</span>{h_profile.get("thrives", "—")}<br>
      <span style='color:var(--gold);font-weight:600'>△ 弱點所在：</span>{h_profile.get("weakness", "—")}<br>
      <span style='color:var(--red);font-weight:600'>⚡ 需防對手：</span>{h_profile.get("threat", "—")}
    </div>
  </div>

  <div style='margin-bottom:8px;padding:8px 10px;background:rgba(245,158,11,0.06);border-radius:6px;
  border-left:3px solid var(--gold)'>
    <div style='font-size:0.68rem;font-weight:700;color:var(--gold);margin-bottom:5px'>
      {away_zh_name} · {a_style_zh}
    </div>
    <div style='font-size:0.71rem;color:var(--text);line-height:1.7'>
      <span style='color:#34d399;font-weight:600'>✓ 優勢條件：</span>{a_profile.get("thrives", "—")}<br>
      <span style='color:var(--gold);font-weight:600'>△ 弱點所在：</span>{a_profile.get("weakness", "—")}<br>
      <span style='color:var(--red);font-weight:600'>⚡ 需防對手：</span>{a_profile.get("threat", "—")}
    </div>
  </div>

  <div style='padding:8px 10px;background:rgba(255,255,255,0.02);border-radius:6px;
  border:1px dashed rgba(100,116,139,0.4)'>
    <div style='font-size:0.67rem;font-weight:700;color:var(--muted);margin-bottom:4px'>
      本場關鍵評估 {matchup_tag}
    </div>
    <div style='font-size:0.71rem;color:var(--text);line-height:1.6'>
      {matchup_note}。{mid_note}。
    </div>
  </div>
</div>"""

def _ah_covers(h: int, a: int, ah_line: float, ah_pred: str) -> bool:
    """True if score (h, a) covers the Asian Handicap prediction."""
    diff = h - a
    if ah_pred == "home":
        return diff > -ah_line   # e.g. line=-1.5 → need diff>1.5 → diff>=2
    else:
        return diff < -ah_line   # e.g. line=-1.5 → need diff<1.5 → diff<=1


def _ou_covers(h: int, a: int, ou_line: float, ou_pred: str) -> bool:
    """True if score (h, a) covers the Over/Under prediction."""
    total = h + a
    return total > ou_line if ou_pred == "over" else total < ou_line


def _score_dist_html(lh: float, la: float,
                     ah_line: float = None, ah_pred: str = None,
                     ou_line: float = None, ou_pred: str = None) -> str:
    """Top-8 Poisson score distribution with mini bar chart.

    When AH/OU params supplied, highlights scores satisfying both and shows
    cumulative combined-cover probability.
    """
    if lh <= 0 or la <= 0:
        return ""

    def pmf(k, lam):
        return math.exp(-lam) * (lam ** k) / math.factorial(k)

    has_context = (ah_line is not None and ah_pred and ou_line is not None and ou_pred)

    # Build full 9×9 grid
    all_combos = []
    p_both_total = 0.0
    p_ah_total = 0.0
    p_ou_total = 0.0
    for h in range(9):
        for a in range(9):
            p = pmf(h, lh) * pmf(a, la)
            covers_ah = _ah_covers(h, a, ah_line, ah_pred) if has_context else False
            covers_ou = _ou_covers(h, a, ou_line, ou_pred) if has_context else False
            covers_both = covers_ah and covers_ou
            if covers_ah:
                p_ah_total += p
            if covers_ou:
                p_ou_total += p
            if covers_both:
                p_both_total += p
            all_combos.append((h, a, p, covers_both))

    all_combos.sort(key=lambda x: -x[2])
    top = all_combos[:8]
    max_p = top[0][2]

    rows = ""
    for h, a, p, both in top:
        pct = round(p * 100, 1)
        bar_w = round(p / max_p * 100)
        if h > a:
            bar_color = "var(--accent)"
        elif a > h:
            bar_color = "var(--gold)"
        else:
            bar_color = "var(--muted)"

        # Highlight scores that cover both conditions
        score_style = (
            "color:#4ade80;font-weight:800" if both
            else "color:var(--text);font-weight:700"
        )
        check = "✓" if both else ""
        rows += (
            f"<div style='display:flex;align-items:center;gap:6px;margin-bottom:4px'>"
            f"<div style='width:10px;font-size:0.65rem;color:#4ade80'>{check}</div>"
            f"<div style='width:26px;text-align:center;font-size:0.73rem;{score_style}'>{h}-{a}</div>"
            f"<div style='flex:1;height:5px;background:var(--border);border-radius:3px'>"
            f"<div style='width:{bar_w}%;height:100%;background:{bar_color};"
            f"{'box-shadow:0 0 4px #4ade8088' if both else ''};border-radius:3px'></div></div>"
            f"<div style='width:34px;text-align:right;font-size:0.69rem;color:var(--muted)'>{pct}%</div>"
            f"</div>"
        )

    # Combined cover badge
    combined_html = ""
    if has_context:
        pct_both = round(p_both_total * 100)
        pct_ah = round(p_ah_total * 100)
        pct_ou = round(p_ou_total * 100)
        ah_lbl = f"讓分覆蓋 {pct_ah}%"
        ou_lbl = f"大小球覆蓋 {pct_ou}%"
        col = "#4ade80" if pct_both >= 35 else ("var(--gold)" if pct_both >= 20 else "var(--muted)")
        combined_html = (
            f"<div style='margin-top:10px;padding:8px 10px;"
            f"background:rgba(74,222,128,0.08);border:1px solid rgba(74,222,128,0.25);"
            f"border-radius:6px'>"
            f"<div style='font-size:0.67rem;color:var(--muted);margin-bottom:4px'>"
            f"{ah_lbl}　{ou_lbl}</div>"
            f"<div style='display:flex;align-items:baseline;gap:6px'>"
            f"<span style='font-size:1.1rem;font-weight:800;color:{col}'>{pct_both}%</span>"
            f"<span style='font-size:0.72rem;color:var(--muted)'>兩盤同時覆蓋概率（綠色✓比分）</span>"
            f"</div></div>"
        )

    return (
        "<div class='market-box'>"
        "<div class='market-label'>比分概率分佈（Poisson）</div>"
        f"<div style='margin-top:6px;font-size:0.67rem;color:var(--muted);margin-bottom:6px'>"
        f"藍=主勝　黃=客勝　灰=平局　<span style='color:#4ade80'>✓=兩盤同覆</span></div>"
        f"<div>{rows}</div>"
        f"{combined_html}"
        "</div>"
    )


def _us_odds_to_prob(ml_str) -> float:
    """Convert American moneyline string to implied probability (no vig)."""
    try:
        v = int(str(ml_str).replace("+", ""))
        return abs(v) / (abs(v) + 100) if v < 0 else 100 / (v + 100)
    except Exception:
        return 0.0


def _goal_dist_summary_html(lh: float, la: float) -> str:
    """Compact goal-distribution stats: BTTS, O1.5, O2.5, O3.5, clean sheet."""
    if lh <= 0 or la <= 0:
        return ""
    import math as _m

    def _poisson_cdf_ge(k_min, lam):
        return 1.0 - sum(_m.exp(-lam) * lam**k / _m.factorial(k) for k in range(k_min))

    p_home_score = 1 - _m.exp(-lh)   # P(home ≥ 1)
    p_away_score = 1 - _m.exp(-la)
    p_btts = p_home_score * p_away_score

    # Total = sum of two independent Poisson → Poisson(lh+la) for OU approximation
    lt = lh + la
    p_o15 = _poisson_cdf_ge(2, lt)
    p_o25 = _poisson_cdf_ge(3, lt)
    p_o35 = _poisson_cdf_ge(4, lt)
    p_cs_home = _m.exp(-la)   # away scores 0
    p_cs_away = _m.exp(-lh)   # home scores 0

    def _pct(v): return f"{round(v*100)}%"
    def _chip(label, val, hi_thresh=0.6, lo_thresh=0.4):
        pct = round(val * 100)
        col = "var(--accent)" if val >= hi_thresh else ("var(--red)" if val <= lo_thresh else "var(--muted)")
        return (f"<div class='gd-chip'><span class='gd-lbl'>{label}</span>"
                f"<span class='gd-val' style='color:{col}'>{pct}%</span></div>")

    return (
        "<div class='gd-grid'>"
        + _chip("雙方進球", p_btts)
        + _chip("逾1.5球", p_o15, 0.8, 0.5)
        + _chip("逾2.5球", p_o25, 0.65, 0.35)
        + _chip("逾3.5球", p_o35, 0.45, 0.25)
        + _chip("主隊零失球", p_cs_home, 0.35, 0.15)
        + _chip("客隊零失球", p_cs_away, 0.35, 0.15)
        + "</div>"
    )


def _odds_edge_html(p_hw: float, p_d: float, p_aw: float,
                    dk_ml_home, dk_ml_draw, dk_ml_away) -> str:
    """Compare model probabilities vs DK market implied probs; show edge per outcome."""
    mkt_h = _us_odds_to_prob(dk_ml_home)
    mkt_d = _us_odds_to_prob(dk_ml_draw)
    mkt_a = _us_odds_to_prob(dk_ml_away)

    if mkt_h == 0 and mkt_d == 0 and mkt_a == 0:
        return ""

    # Normalise market (remove vig)
    tot = mkt_h + mkt_d + mkt_a
    if tot > 0:
        mkt_h /= tot
        mkt_d /= tot
        mkt_a /= tot

    def _edge_chip(label, model_p, mkt_p, color):
        edge = model_p - mkt_p
        edge_str = f"{edge:+.0%}"
        if edge > 0.04:
            badge_col = "var(--green)"
            badge_txt = f"▲{edge_str}"
        elif edge < -0.04:
            badge_col = "var(--red)"
            badge_txt = f"▼{edge_str}"
        else:
            badge_col = "var(--muted)"
            badge_txt = edge_str
        return (
            f"<div class='oe-item'>"
            f"<span class='oe-lbl' style='color:{color}'>{label}</span>"
            f"<span class='oe-mkt'>{round(mkt_p*100)}%</span>"
            f"<span class='oe-arr'>→</span>"
            f"<span class='oe-model'>{round(model_p*100)}%</span>"
            f"<span class='oe-badge' style='color:{badge_col}'>{badge_txt}</span>"
            f"</div>"
        )

    return (
        "<div class='oe-wrap'>"
        + _edge_chip("主勝", p_hw, mkt_h, "var(--accent)")
        + _edge_chip("平局", p_d, mkt_d, "var(--muted)")
        + _edge_chip("客勝", p_aw, mkt_a, "var(--gold)")
        + "</div>"
    )


def _et_advancement_html(lh: float, la: float, home_zh: str, away_zh: str) -> str:
    """Full knockout probability tree: 90' outcomes → ET → penalties → overall advancement."""
    if lh <= 0 or la <= 0:
        return ""

    def pmf(k, lam):
        return math.exp(-lam) * (lam ** k) / math.factorial(k)

    # 90-minute outcomes
    p_h90 = p_d90 = p_a90 = 0.0
    for h in range(10):
        for a in range(10):
            p = pmf(h, lh) * pmf(a, la)
            if h > a:
                p_h90 += p
            elif h == a:
                p_d90 += p
            else:
                p_a90 += p

    # ET goal rates (30 min, fatigue factor 0.85)
    lh_et = lh * (1 / 3) * 0.85
    la_et = la * (1 / 3) * 0.85

    p_home_et = p_away_et = 0.0
    for h in range(9):
        for a in range(9):
            p = pmf(h, lh_et) * pmf(a, la_et)
            if h > a:
                p_home_et += p
            elif a > h:
                p_away_et += p
    p_draw_et = 1.0 - p_home_et - p_away_et

    # PK: slight strength-ratio tilt, max ±10%
    strength_ratio = lh / (lh + la)
    pk_home = 0.5 + (strength_ratio - 0.5) * 0.2
    pk_away = 1.0 - pk_home

    # Overall advancement probability
    p_home_wins = p_h90 + p_d90 * (p_home_et + p_draw_et * pk_home)
    p_away_wins = p_a90 + p_d90 * (p_away_et + p_draw_et * pk_away)
    p_pens = p_d90 * p_draw_et

    h90_pct = round(p_h90 * 100)
    d90_pct = round(p_d90 * 100)
    a90_pct = round(p_a90 * 100)
    et_home_pct = round(p_home_et * 100)
    et_away_pct = round(p_away_et * 100)
    pk_pct = round(p_pens * 100)
    hw_pct = round(p_home_wins * 100)
    aw_pct = 100 - hw_pct

    hw_col = "var(--accent)" if hw_pct >= 55 else ("var(--gold)" if hw_pct <= 45 else "var(--text)")
    aw_col = "var(--gold)" if aw_pct >= 55 else ("var(--accent)" if aw_pct <= 45 else "var(--text)")
    et_col = "#f59e0b" if d90_pct >= 30 else "var(--muted)"

    return f"""<div class='market-box et-box'>
  <div class='market-label'>🏆 淘汰賽勝出路徑（含加時 / 點球）</div>
  <div style='margin-top:8px;display:flex;flex-direction:column;gap:5px'>
    <div style='display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:rgba(255,255,255,0.03);border-radius:6px'>
      <span style='font-size:0.75rem;color:var(--muted)'>正規90分鐘</span>
      <div style='display:flex;gap:12px;font-size:0.78rem'>
        <span style='color:var(--accent);font-weight:700'>{home_zh} {h90_pct}%</span>
        <span style='color:{et_col}'>平局→加時 {d90_pct}%</span>
        <span style='color:var(--gold);font-weight:700'>{a90_pct}% {away_zh}</span>
      </div>
    </div>
    <div style='display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:rgba(245,158,11,0.05);border-radius:6px;border:1px solid rgba(245,158,11,0.15)'>
      <span style='font-size:0.75rem;color:{et_col}'>加時賽（條件）</span>
      <div style='display:flex;gap:12px;font-size:0.75rem'>
        <span style='color:var(--accent)'>{et_home_pct}%主勝</span>
        <span style='color:var(--muted)'>點球 {pk_pct}%</span>
        <span style='color:var(--gold)'>{et_away_pct}%客勝</span>
      </div>
    </div>
    <div style='display:flex;justify-content:space-between;align-items:center;padding:7px 10px;background:rgba(59,130,246,0.08);border-radius:6px;border:1px solid rgba(59,130,246,0.2)'>
      <div>
        <div style='font-size:0.65rem;color:var(--muted);margin-bottom:1px'>整體晉級</div>
        <div style='font-size:1.1rem;font-weight:800;color:{hw_col}'>{home_zh} {hw_pct}%</div>
      </div>
      <div style='font-size:0.68rem;color:var(--muted)'>含加時+點球</div>
      <div style='text-align:right'>
        <div style='font-size:0.65rem;color:var(--muted);margin-bottom:1px'>整體晉級</div>
        <div style='font-size:1.1rem;font-weight:800;color:{aw_col}'>{aw_pct}% {away_zh}</div>
      </div>
    </div>
  </div>
</div>"""


def _ah_pred_label(ah_prediction: str, ah_line: float, home: str = "主隊", away: str = "客隊") -> str:
    if ah_prediction == "home":
        return f"{home}讓球勝" if ah_line < 0 else f"{home}受讓勝"
    else:
        return f"{away}受讓勝" if ah_line < 0 else f"{away}讓球勝"
_OU_LABEL = {"over": "大球", "under": "小球"}
_AH_COLOR = {"home": "#3b82f6", "away": "#f59e0b"}
_OU_COLOR = {"over": "#10b981", "under": "#ef4444"}

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #080c14;
  --surface: #0e1523;
  --card: #131d2e;
  --border: #1e2d45;
  --accent: #3b82f6;
  --gold: #f59e0b;
  --green: #10b981;
  --red: #ef4444;
  --text: #e2e8f0;
  --muted: #64748b;
  --radius: 12px;
}
body {
  font-family: "Inter", "PingFang TC", "Microsoft JhengHei", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  line-height: 1.5;
}
/* ── header ── */
header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(8px);
}
.logo { display: flex; align-items: center; gap: 10px; }
.logo-icon { font-size: 1.5rem; }
.logo-text { font-size: 1.1rem; font-weight: 700; color: var(--text); letter-spacing: -0.3px; }
.logo-sub { font-size: 0.72rem; color: var(--muted); margin-top: 1px; }
/* ── nav ── */
nav { display: flex; gap: 2px; }
nav a {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 16px;
  color: var(--muted);
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 500;
  border-radius: 8px;
  transition: all 0.15s;
}
nav a:hover { color: var(--text); background: rgba(255,255,255,0.05); }
nav a.active { color: var(--accent); background: rgba(59,130,246,0.1); }
/* ── mobile ── */
@media (max-width: 600px) {
  header { padding: 0 14px; height: auto; min-height: 56px; flex-wrap: wrap; gap: 6px; padding-top: 8px; padding-bottom: 8px; }
  .logo-sub { display: none; }
  .logo-text { font-size: 0.95rem; }
  .logo-icon { font-size: 1.2rem; }
  nav { gap: 0; }
  nav a { padding: 6px 9px; font-size: 0.75rem; gap: 4px; }
  main { padding: 20px 14px; }
  .card-header { padding: 14px 16px 12px; }
  .card-body { padding: 12px 16px; }
  .teams { gap: 8px; }
  .team-name { font-size: 0.9rem; }
  .predicted-score { font-size: 1.3rem; }
}
/* ── main ── */
main { max-width: 1100px; margin: 0 auto; padding: 32px 20px; }
/* ── page header ── */
.page-header { margin-bottom: 28px; }
.page-title { font-size: 1.5rem; font-weight: 700; color: var(--text); margin-bottom: 6px; }
.date-chip {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 20px; padding: 4px 12px;
  font-size: 0.78rem; color: var(--muted);
}
/* ── match card ── */
.cards { display: flex; flex-direction: column; gap: 16px; }
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.card:hover { border-color: rgba(59,130,246,0.4); box-shadow: 0 4px 24px rgba(59,130,246,0.08); }
.card-header {
  padding: 18px 24px 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--border);
}
.teams {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 16px;
  min-height: 52px;
}
.team { display: flex; flex-direction: column; gap: 3px; }
.team.home { text-align: right; }
.team.away { text-align: left; }
.team-name { font-size: 1.05rem; font-weight: 700; color: var(--text); }
.team-strength { font-size: 0.75rem; color: var(--muted); }
.vs-block { text-align: center; min-width: 80px; }
.vs-label { font-size: 0.65rem; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
.predicted-score {
  font-size: 1.6rem; font-weight: 800;
  background: linear-gradient(135deg, var(--accent), var(--gold));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.source-chip {
  font-size: 0.7rem; color: var(--muted);
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 10px;
  white-space: nowrap;
}
/* ── card body ── */
.card-body { padding: 16px 24px; display: flex; gap: 16px; flex-wrap: wrap; }
.market-box {
  flex: 1; min-width: 180px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
}
.et-box {
  flex: 1 1 100%;
  background: rgba(139,92,246,0.06);
  border-color: rgba(139,92,246,0.25);
}
.market-label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 10px; }
.market-prediction {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 8px;
}
.market-name { font-size: 0.95rem; font-weight: 700; }
.market-name.blue { color: var(--accent); }
.market-name.gold { color: var(--gold); }
.market-name.green { color: var(--green); }
.market-name.red { color: var(--red); }
.conf-badge {
  font-size: 0.72rem; font-weight: 700;
  padding: 3px 8px; border-radius: 4px;
}
.conf-high { background: rgba(16,185,129,0.15); color: var(--green); }
.conf-mid  { background: rgba(245,158,11,0.15); color: var(--gold); }
.conf-low  { background: rgba(100,116,139,0.12); color: var(--muted); }
/* prob bar */
.prob-bar-track {
  height: 4px; background: var(--border); border-radius: 2px; overflow: hidden;
}
.prob-bar-fill { height: 100%; border-radius: 2px; transition: width 0.3s; }
.fill-blue  { background: var(--accent); }
.fill-gold  { background: var(--gold); }
.fill-green { background: var(--green); }
.fill-red   { background: var(--red); }
/* 1x2 row */
.onex2 { display: flex; gap: 8px; margin-top: 12px; }
.onex2-item { flex: 1; text-align: center; }
.onex2-pct { font-size: 1rem; font-weight: 700; }
.onex2-lbl { font-size: 0.65rem; color: var(--muted); margin-top: 1px; }
.onex2-odds { font-size: 0.67rem; color: #475569; margin-top: 3px; letter-spacing: 0.3px; }
.onex2-bar {
  display: flex; height: 6px; border-radius: 4px; overflow: hidden;
  margin-top: 10px; background: var(--border); gap: 1px;
}
.onex2-bar > div { transition: width 0.3s; }
/* ── odds edge ── */
.oe-wrap { margin-top: 9px; display: flex; flex-direction: column; gap: 4px; }
.oe-item { display: flex; align-items: center; gap: 5px; font-size: 0.69rem; }
.oe-lbl  { width: 28px; font-weight: 700; }
.oe-mkt  { width: 30px; color: var(--muted); text-align: right; }
.oe-arr  { color: var(--border); }
.oe-model{ width: 30px; color: var(--text); font-weight: 600; }
.oe-badge{ font-size: 0.65rem; font-weight: 700; margin-left: 2px; }
/* ── goal distribution chips ── */
.gd-grid { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 9px; }
.gd-chip {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 5px; padding: 3px 7px; display: flex; gap: 4px;
  align-items: center;
}
.gd-lbl { font-size: 0.64rem; color: var(--muted); font-weight: 600; }
.gd-val { font-size: 0.68rem; font-weight: 700; }
/* ── empty state ── */
.empty { text-align: center; padding: 72px 20px; color: var(--muted); }
.empty-icon { font-size: 2.5rem; margin-bottom: 12px; }
.empty p { font-size: 0.9rem; }
/* ── table ── */
table { width: 100%; border-collapse: collapse; }
thead tr { background: var(--surface); }
th {
  padding: 12px 16px;
  text-align: left;
  font-size: 0.72rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}
td {
  padding: 14px 16px;
  font-size: 0.88rem;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255,255,255,0.02); }
.tbl-wrap {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
/* ── misc ── */
.section-title { font-size: 1rem; font-weight: 600; margin: 28px 0 14px; color: var(--text); }
p { color: var(--muted); font-size: 0.88rem; line-height: 1.7; margin-bottom: 12px; }
.tag {
  display: inline-flex; align-items: center;
  background: rgba(59,130,246,0.1); color: var(--accent);
  border-radius: 4px; padding: 2px 8px; font-size: 0.72rem; font-weight: 600;
}
.correct { color: var(--green); font-weight: 600; }
.wrong   { color: var(--red); font-weight: 600; }
/* ── stat summary row ── */
.stat-row {
  display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px;
}
.stat-box {
  flex: 1; min-width: 100px;
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 12px; text-align: center;
}
.stat-num { font-size: 1.6rem; font-weight: 700; line-height: 1.2; }
.stat-lbl { font-size: 0.75rem; color: var(--muted); margin-top: 4px; }
/* ── kickoff time ── */
.kickoff-time {
  font-size: 0.78rem; color: var(--gold); font-weight: 600;
  margin-bottom: 10px; letter-spacing: 0.3px;
}
/* ── reasoning ── */
.time-basis-note {
  font-size: 0.75rem;
  color: #64748b;
  background: rgba(100,116,139,0.08);
  border: 1px solid rgba(100,116,139,0.2);
  border-radius: 6px;
  padding: 6px 10px;
  margin-bottom: 10px;
}
.time-basis-note strong { color: #94a3b8; }
.reasoning-box {
  margin-top: 14px;
  background: rgba(30,45,69,0.6);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
}
.reasoning-title {
  font-size: 0.72rem; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px;
}
.reasoning-line {
  font-size: 0.82rem; color: #94a3b8; line-height: 1.7;
}
.reasoning-line + .reasoning-line { margin-top: 3px; }
/* ── injury ── */
.injury-box {
  margin-top: 10px;
  background: rgba(239,68,68,0.06);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 0.8rem;
}
.injury-none {
  color: var(--muted); font-size: 0.76rem;
  background: transparent; border-color: var(--border);
}
.injury-title {
  font-size: 0.72rem; font-weight: 700; color: #ef4444;
  text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px;
}
.injury-item { color: #fca5a5; margin-top: 3px; }
/* ── mobile responsive ── */
@media (max-width: 640px) {
  header {
    padding: 10px 14px;
    height: auto;
    flex-wrap: wrap;
    gap: 6px;
  }
  nav {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 2px;
    gap: 2px;
    scrollbar-width: none;
  }
  nav::-webkit-scrollbar { display: none; }
  nav a {
    padding: 6px 10px;
    font-size: 0.78rem;
    white-space: nowrap;
  }
  main { padding: 16px 12px; }
  .card-header { padding: 12px 14px 10px; flex-wrap: wrap; }
  .card-body { padding: 12px 14px; gap: 10px; }
  .teams {
    grid-template-columns: 1fr 68px 1fr;
    gap: 8px;
  }
  .team-name { font-size: 0.88rem; }
  .predicted-score { font-size: 1.25rem; }
  .vs-block { min-width: 68px; }
  .market-box { min-width: 0; flex: 1 1 calc(50% - 5px); }
  .reasoning-box { width: 100%; }
  .injury-box { width: 100%; }
  .stat-row { gap: 8px; }
  .stat-box { min-width: 72px; padding: 10px 8px; }
  .stat-num { font-size: 1.3rem; }
  .tbl-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .tbl-wrap table { min-width: 480px; }
  .page-title { font-size: 1.2rem; }
}
"""


def _base_html(title: str, body: str, active_nav: str = "") -> str:
    nav_items = [
        ("index.html", "今日預測", "📊"),
        ("results.html", "歷史結果", "📜"),
        ("calibration.html", "模型校正", "⚙️"),
        ("postmortem.html", "復盤分析", "🔍"),
    ]
    nav_html = "".join(
        f'<a href="{href}" class="{"active" if active_nav == label else ""}">{icon} {label}</a>'
        for href, label, icon in nav_items
    )
    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="logo">
    <span class="logo-icon">⚽</span>
    <div>
      <div class="logo-text">世界盃 2026 預測系統</div>
      <div class="logo-sub">亞洲讓球盤 · 大小球 · 比分預測</div>
    </div>
  </div>
  <nav>{nav_html}</nav>
</header>
<main>
{body}
</main>
<script>
document.querySelectorAll('time.local-time').forEach(function(el) {{
  var dt = new Date(el.getAttribute('datetime'));
  if (!isNaN(dt)) {{
    var mm = String(dt.getMonth() + 1).padStart(2, '0');
    var dd = String(dt.getDate()).padStart(2, '0');
    var hh = String(dt.getHours()).padStart(2, '0');
    var mi = String(dt.getMinutes()).padStart(2, '0');
    el.textContent = mm + '/' + dd + ' ' + hh + ':' + mi;
  }}
}});
</script>
</body>
</html>"""


def _fmt_ah_val(val: float) -> str:
    """Convert AH line absolute value to Asian bookmaker notation.
    0.25 → '0+50', 0.75 → '1-50', 1.25 → '1+50', 0.5 → '0.5', 1.0 → '1'
    """
    frac = round(val % 1, 2)
    whole = int(val)
    if frac == 0.25:
        return "%d+50" % whole
    if frac == 0.75:
        return "%d-50" % (whole + 1)
    if frac == 0:
        return "%d" % whole
    return "%.1f" % val


def _fmt_ah_line(ah_line: float) -> str:
    """Format AH line with direction label."""
    if ah_line == 0:
        return "平手盤"
    val = _fmt_ah_val(abs(ah_line))
    return ("主讓 %s" if ah_line < 0 else "客讓 %s") % val


def _conf_class(conf: int) -> str:
    if conf >= 55:
        return "conf-high"
    if conf >= 35:
        return "conf-mid"
    return "conf-low"


def _prob_bar(pct: int, color_class: str) -> str:
    return (
        f'<div class="prob-bar-track">'
        f'<div class="prob-bar-fill {color_class}" style="width:{min(100,pct)}%"></div>'
        f'</div>'
    )


def render_index(predictions: list, date: str, out_path: str = None) -> None:
    if predictions:
        cards = ""
        for p in predictions:
            ah_dir = p["ah_prediction"]
            ou_dir = p["ou_prediction"]
            ou_label = _OU_LABEL.get(ou_dir, ou_dir)
            ah_conf = p["ah_confidence"]
            ou_conf = p["ou_confidence"]
            ah_color = "blue" if ah_dir == "home" else "gold"
            ou_color = "green" if ou_dir == "over" else "red"
            ah_fill = "fill-blue" if ah_dir == "home" else "fill-gold"
            ou_fill = "fill-green" if ou_dir == "over" else "fill-red"
            cc_ah = _conf_class(ah_conf)
            cc_ou = _conf_class(ou_conf)

            lh_val = float(p.get("lambda_home") or 0)
            la_val = float(p.get("lambda_away") or 0)
            score = p.get("predicted_score") or "?-?"
            score_prob = p.get("predicted_score_prob", "")
            p_hw_raw = p.get("p_home_win", 0) or 0
            p_d_raw = p.get("p_draw", 0) or 0
            p_aw_raw = p.get("p_away_win", 0) or 0
            p_hw = int(p_hw_raw * 100)
            p_d = int(p_d_raw * 100)
            p_aw = int(p_aw_raw * 100)
            # implied fair odds
            odds_hw = f"{1/p_hw_raw:.2f}" if p_hw_raw > 0 else "-"
            odds_d  = f"{1/p_d_raw:.2f}"  if p_d_raw  > 0 else "-"
            odds_aw = f"{1/p_aw_raw:.2f}" if p_aw_raw > 0 else "-"
            factors = "、".join(p.get("key_factors", []))
            source = ""
            for f in p.get("key_factors", []):
                if "強度來源" in f:
                    source = f.replace("強度來源：", "")

            home_zh = team_zh(p['home_team'])
            away_zh = team_zh(p['away_team'])

            ah_line_val = p.get("ah_line") or p.get("dk_ah_line")
            if ah_line_val is None:
                # Old prediction format without ah_line: derive from stored lambdas
                _lh = float(p.get("lambda_home", 0) or 0)
                _la = float(p.get("lambda_away", 0) or 0)
                ah_line_val = round(round(-(_lh - _la) * 4) / 4, 2) if (_lh and _la) else 0
            ah_line_val = ah_line_val or 0
            ou_line_val = p.get("ou_line") or p.get("dk_ou_line") or 2.5
            ah_label = _ah_pred_label(ah_dir, ah_line_val, home_zh, away_zh)
            ah_line_label = "亞洲讓球盤（%s）" % _fmt_ah_line(ah_line_val)
            ou_line_label = "大小球（%g）" % ou_line_val

            kickoff = p.get("kickoff", "")
            kickoff_utc = p.get("kickoff_utc", "")
            reasoning_lines = p.get("reasoning", "").split("\n")
            injury_notes = p.get("injury_notes", [])

            reasoning_html = "".join(
                f'<div class="reasoning-line">{line}</div>'
                for line in reasoning_lines if line.strip()
            )
            injury_html = ""
            if injury_notes:
                items = "".join(f'<div class="injury-item">🤕 {n}</div>' for n in injury_notes)
                injury_html = f'<div class="injury-box"><div class="injury-title">傷兵報告</div>{items}</div>'
            else:
                injury_html = '<div class="injury-box injury-none">傷兵狀況：暫無已知缺陣</div>'

            cards += f"""
<div class="card">
  <div class="card-header">
    {'<div class="kickoff-time">🕐 開賽時間：<time class="local-time" datetime="' + kickoff_utc + '">' + kickoff + '</time></div>' if kickoff_utc else ''}
    <div class="teams">
      <div class="team home">
        <div class="team-name">{home_zh}</div>
        <div class="team-strength">λ={p.get('lambda_home','?')}</div>
      </div>
      <div class="vs-block">
        <div class="vs-label">最可能比分</div>
        <div class="predicted-score">{score}</div>
        {f"<div style='font-size:0.6rem;color:var(--muted);margin-top:2px'>概率 {score_prob}%</div>" if score_prob else ""}
      </div>
      <div class="team away">
        <div class="team-name">{away_zh}</div>
        <div class="team-strength">λ={p.get('lambda_away','?')}</div>
      </div>
    </div>
    {'<span class="source-chip">' + source + '</span>' if source else ''}
  </div>
  <div class="card-body">
    <div class="time-basis-note">⏱ 以下預測均以<strong>正規90分鐘</strong>為基準，不含加時賽（AET）及互射十二碼（PK）</div>
    <div class="market-box">
      <div class="market-label">{ah_line_label}</div>
      <div class="market-prediction">
        <span class="market-name {ah_color}">{ah_label}</span>
        <span class="conf-badge {cc_ah}">信心 {ah_conf}%</span>
      </div>
      {_prob_bar(ah_conf, ah_fill)}
    </div>
    <div class="market-box">
      <div class="market-label">{ou_line_label}</div>
      <div class="market-prediction">
        <span class="market-name {ou_color}">{ou_label}</span>
        <span class="conf-badge {cc_ou}">信心 {ou_conf}%</span>
      </div>
      {_prob_bar(ou_conf, ou_fill)}
    </div>
    <div class="market-box">
      <div class="market-label">勝負賠率（1X2）</div>
      <div class="onex2">
        <div class="onex2-item">
          <div class="onex2-pct" style="color:var(--accent)">{p_hw}%</div>
          <div class="onex2-lbl">主隊勝</div>
          <div class="onex2-odds">{odds_hw}</div>
        </div>
        <div class="onex2-item">
          <div class="onex2-pct" style="color:var(--muted)">{p_d}%</div>
          <div class="onex2-lbl">平局</div>
          <div class="onex2-odds">{odds_d}</div>
        </div>
        <div class="onex2-item">
          <div class="onex2-pct" style="color:var(--gold)">{p_aw}%</div>
          <div class="onex2-lbl">客隊勝</div>
          <div class="onex2-odds">{odds_aw}</div>
        </div>
      </div>
      <div class="onex2-bar">
        <div style="width:{p_hw}%;background:var(--accent)" title="主隊勝 {p_hw}%"></div>
        <div style="width:{p_d}%;background:var(--muted)" title="平局 {p_d}%"></div>
        <div style="width:{p_aw}%;background:var(--gold)" title="客隊勝 {p_aw}%"></div>
      </div>
      {_odds_edge_html(p_hw_raw, p_d_raw, p_aw_raw, p.get('dk_ml_home'), p.get('dk_ml_draw'), p.get('dk_ml_away'))}
      {_goal_dist_summary_html(lh_val, la_val)}
    </div>
    {_score_dist_html(lh_val, la_val, ah_line_val, ah_dir, ou_line_val, ou_dir)}
    {_et_advancement_html(lh_val, la_val, home_zh, away_zh) if p.get('stage', 'GROUP_STAGE') not in ('GROUP_STAGE', '') else ''}
    <div class="reasoning-box">
      <div class="reasoning-title">分析依據</div>
      {reasoning_html}
    </div>
    {_formation_analysis_html(p['home_team'], p['away_team'], home_zh, away_zh)}
    {_discipline_stats_html(p['home_team'], p['away_team'], home_zh, away_zh)}
    {injury_html}
  </div>
</div>"""
        content = f'<div class="cards">{cards}</div>'
    else:
        content = '<div class="empty"><div class="empty-icon">📋</div><p>今日暫無比賽資料<br>GitHub Actions 將在每日 06:00 UTC 自動更新</p></div>'

    body = f"""
<div class="page-header">
  <div class="page-title">今日賽事預測</div>
  <span class="date-chip">📅 {date}</span>
</div>
{content}"""
    html = _base_html(f"世界盃預測 {date}", body, active_nav="今日預測")
    path = out_path or str(DOCS_DIR / "index.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def _load_postmortem() -> dict:
    path = Path(__file__).parent.parent / "data" / "backtest" / "postmortem.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def render_postmortem(out_path: str = None) -> None:
    pm = _load_postmortem()
    _AH_PRED_ZH = {"home": "主隊", "away": "客隊"}
    _OU_PRED_ZH = {"over": "大球", "under": "小球"}

    if not pm or not pm.get("matches"):
        body = (
            "<div class='page-header'><div class='page-title'>復盤分析</div></div>"
            "<div class='empty'><div class='empty-icon'>🔍</div>"
            "<p>賽後復盤將在每次有新比賽結果後自動更新</p></div>"
        )
        html = _base_html("復盤分析", body, active_nav="復盤分析")
        path = out_path or str(DOCS_DIR / "postmortem.html")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(html, encoding="utf-8")
        return

    s = pm["summary"]
    updated = pm.get("generated_at", "")[:10]

    summary = (
        "<div class='stat-row'>"
        "<div class='stat-box'><div class='stat-num'>%d</div><div class='stat-lbl'>回測場數</div></div>"
        "<div class='stat-box'><div class='stat-num' style='color:var(--accent)'>%.1f%%</div><div class='stat-lbl'>讓球盤準確率</div></div>"
        "<div class='stat-box'><div class='stat-num' style='color:var(--gold)'>%.1f%%</div><div class='stat-lbl'>大小球準確率</div></div>"
        "<div class='stat-box'><div class='stat-num'>%d</div><div class='stat-lbl'>比分完全猜對</div></div>"
        "<div class='stat-box'><div class='stat-num'>%.1f</div><div class='stat-lbl'>總球數誤差均值</div></div>"
        "</div>"
    ) % (pm["total_matches"], s["ah_accuracy"] * 100, s["ou_accuracy"] * 100,
         s["score_exact_match"], s["avg_goal_total_error"])

    # Team bias table
    team_rows = ""
    for t in pm["team_analysis"][:12]:
        bias = t["goal_bias"]
        if bias > 0.3:
            bias_color = "var(--red)"
            bias_txt = "+%.2f 高估" % bias
        elif bias < -0.3:
            bias_color = "var(--green)"
            bias_txt = "%.2f 低估" % bias
        else:
            bias_color = "var(--muted)"
            bias_txt = "%.2f 準確" % bias
        ah_txt = "%.1f%%" % (t["ah_accuracy"] * 100) if t["ah_accuracy"] is not None else "-"
        team_rows += (
            "<tr>"
            "<td>%s</td><td>%d</td><td>%.2f</td><td>%.2f</td>"
            "<td style='color:%s;font-weight:600'>%s</td><td>%s</td>"
            "</tr>"
        ) % (team_zh(t["team"]), t["matches"],
             t["pred_goals_avg"], t["actual_goals_avg"],
             bias_color, bias_txt, ah_txt)

    team_tbl = (
        "<div class='section-title'>進球預測偏差</div>"
        "<p>正值＝高估進球；負值＝低估。偏差大代表模型對該隊掌握較不準確。</p>"
        "<div class='tbl-wrap'><table><thead><tr>"
        "<th>隊伍</th><th>場次</th><th>預測均值</th><th>實際均值</th><th>偏差</th><th>AH準確率</th>"
        "</tr></thead><tbody>%s</tbody></table></div>"
    ) % team_rows

    # Missed AH table
    missed = pm.get("missed_ah_matches", [])
    if missed:
        missed_rows = ""
        for m in missed:
            pred_zh = _AH_PRED_ZH.get(m["ah_pred"], m["ah_pred"])
            actual_zh = _AH_PRED_ZH.get(m.get("actual_ah") or "", "")
            missed_rows += (
                "<tr>"
                "<td style='color:var(--muted)'>%s</td>"
                "<td style='color:var(--muted)'>%s組</td>"
                "<td><b>%s</b> vs <b>%s</b></td>"
                "<td style='text-align:center'>"
                "<div style='font-size:0.7rem;color:var(--muted)'>預測 %s</div>"
                "<div style='font-weight:700'>%s</div>"
                "</td>"
                "<td><span class='wrong'>預測%s →實際%s</span></td>"
                "</tr>"
            ) % (m["date"], m["group"],
                 team_zh(m["home"]), team_zh(m["away"]),
                 m["predicted_score"], m["actual_score"],
                 pred_zh, actual_zh)

        missed_tbl = (
            "<div class='section-title'>讓球盤預測失準（%d 場）</div>"
            "<div class='tbl-wrap'><table><thead><tr>"
            "<th>日期</th><th>組別</th><th>比賽</th><th>比分</th><th>讓球盤結果</th>"
            "</tr></thead><tbody>%s</tbody></table></div>"
        ) % (len(missed), missed_rows)
    else:
        missed_tbl = (
            "<div class='section-title'>讓球盤預測失準</div>"
            "<div class='empty'><div class='empty-icon'>✅</div><p>目前無失準記錄</p></div>"
        )

    body = (
        "<div class='page-header'><div class='page-title'>復盤分析</div>"
        "<span class='date-chip'>最後更新 %s</span></div>"
        "<p>Walk-forward 回測：每場比賽僅使用賽前數據預測，無未來資料洩漏。</p>"
        "%s%s%s"
    ) % (updated, summary, team_tbl, missed_tbl)

    html = _base_html("復盤分析", body, active_nav="復盤分析")
    path = out_path or str(DOCS_DIR / "postmortem.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_calibration(calibration: dict, brier_history: list, out_path: str = None) -> None:
    if brier_history:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=brier_history, mode="lines+markers", name="Brier Score",
            line=dict(color="#3b82f6", width=2),
            marker=dict(size=6, color="#3b82f6"),
        ))
        fig.add_hline(y=0.25, line_dash="dash", line_color="#ef4444",
                      annotation_text="重置閾值 0.25")
        fig.update_layout(
            paper_bgcolor="#0e1523", plot_bgcolor="#131d2e",
            font_color="#e2e8f0", font_family="Inter, system-ui",
            title=dict(text="模型 Brier Score 走勢（越低越準）", font_color="#3b82f6", font_size=15),
            xaxis=dict(title="天數", gridcolor="#1e2d45", zeroline=False),
            yaxis=dict(title="Brier Score", gridcolor="#1e2d45", range=[0, 0.5]),
            margin=dict(l=50, r=30, t=60, b=50),
            showlegend=False,
        )
        chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    else:
        chart_html = "<div class='empty'><div class='empty-icon'>📈</div><p>累積足夠資料後將顯示走勢圖</p></div>"

    param_labels = {
        "ah_weight": "讓球盤權重", "ou_weight": "大小球權重",
        "sharp_money_multiplier": "莊家資金信號係數",
        "incentive_boost": "必贏場進攻加成",
        "climate_penalty": "氣候不適應懲罰",
        "age_decay_threshold": "球隊老化閾值",
        "version": "模型版本", "last_updated": "最後更新",
    }
    rows = "".join(
        f"<tr><td>{param_labels.get(k, k)}</td><td><span class='tag'>{v}</span></td></tr>"
        for k, v in calibration.items()
    )
    body = f"""
<div class="page-header">
  <div class="page-title">模型校正</div>
</div>
{chart_html}
<div class="section-title">當前參數權重</div>
<div class="tbl-wrap">
  <table><thead><tr><th>參數</th><th>數值</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>"""
    html = _base_html("模型校正", body, active_nav="模型校正")
    path = out_path or str(DOCS_DIR / "calibration.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def _load_validation_results() -> dict:
    path = Path(__file__).parent.parent / "data" / "backtest" / "wc2026_validation.json"
    if path.exists():
        import json as _json
        return _json.loads(path.read_text())
    return {}


def _load_goal_events_for_date(date: str) -> dict:
    """Load goal events from match day JSON for a given date."""
    import json as _json
    path = Path(__file__).parent.parent / "data" / "matches" / f"{date}.json"
    if not path.exists():
        return {}
    try:
        return _json.loads(path.read_text()).get("goal_events", {})
    except Exception:
        return {}


def _load_predictions_for_date(date: str) -> list:
    """Load predictions JSON for a given date."""
    import json as _json
    path = Path(__file__).parent.parent / "data" / "predictions" / f"{date}.json"
    if not path.exists():
        return []
    try:
        return _json.loads(path.read_text())
    except Exception:
        return []


def _build_goal_timeline_html(match_detail) -> str:
    """Render goal/card timeline. Accepts both old (list) and new (dict) format."""
    if isinstance(match_detail, list):
        events = match_detail
    else:
        events = match_detail.get("events", []) if isinstance(match_detail, dict) else []

    if not events:
        return ""
    parts = []
    for e in events:
        if e.get("is_goal") and not e.get("is_shootout"):
            icon = "⚽(OG)" if e.get("is_own_goal") else "⚽"
            pk = " PK" if e.get("is_penalty") else ""
            parts.append(
                f"<span style='margin-right:10px;font-size:0.78rem'>"
                f"{icon} <b>{e['minute']}</b> {e['team']} {e['player']}{pk}</span>"
            )
        elif e.get("red_card"):
            parts.append(
                f"<span style='margin-right:10px;font-size:0.78rem'>"
                f"🟥 {e['minute']} {e['team']} {e['player']}</span>"
            )
    return "".join(parts) if parts else ""


def _build_penalty_html(penalties: dict, home_zh: str, away_zh: str) -> str:
    """Render penalty shootout as alternating kicks."""
    home_shots = penalties.get("home", [])
    away_shots = penalties.get("away", [])
    if not home_shots and not away_shots:
        return ""

    home_score = sum(1 for s in home_shots if s.get("scored"))
    away_score = sum(1 for s in away_shots if s.get("scored"))

    rows = ""
    max_kicks = max(len(home_shots), len(away_shots))
    for i in range(max_kicks):
        h = home_shots[i] if i < len(home_shots) else None
        a = away_shots[i] if i < len(away_shots) else None
        h_cell = f"{'✅' if h['scored'] else '❌'} {h['player']}" if h else ""
        a_cell = f"{'✅' if a['scored'] else '❌'} {a['player']}" if a else ""
        rows += (
            f"<tr>"
            f"<td style='text-align:right;font-size:0.75rem;padding:1px 6px'>{h_cell}</td>"
            f"<td style='text-align:center;font-size:0.7rem;color:var(--muted);padding:1px 4px'>{i+1}</td>"
            f"<td style='font-size:0.75rem;padding:1px 6px'>{a_cell}</td>"
            f"</tr>"
        )

    return (
        f"<div style='margin-top:6px'>"
        f"<div style='font-size:0.72rem;color:var(--muted);font-weight:600;margin-bottom:4px'>"
        f"🥅 點球大戰 {home_zh} {home_score}–{away_score} {away_zh}</div>"
        f"<table style='border-collapse:collapse;font-size:0.75rem'>"
        f"<thead><tr>"
        f"<th style='text-align:right;padding:1px 6px;font-size:0.7rem;color:var(--accent)'>{home_zh}</th>"
        f"<th style='padding:1px 4px;font-size:0.7rem;color:var(--muted)'>#</th>"
        f"<th style='padding:1px 6px;font-size:0.7rem;color:var(--gold)'>{away_zh}</th>"
        f"</tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _build_review_html(r: dict, pred, match_detail) -> str:
    """Build POST-MATCH REVIEW section for a result record."""
    home_zh = team_zh(r["home"])
    away_zh = team_zh(r["away"])
    actual_score = r["score"]
    # Use stored daily prediction as source of truth
    if pred and pred.get("predicted_score"):
        pred_score = pred["predicted_score"]
    else:
        pred_score = r.get("predicted_score", "?")

    hg, ag = map(int, actual_score.split("-")) if "-" in actual_score else (0, 0)
    actual_winner = "home" if hg > ag else ("away" if ag > hg else "draw")
    pred_hg, pred_ag = map(int, pred_score.split("-")) if "-" in pred_score else (-1, -1)
    pred_winner = "home" if pred_hg > pred_ag else ("away" if pred_ag > pred_hg else "draw")

    winner_zh = {"home": home_zh, "away": away_zh, "draw": "平局"}
    score_correct = pred_score == actual_score
    winner_correct = pred_winner == actual_winner

    # Extract extended match detail (new dict format) — must come before decided/advanced usage
    md = match_detail if isinstance(match_detail, dict) and "events" in match_detail else {}
    formations  = md.get("formations", {})
    lineups     = md.get("lineups", {})
    subs        = md.get("substitutions", [])
    stats       = md.get("stats", {})
    penalties   = md.get("penalties", {})
    linescores  = md.get("linescores", {})
    decided     = md.get("decided", "90min")  # "90min" | "extra_time" | "penalties"

    # Compute per-period scores from linescores
    ls_h = linescores.get("home", [])
    ls_a = linescores.get("away", [])
    def _ls(ls, idx): return ls[idx] if len(ls) > idx else 0
    ht_score  = f"{_ls(ls_h,0)}-{_ls(ls_a,0)}"
    ft_score  = f"{_ls(ls_h,0)+_ls(ls_h,1)}-{_ls(ls_a,0)+_ls(ls_a,1)}" if ls_h else actual_score
    aet_score = f"{sum(ls_h[:4])}-{sum(ls_a[:4])}" if decided in ("extra_time","penalties") and ls_h else ""
    pen_score = f"{_ls(ls_h,4)}-{_ls(ls_a,4)}" if decided == "penalties" and ls_h else ""

    # Winner in knockout = team that advanced (after pens if needed)
    advanced = None
    if decided == "penalties" and penalties:
        h_pens = sum(1 for s in penalties.get("home",[]) if s.get("scored"))
        a_pens = sum(1 for s in penalties.get("away",[]) if s.get("scored"))
        advanced = "home" if h_pens > a_pens else "away"
    elif decided == "extra_time" and aet_score:
        ah, aa = map(int, aet_score.split("-"))
        advanced = "home" if ah > aa else "away"
    else:
        advanced = actual_winner

    # In knockout, correct = predicted the team that advanced
    advance_correct = advanced == pred_winner if advanced else winner_correct

    # Model GOT RIGHT / MISSED
    got_right, missed = [], []
    if decided == "90min":
        if winner_correct:
            got_right.append(f"勝負方向（90分鐘）：預測{winner_zh[pred_winner]}")
        else:
            missed.append(f"勝負失準：預測{winner_zh[pred_winner]}→實際{winner_zh[actual_winner]}")
    else:
        stage_label = {"extra_time": "加時賽", "penalties": "點球大戰"}.get(decided, "")
        if advance_correct:
            got_right.append(f"晉級方向正確（{stage_label}）：預測{winner_zh[pred_winner]}晉級")
        else:
            adv_zh = winner_zh.get(advanced, "")
            missed.append(f"晉級失準：預測{winner_zh[pred_winner]}→{stage_label}後實際{adv_zh}晉級")
        # FT draw prediction
        if pred_winner == "draw":
            got_right.append(f"預測90分鐘平局→確實進入{stage_label}")
        elif actual_winner == "draw":
            missed.append(f"90分鐘實際平局，模型未預測到拖延（{stage_label}）")
    if score_correct:
        got_right.append(f"90分鐘比分命中：{pred_score}")
    if r.get("ah_correct"):
        got_right.append(f"讓球盤（信心{int(r.get('ah_prob',0)*100)}%）")
    elif not r.get("ah_is_push"):
        actual_ah_zh = {"home": home_zh, "away": away_zh}.get(r.get("actual_ah",""), "")
        missed.append(f"讓球盤失準（信心{int(r.get('ah_prob',0)*100)}%，實際{actual_ah_zh}）")
    if r.get("ou_correct"):
        got_right.append(f"大小球（信心{int(r.get('ou_prob',0)*100)}%）")
    else:
        actual_ou_zh = {"over":"大球","under":"小球"}.get(r.get("actual_ou",""),"")
        missed.append(f"大小球失準（信心{int(r.get('ou_prob',0)*100)}%，實際{actual_ou_zh}）")

    # Key factors from prediction
    key_factors, reasoning_snippet = [], ""
    if pred:
        key_factors = pred.get("key_factors", [])
        lines = [l.strip() for l in pred.get("reasoning","").split("\n") if l.strip()]
        reasoning_snippet = " · ".join(lines[:2]) if lines else ""

    review_parts = []

    # ── 比賽進程標題 ─────────────────────────────────────
    if decided == "extra_time":
        progress_label = f"90分鐘 {ft_score} → 加時 {aet_score} (AET)"
    elif decided == "penalties":
        progress_label = f"90分鐘 {ft_score} → 加時 {aet_score} → 點球 {pen_score}"
    else:
        progress_label = f"90分鐘 {actual_score}"
    if decided != "90min" and aet_score:
        review_parts.append(
            f"<div style='font-size:0.78rem;margin-bottom:8px;"
            f"color:var(--gold);font-weight:600'>⏱ {progress_label}</div>"
        )

    # ── 進球時間軸 ───────────────────────────────────────
    timeline_html = _build_goal_timeline_html(match_detail)
    if timeline_html:
        review_parts.append(
            f"<div style='margin:4px 0 2px;font-size:0.72rem;color:var(--muted);font-weight:600'>⚽ 進球時間軸</div>"
            f"<div style='margin-bottom:8px'>{timeline_html}</div>"
        )

    # ── 點球大戰 ─────────────────────────────────────────
    if penalties:
        pen_html = _build_penalty_html(penalties, home_zh, away_zh)
        if pen_html:
            review_parts.append(pen_html)

    # ── 陣型 + 首發 ─────────────────────────────────────
    if formations:
        home_f = formations.get("home", "")
        away_f = formations.get("away", "")
        home_xi = lineups.get("home", {}).get("starters", [])[:11]
        away_xi = lineups.get("away", {}).get("starters", [])[:11]
        home_subs = lineups.get("home", {}).get("subs_used", [])
        away_subs = lineups.get("away", {}).get("subs_used", [])
        fmt_row = (
            f"<div style='display:flex;gap:24px;flex-wrap:wrap;margin-bottom:8px'>"
            f"<div style='flex:1;min-width:180px'>"
            f"<div style='font-size:0.72rem;color:var(--accent);font-weight:700'>{home_zh} [{home_f}]</div>"
            f"<div style='font-size:0.73rem;color:var(--text)'>{', '.join(home_xi)}</div>"
            + (f"<div style='font-size:0.7rem;color:var(--muted)'>換人：{', '.join(home_subs)}</div>" if home_subs else "")
            + f"</div>"
            f"<div style='flex:1;min-width:180px'>"
            f"<div style='font-size:0.72rem;color:var(--gold);font-weight:700'>{away_zh} [{away_f}]</div>"
            f"<div style='font-size:0.73rem;color:var(--text)'>{', '.join(away_xi)}</div>"
            + (f"<div style='font-size:0.7rem;color:var(--muted)'>換人：{', '.join(away_subs)}</div>" if away_subs else "")
            + f"</div></div>"
        )
        review_parts.append(fmt_row)

    # ── 統計對比 ─────────────────────────────────────────
    if stats:
        home_s = stats.get("home", {})
        away_s = stats.get("away", {})
        stat_keys = [("Possession", "控球率"), ("SHOTS", "射門"), ("Corner Kicks", "角球"), ("Saves", "撲救")]
        stat_cells = ""
        for key, label in stat_keys:
            hv = home_s.get(key, "")
            av = away_s.get(key, "")
            if hv or av:
                stat_cells += (
                    f"<div style='text-align:center;padding:0 12px'>"
                    f"<div style='font-size:0.85rem;font-weight:700'>{hv}</div>"
                    f"<div style='font-size:0.68rem;color:var(--muted)'>{label}</div>"
                    f"<div style='font-size:0.85rem;font-weight:700'>{av}</div>"
                    f"</div>"
                )
        if stat_cells:
            review_parts.append(
                f"<div style='display:flex;justify-content:center;margin-bottom:8px;"
                f"border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:6px 0'>"
                f"<div style='font-size:0.7rem;color:var(--accent);writing-mode:vertical-rl;margin-right:8px'>{home_zh}</div>"
                f"{stat_cells}"
                f"<div style='font-size:0.7rem;color:var(--gold);writing-mode:vertical-rl;margin-left:8px'>{away_zh}</div>"
                f"</div>"
            )

    # ── 模型說對了 / 偏差 ────────────────────────────────
    if got_right or missed:
        cols = ""
        if got_right:
            items = "".join(f"<li>✓ {g}</li>" for g in got_right)
            cols += (f"<div style='flex:1;min-width:180px'>"
                     f"<div style='font-size:0.72rem;color:var(--green);font-weight:700;margin-bottom:3px'>模型說對了</div>"
                     f"<ul style='margin:0;padding-left:14px;font-size:0.77rem;color:var(--text)'>{items}</ul></div>")
        if missed:
            items = "".join(f"<li>✗ {m}</li>" for m in missed)
            cols += (f"<div style='flex:1;min-width:180px'>"
                     f"<div style='font-size:0.72rem;color:var(--red);font-weight:700;margin-bottom:3px'>偏差 / 盲區</div>"
                     f"<ul style='margin:0;padding-left:14px;font-size:0.77rem;color:var(--text)'>{items}</ul></div>")
        review_parts.append(f"<div style='display:flex;gap:16px;flex-wrap:wrap;margin-bottom:6px'>{cols}</div>")

    # ── 賽前論點 ─────────────────────────────────────────
    if key_factors:
        review_parts.append(
            f"<div style='font-size:0.72rem;color:var(--muted);margin-top:4px'>"
            f"賽前論點：{' · '.join(key_factors[:3])}</div>"
        )
    if reasoning_snippet:
        review_parts.append(
            f"<div style='font-size:0.72rem;color:var(--muted);font-style:italic;margin-top:2px'>{reasoning_snippet}</div>"
        )

    if not review_parts:
        return ""

    border_color = "var(--green)" if advance_correct else "var(--red)"
    stage_tag = {"90min": "FT", "extra_time": "AET", "penalties": "PEN"}.get(decided, "FT")
    result_tag = f"FT {actual_score}" + (f" (AET {aet_score})" if aet_score else "") + \
                 (f" · PEN {pen_score}" if pen_score else "")
    correct_tag = "✓ 方向正確" if advance_correct else "✗ 方向失準"
    return (
        f"<tr><td colspan='6' style='padding:0 8px 12px;background:rgba(10,17,32,0.6)'>"
        f"<div class='review-block' style='border-left:3px solid {border_color};padding:8px 12px;"
        f"background:rgba(20,35,60,0.6);border-radius:0 8px 8px 0'>"
        f"<div style='font-size:0.72rem;font-weight:700;color:var(--muted);letter-spacing:0.5px;margin-bottom:8px'>"
        f"POST-MATCH REVIEW · 賽後復盤 · {result_tag} · {correct_tag}</div>"
        + "".join(review_parts)
        + "</div></td></tr>"
    )


def render_results(out_path: str = None) -> None:
    val = _load_validation_results()
    records = val.get("all_results", [])

    _AH_PRED_ZH = {"home": "主隊", "away": "客隊"}
    _OU_PRED_ZH = {"over": "大球", "under": "小球"}

    if records:
        decisive = [r for r in records if not r.get("ah_is_push")]
        ah_acc = sum(r["ah_correct"] for r in decisive) / len(decisive) if decisive else 0
        ou_acc = sum(r["ou_correct"] for r in records) / len(records) if records else 0

        summary = (
            "<div class='stat-row'>"
            "<div class='stat-box'>"
            "<div class='stat-num'>%d</div><div class='stat-lbl'>總場數</div></div>" % len(records) +
            "<div class='stat-box'>"
            "<div class='stat-num' style='color:var(--accent)'>%.1f%%</div>"
            "<div class='stat-lbl'>讓球盤準確率</div></div>" % (ah_acc * 100) +
            "<div class='stat-box'>"
            "<div class='stat-num' style='color:var(--gold)'>%.1f%%</div>"
            "<div class='stat-lbl'>大小球準確率</div></div>" % (ou_acc * 100) +
            "<div class='stat-box'>"
            "<div class='stat-num'>%d</div><div class='stat-lbl'>決出勝負</div></div>" % len(decisive) +
            "<div class='stat-box'>"
            "<div class='stat-num'>%d</div><div class='stat-lbl'>平局 Push</div></div>" % (len(records) - len(decisive)) +
            "</div>"
        )

        # Pre-load goal events and predictions indexed by date
        import json as _json
        from pathlib import Path as _Path
        _matches_dir = _Path(__file__).parent.parent / "data" / "matches"
        _preds_dir   = _Path(__file__).parent.parent / "data" / "predictions"
        _goal_cache: dict = {}
        _pred_cache: dict = {}

        def _get_goal_events(date: str, home_short: str, away_short: str) -> list:
            if date not in _goal_cache:
                p = _matches_dir / f"{date}.json"
                try:
                    _goal_cache[date] = _json.loads(p.read_text()).get("goal_events", {}) if p.exists() else {}
                except Exception:
                    _goal_cache[date] = {}
            ge = _goal_cache[date]
            for key in ge:
                parts = key.split("|")
                if len(parts) == 2:
                    h, a = parts
                    if (home_short.lower() in h.lower() or h.lower() in home_short.lower() or
                            away_short.lower() in a.lower() or a.lower() in away_short.lower()):
                        return ge[key]
            return []

        def _get_pred(date: str, home: str, away: str):
            if date not in _pred_cache:
                p = _preds_dir / f"{date}.json"
                try:
                    _pred_cache[date] = _json.loads(p.read_text()) if p.exists() else []
                except Exception:
                    _pred_cache[date] = []
            for p in _pred_cache[date]:
                ph = p.get("home_team", "")
                pa = p.get("away_team", "")
                if home.lower() in ph.lower() or ph.lower() in home.lower():
                    if away.lower() in pa.lower() or pa.lower() in away.lower():
                        return p
            return None

        rows = ""
        for r in records:
            home_zh = team_zh(r["home"])
            away_zh = team_zh(r["away"])
            ah_is_push = r.get("ah_is_push", False)
            ah_pred_zh = _ah_pred_label(r["ah_pred"], r.get("ah_line") or 0, home_zh, away_zh)
            ou_pred_zh = _OU_PRED_ZH.get(r["ou_pred"], r["ou_pred"])
            ah_prob_pct = int(r["ah_prob"] * 100)
            ou_prob_pct = int(r["ou_prob"] * 100)

            ah_line_val = r.get("ah_line") or 0
            ou_line_val = r.get("ou_line") or 2.5
            ah_line_str = _fmt_ah_line(ah_line_val)

            ah_cc = _conf_class(ah_prob_pct)
            ou_cc = _conf_class(ou_prob_pct)
            if ah_is_push:
                ah_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='tag'>平局 Push</span>"
                ) % ah_line_str
            elif r["ah_correct"]:
                ah_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='correct'>✓ %s</span>"
                    "<span class='conf-badge %s' style='margin-left:4px'>信心 %d%%</span>"
                ) % (ah_line_str, ah_pred_zh, ah_cc, ah_prob_pct)
            else:
                actual_label = _ah_pred_label(r["actual_ah"], ah_line_val, home_zh, away_zh) if r.get("actual_ah") else ""
                ah_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='wrong'>✗ 預測%s</span>"
                    "<span class='conf-badge %s' style='margin-left:4px'>信心 %d%%</span>"
                    "<div style='font-size:0.7rem;color:var(--muted)'>實際：%s</div>"
                ) % (ah_line_str, ah_pred_zh, ah_cc, ah_prob_pct, actual_label)

            ou_line_str = "大小 %g" % ou_line_val
            if r["ou_correct"]:
                ou_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='correct'>✓ %s</span>"
                    "<span class='conf-badge %s' style='margin-left:4px'>信心 %d%%</span>"
                ) % (ou_line_str, ou_pred_zh, ou_cc, ou_prob_pct)
            else:
                actual_ou_zh = _OU_PRED_ZH.get(r.get("actual_ou", ""), "")
                ou_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='wrong'>✗ 預測%s</span>"
                    "<span class='conf-badge %s' style='margin-left:4px'>信心 %d%%</span>"
                    "<div style='font-size:0.7rem;color:var(--muted)'>實際：%s</div>"
                ) % (ou_line_str, ou_pred_zh, ou_cc, ou_prob_pct, actual_ou_zh)

            actual_score = r["score"]

            # Use stored daily prediction as source of truth for predicted_score
            _pred_r = _get_pred(r["date"], r["home"], r["away"])
            if _pred_r and _pred_r.get("predicted_score"):
                pred_score = _pred_r["predicted_score"]
            else:
                pred_score = r.get("predicted_score", "?-?")

            score_cell = (
                "<div style='text-align:center'>"
                "<div style='font-size:0.7rem;color:var(--muted)'>預測 %s</div>"
                "<div style='font-weight:700;font-size:1.1rem'>%s</div>"
                "</div>"
            ) % (pred_score, actual_score)

            date_short = r["date"][5:]
            hg2, ag2 = map(int, r["score"].split("-")) if "-" in r["score"] else (0,0)
            row_winner = "home" if hg2>ag2 else ("away" if ag2>hg2 else "draw")
            pred_winner = (_pred_r.get("predicted_winner", "") if _pred_r else "")
            row_correct = "1" if ({"home": home_zh, "away": away_zh, "draw":"平局"}.get(row_winner,"") ==
                                   {"home": home_zh, "away": away_zh, "draw":"平局"}.get(pred_winner,"")) else "0"
            rows += (
                "<tr data-home='%s' data-away='%s' data-date='%s' data-correct='%s'>"
                "<td style='color:var(--muted);white-space:nowrap;width:52px'>%s</td>"
                "<td style='color:var(--muted);width:44px'>%s組</td>"
                "<td><b>%s</b> vs <b>%s</b></td>"
                "<td style='width:110px'>%s</td>"
                "<td style='width:140px'>%s</td>"
                "<td style='width:130px'>%s</td>"
                "</tr>"
            ) % (home_zh, away_zh, r["date"], row_correct,
                 date_short, r["group"], home_zh, away_zh, score_cell, ah_result, ou_result)

            # POST-MATCH REVIEW row
            goal_events = _get_goal_events(r["date"], r["home"], r["away"])
            pred = _get_pred(r["date"], r["home"], r["away"])
            review = _build_review_html(r, pred, goal_events)
            if review:
                rows += review

        tbl = (
            "<div class='tbl-wrap'><table><thead><tr>"
            "<th style='width:52px'>日期</th><th style='width:44px'>組別</th>"
            "<th>比賽</th><th style='width:110px'>比分</th>"
            "<th style='width:140px'>讓球盤</th><th style='width:130px'>大小球</th>"
            "</tr></thead><tbody>%s</tbody></table></div>"
        ) % rows
    else:
        summary = ""
        tbl = "<div class='empty'><div class='empty-icon'>🏆</div><p>賽事結果將在比賽後自動更新</p></div>"

    # Build list of all teams and dates for filter dropdowns
    all_teams = sorted({team_zh(r["home"]) for r in records} | {team_zh(r["away"]) for r in records})
    all_dates = sorted({r["date"][:7] for r in records}, reverse=True)  # YYYY-MM

    team_opts = "<option value=''>所有球隊</option>" + \
                "".join(f"<option value='{t}'>{t}</option>" for t in all_teams)
    date_opts = "<option value=''>所有月份</option>" + \
                "".join(f"<option value='{d}'>{d}</option>" for d in all_dates)

    filter_bar = (
        "<div class='card' style='padding:14px 20px;margin-bottom:16px'>"
        "<div style='font-size:0.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;"
        "letter-spacing:0.5px;margin-bottom:10px'>篩選</div>"
        "<div style='display:flex;gap:10px;flex-wrap:wrap;align-items:center'>"
        "<select id='filter-team' onchange='applyFilters()' style='"
        "background:var(--bg);color:var(--text);border:1px solid var(--border);"
        "border-radius:8px;padding:6px 12px;font-size:0.85rem;min-width:120px'>" + team_opts + "</select>"
        "<select id='filter-date' onchange='applyFilters()' style='"
        "background:var(--bg);color:var(--text);border:1px solid var(--border);"
        "border-radius:8px;padding:6px 12px;font-size:0.85rem'>" + date_opts + "</select>"
        "<select id='filter-result' onchange='applyFilters()' style='"
        "background:var(--bg);color:var(--text);border:1px solid var(--border);"
        "border-radius:8px;padding:6px 12px;font-size:0.85rem'>"
        "<option value=''>所有結果</option>"
        "<option value='correct'>✓ 方向正確</option>"
        "<option value='wrong'>✗ 方向失準</option>"
        "</select>"
        "<span id='filter-count' style='font-size:0.82rem;color:var(--muted)'></span>"
        "<button onclick='clearFilters()' style='"
        "background:none;color:var(--muted);border:1px solid var(--border);"
        "border-radius:8px;padding:5px 12px;font-size:0.82rem;cursor:pointer'>重置</button>"
        "</div>"
        "</div>"
    )

    filter_js = """
<script>
function applyFilters() {
  const team   = document.getElementById('filter-team').value;
  const month  = document.getElementById('filter-date').value;
  const result = document.getElementById('filter-result').value;
  const rows   = document.querySelectorAll('tr[data-home]');
  let shown = 0;
  rows.forEach(row => {
    const home   = row.dataset.home || '';
    const away   = row.dataset.away || '';
    const date   = row.dataset.date || '';
    const correct= row.dataset.correct || '';
    const next   = row.nextElementSibling;
    let show = true;
    if (team   && home !== team && away !== team) show = false;
    if (month  && !date.startsWith(month))        show = false;
    if (result === 'correct' && correct !== '1')  show = false;
    if (result === 'wrong'   && correct !== '0')  show = false;
    row.style.display = show ? '' : 'none';
    if (next && next.querySelector('.review-block')) {
      next.style.display = show ? '' : 'none';
    }
    if (show) shown++;
  });
  const cnt = document.getElementById('filter-count');
  if (cnt) cnt.textContent = `顯示 ${shown} 場`;
}
function clearFilters() {
  document.getElementById('filter-team').value   = '';
  document.getElementById('filter-date').value   = '';
  document.getElementById('filter-result').value = '';
  document.querySelectorAll('tr[data-home]').forEach(r => {
    r.style.display = '';
    const next = r.nextElementSibling;
    if (next && next.querySelector('.review-block')) next.style.display = '';
  });
  const cnt = document.getElementById('filter-count');
  if (cnt) cnt.textContent = '';
}
</script>
"""

    body = (
        "<div class='page-header'><div class='page-title'>賽程與預測結果</div></div>"
        "<p style='color:var(--muted);margin-bottom:1rem'>"
        "Walk-forward 回測：每場比賽僅使用賽前數據預測，不含未來資訊。</p>"
        "%s%s%s%s"
    ) % (summary, filter_bar, tbl, filter_js)
    html = _base_html("歷史結果", body, active_nav="歷史結果")
    path = out_path or str(DOCS_DIR / "results.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_all(date: str) -> None:
    from src.backtest import load_calibration, load_brier_history
    from src.predict import _load_predictions
    from datetime import datetime, timedelta, timezone

    # Load today's predictions, backfill recent dates, and look ahead 1 day
    predictions = _load_predictions(date)
    seen_ids = {str(p.get("match_id", "")) for p in predictions}
    now_utc = datetime.now(timezone.utc)

    # Backfill: include in-progress matches from previous 2 days
    for delta in (1, 2):
        prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=delta)).strftime("%Y-%m-%d")
        for p in _load_predictions(prev_date):
            kick = p.get("kickoff_utc", "")
            mid = str(p.get("match_id", ""))
            if not kick or mid in seen_ids:
                continue
            kick_dt = datetime.fromisoformat(kick.replace("Z", "+00:00"))
            elapsed = (now_utc - kick_dt).total_seconds()
            if elapsed < 10800 and p.get("home_team") and p.get("away_team"):  # within 3 hrs
                predictions.append(p)
                seen_ids.add(mid)

    # Look ahead: include upcoming matches from next 1 day's predictions file
    next_date = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    for p in _load_predictions(next_date):
        kick = p.get("kickoff_utc", "")
        mid = str(p.get("match_id", ""))
        if not kick or mid in seen_ids:
            continue
        kick_dt = datetime.fromisoformat(kick.replace("Z", "+00:00"))
        if kick_dt > now_utc and p.get("home_team") and p.get("away_team"):
            predictions.append(p)
            seen_ids.add(mid)

    predictions.sort(key=lambda p: p.get("kickoff_utc", ""))
    render_index(predictions, date)

    calibration = load_calibration()
    brier_history = load_brier_history()
    render_calibration(calibration, brier_history)

    render_postmortem()
    render_results()
