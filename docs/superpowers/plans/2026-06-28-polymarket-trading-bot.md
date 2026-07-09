# Polymarket 自動交易系統 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立三模組自動交易系統，透過獨立機率引擎在 Polymarket 世界盃市場找到 EV 機會並自動執行。

**Architecture:** `pm_portfolio.py` 管理共享狀態（portfolio.json），`pm_predict.py` 每 5 分鐘寫入獨立機率，`pm_monitor.py` 每 60 秒監聽比賽事件，`pm_trader.py` 執行 Kelly 倉位並透過 CLOB API 下單。三個 process 獨立執行，透過 portfolio.json 溝通。

**Tech Stack:** Python 3.9, py-clob-client（GitHub 安裝），eth-account，requests，scipy，football-data.org API

## Global Constraints

- Python 3.9+（match、walrus operator 不可用）
- 單筆最大下注：$25（5% 本金）
- 同時最多 4 筆持倉
- 單日虧損上限：$75，觸發後停止當日所有交易
- 最低 EV 門檻：5%（our_prob - market_price > 0.05）
- 只用限價單建倉；緊急出場用市價單
- 錢包私鑰只從 `.env` 讀取，絕不寫入任何 source file
- 所有 process 的日誌都印 timestamp

---

## File Structure

```
src/
  pm_portfolio.py     # 新建：共享狀態 CRUD，帶 flock
  pm_predict.py       # 新建：獨立機率引擎（ELO + player_lambdas，零市場賠率）
  pm_monitor.py       # 新建：即時事件監聽（football-data.org + ESPN）
  pm_trader.py        # 新建：Kelly + CLOB 執行 + 出場邏輯 + 主迴圈
  pm_ev_scanner.py    # 修改：find_opportunities() 使用 model_probs 替代 peer_median
  config.py           # 不動

data/
  portfolio.json      # 自動建立（pm_portfolio.py 第一次執行時）

tests/
  test_pm_portfolio.py
  test_pm_predict.py
  test_pm_trader.py
  test_pm_monitor.py

requirements.txt      # 新增 py-clob-client, python-dotenv
.env                  # 已建立（不 commit）
```

---

## Task 1: Portfolio State Manager

**Files:**
- Create: `src/pm_portfolio.py`
- Test: `tests/test_pm_portfolio.py`

**Interfaces:**
- Produces:
  - `load() -> dict`
  - `save(data: dict) -> None`
  - `get_bankroll() -> float`
  - `is_halted() -> bool`
  - `add_position(pos: dict) -> None`
  - `remove_position(market_id: str) -> dict | None`
  - `update_pnl(delta: float) -> None`
  - `push_exit_signal(market_id: str, reason: str) -> None`
  - `pop_exit_signals() -> list[dict]`
  - `log_trade(entry: dict) -> None`

- [ ] **Step 1: 寫測試**

```python
# tests/test_pm_portfolio.py
import json
import pytest
from pathlib import Path
import src.pm_portfolio as pf


@pytest.fixture(autouse=True)
def tmp_portfolio(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", tmp_path / "portfolio.json")


def test_load_creates_default():
    data = pf.load()
    assert data["bankroll"] == 500.0
    assert data["positions"] == []
    assert data["trading_halted"] is False


def test_save_and_load_roundtrip():
    data = pf.load()
    data["bankroll"] = 480.0
    pf.save(data)
    assert pf.load()["bankroll"] == 480.0


def test_add_and_remove_position():
    pos = {"market_id": "abc", "team": "Switzerland", "size_usd": 20.0}
    pf.add_position(pos)
    assert len(pf.load()["positions"]) == 1
    removed = pf.remove_position("abc")
    assert removed["team"] == "Switzerland"
    assert pf.load()["positions"] == []


def test_update_pnl_halts_on_limit():
    pf.update_pnl(-80.0)
    assert pf.is_halted() is True


def test_exit_signals_push_pop():
    pf.push_exit_signal("abc", "RED_CARD")
    signals = pf.pop_exit_signals()
    assert signals[0]["market_id"] == "abc"
    assert pf.pop_exit_signals() == []
```

- [ ] **Step 2: 確認測試失敗**

```bash
cd /Users/anchor/claude/world-cup-model
python -m pytest tests/test_pm_portfolio.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` 或 `ImportError`

- [ ] **Step 3: 實作 pm_portfolio.py**

```python
# src/pm_portfolio.py
import fcntl
import json
from datetime import date
from pathlib import Path

PORTFOLIO_PATH = Path(__file__).parent.parent / "data" / "portfolio.json"

_DEFAULT: dict = {
    "bankroll": 500.0,
    "daily_pnl": 0.0,
    "daily_pnl_date": "",
    "daily_loss_limit": 75.0,
    "trading_halted": False,
    "positions": [],
    "model_probs": {},
    "match_probs": {},
    "live_events": {},
    "exit_signals": [],
    "trade_log": [],
    "calibration": {"n_settled": 0, "factor": 1.0, "history": []},
}


def load() -> dict:
    if not PORTFOLIO_PATH.exists():
        return {k: (v.copy() if isinstance(v, (dict, list)) else v)
                for k, v in _DEFAULT.items()}
    with open(PORTFOLIO_PATH) as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        data = json.load(f)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return data


def save(data: dict) -> None:
    PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PORTFOLIO_PATH, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(data, f, indent=2, ensure_ascii=False)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def get_bankroll() -> float:
    return load()["bankroll"]


def is_halted() -> bool:
    data = load()
    today = date.today().isoformat()
    if data.get("daily_pnl_date") != today:
        return False
    return data.get("trading_halted", False)


def add_position(pos: dict) -> None:
    data = load()
    data["positions"].append(pos)
    save(data)


def remove_position(market_id: str) -> dict | None:
    data = load()
    for i, p in enumerate(data["positions"]):
        if p["market_id"] == market_id:
            removed = data["positions"].pop(i)
            save(data)
            return removed
    return None


def update_pnl(delta: float) -> None:
    data = load()
    today = date.today().isoformat()
    if data.get("daily_pnl_date") != today:
        data["daily_pnl"] = 0.0
        data["daily_pnl_date"] = today
        data["trading_halted"] = False
    data["daily_pnl"] = round(data["daily_pnl"] + delta, 4)
    data["bankroll"] = round(data["bankroll"] + delta, 4)
    if data["daily_pnl"] <= -data["daily_loss_limit"]:
        data["trading_halted"] = True
    save(data)


def push_exit_signal(market_id: str, reason: str) -> None:
    data = load()
    data["exit_signals"].append({"market_id": market_id, "reason": reason})
    save(data)


def pop_exit_signals() -> list:
    data = load()
    signals = data.get("exit_signals", [])
    data["exit_signals"] = []
    save(data)
    return signals


def log_trade(entry: dict) -> None:
    data = load()
    data["trade_log"].append(entry)
    save(data)
```

- [ ] **Step 4: 跑測試確認通過**

```bash
python -m pytest tests/test_pm_portfolio.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pm_portfolio.py tests/test_pm_portfolio.py
git commit -m "feat: add portfolio state manager with flock"
```

---

## Task 2: Independent Match Probability Engine

**Files:**
- Create: `src/pm_predict.py`
- Test: `tests/test_pm_predict.py`

**Interfaces:**
- Consumes: `player_lambdas(home, away)` from `src/player_strength.py`; `data/elo_ratings_hybrid.json`
- Produces:
  - `match_win_probs(home: str, away: str) -> tuple[float, float, float]`
    返回 `(p_home_win, p_draw, p_away_win)`，全用 ELO + player_lambdas
  - `run_once() -> None` 計算所有即將到來的比賽並寫入 portfolio.json
  - `run_daemon(interval: int = 300) -> None` 持續循環

- [ ] **Step 1: 寫測試**

```python
# tests/test_pm_predict.py
import pytest
from unittest.mock import patch
from src.pm_predict import match_win_probs, _elo_lambdas, _poisson_match_probs


def test_probs_sum_to_one():
    with patch("src.pm_predict.player_lambdas", return_value=(1.5, 1.2)):
        p_h, p_d, p_a = match_win_probs("Brazil", "Germany")
    assert abs(p_h + p_d + p_a - 1.0) < 1e-6


def test_stronger_team_wins_more():
    # Brazil ELO >> Haiti ELO → Brazil should win more
    p_h, _, p_a = match_win_probs("Brazil", "Haiti")
    assert p_h > p_a


def test_elo_lambdas_favors_higher_elo():
    lh, la = _elo_lambdas("Brazil", "Haiti")
    assert lh > la


def test_poisson_probs_sum_to_one():
    p_h, p_d, p_a = _poisson_match_probs(1.5, 0.8)
    assert abs(p_h + p_d + p_a - 1.0) < 1e-6


def test_player_lambda_fallback():
    # When player data unavailable, falls back to ELO
    with patch("src.pm_predict.player_lambdas", return_value=(None, None)):
        p_h, p_d, p_a = match_win_probs("Brazil", "Germany")
    assert abs(p_h + p_d + p_a - 1.0) < 1e-6
```

- [ ] **Step 2: 確認測試失敗**

```bash
python -m pytest tests/test_pm_predict.py -v 2>&1 | head -10
```

- [ ] **Step 3: 實作 pm_predict.py**

```python
# src/pm_predict.py
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from src.config import FOOTBALL_DATA_BASE, BASE_LAMBDA, RANK_DECAY, FIFA_RANKINGS
from src.player_strength import player_lambdas
import src.pm_portfolio as portfolio

ELO_PATH = Path(__file__).parent.parent / "data" / "elo_ratings_hybrid.json"
_elo_cache: dict = {}


def _load_elo() -> dict:
    global _elo_cache
    if not _elo_cache:
        with open(ELO_PATH) as f:
            _elo_cache = json.load(f)
    return _elo_cache


def _elo_lambdas(home: str, away: str) -> tuple[float, float]:
    elo = _load_elo()
    elo_h = elo.get(home, 1500.0)
    elo_a = elo.get(away, 1500.0)
    diff = elo_h - elo_a
    rank_h = FIFA_RANKINGS.get(home, 48)
    rank_a = FIFA_RANKINGS.get(away, 48)
    lh = max(0.3, BASE_LAMBDA * math.exp(RANK_DECAY * (rank_a - rank_h)) * (1 + diff / 800))
    la = max(0.3, BASE_LAMBDA * math.exp(RANK_DECAY * (rank_h - rank_a)) * (1 - diff / 800))
    return round(lh, 3), round(la, 3)


def _poisson_match_probs(lh: float, la: float, max_goals: int = 8) -> tuple[float, float, float]:
    def pois(lam: float, k: int) -> float:
        return (lam ** k) * math.exp(-lam) / math.factorial(k)

    p_home = p_draw = p_away = 0.0
    for h in range(max_goals):
        for a in range(max_goals):
            p = pois(lh, h) * pois(la, a)
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    return p_home, p_draw, p_away


def match_win_probs(home: str, away: str) -> tuple[float, float, float]:
    lh, la = player_lambdas(home, away)
    if lh is None:
        lh, la = _elo_lambdas(home, away)
    return _poisson_match_probs(lh, la)


def _upcoming_fixtures() -> list[dict]:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not key:
        return []
    import requests
    headers = {"X-Auth-Token": key}
    url = f"{FOOTBALL_DATA_BASE}/competitions/2000/matches"
    try:
        r = requests.get(url, headers=headers,
                         params={"status": "SCHEDULED,TIMED"}, timeout=10)
        r.raise_for_status()
        return r.json().get("matches", [])
    except Exception as e:
        print(f"[pm_predict] fixture fetch failed: {e}")
        return []


def run_once() -> None:
    ts = datetime.now(timezone.utc).isoformat()
    fixtures = _upcoming_fixtures()
    match_probs: dict = {}
    for m in fixtures[:20]:
        home = m.get("homeTeam", {}).get("name", "")
        away = m.get("awayTeam", {}).get("name", "")
        mid = str(m.get("id", ""))
        if not home or not away:
            continue
        ph, pd, pa = match_win_probs(home, away)
        cal = portfolio.load()["calibration"]["factor"]
        ph = min(0.99, ph * cal)
        pa = min(0.99, pa * cal)
        pd = max(0.01, 1.0 - ph - pa)
        match_probs[mid] = {
            "home": home, "away": away,
            "p_home_win": round(ph, 4),
            "p_draw": round(pd, 4),
            "p_away_win": round(pa, 4),
        }
    data = portfolio.load()
    data["match_probs"] = match_probs
    data["model_probs_updated_at"] = ts
    portfolio.save(data)
    print(f"[{ts}] pm_predict: wrote {len(match_probs)} match probs")


def run_daemon(interval: int = 300) -> None:
    print(f"[pm_predict] daemon started, interval={interval}s")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[pm_predict] error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()
    if args.daemon:
        run_daemon(args.interval)
    else:
        run_once()
```

- [ ] **Step 4: 跑測試確認通過**

```bash
python -m pytest tests/test_pm_predict.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pm_predict.py tests/test_pm_predict.py
git commit -m "feat: add independent match probability engine (ELO + player strength)"
```

---

## Task 3: EV Scanner Integration

**Files:**
- Modify: `src/pm_ev_scanner.py` lines 265–268（`find_opportunities` 內）

**目標：** 當 `portfolio.json["match_probs"]` 有資料時，用我們的模型機率取代 `peer_median` 作為晉級市場的公允值基準。

- [ ] **Step 1: 寫測試**

```python
# 加入 tests/test_pm_portfolio.py 底部，或新建 tests/test_pm_ev_scanner.py
# tests/test_pm_ev_scanner.py
import json
import pytest
from unittest.mock import patch
from src.pm_ev_scanner import find_opportunities, build_matrix


SAMPLE_STAGE_DATA = {
    "qf": {"Switzerland": 0.50, "Argentina": 0.85, "Brazil": 0.80},
    "sf": {"Switzerland": 0.10, "Argentina": 0.60, "Brazil": 0.55},
    "final": {"Switzerland": 0.05, "Argentina": 0.35, "Brazil": 0.30},
    "winner": {"Switzerland": 0.02, "Argentina": 0.20, "Brazil": 0.18},
}

SAMPLE_MODEL_PROBS = {
    "Switzerland": {"qf": 0.50, "sf": 0.23, "final": 0.10, "winner": 0.04},
}


def test_find_opportunities_uses_model_probs_when_available(tmp_path, monkeypatch):
    import src.pm_portfolio as pf
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    data = pf.load()
    data["model_probs"] = SAMPLE_MODEL_PROBS
    pf.save(data)

    matrix = build_matrix(SAMPLE_STAGE_DATA)
    opps = find_opportunities(matrix, min_ev=0.0)
    swiss_sf = next((o for o in opps if o.team == "Switzerland" and o.to_stage == "sf"), None)
    # fair_value should be model prob 0.23, not peer_median * 0.50
    assert swiss_sf is not None
    assert abs(swiss_sf.fair_value - 0.23) < 0.01


def test_find_opportunities_falls_back_to_peer_median(tmp_path, monkeypatch):
    import src.pm_portfolio as pf
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    # No model_probs set → should still work with peer_median

    matrix = build_matrix(SAMPLE_STAGE_DATA)
    opps = find_opportunities(matrix, min_ev=0.0)
    assert len(opps) > 0
```

- [ ] **Step 2: 確認測試當前行為（test_uses_model_probs 應該失敗）**

```bash
python -m pytest tests/test_pm_ev_scanner.py -v 2>&1 | head -20
```

- [ ] **Step 3: 修改 pm_ev_scanner.py**

在 `find_opportunities()` 函式的第 265–268 行，替換公允值計算邏輯：

找到這段：
```python
            actual_conv  = row["conv"][key]
            peer_med     = _peer_median(matrix, from_s, key, p_from)
            fair_value   = p_from * peer_med
            ev           = fair_value - p_to
```

替換為：
```python
            actual_conv  = row["conv"][key]
            peer_med     = _peer_median(matrix, from_s, key, p_from)
            # 優先用我們的獨立模型機率；無資料時 fallback 到 peer_median
            _mp = _read_model_prob(team, to_s)
            fair_value   = _mp if _mp is not None else p_from * peer_med
            ev           = fair_value - p_to
```

並在 `find_opportunities` 前新增這個 helper（加在 `_peer_median` 後面）：

```python
def _read_model_prob(team: str, stage: str) -> float | None:
    """從 portfolio.json 讀取我們的獨立模型機率。讀取失敗時返回 None。"""
    try:
        import src.pm_portfolio as pf
        model_probs = pf.load().get("model_probs", {})
        return model_probs.get(team, {}).get(stage)
    except Exception:
        return None
```

- [ ] **Step 4: 跑測試確認通過**

```bash
python -m pytest tests/test_pm_ev_scanner.py -v
```
Expected: 2 passed

- [ ] **Step 5: 執行掃描器確認仍正常運作**

```bash
python -m src.pm_ev_scanner --min-ev 0.05 2>&1 | head -30
```
Expected: 正常輸出機會列表（model_probs 為空時走 fallback）

- [ ] **Step 6: 在 pm_ev_scanner.py 中提取 token_id**

`Opportunity` dataclass 需要加入 `token_id` 欄位，讓 pm_trader 下單時可以使用。

在 `pm_ev_scanner.py` 的 `_fetch_stage` 函式中，Gamma API 回應包含 `clobTokenIds`。在 `Opportunity` dataclass 加入欄位：

```python
# 在 Opportunity dataclass 中加入（約第 215 行）
token_id: str = ""   # Polymarket CLOB token ID (YES side)
```

在 `_fetch_stage` 修改回傳，同時回傳 token_ids：
```python
def _fetch_stage(stage: str) -> tuple[dict[str, float], dict[str, str]]:
    # 原有邏輯不變，額外回傳 {team: token_id}
    prices: dict[str, float] = {}
    token_ids: dict[str, str] = {}
    # ... 原有抓取邏輯 ...
    # 在解析市場時加入：
    # clob_ids = market.get("clobTokenIds", [])
    # if clob_ids: token_ids[team] = clob_ids[0]  # YES side
    return prices, token_ids
```

並在 `find_opportunities` 建立 `Opportunity` 時填入 `token_id`。

- [ ] **Step 7: Commit**

```bash
git add src/pm_ev_scanner.py tests/test_pm_ev_scanner.py
git commit -m "feat: ev scanner uses independent model probs + extracts token_ids for trading"
```

---

## Task 4: Live Event Monitor

**Files:**
- Create: `src/pm_monitor.py`
- Test: `tests/test_pm_monitor.py`

**Interfaces:**
- Consumes: `portfolio.json["positions"]`（知道我們在哪些比賽有倉位）
- Produces: `portfolio.json["exit_signals"]`（透過 `push_exit_signal`）
- Produces:
  - `fetch_live_matches() -> list[dict]` 返回 IN_PLAY 比賽
  - `fetch_match_events(fixture_id: int) -> list[dict]` 返回事件列表
  - `detect_exit_triggers(events: list, our_team: str) -> str | None` 返回觸發原因或 None
  - `run_daemon(interval: int = 60) -> None`

- [ ] **Step 1: 寫測試**

```python
# tests/test_pm_monitor.py
import pytest
from src.pm_monitor import detect_exit_triggers, _classify_event


def _make_event(etype: str, team: str, minute: int = 34) -> dict:
    return {"type": etype, "team": {"name": team}, "minute": minute}


def test_red_card_our_team_triggers_exit():
    events = [_make_event("YELLOW_RED_CARD", "Switzerland")]
    result = detect_exit_triggers(events, our_team="Switzerland")
    assert result == "RED_CARD"


def test_red_card_opponent_no_exit():
    events = [_make_event("YELLOW_RED_CARD", "Argentina")]
    result = detect_exit_triggers(events, our_team="Switzerland")
    assert result is None


def test_goal_against_must_win_triggers():
    events = [_make_event("GOAL", "Argentina")]
    result = detect_exit_triggers(events, our_team="Switzerland", must_win=True, score=(0, 1))
    assert result == "GOAL_AGAINST_MUST_WIN"


def test_goal_for_triggers_lock_profit():
    events = [_make_event("GOAL", "Switzerland")]
    result = detect_exit_triggers(events, our_team="Switzerland", score=(1, 0))
    assert result == "LOCK_PROFIT"


def test_no_event_no_trigger():
    events = [_make_event("YELLOW_CARD", "Switzerland")]
    result = detect_exit_triggers(events, our_team="Switzerland")
    assert result is None
```

- [ ] **Step 2: 確認測試失敗**

```bash
python -m pytest tests/test_pm_monitor.py -v 2>&1 | head -10
```

- [ ] **Step 3: 實作 pm_monitor.py**

```python
# src/pm_monitor.py
import os
import time
from datetime import datetime, timezone

import requests

from src.config import FOOTBALL_DATA_BASE
import src.pm_portfolio as portfolio

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
_ESPN_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_live_matches() -> list[dict]:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    headers = {"X-Auth-Token": key}
    try:
        r = requests.get(
            f"{FOOTBALL_DATA_BASE}/competitions/2000/matches",
            headers=headers, params={"status": "IN_PLAY"}, timeout=10,
        )
        r.raise_for_status()
        return r.json().get("matches", [])
    except Exception as e:
        print(f"[pm_monitor] football-data live fetch failed: {e}")
        return _fetch_live_espn()


def _fetch_live_espn() -> list[dict]:
    try:
        r = requests.get(ESPN_SCOREBOARD, headers=_ESPN_HEADERS, timeout=10)
        r.raise_for_status()
        events = r.json().get("events", [])
        live = []
        for ev in events:
            status = ev.get("status", {}).get("type", {}).get("state", "")
            if status == "in":
                comp = ev["competitions"][0]
                live.append({
                    "id": ev["id"],
                    "homeTeam": {"name": comp["competitors"][0]["team"]["displayName"]},
                    "awayTeam": {"name": comp["competitors"][1]["team"]["displayName"]},
                    "_source": "espn",
                })
        return live
    except Exception as e:
        print(f"[pm_monitor] ESPN fallback failed: {e}")
        return []


def fetch_match_events(fixture_id: int) -> list[dict]:
    key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    headers = {"X-Auth-Token": key}
    try:
        r = requests.get(
            f"{FOOTBALL_DATA_BASE}/matches/{fixture_id}",
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        return r.json().get("bookings", []) + r.json().get("goals", [])
    except Exception as e:
        print(f"[pm_monitor] event fetch failed for {fixture_id}: {e}")
        return []


def _classify_event(event: dict) -> str:
    return event.get("type", "UNKNOWN")


def detect_exit_triggers(
    events: list,
    our_team: str,
    must_win: bool = False,
    score: tuple = (0, 0),
) -> str | None:
    for ev in events:
        etype = _classify_event(ev)
        team_name = ev.get("team", {}).get("name", "")
        is_ours = team_name == our_team

        if etype in ("YELLOW_RED_CARD", "RED_CARD") and is_ours:
            return "RED_CARD"
        if etype == "GOAL":
            if not is_ours and must_win and score[0] <= score[1]:
                return "GOAL_AGAINST_MUST_WIN"
            if is_ours and score[0] > score[1]:
                return "LOCK_PROFIT"
    return None


def run_once(positions: list | None = None) -> None:
    if positions is None:
        positions = portfolio.load().get("positions", [])
    live = fetch_live_matches()
    if not live:
        return

    live_ids = {str(m.get("id", "")): m for m in live}
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

    for pos in positions:
        fixture_id = pos.get("fixture_id")
        if not fixture_id or str(fixture_id) not in live_ids:
            continue
        match = live_ids[str(fixture_id)]
        events = fetch_match_events(fixture_id)
        our_team = pos.get("team", "")
        trigger = detect_exit_triggers(events, our_team)
        if trigger:
            print(f"[{ts}] pm_monitor: EXIT signal {trigger} for {our_team}")
            portfolio.push_exit_signal(pos["market_id"], trigger)


def run_daemon(interval: int = 60) -> None:
    print(f"[pm_monitor] daemon started, interval={interval}s")
    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[pm_monitor] error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()
    if args.daemon:
        run_daemon(args.interval)
    else:
        run_once()
```

- [ ] **Step 4: 跑測試確認通過**

```bash
python -m pytest tests/test_pm_monitor.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/pm_monitor.py tests/test_pm_monitor.py
git commit -m "feat: add live event monitor with football-data + ESPN fallback"
```

---

## Task 5: Kelly Sizing + CLOB Execution Engine

**Files:**
- Create: `src/pm_trader.py`
- Test: `tests/test_pm_trader.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `portfolio.json["match_probs"]`, `pm_portfolio.*`
- Produces:
  - `kelly_size(our_prob: float, market_price: float, bankroll: float) -> float`
  - `place_limit_order(client, token_id: str, size_usd: float, limit_price: float) -> dict`
  - `market_sell(client, token_id: str, size_usd: float) -> dict`
  - `scan_and_trade(client) -> None`
  - `handle_exits(client) -> None`
  - `run_daemon(interval: int = 300) -> None`

- [ ] **Step 1: 安裝依賴**

```bash
pip install git+https://github.com/Polymarket/py-clob-client-v2 python-dotenv
```

在 requirements.txt 加入：
```
python-dotenv==1.0.1
```
（py-clob-client-v2 從 GitHub 安裝，不在 PyPI）

- [ ] **Step 2: 寫測試**

```python
# tests/test_pm_trader.py
import pytest
from unittest.mock import MagicMock, patch
from src.pm_trader import kelly_size, _ev, _build_client


def test_kelly_zero_ev_returns_zero():
    assert kelly_size(our_prob=0.50, market_price=0.50, bankroll=500.0) == 0.0


def test_kelly_positive_ev():
    size = kelly_size(our_prob=0.65, market_price=0.50, bankroll=500.0)
    assert 0 < size <= 25.0


def test_kelly_respects_max_bet():
    # Even with huge edge, never exceed $25
    size = kelly_size(our_prob=0.99, market_price=0.10, bankroll=500.0)
    assert size <= 25.0


def test_kelly_negative_ev_returns_zero():
    size = kelly_size(our_prob=0.30, market_price=0.50, bankroll=500.0)
    assert size == 0.0


def test_ev_calculation():
    assert _ev(our_prob=0.60, market_price=0.50) == pytest.approx(0.10)


def test_build_client_requires_key(monkeypatch):
    monkeypatch.delenv("WALLET_PRIVATE_KEY", raising=False)
    with pytest.raises(ValueError, match="WALLET_PRIVATE_KEY"):
        _build_client()
```

- [ ] **Step 3: 確認測試失敗**

```bash
python -m pytest tests/test_pm_trader.py -v 2>&1 | head -10
```

- [ ] **Step 4: 實作 pm_trader.py**

```python
# src/pm_trader.py
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

import src.pm_portfolio as portfolio

MAX_BET = 25.0
MAX_POSITIONS = 4
MIN_EV = 0.05
MIN_ROI = 0.20
ORDER_TIMEOUT_MIN = 10
CLOB_HOST = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137


def _ev(our_prob: float, market_price: float) -> float:
    return our_prob - market_price


def kelly_size(our_prob: float, market_price: float, bankroll: float) -> float:
    ev = _ev(our_prob, market_price)
    if ev <= 0:
        return 0.0
    b = (1.0 / market_price) - 1.0
    q = 1.0 - our_prob
    kelly = (our_prob * b - q) / b
    half_kelly = kelly * 0.5
    return round(min(half_kelly * bankroll, bankroll * 0.05, MAX_BET), 2)


def _build_client():
    key = os.environ.get("WALLET_PRIVATE_KEY", "")
    if not key:
        raise ValueError("WALLET_PRIVATE_KEY not set in environment")
    try:
        from py_clob_client.client import ClobClient
        return ClobClient(host=CLOB_HOST, key=key, chain_id=POLYGON_CHAIN_ID)
    except ImportError:
        raise ImportError("py-clob-client-v2 not installed. Run: pip install git+https://github.com/Polymarket/py-clob-client-v2")


def place_limit_order(client, token_id: str, size_usd: float, limit_price: float) -> dict:
    from py_clob_client.clob_types import OrderArgs, OrderType, Side
    order = client.create_order(OrderArgs(
        token_id=token_id,
        price=limit_price,
        size=size_usd,
        side=Side.BUY,
    ))
    return client.post_order(order, OrderType.GTC)


def market_sell(client, token_id: str, size_usd: float) -> dict:
    from py_clob_client.clob_types import OrderArgs, OrderType, Side
    order = client.create_order(OrderArgs(
        token_id=token_id,
        price=0.01,   # 極低限價 = 實際上的市價賣出
        size=size_usd,
        side=Side.SELL,
    ))
    return client.post_order(order, OrderType.FOK)  # Fill-or-Kill


def handle_exits(client) -> None:
    signals = portfolio.pop_exit_signals()
    for sig in signals:
        pos = portfolio.remove_position(sig["market_id"])
        if not pos:
            continue
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] EXIT {pos['team']} reason={sig['reason']} size=${pos['size_usd']}")
        try:
            market_sell(client, pos["token_id"], pos["size_usd"])
            portfolio.update_pnl(0.0)  # PnL 在 Polymarket 結算後確認
            portfolio.log_trade({
                "type": "EXIT", "team": pos["team"],
                "reason": sig["reason"], "time": ts,
            })
        except Exception as e:
            print(f"[{ts}] EXIT FAILED for {pos['team']}: {e}")
            portfolio.add_position(pos)  # 放回去


def scan_and_trade(client) -> None:
    if portfolio.is_halted():
        print("[pm_trader] trading halted (daily loss limit)")
        return

    data = portfolio.load()
    if len(data["positions"]) >= MAX_POSITIONS:
        return

    match_probs = data.get("match_probs", {})
    bankroll = data["bankroll"]

    try:
        from src.pm_ev_scanner import fetch_all, build_matrix, find_opportunities
        stage_data = fetch_all()
        matrix = build_matrix(stage_data)
        opps = find_opportunities(matrix, min_ev=MIN_EV)
    except Exception as e:
        print(f"[pm_trader] scanner error: {e}")
        return

    existing_keys = {(p["team"], p.get("stage")) for p in data["positions"]}
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

    for opp in opps:
        if opp.ev < MIN_EV:
            continue
        if opp.ev_roi < MIN_ROI:
            continue
        if (opp.team, opp.to_stage) in existing_keys:
            continue
        if len(data["positions"]) >= MAX_POSITIONS:
            break

        size = kelly_size(opp.fair_value, opp.p_to, bankroll)
        if size < 1.0:
            continue

        limit_price = round((opp.p_to + opp.fair_value) / 2, 4)
        print(f"[{ts}] BUY {opp.team} [{opp.label}] size=${size} limit={limit_price}")

        try:
            resp = place_limit_order(client, token_id="", size_usd=size, limit_price=limit_price)
            order_id = resp.get("orderID", "")
            pos = {
                "market_id": f"{opp.team}:{opp.to_stage}",
                "token_id": "",
                "team": opp.team,
                "stage": opp.to_stage,
                "size_usd": size,
                "entry_price": limit_price,
                "our_prob": opp.fair_value,
                "entry_time": ts,
                "order_id": order_id,
                "fixture_id": None,
            }
            portfolio.add_position(pos)
            portfolio.log_trade({"type": "BUY", **pos})
            existing_keys.add((opp.team, opp.to_stage))
        except Exception as e:
            print(f"[{ts}] ORDER FAILED {opp.team}: {e}")


def run_daemon(interval: int = 300) -> None:
    print(f"[pm_trader] daemon started, interval={interval}s")
    client = _build_client()
    while True:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        try:
            handle_exits(client)
            scan_and_trade(client)
        except Exception as e:
            print(f"[{ts}] pm_trader loop error: {e}")
        print(f"[{ts}] bankroll=${portfolio.get_bankroll():.2f}  next check in {interval}s")
        time.sleep(interval)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()
    if args.daemon:
        run_daemon(args.interval)
    else:
        client = _build_client()
        handle_exits(client)
        scan_and_trade(client)
```

- [ ] **Step 5: 跑測試確認通過**

```bash
python -m pytest tests/test_pm_trader.py -v
```
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/pm_trader.py tests/test_pm_trader.py requirements.txt
git commit -m "feat: add Kelly sizing and CLOB execution engine"
```

---

## Task 6: Calibration Loop

**Files:**
- Modify: `src/pm_portfolio.py`（新增 3 個函式）
- Test: 加入 `tests/test_pm_portfolio.py`

**目標：** 每 10 筆交易結算後，用 isotonic regression 擬合校準係數，讓 pm_predict 的機率越跑越準。

- [ ] **Step 1: 新增測試到 test_pm_portfolio.py**

```python
# 加到 tests/test_pm_portfolio.py 尾端

from src.pm_portfolio import record_settled_trade, get_calibration_factor


def test_calibration_factor_default_is_one(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    assert get_calibration_factor() == pytest.approx(1.0)


def test_calibration_updates_after_ten_trades(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    # 10 trades: predicted 0.7 each, but all lost (actual=0)
    for _ in range(10):
        record_settled_trade(predicted_prob=0.7, actual_outcome=0)
    # Factor should be less than 1.0 (we were overconfident)
    assert get_calibration_factor() < 1.0
```

- [ ] **Step 2: 確認測試失敗**

```bash
python -m pytest tests/test_pm_portfolio.py::test_calibration_factor_default_is_one -v 2>&1 | head -10
```

- [ ] **Step 3: 在 pm_portfolio.py 新增校準函式**

```python
# 在 pm_portfolio.py 尾端加入

from scipy.stats import pearsonr
import numpy as np


def record_settled_trade(predicted_prob: float, actual_outcome: int) -> None:
    """actual_outcome: 1 = 贏, 0 = 輸"""
    data = load()
    cal = data["calibration"]
    cal["history"].append({"pred": predicted_prob, "actual": actual_outcome})
    cal["n_settled"] += 1
    if cal["n_settled"] % 10 == 0:
        _refit_calibration(data)
    else:
        save(data)


def _refit_calibration(data: dict) -> None:
    from scipy.interpolate import PchipInterpolator
    history = data["calibration"]["history"]
    if len(history) < 5:
        return
    preds = np.array([h["pred"] for h in history])
    actuals = np.array([h["actual"] for h in history], dtype=float)
    # Simple linear calibration: slope of actual vs predicted
    if preds.std() < 1e-6:
        return
    slope = np.cov(preds, actuals)[0, 1] / np.var(preds)
    factor = max(0.5, min(1.5, slope))
    data["calibration"]["factor"] = round(float(factor), 4)
    save(data)


def get_calibration_factor() -> float:
    return load()["calibration"]["factor"]
```

- [ ] **Step 4: 跑測試確認通過**

```bash
python -m pytest tests/test_pm_portfolio.py -v
```
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/pm_portfolio.py tests/test_pm_portfolio.py
git commit -m "feat: add calibration loop with linear regression factor"
```

---

## Task 7: End-to-End Wiring + Smoke Test

**Files:**
- Create: `run_trading.sh`（啟動腳本）
- Test: 手動 smoke test

- [ ] **Step 1: 建立啟動腳本**

```bash
# run_trading.sh
#!/bin/bash
set -e
export $(cat .env | grep -v '^#' | xargs)

echo "=== Polymarket Trading Bot ==="
echo "Wallet: $WALLET_ADDRESS"
echo "Bankroll: $BANKROLL"
echo ""

# 背景啟動 daemon processes
python -m src.pm_predict --daemon --interval 300 &
PID_PREDICT=$!
echo "pm_predict PID=$PID_PREDICT"

python -m src.pm_monitor --daemon --interval 60 &
PID_MONITOR=$!
echo "pm_monitor PID=$PID_MONITOR"

# 清理函式
cleanup() {
    echo "Shutting down..."
    kill $PID_PREDICT $PID_MONITOR 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# 前台跑 trader（主迴圈）
python -m src.pm_trader --daemon --interval 300
```

```bash
chmod +x run_trading.sh
```

- [ ] **Step 2: Smoke test（不實際下單）**

```bash
# 驗證 pm_portfolio 初始化
python3 -c "
import src.pm_portfolio as pf
data = pf.load()
print('bankroll:', data['bankroll'])
print('positions:', data['positions'])
print('halted:', data['trading_halted'])
print('OK')
"
```
Expected:
```
bankroll: 500.0
positions: []
halted: False
OK
```

- [ ] **Step 3: 驗證 pm_predict 可執行**

```bash
python -m src.pm_predict
```
Expected: `[timestamp] pm_predict: wrote N match probs`（N 可能為 0 若無 API key）

- [ ] **Step 4: 驗證 pm_ev_scanner 仍正常**

```bash
python -m src.pm_ev_scanner --min-ev 0.05 2>&1 | head -15
```
Expected: 正常列出機會

- [ ] **Step 5: 跑全部測試確認無回歸**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: 所有原有測試 + 新測試全部 pass

- [ ] **Step 6: 最終 commit**

```bash
git add run_trading.sh
git commit -m "feat: complete polymarket trading bot - portfolio, predict, monitor, trader, calibration"
```

---

## 上線前 Checklist

在 `.env` 確認以下都已填入：
```
WALLET_PRIVATE_KEY=<已生成>
WALLET_ADDRESS=0x3b805FE536DF867D86Fa925E8515FA8171B2c8e9
FOOTBALL_DATA_API_KEY=<從 football-data.org 取得>
BANKROLL=500.0
```

等待你轉入 USDC + MATIC 到錢包地址後，執行：
```bash
./run_trading.sh
```
