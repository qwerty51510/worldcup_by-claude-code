import json
from pathlib import Path

import plotly.graph_objects as go

DOCS_DIR = Path(__file__).parent.parent / "docs"

_AH_LABEL = {"home": "主隊讓球", "away": "客隊受讓"}
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
.correct { color: var(--green); }
.wrong   { color: var(--red); }
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
</body>
</html>"""


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
            ah_label = _AH_LABEL.get(ah_dir, ah_dir)
            ou_label = _OU_LABEL.get(ou_dir, ou_dir)
            ah_conf = p["ah_confidence"]
            ou_conf = p["ou_confidence"]
            ah_color = "blue" if ah_dir == "home" else "gold"
            ou_color = "green" if ou_dir == "over" else "red"
            ah_fill = "fill-blue" if ah_dir == "home" else "fill-gold"
            ou_fill = "fill-green" if ou_dir == "over" else "fill-red"
            cc_ah = _conf_class(ah_conf)
            cc_ou = _conf_class(ou_conf)

            score = p.get("predicted_score", "?-?")
            p_hw = int(p.get("p_home_win", 0) * 100)
            p_d = int(p.get("p_draw", 0) * 100)
            p_aw = int(p.get("p_away_win", 0) * 100)
            factors = "、".join(p.get("key_factors", []))
            source = ""
            for f in p.get("key_factors", []):
                if "強度來源" in f:
                    source = f.replace("強度來源：", "")

            # AH line display
            ah_line_val = p.get("lambda_home", 0) - p.get("lambda_away", 0)

            cards += f"""
<div class="card">
  <div class="card-header">
    <div class="teams">
      <div class="team home">
        <div class="team-name">{p['home_team']}</div>
        <div class="team-strength">λ={p.get('lambda_home','?')}</div>
      </div>
      <div class="vs-block">
        <div class="vs-label">預測比分</div>
        <div class="predicted-score">{score}</div>
      </div>
      <div class="team away">
        <div class="team-name">{p['away_team']}</div>
        <div class="team-strength">λ={p.get('lambda_away','?')}</div>
      </div>
    </div>
    {'<span class="source-chip">' + source + '</span>' if source else ''}
  </div>
  <div class="card-body">
    <div class="market-box">
      <div class="market-label">亞洲讓球盤</div>
      <div class="market-prediction">
        <span class="market-name {ah_color}">{ah_label}</span>
        <span class="conf-badge {cc_ah}">信心 {ah_conf}%</span>
      </div>
      {_prob_bar(50 + ah_conf // 2, ah_fill)}
    </div>
    <div class="market-box">
      <div class="market-label">大小球（2.5）</div>
      <div class="market-prediction">
        <span class="market-name {ou_color}">{ou_label}</span>
        <span class="conf-badge {cc_ou}">信心 {ou_conf}%</span>
      </div>
      {_prob_bar(50 + ou_conf // 2, ou_fill)}
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


def render_postmortem(postmortem: list, out_path: str = None) -> None:
    if postmortem:
        rows = ""
        for p in postmortem:
            err_pct = int(p["error"] * 100)
            cls = "conf-high" if p["error"] < 0.3 else "conf-mid"
            predicted_label = _AH_LABEL.get(p["predicted"], p["predicted"])
            rows += (
                f"<tr>"
                f"<td>{p['home_team']} vs {p['away_team']}</td>"
                f"<td>{predicted_label}（{p['confidence']}%）</td>"
                f"<td>{p['actual_score']}</td>"
                f"<td><span class='conf-badge {cls}'>{err_pct}% 誤差</span></td>"
                f"</tr>"
            )
        tbl = (
            "<div class='tbl-wrap'><table><thead><tr>"
            "<th>比賽</th><th>預測方向</th><th>實際比分</th><th>誤差</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
    else:
        tbl = "<div class='empty'><div class='empty-icon'>✅</div><p>目前尚無高誤差預測紀錄</p></div>"

    body = f"""
<div class="page-header">
  <div class="page-title">復盤分析</div>
</div>
<p>列出模型信心高但預測錯誤的比賽，用於識別模型盲點並調整參數。</p>
{tbl}"""
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


def render_results(results_history: list, out_path: str = None) -> None:
    if results_history:
        rows = ""
        for r in results_history:
            ah_ok = r.get("ah_correct")
            ou_ok = r.get("ou_correct")
            ah_cls = "correct" if ah_ok else "wrong"
            ou_cls = "correct" if ou_ok else "wrong"
            rows += (
                f"<tr>"
                f"<td style='color:var(--muted)'>{r.get('date','')}</td>"
                f"<td><b>{r.get('home_team','')} vs {r.get('away_team','')}</b></td>"
                f"<td style='font-weight:700;font-size:1.05rem'>{r.get('actual_score','-')}</td>"
                f"<td class='{ah_cls}'>{'✓' if ah_ok else '✗'} 讓球盤</td>"
                f"<td class='{ou_cls}'>{'✓' if ou_ok else '✗'} 大小球</td>"
                f"</tr>"
            )
        tbl = (
            "<div class='tbl-wrap'><table><thead><tr>"
            "<th>日期</th><th>比賽</th><th>比分</th><th>讓球盤</th><th>大小球</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
    else:
        tbl = "<div class='empty'><div class='empty-icon'>🏆</div><p>賽事結果將在每場比賽後自動更新</p></div>"

    body = f"""
<div class="page-header">
  <div class="page-title">歷史預測結果</div>
</div>
{tbl}"""
    html = _base_html("歷史結果", body, active_nav="歷史結果")
    path = out_path or str(DOCS_DIR / "results.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_all(date: str) -> None:
    from src.backtest import generate_postmortem, load_calibration, load_brier_history
    from src.predict import _load_predictions

    predictions = _load_predictions(date)
    render_index(predictions, date)

    calibration = load_calibration()
    brier_history = load_brier_history()
    render_calibration(calibration, brier_history)

    # postmortem requires completed-match data; pass empty lists when none available
    postmortem = generate_postmortem(predictions, [])
    render_postmortem(postmortem)

    render_results([])
