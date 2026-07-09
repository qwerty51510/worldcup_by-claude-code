"""
操演指揮：協調 4 個 Agent 完成一輪掃描→定位→執行
用法：
  python -m src.orchestrator                   # dry-run，資金 $1000
  python -m src.orchestrator --bankroll 500    # 指定資金規模
  python -m src.orchestrator --min-ev 0.05     # 提高 EV 門檻
  python -m src.orchestrator --live            # 真實下單（尚需 wallet key）
"""

import argparse
import sys
from datetime import date
from pathlib import Path

SEP  = "─" * 68
SEP2 = "═" * 68


def _banner(n: int, title: str) -> None:
    print(f"\n{SEP}")
    print(f"  Agent {n}  |  {title}")
    print(SEP)


def run(bankroll: float = 1000.0, dry_run: bool = True, min_ev: float = 0.03) -> None:
    from src.pm_ev_scanner import scan, _zh, STAGE_ZH
    from src.risk_agent     import size_opportunities
    from src.execution_agent import test_connection, execute, fetch_user_trades

    print(f"\n{SEP2}")
    print(f"  世界盃 PM 交易系統 — 最後操演")
    print(f"  資金規模：${bankroll:,.0f} USDC  "
          f"EV 門檻：{min_ev*100:.0f}¢  "
          f"模式：{'🔵 DRY RUN' if dry_run else '⚡ LIVE'}")
    print(SEP2)

    # ── Agent 1：資料員 ──────────────────────────────────────────────
    _banner(1, "資料員  Data Steward")
    pred_dir = Path("data/predictions")
    today_f  = pred_dir / f"{date.today().isoformat()}.json"
    all_preds = sorted(pred_dir.glob("*.json"))

    if today_f.exists():
        print(f"  ✓ 今日預測存在：{today_f.name}")
    elif all_preds:
        latest = all_preds[-1]
        print(f"  ⚠ 今日預測未找到，最新：{latest.name}")
    else:
        print("  ✗ 無預測資料，請先執行 fetch_data.py")
        sys.exit(1)

    results_f = Path("data/wc2026_results.json")
    if results_f.exists():
        import json
        results = json.loads(results_f.read_text())
        latest_match = max(r["date"] for r in results) if results else "—"
        print(f"  ✓ 賽果資料：{len(results)} 場，最新 {latest_match}")
    else:
        print("  ⚠ 找不到賽果資料")

    # ── Agent 2：信號員 ──────────────────────────────────────────────
    _banner(2, "信號員  Signal Scout")
    stage_opps, group_opps = scan(min_ev=min_ev)
    buys  = [o for o in stage_opps if o.ev > 0]
    sells = [o for o in stage_opps if o.ev < 0]
    print(f"\n  晉級信號：{len(buys)} BUY  /  {len(sells)} SELL")
    print(f"  組冠信號：{len(group_opps)} 個")

    # ── Agent 2.5：持倉監控員 ────────────────────────────────────────
    _banner(3, "持倉監控員  Position Monitor")
    from src.position_monitor import check_and_execute as monitor
    monitor_logs = monitor(dry_run=dry_run)
    for line in monitor_logs:
        print(line)

    # ── Agent 3：風控員 ──────────────────────────────────────────────
    _banner(4, "風控員  Risk Manager")
    from src import pm_portfolio
    from src.risk_agent import _get_group
    _pdata = pm_portfolio.load().get("positions", [])
    _open  = [p for p in _pdata if p.get("status") == "open"]
    _held_tokens = {p.get("token_id","") for p in _open}
    _held_keys   = {(p.get("team",""), p.get("stage","")) for p in _open}
    _held_teams  = {p.get("team","") for p in _open}

    # 路線衝突過濾：查未來賽程，若新標的與現有持倉在 R16/QF 直接對決 → 跳過
    import urllib.request as _ureq, json as _json
    _bracket_conflicts: set[str] = set()
    try:
        import datetime as _dt
        for _d in [(_dt.date.today() + _dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(10)]:
            _sb_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={_d}"
            _r = _ureq.Request(_sb_url, headers={"User-Agent": "Mozilla/5.0"})
            with _ureq.urlopen(_r, timeout=5) as _resp:
                _sb = _json.loads(_resp.read())
            for _ev in _sb.get("events", []):
                _comps = _ev.get("competitions", [{}])[0]
                _competitors = _comps.get("competitors", [])
                _names = [c.get("team", {}).get("shortDisplayName", "") for c in _competitors]
                _held_in_match = [t for t in _held_teams if any(t.lower() in n.lower() or n.lower() in t.lower() for n in _names)]
                if len(_held_in_match) >= 2:
                    for _t in _held_in_match:
                        _bracket_conflicts.add(_t)
    except Exception:
        pass

    _new_opps = [o for o in stage_opps
                 if o.token_id not in _held_tokens and (o.team, o.label) not in _held_keys]
    # 過濾掉與現有持倉即將對決的標的
    _bracket_blocked = [o for o in _new_opps if o.team in _bracket_conflicts]
    _new_opps = [o for o in _new_opps if o.team not in _bracket_conflicts]
    if _pdata:
        print(f"  已持倉過濾：略過 {len(stage_opps) - len(_new_opps) - len(_bracket_blocked)} 個已有部位")
    if _bracket_conflicts:
        print(f"  路線衝突過濾：{_bracket_conflicts} 與現有持倉在未來賽程直接對決，略過 {len(_bracket_blocked)} 個")
        print(f"  ⚠ 衝突持倉 {_bracket_conflicts} — 建議在下場比賽前 CLOB 有流動性時出清較弱一方")

    # 預載已持倉的組別曝險，防止風控計算漏算既有部位
    _init_grp: dict[str, float] = {}
    _init_total = 0.0
    for p in _open:
        grp = _get_group(p.get("team", ""))
        amt = float(p.get("size_usd", 0))
        if grp:
            _init_grp[grp] = _init_grp.get(grp, 0.0) + amt
        _init_total += amt

    bets = size_opportunities(_new_opps, bankroll,
                              initial_group_used=_init_grp,
                              initial_total=_init_total)

    if not bets:
        print("  ── 目前無符合 Kelly 門檻的部位 ──")
    else:
        total = sum(b.size_usdc for b in bets)
        print(f"  建議下注 {len(bets)} 注  合計 ${total:.0f} / ${bankroll:.0f}  "
              f"曝險 {total/bankroll*100:.1f}%\n")
        for b in bets:
            shares = b.size_usdc / b.price
            print(f"  {_zh(b.team):<8} {b.label:<10}  "
                  f"ROI {b.ev_roi*100:+.0f}%  "
                  f"出價 {b.price*100:.1f}¢  "
                  f"投入 ${b.size_usdc:.0f}  → {shares:.0f} 股")

    # ── Agent 4：執行員 ──────────────────────────────────────────────
    _banner(5, "執行員  Executor")
    ok, msg = test_connection()
    status = f"✓ 已連線（{msg}）" if ok else f"✗ 連線失敗（{msg}）"
    print(f"  CLOB API：{status}\n")

    if not bets:
        print("  ── 無部位需執行 ──")
        logs, placed = [], []
    else:
        mode = "DRY RUN — 模擬下單，未送出" if dry_run else "⚡ LIVE — 真實訂單"
        print(f"  [{mode}]\n")
        logs, placed = execute(bets, dry_run=dry_run)
        for log in logs:
            print(log)

    # ── 同步持倉 + 重繪 dashboard ──────────────────────────────────
    if not dry_run:
        _sync_and_render(placed)

    print(f"\n{SEP2}")
    print(f"  操演完成")
    print(f"{SEP2}\n")


def _sync_and_render(newly_placed: list[dict]) -> None:
    """從 CLOB 同步成交記錄 → 更新 portfolio.json → 重繪 trading.html"""
    import datetime
    from src import pm_portfolio
    from src.render_trading import generate as render
    from src.execution_agent import fetch_user_trades

    trades = fetch_user_trades()   # [{asset_id, price, size, taker_order_id, ...}]

    # 建立 order_id → 成交資訊的 map
    trade_map = {t.get("taker_order_id", ""): t for t in trades}

    data = pm_portfolio.load()
    existing_oids = {p.get("order_id") for p in data.get("positions", [])}

    for bet in newly_placed:
        oid = bet.get("order_id", "")
        if oid in existing_oids:
            continue
        fill = trade_map.get(oid, {})
        fill_price = float(fill.get("price", bet["price"])) if fill else bet["price"]
        fill_size  = float(fill.get("size", 0)) if fill else 0.0
        pos = {
            "order_id":    oid,
            "team":        bet["team"],
            "stage":       bet["label"],
            "token_id":    bet["token_id"],
            "size_usd":    bet["size_usdc"],
            "entry_price": fill_price,
            "shares":      fill_size,
            "our_prob":    bet.get("fair_value", 0.0),
            "entry_time":  datetime.datetime.utcnow().isoformat(),
            "status":      "open",
        }
        pm_portfolio.add_position(pos)
        pm_portfolio.log_trade({
            "team":     bet["team"],
            "stage":    bet["label"],
            "action":   "BUY",
            "size_usd": bet["size_usdc"],
            "price":    fill_price,
            "shares":   fill_size,
            "order_id": oid,
            "time":     pos["entry_time"],
            "pnl":      None,
        })

    render()
    print(f"\n  ✓ 面板已更新 → docs/trading.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bankroll", type=float, default=1000.0, help="資金規模 USDC")
    parser.add_argument("--min-ev",   type=float, default=0.03,   help="EV 門檻（小數）")
    parser.add_argument("--live",     action="store_true",         help="真實下單模式")
    args = parser.parse_args()
    run(bankroll=args.bankroll, dry_run=not args.live, min_ev=args.min_ev)
