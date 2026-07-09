# Polymarket 自動交易系統設計文件

**日期：** 2026-06-28
**起始資金：** $500 USDC
**錢包地址：** `0x3b805FE536DF867D86Fa925E8515FA8171B2c8e9`（私鑰存 `.env`）
**目標市場：** Polymarket 世界盃晉級市場（八強/四強/決賽）+ 單場勝負

---

## 一、系統目標

在 Polymarket 上以 **獨立機率模型** 對抗人類交易者，找出定價錯誤的機會，透過 EV 過濾 + Kelly 倉位管理 + 即時事件監聽出場，讓 $500 本金在世界盃剩餘賽事中穩定成長。

核心優勢：人類對條件機率和錦標賽組合數學的計算能力弱，這是我們的 edge。

---

## 二、架構概覽（方案 B：三模組 + 共享狀態）

```
src/pm_predict.py    ← 獨立機率引擎（純 ELO + 球員強度，零市場賠率）
src/pm_trader.py     ← Kelly 計算 + CLOB 下單 + 倉位管理
src/pm_monitor.py    ← 即時事件監聽 → 觸發重算 / 出場
data/portfolio.json  ← 共享狀態（持倉 / 資金 / 校準紀錄）

現有不動：
src/pm_ev_scanner.py ← 改為讀 portfolio.json["model_probs"] 作為基準
src/predict.py       ← 維持現有每日預測用途不變
```

三個 process 各自常駐，透過 `portfolio.json` 溝通，可個別重啟。

---

## 三、pm_predict.py — 獨立機率引擎

### 設計原則
完全不碰市場賠率。強度來源只有：
- `data/elo_ratings_hybrid.json`（ELO 評分）
- `src/player_strength.py`（球員強度，首次整合進交易信號）
- 組內情境：休息天數、晉級壓力（safe_draw / must_win）

### 輸出
每 5 分鐘寫入 `portfolio.json["model_probs"]`：
```json
{
  "model_probs": {
    "Switzerland": {"qf": 0.51, "sf": 0.23, "final": 0.10, "winner": 0.04},
    "Colombia":    {"qf": 0.68, "sf": 0.31, "final": 0.14, "winner": 0.06}
  },
  "match_probs": {
    "537414": {"home_win": 0.32, "draw": 0.28, "away_win": 0.40}
  },
  "updated_at": "2026-06-28T14:00:00Z"
}
```

### Monte Carlo
- 10,000 次模擬剩餘賽事
- 每次模擬以我們的 Poisson 模型抽樣比賽結果
- 統計每隊各階段出現次數 → 晉級機率
- 完全獨立於 Polymarket 當前價格

### 自我修正（校準迴路）
每 10 筆交易結算後：
1. 比對預測機率 vs 實際結果
2. 分析偏差維度（ELO 差距段、賽段、信心區間）
3. 用 isotonic regression 擬合校準係數
4. 下次預測自動套用校準

---

## 四、pm_trader.py — 執行引擎

### 依賴
```
pip install git+https://github.com/Polymarket/py-clob-client-v2 python-dotenv
```

### 初始化
```python
client = ClobClient(
    host="https://clob.polymarket.com",
    key=os.environ["WALLET_PRIVATE_KEY"],
    chain_id=137,
)
```

### Kelly 倉位計算
```python
def kelly_size(our_prob, market_price, bankroll):
    b = (1 / market_price) - 1
    kelly = (our_prob * b - (1 - our_prob)) / b
    half_kelly = kelly * 0.5
    return min(half_kelly * bankroll, bankroll * 0.05, 25.0)
```

### 進場流程
1. 讀 `portfolio.json["model_probs"]` + Polymarket 即時價格
2. 計算 EV = `our_prob - market_price`
3. EV > 5% 且 ROI > 20% → 計算 Kelly 倉位
4. 抓 CLOB orderbook，掛限價單於 `(best_bid + best_ask) / 2`
5. 等待 10 分鐘：成交 → 寫入持倉；未成交 → 取消

### 出場流程
- **正常出場（鎖利）**：market_price 已追上 our_prob → 限價賣出
- **緊急出場（止損）**：事件觸發 EV 變負 → 市價賣出（優先速度）

### 風控護欄

| 規則 | 值 |
|------|-----|
| 單筆上限 | $25（5% 本金） |
| 同時持倉上限 | 4 筆 |
| 最大曝險 | $100（20% 本金） |
| 單日虧損上限 | $75（觸發後暫停當日交易） |
| 最低 EV 門檻 | 5% |
| 最低 ROI 門檻 | 20% |

---

## 五、pm_monitor.py — 即時事件監聽

### 資料來源
**主要：football-data.org**（已整合，免費，10 req/min）
- `/competitions/2000/matches?status=IN_PLAY` — 即時進球 / 紅牌 / 比分
- `/matches/{id}` — 單場詳細事件

**備援：ESPN Scoreboard API**（完全免費，無需 key，已整合）
- `site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard`
- 事件異常時交叉確認

兩者合計：~60 秒更新頻率，足夠晉級市場出場需求。

### 輪詢策略

| 時機 | 頻率 | 動作 |
|------|------|------|
| 賽前 60 分鐘 | 每 5 分鐘 | 抓首發，主力缺陣 → 取消掛單 |
| 比賽進行中 | 每 30 秒 | 抓事件，觸發重算 |
| 比賽結束後 | 一次 | pm_monitor 偵測 FINISHED 狀態 → 通知 pm_trader 結算 → 更新校準 |

### 事件優先級

| 優先級 | 事件 | 動作 |
|--------|------|------|
| 🔴 緊急 | 我方紅牌 | 立即市價出場 |
| 🔴 緊急 | 必贏場落後進球 | 立即重算，大概率出場 |
| 🟡 警告 | 核心球員傷停 | 重算，視 EV 決定 |
| 🟢 機會 | 我方領先進球 | 鎖利：出場 50% |
| 🟢 機會 | 同組結果有利 | 重算，考慮加碼 |

---

## 六、portfolio.json 結構

```json
{
  "bankroll": 500.0,
  "daily_pnl": 0.0,
  "daily_loss_limit": 75.0,
  "trading_halted": false,
  "positions": [
    {
      "market_id": "...",
      "token_id": "...",
      "team": "Switzerland",
      "stage": "sf",
      "size_usd": 20.0,
      "entry_price": 0.075,
      "our_prob": 0.128,
      "entry_time": "2026-06-28T14:00:00Z",
      "fixture_id": 537414
    }
  ],
  "model_probs": {},
  "match_probs": {},
  "trade_log": [],
  "calibration": {
    "n_settled": 0,
    "factor": 1.0,
    "history": []
  }
}
```

---

## 七、啟動方式

```bash
# 複製環境變數
cp .env.example .env  # 填入 API_FOOTBALL_KEY

# 安裝依賴
pip install py-clob-client-v2 python-dotenv requests web3

# 各自背景啟動
python -m src.pm_predict --daemon &
python -m src.pm_monitor --daemon &
python -m src.pm_trader          # 前台主迴圈，可看即時狀態
```

---

## 八、外部依賴

| 服務 | 用途 | 費用 |
|------|------|------|
| Polymarket CLOB API | 下單 / 查帳 | 免費 |
| Polygon RPC | 交易上鏈 | 免費（公共節點） |
| MATIC | Gas 費 | ~$2（一次性） |
| USDC on Polygon | 交易本金 | $500 |
| football-data.org | 即時事件（主要） | 免費（已有 key，10 req/min） |
| ESPN Scoreboard API | 即時事件（備援） | 完全免費，無需 key |

---

## 九、風險與限制

- **樣本小**：世界盃剩餘約 30 場，校準數據有限
- **流動性**：部分市場可能掛單難成交，需設逾時取消
- **Polymarket USDC**：需確認平台使用 USDC（非 USDT），轉帳時注意
- **API-Football 免費層**：每日 100 次請求，比賽日需升級計劃
