"""
風控員：將 EV 機會轉換為 Kelly 建議部位
"""

from dataclasses import dataclass
from typing import Optional

# 相關性分組：同組總曝險上限 max_group_pct（預設 10%）
CORR_GROUPS: dict[str, list[str]] = {
    "CONCACAF": ["USA", "United States", "Mexico", "Canada"],
    "CONMEBOL": ["Argentina", "Brazil", "Colombia", "Uruguay", "Ecuador", "Chile"],
    "UEFA_BIG": ["France", "Spain", "Germany", "England", "Portugal"],
    "UEFA_MID": ["Switzerland", "Belgium", "Netherlands", "Croatia", "Austria"],
    "AFRICA":   ["Morocco", "Senegal", "Nigeria", "Ghana"],
    "ASIA":     ["Japan", "South Korea", "Australia"],
}


@dataclass
class SizedBet:
    team:       str
    label:      str
    token_id:   str
    price:      float   # 建議出價（suggested_price 或 p_to）
    size_usdc:  float
    ev_roi:     float
    fair_value: float


def _kelly(ev: float, p_to: float, frac: float = 0.50) -> float:
    """1/2 Kelly: f = EV / (1 - p_to)"""
    if p_to >= 1.0 or ev <= 0:
        return 0.0
    return ev / (1 - p_to) * frac


def _get_group(team: str) -> Optional[str]:
    t = team.lower()
    for grp, members in CORR_GROUPS.items():
        if any(m.lower() in t or t in m.lower() for m in members):
            return grp
    return None


def size_opportunities(
    opps:               list,
    bankroll:           float,
    max_bet_pct:        float = 0.05,
    max_total_pct:      float = 0.25,
    max_group_pct:      float = 0.10,
    min_size:           float = 12.0,
    initial_group_used: Optional[dict] = None,
    initial_total:      float = 0.0,
) -> list[SizedBet]:
    buys = sorted([o for o in opps if o.ev > 0], key=lambda o: o.ev_roi, reverse=True)
    bets = []
    total = initial_total
    group_used: dict[str, float] = dict(initial_group_used or {})

    for o in buys:
        if total >= bankroll * max_total_pct:
            break
        grp       = _get_group(o.team)
        grp_total = group_used.get(grp, 0.0) if grp else 0.0
        raw       = bankroll * _kelly(o.ev, o.p_to)
        group_cap = bankroll * max_group_pct - grp_total if grp else float("inf")
        size      = min(raw, bankroll * max_bet_pct, bankroll * max_total_pct - total, group_cap)
        if size < min_size:
            continue
        bets.append(SizedBet(
            team=o.team,
            label=o.label,
            token_id=o.token_id,
            price=o.suggested_price if o.suggested_price > 0 else o.p_to,
            size_usdc=round(size, 2),
            ev_roi=o.ev_roi,
            fair_value=o.fair_value,
        ))
        total += size
        if grp:
            group_used[grp] = grp_total + size

    return bets
