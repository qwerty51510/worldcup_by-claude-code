import json
from pathlib import Path

import plotly.graph_objects as go

DOCS_DIR = Path(__file__).parent.parent / "docs"


def _base_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; background: #0f0f0f; color: #e0e0e0; }}
  h1 {{ color: #f5c518; }} h2 {{ color: #aaa; border-bottom: 1px solid #333; padding-bottom: 6px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  th {{ background: #1a1a1a; padding: 10px; text-align: left; color: #f5c518; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #222; }}
  .high {{ color: #4caf50; font-weight: bold; }} .low {{ color: #f44336; }} .mid {{ color: #ff9800; }}
  nav {{ margin-bottom: 32px; }} nav a {{ margin-right: 16px; color: #f5c518; text-decoration: none; font-weight: bold; }}
</style>
</head>
<body>
<nav>
  <a href="index.html">Predictions</a>
  <a href="results.html">Results</a>
  <a href="calibration.html">Calibration</a>
  <a href="postmortem.html">Postmortem</a>
</nav>
{body}
</body>
</html>"""


def _conf_class(conf: int) -> str:
    if conf >= 65:
        return "high"
    if conf >= 50:
        return "mid"
    return "low"


def render_index(predictions: list, date: str, out_path: str = None) -> None:
    rows = ""
    for p in predictions:
        cc_ah = _conf_class(p["ah_confidence"])
        cc_ou = _conf_class(p["ou_confidence"])
        factors = ", ".join(p.get("key_factors", []))
        rows += (
            f"<tr>"
            f"<td>{p['home_team']} vs {p['away_team']}</td>"
            f"<td class='{cc_ah}'>{p['ah_prediction'].upper()} ({p['ah_confidence']}%)</td>"
            f"<td class='{cc_ou}'>{p['ou_prediction'].upper()} ({p['ou_confidence']}%)</td>"
            f"<td style='font-size:0.85em;color:#888'>{factors}</td>"
            f"</tr>"
        )
    body = (
        f"<h1>World Cup 2026 Predictions — {date}</h1>"
        f"<table><thead><tr><th>Match</th><th>AH Prediction</th><th>O/U Prediction</th><th>Key Factors</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    html = _base_html(f"WC2026 Predictions {date}", body)
    path = out_path or str(DOCS_DIR / "index.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_postmortem(postmortem: list, out_path: str = None) -> None:
    rows = ""
    for p in postmortem:
        err_pct = int(p["error"] * 100)
        cls = "low" if p["error"] > 0.5 else "mid"
        factors = ", ".join(p.get("key_factors", []))
        rows += (
            f"<tr>"
            f"<td>{p['home_team']} vs {p['away_team']}</td>"
            f"<td>{p['predicted'].upper()} ({p['confidence']}%)</td>"
            f"<td>{p['actual_score']}</td>"
            f"<td class='{cls}'>{err_pct}%</td>"
            f"<td style='font-size:0.85em;color:#888'>{factors}</td>"
            f"</tr>"
        )
    body = (
        "<h1>Postmortem — High-Error Predictions</h1>"
        "<p>Matches where model confidence was high but prediction was wrong.</p>"
        "<table><thead><tr><th>Match</th><th>Predicted</th><th>Actual</th><th>Error</th><th>Factors</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    html = _base_html("WC2026 Postmortem", body)
    path = out_path or str(DOCS_DIR / "postmortem.html")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(html, encoding="utf-8")


def render_calibration(calibration: dict, brier_history: list, out_path: str = None) -> None:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        y=brier_history, mode="lines+markers", name="Brier Score",
        line=dict(color="#f5c518"),
    ))
    fig.update_layout(
        paper_bgcolor="#0f0f0f", plot_bgcolor="#1a1a1a",
        font_color="#e0e0e0", title="Rolling Brier Score",
    )
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in calibration.items())
    body = (
        "<h1>Model Calibration</h1>"
        f"{chart_html}"
        "<h2>Current Weights</h2>"
        f"<table><thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table>"
    )
    html = _base_html("WC2026 Calibration", body)
    path = out_path or str(DOCS_DIR / "calibration.html")
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
    (DOCS_DIR / "results.html").write_text(
        _base_html("WC2026 Results", "<h1>Results</h1><p>Updated daily after matches.</p>"),
        encoding="utf-8",
    )
