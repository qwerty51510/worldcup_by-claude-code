import json
from pathlib import Path

import plotly.graph_objects as go
from src.config import team_zh

DOCS_DIR = Path(__file__).parent.parent / "docs"

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
            score = f"{lh_val:.1f}–{la_val:.1f}" if lh_val and la_val else p.get("predicted_score", "?-?")
            p_hw = int(p.get("p_home_win", 0) * 100)
            p_d = int(p.get("p_draw", 0) * 100)
            p_aw = int(p.get("p_away_win", 0) * 100)
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
        <div class="vs-label">期望進球</div>
        <div class="predicted-score">{score}</div>
      </div>
      <div class="team away">
        <div class="team-name">{away_zh}</div>
        <div class="team-strength">λ={p.get('lambda_away','?')}</div>
      </div>
    </div>
    {'<span class="source-chip">' + source + '</span>' if source else ''}
  </div>
  <div class="card-body">
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
        </div>
        <div class="onex2-item">
          <div class="onex2-pct" style="color:var(--muted)">{p_d}%</div>
          <div class="onex2-lbl">平局</div>
        </div>
        <div class="onex2-item">
          <div class="onex2-pct" style="color:var(--gold)">{p_aw}%</div>
          <div class="onex2-lbl">客隊勝</div>
        </div>
      </div>
    </div>
    <div class="reasoning-box">
      <div class="reasoning-title">分析依據</div>
      {reasoning_html}
    </div>
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

            if ah_is_push:
                ah_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='tag'>平局 Push</span>"
                ) % ah_line_str
            elif r["ah_correct"]:
                ah_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='correct'>✓ %s %d%%</span>"
                ) % (ah_line_str, ah_pred_zh, ah_prob_pct)
            else:
                actual_team = home_zh if r.get("actual_ah") == "home" else away_zh if r.get("actual_ah") == "away" else ""
                actual_label = _ah_pred_label(r["actual_ah"], ah_line_val, home_zh, away_zh) if r.get("actual_ah") else ""
                ah_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='wrong'>✗ 預測%s，實際%s</span>"
                ) % (ah_line_str, ah_pred_zh, actual_label)

            ou_line_str = "大小 %g" % ou_line_val
            if r["ou_correct"]:
                ou_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='correct'>✓ %s %d%%</span>"
                ) % (ou_line_str, ou_pred_zh, ou_prob_pct)
            else:
                actual_ou_zh = _OU_PRED_ZH.get(r.get("actual_ou", ""), "")
                ou_result = (
                    "<div style='font-size:0.7rem;color:var(--muted)'>%s</div>"
                    "<span class='wrong'>✗ 預測%s，實際%s</span>"
                ) % (ou_line_str, ou_pred_zh, actual_ou_zh)

            pred_score = r.get("predicted_score", "?-?")
            actual_score = r["score"]
            score_cell = (
                "<div style='text-align:center'>"
                "<div style='font-size:0.7rem;color:var(--muted)'>預測 %s</div>"
                "<div style='font-weight:700;font-size:1.1rem'>%s</div>"
                "</div>"
            ) % (pred_score, actual_score)

            date_short = r["date"][5:]  # strip year: "2026-06-22" → "06-22"
            rows += (
                "<tr>"
                "<td style='color:var(--muted);white-space:nowrap;width:52px'>%s</td>"
                "<td style='color:var(--muted);width:44px'>%s組</td>"
                "<td><b>%s</b> vs <b>%s</b></td>"
                "<td style='width:110px'>%s</td>"
                "<td style='width:140px'>%s</td>"
                "<td style='width:130px'>%s</td>"
                "</tr>"
            ) % (date_short, r["group"], home_zh, away_zh, score_cell, ah_result, ou_result)

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

    body = (
        "<div class='page-header'><div class='page-title'>賽程與預測結果</div></div>"
        "<p style='color:var(--muted);margin-bottom:1rem'>"
        "Walk-forward 回測：每場比賽僅使用賽前數據預測，不含未來資訊。</p>"
        "%s%s"
    ) % (summary, tbl)
    html = _base_html("歷史結果", body, active_nav="歷史結果")
    path = out_path or str(DOCS_DIR / "results.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_all(date: str) -> None:
    from src.backtest import load_calibration, load_brier_history
    from src.predict import _load_predictions

    predictions = _load_predictions(date)
    render_index(predictions, date)

    calibration = load_calibration()
    brier_history = load_brier_history()
    render_calibration(calibration, brier_history)

    render_postmortem()
    render_results()
