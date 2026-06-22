# 2026 World Cup Prediction System — Design Spec
_Date: 2026-06-22_

## 1. Goal

Build a prediction system for the 2026 FIFA World Cup focused on **Asian Handicap (AH)** and **Over/Under (O/U)** markets. The system must:
- Auto-update daily after matches complete
- Display results via GitHub Pages (static HTML)
- Backtest predictions against actual results and self-correct model weights
- Support retrospective (復盤) analysis identifying why predictions failed

---

## 2. Architecture

```
GitHub Actions (cron)
    ↓  runs daily after matches
Python pipeline
    ├── fetch_data.py       → football-data.org + The Odds API + Polymarket
    ├── predict.py          → Poisson model + feature scoring
    ├── backtest.py         → compare predictions vs results, update calibration.json
    └── render.py           → generate static HTML report
    ↓  commits output
data/
    matches/YYYY-MM-DD.json
    predictions/YYYY-MM-DD.json
    backtest/calibration.json
docs/
    index.html              → GitHub Pages dashboard
```

**Hosting:** GitHub Actions (free) + GitHub Pages (free). No external server required.

---

## 3. Data Sources

| Type | Source | Notes |
|---|---|---|
| Match scores, lineups | football-data.org v4 (free) | 10 req/min limit |
| AH + O/U odds | The Odds API (free, 500/month) | snapshot at kickoff |
| Prediction market | Polymarket Gamma API (public) | implied win probabilities |
| Historical odds (backtest) | OddsPortal (scraper fallback) | only if API quota exhausted |

Data is stored as daily JSON snapshots. Git history = complete audit trail.

---

## 4. Feature Set

### 4a. Technical Stats (per team, rolling 5-match window)
- Goals scored / conceded
- xG / xGA (expected goals — more stable than actuals)
- Shots, shots on target, shot quality
- Possession %, pass accuracy
- Corners earned / conceded
- Fouls, yellow/red cards (discipline profile)
- PPDA (passes per defensive action — pressing intensity)

### 4b. Style Classification (auto-labeled)
- High-press / Low-block / Possession / Set-piece-dependent
- Cross-validated against AH line movement

### 4c. Psychological / Situational Factors
- `must_win`: bool — team is eliminated if they don't win this match
- `safe_draw`: bool — a draw is sufficient to advance
- `dead_rubber`: bool — already eliminated, result irrelevant
- `tournament_incentive_score`: composite score of motivation to attack (0–1)
- Days rest since last match
- Win/loss streak momentum

### 4d. Squad Health
- Key player absences (injury / suspension)
- Squad average age + age-decay factor (recent 12-month vs 24-month form ratio)
- `league_level_adjusted_elo`: player-weighted team strength using club league tier

### 4e. Context / Environment
- Venue altitude, average temperature (climate mismatch vs team origin)
- Travel distance since last match
- Crowd composition (neutral / partial home support)

### 4f. Market Intelligence (most predictive)
- AH line movement from open to kickoff (direction + magnitude)
- O/U line movement
- Polymarket implied probability vs bookmaker implied probability (gap = edge signal)
- `sharp_money_signal`: line moved against public betting volume

---

## 5. Prediction Model

**Step 1 — Poisson Base**
Estimate each team's expected goals (λ_home, λ_away) using Dixon-Coles Poisson model fit on historical World Cup + qualifying data.

**Step 2 — Feature Adjustments**
Apply multiplicative corrections from the feature set:
- `tournament_incentive_score` adjusts λ upward for must-win teams
- `climate_mismatch` applies a small λ penalty
- `squad_age_decay` reduces λ for over-the-hill squads

**Step 3 — Market Calibration**
Use `sharp_money_signal` as a Bayesian update. If the market moved significantly against a team, reduce their predicted win probability by a calibrated factor (updated weekly via backtest).

**Step 4 — Output**
For each match:
```json
{
  "match": "Spain vs Morocco",
  "date": "2026-06-25",
  "ah_prediction": "Morocco +0.5",
  "ah_confidence": 62,
  "ou_prediction": "Under 2.5",
  "ou_confidence": 58,
  "model_version": "v1.3",
  "key_factors": ["must_win for Morocco", "Spain resting starters", "sharp line move to Morocco"]
}
```

---

## 6. Backtest & Self-Correction (復盤模組)

After each match day:
1. Compare `predictions/YYYY-MM-DD.json` vs actual results
2. Compute **Brier Score** per prediction category (AH / O/U)
3. Log to `backtest/calibration.json`:
   - Feature weights for each failed prediction
   - Match context (must_win? fatigue? upset?)
4. Weekly: re-fit calibration coefficients using all logged data
5. Flag high-error matches for manual review in the dashboard (red-highlighted)

**Brier Score threshold:** If rolling 7-day score > 0.25, trigger a weight reset to default and alert in dashboard.

---

## 7. Gaps Identified from 2026 WC Data (June 11–22)

Real match data revealed these blind spots not covered by standard models:

| Gap | Example | Fix |
|---|---|---|
| New format incentive (8 best 3rd-place advance) | Spain 0-0 Cape Verde (tactical draw) | `tournament_incentive_score` |
| Old squad decay | Croatia 0pts, Uruguay 1pt | `squad_age_decay` |
| Rising minor nation strength | DR Congo 1-1 Portugal | `league_level_adjusted_elo` |
| Climate/travel mismatch | Multiple US/Mexico/Canada venues | `climate_mismatch` |

---

## 8. Dashboard (GitHub Pages)

Static HTML generated by `render.py` using Plotly charts embedded inline.

**Pages:**
- `index.html` — Today's predictions with confidence bars
- `results.html` — Historical predictions vs actuals (color-coded)
- `calibration.html` — Brier Score trend, feature weight history
- `postmortem.html` — Auto-generated 復盤 for high-error matches

**Auto-deploy:** GitHub Actions pushes to `gh-pages` branch after each pipeline run.

---

## 9. GitHub Actions Cron Schedule

```yaml
# Runs at 06:00 UTC daily (after most matches end)
on:
  schedule:
    - cron: '0 6 * * *'
  workflow_dispatch:  # manual trigger also supported
```

---

## 10. Repo Structure

```
worldcup_by-claude-code/
├── .github/workflows/daily.yml
├── data/
│   ├── matches/
│   ├── predictions/
│   └── backtest/calibration.json
├── src/
│   ├── fetch_data.py
│   ├── predict.py
│   ├── backtest.py
│   └── render.py
├── docs/           ← GitHub Pages root
│   ├── index.html
│   ├── results.html
│   ├── calibration.html
│   └── postmortem.html
└── requirements.txt
```
