"""
render_trading.py — 生成 docs/trading.html 交易儀表板

用法：
  python3 -m src.render_trading          # 生成一次
  python3 -m src.render_trading --watch  # 每 30 秒重新生成
"""

import json
import os
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone

PORTFOLIO_PATH = Path(__file__).parent.parent / "data" / "portfolio.json"
OUTPUT_PATH = Path(__file__).parent.parent / "docs" / "trading.html"

STAGE_LABELS = {"qf": "八強", "sf": "四強", "final": "決賽", "winner": "奪冠"}

DATA_API = "https://data-api.polymarket.com"


def _fetch_live_data() -> dict:
    """從 Polymarket data-api 拉 live 資料，回傳 dict（失敗欄位為 None）。"""
    _load_env_once()
    maker = os.environ.get("POLY_MAKER", "")
    result = {"positions_value": None, "invested": None, "positions": [], "bankroll": None}
    if not maker:
        return result
    try:
        rv = requests.get(f"{DATA_API}/value?user={maker}", timeout=8)
        rp = requests.get(f"{DATA_API}/positions?user={maker}", timeout=8)
        if rv.ok and rv.json():
            result["positions_value"] = round(rv.json()[0]["value"], 2)
        if rp.ok:
            raw = rp.json()
            result["positions"] = raw
            result["invested"]  = round(sum(p.get("initialValue", 0) for p in raw), 2)
        # available USDC = off-chain，用 portfolio.json bankroll - invested 估算
        if result["invested"] is not None:
            from src.pm_portfolio import load as _pl
            bankroll = _pl().get("bankroll", 0.0)
            result["bankroll"] = round(bankroll, 2)
    except Exception:
        pass
    return result


def _load_env_once() -> None:
    from pathlib import Path
    env = Path(__file__).parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


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


def _pnl_row(p: dict) -> str:
    """data-api position → 損益表一行"""
    title  = p.get("title", "")
    team   = title.replace("Will ", "").split(" reach")[0] if "Will " in title else title[:30]
    cost   = p.get("initialValue", 0)
    val    = p.get("currentValue",  0)
    pnl    = p.get("cashPnl",       0)
    pct    = p.get("percentPnl",    0)
    avg    = p.get("avgPrice",       0)
    cur    = p.get("curPrice",       avg)
    shares = p.get("size",           0)
    cls    = "profit" if pnl >= 0 else "loss"
    sign   = "+" if pnl >= 0 else "-"
    return f"""
        <tr>
          <td class="team-cell">{team}</td>
          <td style="text-align:right;">${cost:.2f}</td>
          <td style="text-align:right;">${val:.2f}</td>
          <td style="text-align:right;" class="{cls}">{sign}${abs(pnl):.2f}</td>
          <td style="text-align:right;" class="{cls}">{sign}{abs(pct):.1f}%</td>
          <td style="text-align:right;" class="muted">{avg*100:.1f}¢</td>
          <td style="text-align:right;">{cur*100:.1f}¢</td>
          <td style="text-align:right;" class="muted">{shares:.1f}</td>
        </tr>"""


def _positions_rows(positions: list, live_positions: list = None) -> str:
    """live_positions: data-api format（優先）；positions: portfolio.json format（fallback）"""
    # 優先使用 data-api live 數據
    if live_positions:
        rows = []
        for p in live_positions:
            if p.get("initialValue", 0) < 1.0:  # skip neg-risk dust positions
                continue
            title = p.get("title", "—")
            outcome = p.get("outcome", "Yes")
            # 萃取球隊名
            if "Will " in title and " reach" in title:
                team = title.replace("Will ", "").split(" reach")[0]
            elif "Will " in title and " win" in title:
                team = title.replace("Will ", "").split(" win")[0]
            else:
                team = title[:25]
            # 方向標籤
            if outcome == "No":
                dir_badge = '<span class="sell-badge">做空 NO</span>'
            else:
                dir_badge = '<span class="buy-badge">做多 YES</span>'
            # 市場類型
            if "Semifinals" in title:
                mkt = "SF"
            elif "win the 2026" in title:
                mkt = "WC冠軍"
            else:
                mkt = "—"
            avg   = p.get("avgPrice", 0)
            cur   = p.get("curPrice", avg)
            size  = p.get("initialValue", 0)
            cur_v = p.get("currentValue", 0)
            pnl   = p.get("cashPnl", 0)
            pct   = p.get("percentPnl", 0)
            shares= p.get("size", 0)
            pnl_cls = "profit" if pnl >= 0 else "loss"
            rows.append(f"""
        <tr>
          <td class="team-cell">{team}</td>
          <td>{dir_badge}</td>
          <td><span class="stage-badge">{mkt}</span></td>
          <td style="text-align:right">${size:.2f}</td>
          <td style="text-align:right">{avg*100:.1f}¢ → {cur*100:.1f}¢</td>
          <td style="text-align:right">{shares:.1f}股</td>
          <td class="{pnl_cls}" style="text-align:right">{'+' if pnl>=0 else ''}{pnl:.2f} ({pct:+.1f}%)</td>
          <td style="text-align:right" class="neutral">${cur_v:.2f}</td>
        </tr>""")
        return "\n".join(rows)

    # fallback: portfolio.json
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
        size_str = f"${size:.2f}" if size is not None else "—"
        rows.append(f"""
        <tr>
          <td class="team-cell">{team}</td>
          <td><span class="stage-badge">{stage}</span></td>
          <td><span class="{action_cls}">{action}</span></td>
          <td>{size_str}</td>
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


def _audit_log_rows(entries: list) -> str:
    if not entries:
        return '<tr><td colspan="6" class="empty-row">尚無稽核記錄</td></tr>'
    rows = []
    for e in reversed(entries):
        ts = e.get("ts", "")[:19].replace("T", " ")
        kind = "晉級" if e.get("type") == "advancement" else "單場"
        label = e.get("team") or e.get("match", "—")
        ev = e.get("ev", 0)
        approved = e.get("approved", False)
        reason = e.get("reason", "—")
        ap_cls = "profit" if approved else "loss"
        ap_text = "✅ 通過" if approved else "❌ 拒絕"
        rows.append(f"""
        <tr>
          <td class="muted">{ts}</td>
          <td><span class="stage-badge">{kind}</span></td>
          <td class="team-cell">{label}</td>
          <td>{ev*100:+.1f}¢</td>
          <td class="{ap_cls}">{ap_text}</td>
          <td class="muted" style="font-size:0.75rem">{reason}</td>
        </tr>""")
    return "\n".join(rows)


def render(data: dict, chain_usdc: float = None, chain_matic: float = None,
           audit_entries: list = None, live_positions: list = None) -> str:
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

    # chain_usdc 現在是 data-api 組合市值，chain_matic 是已投入成本
    portfolio_value = chain_usdc   # float | None
    invested_cost   = chain_matic  # float | None
    bankroll = portfolio_value if portfolio_value is not None else data.get("bankroll", 0.0)
    invested_str = f"${invested_cost:.2f}" if invested_cost is not None else "—"
    live_ok = portfolio_value is not None

    audit_entries  = audit_entries or []
    live_positions = live_positions or []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    status_cls = "halted" if halted else "active"
    status_text = "HALTED" if halted else "ACTIVE"

    # Split live_positions into active (open) and settled (redeemable=True, value=$0)
    _resolved_positions = [
        p for p in live_positions
        if p.get("redeemable") and p.get("currentValue", 1) < 0.01
        and p.get("initialValue", 0) >= 1.0
    ]
    _resolved_ids = {id(p) for p in _resolved_positions}
    live_positions = [p for p in live_positions if id(p) not in _resolved_ids]

    # 優先用 live_positions（data-api）計算曝險，fallback 用 portfolio.json
    if live_positions:
        total_exposed = sum(p.get("initialValue", 0) for p in live_positions)
        n_positions   = len(live_positions)
    else:
        total_exposed = sum(p.get("size_usd", 0) for p in positions)
        n_positions   = len(positions)

    pnl_cls = _pnl_class(daily_pnl)

    settled_wins = sum(1 for t in trade_log if (t.get("pnl") or 0) > 0)
    settled_total = sum(1 for t in trade_log if t.get("pnl") is not None)
    win_rate = f"{settled_wins/settled_total*100:.0f}%" if settled_total > 0 else "—"
    total_pnl = sum(t.get("pnl", 0) for t in trade_log if t.get("pnl") is not None)
    # Include resolved data-api positions as confirmed realized losses
    total_pnl += sum(p.get("cashPnl", 0) for p in _resolved_positions)

    # ── live P&L from data-api ──────────────────────────────────────
    live_total_invested = sum(p.get("initialValue", 0) for p in live_positions)
    live_total_value    = sum(p.get("currentValue",  0) for p in live_positions)
    live_total_pnl      = sum(p.get("cashPnl",       0) for p in live_positions)
    live_pnl_pct        = (live_total_pnl / live_total_invested * 100) if live_total_invested > 0 else 0
    live_pnl_cls        = "profit" if live_total_pnl >= 0 else "loss"
    live_sign           = "+" if live_total_pnl >= 0 else "-"

    # 預先計算 tfoot HTML（避免巢狀 f-string 在 Python 3.9 報錯）
    if live_positions:
        _tfoot = (
            f'<tfoot><tr style="border-top:2px solid var(--border);font-weight:700;">'
            f'<td>合計</td>'
            f'<td style="text-align:right;">${live_total_invested:.2f}</td>'
            f'<td style="text-align:right;">${live_total_value:.2f}</td>'
            f'<td style="text-align:right;" class="{live_pnl_cls}">{live_sign}${abs(live_total_pnl):.2f}</td>'
            f'<td style="text-align:right;" class="{live_pnl_cls}">{live_sign}{abs(live_pnl_pct):.2f}%</td>'
            f'<td colspan="3"></td>'
            f'</tr></tfoot>'
        )
        _pnl_rows = "".join(_pnl_row(p) for p in live_positions)
    else:
        _tfoot = ""
        _pnl_rows = '<tr><td colspan="8" class="empty-row">無持倉資料</td></tr>'

    # 已結算部位 HTML block（redeemable=True, $0 value）
    if _resolved_positions:
        _resolved_rows = ""
        for p in _resolved_positions:
            title = p.get("title", "")
            team = title.replace("Will ", "").split(" reach")[0] if "Will " in title else title[:30]
            cost = p.get("initialValue", 0)
            pnl_r = p.get("cashPnl", 0)
            pct_r = p.get("percentPnl", 0)
            avg_r = p.get("avgPrice", 0)
            _resolved_rows += (
                f'<tr>'
                f'<td class="team-cell">{team}</td>'
                f'<td style="text-align:right;">${cost:.2f}</td>'
                f'<td style="text-align:right;">$0.00</td>'
                f'<td style="text-align:right;" class="loss">-${abs(pnl_r):.2f}</td>'
                f'<td style="text-align:right;" class="loss">{pct_r:+.1f}%</td>'
                f'<td style="text-align:right;" class="muted">{avg_r*100:.1f}¢</td>'
                f'<td style="text-align:right;" class="muted">0.0¢</td>'
                f'<td style="text-align:right;" class="muted">—</td>'
                f'</tr>'
            )
        _resolved_section = (
            '<div class="section" style="margin-top:12px;">'
            '<div class="section-title" style="color:var(--red);">已結算部位（確認虧損）</div>'
            '<div class="table-wrap"><table>'
            '<thead><tr>'
            '<th>球隊</th>'
            '<th style="text-align:right;">成本</th>'
            '<th style="text-align:right;">市值</th>'
            '<th style="text-align:right;">損益 ($)</th>'
            '<th style="text-align:right;">損益 (%)</th>'
            '<th style="text-align:right;">均價</th>'
            '<th style="text-align:right;">現價</th>'
            '<th style="text-align:right;">份額</th>'
            '</tr></thead>'
            f'<tbody>{_resolved_rows}</tbody>'
            '</table></div></div>'
        )
    else:
        _resolved_section = ""

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
    <a href="index.html">📊 今日預測</a>
    <a href="results.html">📜 歷史結果</a>
    <a href="calibration.html">⚙️ 模型校正</a>
    <a href="postmortem.html">🔍 復盤分析</a>
    <a href="trading.html" class="active">📈 交易</a>
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

  <!-- ── 即時損益表 ── -->
  <div class="section" style="margin-bottom:20px;">
    <div class="section-header" style="margin-bottom:12px;">
      <span class="section-title">即時損益表
        {'<span style="color:var(--green);font-size:0.72rem;margin-left:8px;">● LIVE · 60s 自動刷新</span>' if live_ok else ''}
      </span>
    </div>

    <!-- 總覽橫條 -->
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px;margin-bottom:16px;">
      <div class="stat-card" style="border-color:{'rgba(16,185,129,0.5)' if live_total_pnl>=0 else 'rgba(239,68,68,0.5)'}">
        <div class="stat-label">未實現總損益</div>
        <div class="stat-value {live_pnl_cls}" style="font-size:2rem;">{live_sign}${abs(live_total_pnl):.2f}</div>
        <div style="font-size:0.78rem;color:var(--{'green' if live_total_pnl>=0 else 'red'});margin-top:2px;">{live_sign}{abs(live_pnl_pct):.2f}%</div>
      </div>
      <div class="stat-card" style="border-color:{'rgba(16,185,129,0.5)' if (total_pnl+live_total_pnl)>=0 else 'rgba(239,68,68,0.5)'}">
        <div class="stat-label">總收益</div>
        <div class="stat-value {'profit' if (total_pnl+live_total_pnl)>=0 else 'loss'}">{'+' if (total_pnl+live_total_pnl)>=0 else '-'}${abs(total_pnl+live_total_pnl):.2f}</div>
        <div style="font-size:0.75rem;color:var(--muted);margin-top:2px;">已結算 {'+' if total_pnl>=0 else ''}{total_pnl:.2f} + 未實現 {'+' if live_total_pnl>=0 else ''}{live_total_pnl:.2f}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">已投入成本</div>
        <div class="stat-value">${live_total_invested:.2f}</div>
        <div style="font-size:0.75rem;color:var(--muted);margin-top:2px;">{n_positions} 筆部位</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">持倉市值</div>
        <div class="stat-value">${live_total_value:.2f}</div>
        <div style="font-size:0.75rem;color:var(--muted);margin-top:2px;">data-api 即時</div>
      </div>
    </div>

    <!-- 逐倉損益明細 -->
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>市場</th>
          <th style="text-align:right;">成本</th>
          <th style="text-align:right;">市值</th>
          <th style="text-align:right;">損益 ($)</th>
          <th style="text-align:right;">損益 (%)</th>
          <th style="text-align:right;">均價</th>
          <th style="text-align:right;">現價</th>
          <th style="text-align:right;">份額</th>
        </tr></thead>
        <tbody>
          {_pnl_rows}
        </tbody>
        {_tfoot}
      </table>
    </div>
  </div>

  <!-- ── 關鍵指標 ── -->
  <div class="stats-grid" style="margin-bottom:20px;">
    <div class="stat-card">
      <div class="stat-label">持倉數</div>
      <div class="stat-value">{n_positions}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">已曝險成本</div>
      <div class="stat-value">${total_exposed:.2f}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">已結算勝率</div>
      <div class="stat-value">{win_rate}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">模型校準係數</div>
      <div class="stat-value">{calib_factor:.3f}</div>
    </div>
  </div>

  <!-- ── 持倉明細（data-api） ── -->
  <div class="section">
    <div class="section-title">持倉明細</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>球隊</th><th>方向</th><th>市場</th><th>投注金額</th>
          <th>均價 → 現價</th><th>持有份額</th><th>損益</th><th>當前市值</th>
        </tr></thead>
        <tbody>
          {_positions_rows(positions, live_positions)}
        </tbody>
      </table>
    </div>
  </div>

  {_resolved_section}

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

  <!-- ── 稽核日誌 ──────────────────────────────────── -->
  <div class="section">
    <div class="section-header">
      <span class="section-title">🔍 稽核日誌（最近 20 筆）</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>時間</th><th>類型</th><th>信號</th><th>EV</th><th>結果</th><th>原因</th>
        </tr></thead>
        <tbody>
          {_audit_log_rows(audit_entries)}
        </tbody>
      </table>
    </div>
  </div>

</main>
</body>
</html>"""


def generate() -> None:
    from src.pm_auditor import recent_decisions
    data       = _load()
    live       = _fetch_live_data()
    audit_entries = recent_decisions(20)
    html = render(
        data,
        chain_usdc    = live["positions_value"],
        chain_matic   = live["invested"],
        audit_entries = audit_entries,
        live_positions= live["positions"],
    )
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    pv = live["positions_value"]
    print(f"[render_trading] wrote {OUTPUT_PATH}  positions_value={f'${pv:.2f}' if pv else 'N/A'}")


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
