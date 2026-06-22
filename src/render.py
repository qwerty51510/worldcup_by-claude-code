import json
from pathlib import Path

import plotly.graph_objects as go

DOCS_DIR = Path(__file__).parent.parent / "docs"

_AH_LABEL = {"home": "主隊讓球勝", "away": "客隊受讓勝"}
_OU_LABEL = {"over": "大球", "under": "小球"}


def _base_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "PingFang TC", "Microsoft JhengHei", system-ui, sans-serif;
    background: #0d0d0d;
    color: #e0e0e0;
    min-height: 100vh;
  }}
  header {{
    background: #111;
    border-bottom: 2px solid #f5c518;
    padding: 16px 32px;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  header .logo {{ font-size: 1.6rem; font-weight: 800; color: #f5c518; letter-spacing: -0.5px; }}
  header .sub {{ font-size: 0.85rem; color: #888; }}
  nav {{
    background: #161616;
    padding: 0 32px;
    border-bottom: 1px solid #222;
    display: flex;
    gap: 4px;
  }}
  nav a {{
    display: inline-block;
    padding: 14px 18px;
    color: #aaa;
    text-decoration: none;
    font-size: 0.9rem;
    border-bottom: 3px solid transparent;
    transition: color 0.2s, border-color 0.2s;
  }}
  nav a:hover, nav a.active {{ color: #f5c518; border-bottom-color: #f5c518; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px; }}
  h1 {{ font-size: 1.5rem; color: #f5c518; margin-bottom: 6px; }}
  h2 {{ font-size: 1.1rem; color: #ccc; margin: 28px 0 12px; border-bottom: 1px solid #2a2a2a; padding-bottom: 8px; }}
  .date-badge {{ display: inline-block; background: #1e1e1e; border: 1px solid #333; border-radius: 20px; padding: 3px 12px; font-size: 0.8rem; color: #888; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; background: #111; border-radius: 8px; overflow: hidden; }}
  thead tr {{ background: #1a1a1a; }}
  th {{ padding: 12px 16px; text-align: left; font-size: 0.8rem; color: #f5c518; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }}
  td {{ padding: 14px 16px; border-bottom: 1px solid #1e1e1e; font-size: 0.92rem; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #161616; }}
  .match-name {{ font-weight: 600; color: #fff; }}
  .badge {{
    display: inline-block; padding: 4px 10px; border-radius: 4px;
    font-size: 0.82rem; font-weight: 700; letter-spacing: 0.3px;
  }}
  .high {{ background: #1b3a1b; color: #4caf50; }}
  .mid {{ background: #332200; color: #ff9800; }}
  .low {{ background: #2a1515; color: #f44336; }}
  .factor {{ font-size: 0.8rem; color: #666; }}
  .empty-state {{ text-align: center; padding: 60px 20px; color: #555; }}
  .empty-state .icon {{ font-size: 3rem; margin-bottom: 12px; }}
  p {{ color: #888; line-height: 1.6; margin-bottom: 12px; }}
</style>
</head>
<body>
<header>
  <div>
    <div class="logo">⚽ 世界盃 2026 預測系統</div>
    <div class="sub">亞洲讓球盤 &amp; 大小球自動預測</div>
  </div>
</header>
<nav>
  <a href="index.html">今日預測</a>
  <a href="results.html">歷史結果</a>
  <a href="calibration.html">模型校正</a>
  <a href="postmortem.html">復盤分析</a>
</nav>
<main>
{body}
</main>
</body>
</html>"""


def _conf_class(conf: int) -> str:
    if conf >= 65:
        return "high"
    if conf >= 50:
        return "mid"
    return "low"


def render_index(predictions: list, date: str, out_path: str = None) -> None:
    if predictions:
        rows = ""
        for p in predictions:
            ah_label = _AH_LABEL.get(p["ah_prediction"], p["ah_prediction"])
            ou_label = _OU_LABEL.get(p["ou_prediction"], p["ou_prediction"])
            cc_ah = _conf_class(p["ah_confidence"])
            cc_ou = _conf_class(p["ou_confidence"])
            factors = "、".join(p.get("key_factors", []))
            score = p.get("predicted_score", "?-?")
            p_hw = int(p.get("p_home_win", 0) * 100)
            p_d = int(p.get("p_draw", 0) * 100)
            p_aw = int(p.get("p_away_win", 0) * 100)
            score_cell = (
                f"<span style='font-weight:700;font-size:1.05rem;color:#f5c518'>{score}</span>"
                f"<br><span style='font-size:0.75rem;color:#666'>"
                f"主{p_hw}% 平{p_d}% 客{p_aw}%</span>"
            )
            rows += (
                f"<tr>"
                f"<td class='match-name'>{p['home_team']} vs {p['away_team']}</td>"
                f"<td>{score_cell}</td>"
                f"<td><span class='badge {cc_ah}'>{ah_label} {p['ah_confidence']}%</span></td>"
                f"<td><span class='badge {cc_ou}'>{ou_label} {p['ou_confidence']}%</span></td>"
                f"<td class='factor'>{factors}</td>"
                f"</tr>"
            )
        table = (
            "<table><thead><tr>"
            "<th>比賽</th><th>預測比分</th><th>亞洲讓球盤</th><th>大小球</th><th>關鍵因素</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        table = "<div class='empty-state'><div class='icon'>📋</div><p>今日暫無預測資料</p></div>"

    body = f"<h1>今日預測</h1><div class='date-badge'>📅 {date}</div>{table}"
    html = _base_html(f"世界盃預測 {date}", body)
    path = out_path or str(DOCS_DIR / "index.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_postmortem(postmortem: list, out_path: str = None) -> None:
    if postmortem:
        rows = ""
        for p in postmortem:
            err_pct = int(p["error"] * 100)
            cls = "low" if p["error"] > 0.5 else "mid"
            factors = "、".join(p.get("key_factors", []))
            predicted_label = _AH_LABEL.get(p["predicted"], p["predicted"])
            rows += (
                f"<tr>"
                f"<td class='match-name'>{p['home_team']} vs {p['away_team']}</td>"
                f"<td>{predicted_label}（信心 {p['confidence']}%）</td>"
                f"<td>{p['actual_score']}</td>"
                f"<td><span class='badge {cls}'>{err_pct}% 誤差</span></td>"
                f"<td class='factor'>{factors}</td>"
                f"</tr>"
            )
        table = (
            "<table><thead><tr>"
            "<th>比賽</th><th>預測方向</th><th>實際比分</th><th>誤差</th><th>因素</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        table = "<div class='empty-state'><div class='icon'>✅</div><p>目前尚無高誤差預測紀錄</p></div>"

    body = (
        "<h1>復盤分析</h1>"
        "<p>列出模型信心高但預測錯誤的比賽，用於識別模型盲點。</p>"
        f"{table}"
    )
    html = _base_html("世界盃預測 — 復盤", body)
    path = out_path or str(DOCS_DIR / "postmortem.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_calibration(calibration: dict, brier_history: list, out_path: str = None) -> None:
    if brier_history:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=brier_history, mode="lines+markers", name="Brier Score",
            line=dict(color="#f5c518", width=2),
            marker=dict(size=6),
        ))
        fig.add_hline(y=0.25, line_dash="dash", line_color="#f44336",
                      annotation_text="重置閾值 0.25", annotation_position="bottom right")
        fig.update_layout(
            paper_bgcolor="#111", plot_bgcolor="#1a1a1a",
            font_color="#e0e0e0", font_family="PingFang TC, system-ui",
            title=dict(text="模型 Brier Score 走勢（越低越準）", font_color="#f5c518"),
            xaxis=dict(title="天數", gridcolor="#222"),
            yaxis=dict(title="Brier Score", gridcolor="#222", range=[0, 0.5]),
            margin=dict(l=50, r=30, t=60, b=50),
        )
        chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    else:
        chart_html = "<div class='empty-state'><div class='icon'>📈</div><p>累積足夠資料後將顯示走勢圖</p></div>"

    param_labels = {
        "ah_weight": "讓球盤權重",
        "ou_weight": "大小球權重",
        "sharp_money_multiplier": "莊家資金信號係數",
        "incentive_boost": "必贏場進攻加成",
        "climate_penalty": "氣候不適應懲罰",
        "age_decay_threshold": "球隊老化閾值（平均年齡）",
        "version": "模型版本",
        "last_updated": "最後更新",
    }
    rows = "".join(
        f"<tr><td>{param_labels.get(k, k)}</td><td>{v}</td></tr>"
        for k, v in calibration.items()
    )
    body = (
        "<h1>模型校正</h1>"
        f"{chart_html}"
        "<h2>當前參數權重</h2>"
        f"<table><thead><tr><th>參數</th><th>數值</th></tr></thead><tbody>{rows}</tbody></table>"
    )
    html = _base_html("世界盃預測 — 模型校正", body)
    path = out_path or str(DOCS_DIR / "calibration.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_results(results_history: list, out_path: str = None) -> None:
    if results_history:
        rows = ""
        for r in results_history:
            ah_ok = r.get("ah_correct")
            ou_ok = r.get("ou_correct")
            ah_cls = "high" if ah_ok else "low"
            ou_cls = "high" if ou_ok else "low"
            ah_text = "✓ 正確" if ah_ok else "✗ 錯誤"
            ou_text = "✓ 正確" if ou_ok else "✗ 錯誤"
            rows += (
                f"<tr>"
                f"<td class='match-name'>{r.get('date', '')}</td>"
                f"<td>{r.get('home_team', '')} vs {r.get('away_team', '')}</td>"
                f"<td>{r.get('actual_score', '-')}</td>"
                f"<td><span class='badge {ah_cls}'>{ah_text}</span></td>"
                f"<td><span class='badge {ou_cls}'>{ou_text}</span></td>"
                f"</tr>"
            )
        table = (
            "<table><thead><tr>"
            "<th>日期</th><th>比賽</th><th>比分</th><th>讓球盤</th><th>大小球</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        table = "<div class='empty-state'><div class='icon'>🏆</div><p>賽事結果將在每場比賽後自動更新</p></div>"

    body = f"<h1>歷史預測結果</h1>{table}"
    html = _base_html("世界盃預測 — 歷史結果", body)
    path = out_path or str(DOCS_DIR / "results.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_all(date: str) -> None:
    data_dir = Path(__file__).parent.parent / "data"
    pred_file = data_dir / "predictions" / f"{date}.json"
    cal_file = data_dir / "backtest" / "calibration.json"

    predictions = json.loads(pred_file.read_text()) if pred_file.exists() else []
    calibration = json.loads(cal_file.read_text()) if cal_file.exists() else {}

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    render_index(predictions, date)
    render_postmortem([])
    render_calibration(calibration, [])
    render_results([])
