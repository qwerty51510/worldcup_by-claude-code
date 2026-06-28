"""
render_trading.py — 生成 docs/trading.html 交易儀表板

用法：
  python3 -m src.render_trading          # 生成一次
  python3 -m src.render_trading --watch  # 每 30 秒重新生成
"""

import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

PORTFOLIO_PATH = Path(__file__).parent.parent / "data" / "portfolio.json"
OUTPUT_PATH = Path(__file__).parent.parent / "docs" / "trading.html"

STAGE_LABELS = {"qf": "八強", "sf": "四強", "final": "決賽", "winner": "奪冠"}


def _load() -> dict:
    if not PORTFOLIO_PATH.exists():
        return {}
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return json.load(f)


def _fmt_usd(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}${v:.2f}" if v != 0 else "$0.00"


def _fmt_pct(v: float) -> str:
    return f"{v*100:+.1f}%"


def _pnl_class(v: float) -> str:
    if v > 0:
        return "profit"
    if v < 0:
        return "loss"
    return "neutral"


def _positions_rows(positions: list) -> str:
    if not positions:
        return '<tr><td colspan="7" class="empty-row">目前無持倉</td></tr>'
    rows = []
    for p in positions:
        team = p.get("team", "—")
        stage = STAGE_LABELS.get(p.get("stage", ""), p.get("stage", "—"))
        size = p.get("size_usd", 0)
        entry = p.get("entry_price", 0)
        our_prob = p.get("our_prob", 0)
        ev = our_prob - entry
        ev_cls = "profit" if ev > 0 else "loss"
        entry_time = p.get("entry_time", "")[:16].replace("T", " ")
        rows.append(f"""
        <tr>
          <td class="team-cell">{team}</td>
          <td><span class="stage-badge">{stage}</span></td>
          <td>${size:.2f}</td>
          <td>{entry:.3f}</td>
          <td>{our_prob:.3f}</td>
          <td class="{ev_cls}">{_fmt_pct(ev)}</td>
          <td class="muted">{entry_time}</td>
        </tr>""")
    return "\n".join(rows)


def _trade_log_rows(trade_log: list) -> str:
    if not trade_log:
        return '<tr><td colspan="7" class="empty-row">尚無交易紀錄</td></tr>'
    rows = []
    for t in reversed(trade_log[-50:]):
        team = t.get("team", "—")
        stage = STAGE_LABELS.get(t.get("stage", ""), t.get("stage", "—"))
        action = t.get("action", "BUY")
        size = t.get("size_usd", 0)
        price = t.get("price", 0)
        pnl = t.get("pnl", None)
        ts = t.get("time", "")[:16].replace("T", " ")
        pnl_str = _fmt_usd(pnl) if pnl is not None else "—"
        pnl_cls = _pnl_class(pnl) if pnl is not None else "neutral"
        action_cls = "buy-badge" if action == "BUY" else "sell-badge"
        rows.append(f"""
        <tr>
          <td class="team-cell">{team}</td>
          <td><span class="stage-badge">{stage}</span></td>
          <td><span class="{action_cls}">{action}</span></td>
          <td>${size:.2f}</td>
          <td>{price:.3f}</td>
          <td class="{pnl_cls}">{pnl_str}</td>
          <td class="muted">{ts}</td>
        </tr>""")
    return "\n".join(rows)


def _model_probs_rows(model_probs: dict, match_probs: dict) -> str:
    if not model_probs and not match_probs:
        return '<tr><td colspan="5" class="empty-row">尚無模型機率（等待 pm_predict 首次運行）</td></tr>'
    rows = []
    for team, probs in sorted(model_probs.items()):
        qf = probs.get("qf", "—")
        sf = probs.get("sf", "—")
        final = probs.get("final", "—")
        winner = probs.get("winner", "—")
        fmt = lambda v: f"{v*100:.1f}%" if isinstance(v, float) else "—"
        rows.append(f"""
        <tr>
          <td class="team-cell">{team}</td>
          <td>{fmt(qf)}</td>
          <td>{fmt(sf)}</td>
          <td>{fmt(final)}</td>
          <td>{fmt(winner)}</td>
        </tr>""")
    return "\n".join(rows) if rows else '<tr><td colspan="5" class="empty-row">—</td></tr>'


def _match_probs_rows(match_probs: dict) -> str:
    if not match_probs:
        return '<tr><td colspan="5" class="empty-row">—</td></tr>'
    rows = []
    for mid, mp in match_probs.items():
        home = mp.get("home", "—")
        away = mp.get("away", "—")
        ph = mp.get("p_home_win", 0)
        pd = mp.get("p_draw", 0)
        pa = mp.get("p_away_win", 0)
        rows.append(f"""
        <tr>
          <td class="team-cell">{home}</td>
          <td class="muted">vs</td>
          <td class="team-cell">{away}</td>
          <td>{ph*100:.1f}% / {pd*100:.1f}% / {pa*100:.1f}%</td>
          <td class="muted">{mid}</td>
        </tr>""")
    return "\n".join(rows)


def _calibration_rows(history: list) -> str:
    if not history:
        return '<tr><td colspan="4" class="empty-row">尚無校準紀錄</td></tr>'
    rows = []
    for h in reversed(history[-10:]):
        ts = h.get("time", "")[:16].replace("T", " ")
        n = h.get("n_settled", "—")
        factor = h.get("factor", 1.0)
        rows.append(f"""
        <tr>
          <td class="muted">{ts}</td>
          <td>{n}</td>
          <td>{factor:.4f}</td>
          <td class="{'profit' if factor > 1 else 'loss' if factor < 1 else 'neutral'}">
            {'高估' if factor > 1 else '低估' if factor < 1 else '準確'}
          </td>
        </tr>""")
    return "\n".join(rows)


def render(data: dict) -> str:
    bankroll = data.get("bankroll", 500.0)
    daily_pnl = data.get("daily_pnl", 0.0)
    halted = data.get("trading_halted", False)
    positions = data.get("positions", [])
    trade_log = data.get("trade_log", [])
    model_probs = data.get("model_probs", {})
    match_probs = data.get("match_probs", {})
    calib = data.get("calibration", {})
    calib_factor = calib.get("factor", 1.0)
    calib_n = calib.get("n_settled", 0)
    calib_history = calib.get("history", [])
    updated_at = data.get("model_probs_updated_at", "")
    if updated_at:
        updated_at = updated_at[:19].replace("T", " ") + " UTC"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    status_cls = "halted" if halted else "active"
    status_text = "HALTED" if halted else "ACTIVE"

    total_exposed = sum(p.get("size_usd", 0) for p in positions)
    n_positions = len(positions)

    pnl_cls = _pnl_class(daily_pnl)

    settled_wins = sum(1 for t in trade_log if t.get("pnl", 0) > 0)
    settled_total = sum(1 for t in trade_log if t.get("pnl") is not None)
    win_rate = f"{settled_wins/settled_total*100:.0f}%" if settled_total > 0 else "—"
    total_pnl = sum(t.get("pnl", 0) for t in trade_log if t.get("pnl") is not None)

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>交易儀表板</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
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
}}
body {{
  font-family: "Inter", "PingFang TC", "Microsoft JhengHei", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  line-height: 1.5;
}}
header {{
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
}}
.logo {{ display: flex; align-items: center; gap: 10px; }}
.logo-icon {{ font-size: 1.5rem; }}
.logo-text {{ font-size: 1.1rem; font-weight: 700; color: var(--text); letter-spacing: -0.3px; }}
.logo-sub {{ font-size: 0.72rem; color: var(--muted); margin-top: 1px; }}
nav {{ display: flex; gap: 2px; }}
nav a {{
  display: flex; align-items: center; gap: 6px;
  padding: 8px 16px;
  color: var(--muted);
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 500;
  border-radius: 8px;
  transition: all 0.15s;
}}
nav a:hover {{ color: var(--text); background: rgba(255,255,255,0.05); }}
nav a.active {{ color: var(--accent); background: rgba(59,130,246,0.1); }}
main {{ max-width: 1200px; margin: 0 auto; padding: 32px 20px; }}
.page-header {{ margin-bottom: 28px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }}
.page-title {{ font-size: 1.5rem; font-weight: 700; color: var(--text); }}
.updated-chip {{
  font-size: 0.75rem; color: var(--muted);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 20px; padding: 4px 12px;
}}
.status-badge {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.75rem; font-weight: 700;
  padding: 4px 12px; border-radius: 20px;
  text-transform: uppercase; letter-spacing: 0.5px;
}}
.status-badge.active {{ background: rgba(16,185,129,0.15); color: var(--green); border: 1px solid rgba(16,185,129,0.3); }}
.status-badge.halted {{ background: rgba(239,68,68,0.15); color: var(--red); border: 1px solid rgba(239,68,68,0.3); }}
.status-dot {{ width: 7px; height: 7px; border-radius: 50%; }}
.active .status-dot {{ background: var(--green); box-shadow: 0 0 6px var(--green); animation: pulse 2s infinite; }}
.halted .status-dot {{ background: var(--red); }}
@keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.5; }} }}
/* ── stat cards ── */
.stats-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 28px;
}}
.stat-card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}}
.stat-label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
.stat-value {{ font-size: 1.8rem; font-weight: 800; color: var(--text); }}
.stat-value.profit {{ color: var(--green); }}
.stat-value.loss {{ color: var(--red); }}
.stat-value.neutral {{ color: var(--text); }}
/* ── section ── */
.section {{ margin-bottom: 28px; }}
.section-title {{
  font-size: 0.85rem; font-weight: 700;
  color: var(--muted); text-transform: uppercase; letter-spacing: 0.8px;
  margin-bottom: 12px;
}}
/* ── table ── */
.table-wrap {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}}
table {{ width: 100%; border-collapse: collapse; }}
th {{
  background: var(--surface);
  padding: 10px 16px;
  text-align: left;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  border-bottom: 1px solid var(--border);
}}
td {{
  padding: 12px 16px;
  font-size: 0.85rem;
  border-bottom: 1px solid rgba(30,45,69,0.5);
}}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: rgba(255,255,255,0.02); }}
.empty-row {{ text-align: center; color: var(--muted); padding: 24px; }}
.team-cell {{ font-weight: 600; }}
.muted {{ color: var(--muted); }}
.profit {{ color: var(--green); font-weight: 600; }}
.loss {{ color: var(--red); font-weight: 600; }}
.neutral {{ color: var(--muted); }}
.stage-badge {{
  display: inline-block;
  background: rgba(59,130,246,0.12);
  color: var(--accent);
  border: 1px solid rgba(59,130,246,0.25);
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 0.75rem;
  font-weight: 600;
}}
.buy-badge {{
  display: inline-block;
  background: rgba(16,185,129,0.12);
  color: var(--green);
  border: 1px solid rgba(16,185,129,0.25);
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 0.75rem;
  font-weight: 600;
}}
.sell-badge {{
  display: inline-block;
  background: rgba(239,68,68,0.12);
  color: var(--red);
  border: 1px solid rgba(239,68,68,0.25);
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 0.75rem;
  font-weight: 600;
}}
.calib-info {{
  display: flex; gap: 20px; flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 20px;
  margin-bottom: 14px;
  font-size: 0.85rem;
}}
.calib-item {{ display: flex; flex-direction: column; gap: 2px; }}
.calib-key {{ font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
.calib-val {{ font-weight: 700; color: var(--text); }}
@media (max-width: 600px) {{
  header {{ padding: 0 14px; height: auto; min-height: 56px; flex-wrap: wrap; gap: 6px; padding-top: 8px; padding-bottom: 8px; }}
  .logo-sub {{ display: none; }}
  nav a {{ padding: 6px 9px; font-size: 0.75rem; }}
  main {{ padding: 20px 14px; }}
  .stats-grid {{ grid-template-columns: repeat(2, 1fr); gap: 10px; }}
  .stat-value {{ font-size: 1.4rem; }}
  td, th {{ padding: 8px 10px; font-size: 0.78rem; }}
}}
</style>
</head>
<body>
<header>
  <div class="logo">
    <span class="logo-icon">&#127942;</span>
    <div>
      <div class="logo-text">WC 2026 Model</div>
      <div class="logo-sub">Polymarket Auto-Trader</div>
    </div>
  </div>
  <nav>
    <a href="index.html">&#128197; 今日預測</a>
    <a href="results.html">&#128202; 歷史結果</a>
    <a href="postmortem.html">&#128269; 復盤</a>
    <a href="trading.html" class="active">&#128200; 交易</a>
  </nav>
</header>

<main>
  <div class="page-header">
    <div>
      <div class="page-title">交易儀表板</div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <span class="status-badge {status_cls}">
        <span class="status-dot"></span>
        {status_text}
      </span>
      <span class="updated-chip">頁面每 60 秒自動刷新 &bull; 生成於 {now}</span>
    </div>
  </div>

  <!-- ── 關鍵指標 ── -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">本金餘額</div>
      <div class="stat-value">${bankroll:.2f}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">今日損益</div>
      <div class="stat-value {pnl_cls}">{_fmt_usd(daily_pnl)}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">累計損益</div>
      <div class="stat-value {_pnl_class(total_pnl)}">{_fmt_usd(total_pnl)}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">持倉數 / 上限</div>
      <div class="stat-value">{n_positions} / 4</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">已曝險金額</div>
      <div class="stat-value">${total_exposed:.2f}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">已結算勝率</div>
      <div class="stat-value">{win_rate}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">已結算筆數</div>
      <div class="stat-value">{settled_total}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">模型校準係數</div>
      <div class="stat-value">{calib_factor:.3f}</div>
    </div>
  </div>

  <!-- ── 持倉 ── -->
  <div class="section">
    <div class="section-title">目前持倉</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>球隊</th><th>賽段</th><th>投注金額</th>
          <th>進場價</th><th>模型機率</th><th>當前 EV</th><th>進場時間</th>
        </tr></thead>
        <tbody>
          {_positions_rows(positions)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ── 交易紀錄 ── -->
  <div class="section">
    <div class="section-title">交易紀錄（最近 50 筆）</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>球隊</th><th>賽段</th><th>動作</th>
          <th>金額</th><th>價格</th><th>損益</th><th>時間</th>
        </tr></thead>
        <tbody>
          {_trade_log_rows(trade_log)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ── 模型機率：晉級 ── -->
  <div class="section">
    <div class="section-title">
      模型機率：晉級
      {f'<span style="font-size:0.72rem;color:var(--muted);margin-left:8px;">更新於 {updated_at}</span>' if updated_at else ''}
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>球隊</th><th>八強</th><th>四強</th><th>決賽</th><th>奪冠</th>
        </tr></thead>
        <tbody>
          {_model_probs_rows(model_probs, match_probs)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ── 模型機率：場次 ── -->
  <div class="section">
    <div class="section-title">模型機率：場次</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>主隊</th><th></th><th>客隊</th><th>主勝 / 平 / 客勝</th><th>賽事 ID</th>
        </tr></thead>
        <tbody>
          {_match_probs_rows(match_probs)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- ── 模型校準 ── -->
  <div class="section">
    <div class="section-title">模型校準</div>
    <div class="calib-info">
      <div class="calib-item">
        <span class="calib-key">已結算筆數</span>
        <span class="calib-val">{calib_n}</span>
      </div>
      <div class="calib-item">
        <span class="calib-key">當前係數</span>
        <span class="calib-val">{calib_factor:.4f}</span>
      </div>
      <div class="calib-item">
        <span class="calib-key">下次更新</span>
        <span class="calib-val">再結算 {max(0, 10 - calib_n % 10)} 筆</span>
      </div>
      <div class="calib-item">
        <span class="calib-key">係數說明</span>
        <span class="calib-val" style="color:{'var(--green)' if calib_factor < 1 else 'var(--red)' if calib_factor > 1 else 'var(--muted)'}">
          {'模型低估（勝率比實際低）' if calib_factor < 1 else '模型高估（勝率比實際高）' if calib_factor > 1 else '準確'}
        </span>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>時間</th><th>已結算筆數</th><th>校準係數</th><th>方向</th>
        </tr></thead>
        <tbody>
          {_calibration_rows(calib_history)}
        </tbody>
      </table>
    </div>
  </div>
</main>
</body>
</html>"""


def generate() -> None:
    data = _load()
    html = render(data)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"[render_trading] wrote {OUTPUT_PATH}")


def watch(interval: int = 30) -> None:
    print(f"[render_trading] watching, interval={interval}s")
    while True:
        try:
            generate()
        except Exception as e:
            print(f"[render_trading] error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()
    if args.watch:
        watch(args.interval)
    else:
        generate()
