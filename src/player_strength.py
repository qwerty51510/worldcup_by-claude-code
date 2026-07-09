"""
Player-based team strength estimation for WC 2026.
Data: risingtransfers/world-cup-2026-data (squads.csv + per90_stats.csv).
Method:
  - FW/MF: offensive rating * league_quality  → attack strength
  - DF/GK: defensive rating * league_quality  → defense strength
  - Weighted by sqrt(minutes) to favour regular starters
  - Normalize both dimensions to WC average = 1.0
"""
import csv
import math
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).parent.parent / "data" / "player_data"

# ── League quality tiers ────────────────────────────────────────────────────
# 1.00 = best measurable quality (Big 5 Europe)
# Uses blended UEFA/SPI-style coefficients, calibrated to scoring rate vs WC

_LEAGUE_QUALITY: dict = {
    # Tier 1 – Big 5
    "Premier League":          1.00,
    "La Liga":                 1.00,
    "Bundesliga":              0.98,
    "Serie A":                 0.97,
    "Ligue 1":                 0.95,
    # Tier 2 – Strong European
    "Eredivisie":              0.87,
    "Primeira Liga":           0.85,   # Portugal
    "Belgian Pro League":      0.83,
    "Super Lig":               0.82,   # Turkey
    "Scottish Premiership":    0.79,
    "Austrian Bundesliga":     0.76,
    "Czech First League":      0.75,
    "Swiss Super League":      0.75,
    "Greek Super League":      0.74,
    "Russian Premier League":  0.74,
    "Ukrainian Premier":       0.73,
    "Danish Superliga":        0.76,
    "Norwegian Eliteserien":   0.74,
    "Swedish Allsvenskan":     0.73,
    "Israeli Premier":         0.71,
    "Croatian First":          0.70,
    "Romanian Liga I":         0.69,
    "Cypriot First Division":  0.68,
    # Tier 3 – Americas / Asia
    "Brasileirao":             0.74,
    "Argentine Primera":       0.72,
    "Chilean Primera":         0.65,
    "Colombian Primera":       0.65,
    "Liga MX":                 0.70,
    "MLS":                     0.68,
    "Canadian Premier":        0.60,
    "J1 League":               0.68,
    "K League 1":              0.65,
    "Chinese Super League":    0.62,
    "Saudi Pro League":        0.68,
    "Qatar Stars League":      0.60,
    "UAE Pro League":          0.60,
    "Egyptian Premier":        0.62,
    "South African PSL":       0.60,
    "Jordanian Pro League":    0.55,
    # Tier 4 – Other
    "default":                 0.52,
}

# ── Club → League mapping ───────────────────────────────────────────────────
# Only need the clubs that appear in squads.csv; others fall to "default"

_CLUB_LEAGUE: dict = {
    # ── Premier League ──────────────────────────────────────────────────────
    "Arsenal": "Premier League", "Chelsea": "Premier League",
    "Liverpool": "Premier League", "Manchester City": "Premier League",
    "Manchester United": "Premier League", "Tottenham Hotspur": "Premier League",
    "Newcastle United": "Premier League", "Aston Villa": "Premier League",
    "Brighton & Hove Albion": "Premier League", "West Ham United": "Premier League",
    "Crystal Palace": "Premier League", "Everton": "Premier League",
    "Fulham": "Premier League", "Brentford": "Premier League",
    "Wolverhampton Wanderers": "Premier League", "AFC Bournemouth": "Premier League",
    "Nottingham Forest": "Premier League", "Leicester City": "Premier League",
    "Ipswich Town": "Premier League", "Southampton": "Premier League",
    "Sunderland": "Premier League",  # promoted
    # ── La Liga ─────────────────────────────────────────────────────────────
    "Real Madrid": "La Liga", "FC Barcelona": "La Liga",
    "Atlético Madrid": "La Liga", "Sevilla": "La Liga",
    "Real Sociedad": "La Liga", "Villarreal": "La Liga",
    "Athletic Club": "La Liga", "Real Betis": "La Liga",
    "Valencia": "La Liga", "Celta Vigo": "La Liga",
    "Osasuna": "La Liga", "Getafe": "La Liga",
    "Girona": "La Liga", "Mallorca": "La Liga",
    "Rayo Vallecano": "La Liga", "Alaves": "La Liga",
    "Las Palmas": "La Liga", "Leganés": "La Liga",
    # ── Bundesliga ──────────────────────────────────────────────────────────
    "FC Bayern München": "Bundesliga", "Borussia Dortmund": "Bundesliga",
    "RB Leipzig": "Bundesliga", "Bayer 04 Leverkusen": "Bundesliga",
    "Eintracht Frankfurt": "Bundesliga", "VfB Stuttgart": "Bundesliga",
    "TSG Hoffenheim": "Bundesliga", "SC Freiburg": "Bundesliga",
    "Borussia Mönchengladbach": "Bundesliga", "Werder Bremen": "Bundesliga",
    "FC Augsburg": "Bundesliga", "VfL Wolfsburg": "Bundesliga",
    "1. FSV Mainz 05": "Bundesliga", "VfL Bochum": "Bundesliga",
    "1. FC Union Berlin": "Bundesliga", "1. FC Heidenheim": "Bundesliga",
    "Holstein Kiel": "Bundesliga",
    # ── Serie A ─────────────────────────────────────────────────────────────
    "Inter": "Serie A", "AC Milan": "Serie A",
    "Juventus": "Serie A", "Napoli": "Serie A",
    "AS Roma": "Serie A", "SS Lazio": "Serie A",
    "Atalanta": "Serie A", "Fiorentina": "Serie A",
    "Torino": "Serie A", "Bologna": "Serie A",
    "Udinese": "Serie A", "Monza": "Serie A",
    "Cagliari": "Serie A", "Lecce": "Serie A",
    "Hellas Verona": "Serie A", "Genoa": "Serie A",
    "Parma Calcio": "Serie A", "Como 1907": "Serie A",
    # ── Ligue 1 ─────────────────────────────────────────────────────────────
    "Paris Saint Germain": "Ligue 1", "Monaco": "Ligue 1",
    "LOSC Lille": "Ligue 1", "Olympique Lyonnais": "Ligue 1",
    "OGC Nice": "Ligue 1", "Marseille": "Ligue 1",
    "Stade Rennais": "Ligue 1", "RC Lens": "Ligue 1",
    "Toulouse": "Ligue 1", "Montpellier": "Ligue 1",
    "Angers SCO": "Ligue 1", "Auxerre": "Ligue 1",
    "Reims": "Ligue 1", "Strasbourg": "Ligue 1",
    "Nantes": "Ligue 1", "Saint-Étienne": "Ligue 1",
    "Bastia": "Ligue 1", "Nice": "Ligue 1",
    # ── Eredivisie ──────────────────────────────────────────────────────────
    "Ajax": "Eredivisie", "PSV": "Eredivisie",
    "Feyenoord": "Eredivisie", "AZ": "Eredivisie",
    "FC Twente": "Eredivisie", "FC Utrecht": "Eredivisie",
    "Almere City": "Eredivisie",
    # ── Primeira Liga ───────────────────────────────────────────────────────
    "Benfica": "Primeira Liga", "Porto": "Primeira Liga",
    "Sporting CP": "Primeira Liga", "Braga": "Primeira Liga",
    "Vitória SC": "Primeira Liga",
    # ── Belgian Pro ─────────────────────────────────────────────────────────
    "Club Brugge": "Belgian Pro League", "Anderlecht": "Belgian Pro League",
    "Union Saint-Gilloise": "Belgian Pro League", "Antwerp": "Belgian Pro League",
    "Gent": "Belgian Pro League", "Genk": "Belgian Pro League",
    "Standard Liège": "Belgian Pro League",
    # ── Super Lig ───────────────────────────────────────────────────────────
    "Galatasaray": "Super Lig", "Fenerbahçe": "Super Lig",
    "Beşiktaş": "Super Lig", "Trabzonspor": "Super Lig",
    "Alanyaspor": "Super Lig", "Başakşehir": "Super Lig",
    "Kayserispor": "Super Lig",
    # ── Scottish Premiership ────────────────────────────────────────────────
    "Celtic": "Scottish Premiership", "Rangers": "Scottish Premiership",
    "Hearts": "Scottish Premiership", "Hibernian": "Scottish Premiership",
    "Aberdeen": "Scottish Premiership",
    # ── Other European ──────────────────────────────────────────────────────
    "Bodø / Glimt": "Norwegian Eliteserien",
    "Brøndby": "Danish Superliga",
    "FC Midtjylland": "Danish Superliga",
    "Malmö FF": "Swedish Allsvenskan",
    "Slavia Praha": "Czech First League",
    "Sparta Praha": "Czech First League",
    "Sigma Olomouc": "Czech First League",
    "Rapid Vienna": "Austrian Bundesliga",
    "LASK": "Austrian Bundesliga",
    "Red Bull Salzburg": "Austrian Bundesliga",
    "BSC Young Boys": "Swiss Super League",
    "FC Basel": "Swiss Super League",
    "FC Zürich": "Swiss Super League",
    "Borac Banja Luka": "default",
    "Maccabi Tel Aviv": "Israeli Premier",
    "Hapoel Be'er Sheva": "Israeli Premier",
    "Panathinaikos": "Greek Super League",
    "Olympiakos": "Greek Super League",
    "PAOK": "Greek Super League",
    "Dinamo Zagreb": "Croatian First",
    "Hajduk Split": "Croatian First",
    "CFR Cluj": "Romanian Liga I",
    "Aris Limassol": "Cypriot First Division",
    # ── Brasileirao ─────────────────────────────────────────────────────────
    "Flamengo": "Brasileirao", "Palmeiras": "Brasileirao",
    "Corinthians": "Brasileirao", "São Paulo": "Brasileirao",
    "Atlético Mineiro": "Brasileirao", "Athletico PR": "Brasileirao",
    "Grêmio": "Brasileirao", "Internacional": "Brasileirao",
    "Vasco da Gama": "Brasileirao", "Fluminense": "Brasileirao",
    "Botafogo": "Brasileirao", "Cruzeiro": "Brasileirao",
    "Santos": "Brasileirao", "América": "Brasileirao",
    # ── Argentine Primera ───────────────────────────────────────────────────
    "Boca Juniors": "Argentine Primera",
    "River Plate": "Argentine Primera",
    "Racing Club": "Argentine Primera",
    "Independiente": "Argentine Primera",
    "San Lorenzo": "Argentine Primera",
    "Estudiantes": "Argentine Primera",
    "Talleres": "Argentine Primera",
    "Atlético Nacional": "Argentine Primera",  # actually Colombian but close tier
    # ── Liga MX ─────────────────────────────────────────────────────────────
    "Club América": "Liga MX", "América": "Liga MX",
    "Chivas": "Liga MX", "Atlas": "Liga MX",
    "Cruz Azul": "Liga MX", "Pumas": "Liga MX",
    "Tijuana": "Liga MX", "Monterrey": "Liga MX",
    "Toluca": "Liga MX", "León": "Liga MX",
    "Tigres UANL": "Liga MX",
    # ── MLS ─────────────────────────────────────────────────────────────────
    "Inter Miami": "MLS", "LA Galaxy": "MLS",
    "NYCFC": "MLS", "Seattle Sounders": "MLS",
    "Portland Timbers": "MLS", "Atlanta United": "MLS",
    "New England Revolution": "MLS", "Columbus Crew": "MLS",
    "LAFC": "MLS", "Austin": "MLS",
    "CF Montréal": "MLS", "Chicago Fire": "MLS",
    "D.C. United": "MLS", "FC Cincinnati": "MLS",
    "Nashville SC": "MLS", "Orlando City": "MLS",
    "Real Salt Lake": "MLS", "Sporting Kansas City": "MLS",
    # ── Canadian Premier ────────────────────────────────────────────────────
    "Pacific FC": "Canadian Premier", "Forge FC": "Canadian Premier",
    "Cavalry FC": "Canadian Premier", "HFX Wanderers": "Canadian Premier",
    "York United": "Canadian Premier", "Valour FC": "Canadian Premier",
    # ── Saudi Pro League ────────────────────────────────────────────────────
    "Al Hilal": "Saudi Pro League", "Al Nassr": "Saudi Pro League",
    "Al Ahli": "Saudi Pro League", "Al Ittihad": "Saudi Pro League",
    "Al Ettifaq": "Saudi Pro League", "Al Shabab": "Saudi Pro League",
    "Al Taawoun": "Saudi Pro League", "Al Fayha": "Saudi Pro League",
    "Al Riyadh": "Saudi Pro League", "Al-Fayha": "Saudi Pro League",
    "Al-Qadsiah": "Saudi Pro League", "Al Nasr": "Saudi Pro League",
    "Abha": "Saudi Pro League", "Al Fateh": "Saudi Pro League",
    # ── Qatar Stars League ──────────────────────────────────────────────────
    "Al Sadd": "Qatar Stars League", "Al Duhail": "Qatar Stars League",
    "Al Rayyan": "Qatar Stars League", "Al Gharafa": "Qatar Stars League",
    "Al Wakrah": "Qatar Stars League", "Al Sailiya": "Qatar Stars League",
    "Al Shahaniya": "Qatar Stars League", "Al Shamal SC": "Qatar Stars League",
    "Al-Ahli Doha": "Qatar Stars League", "Al-Arabi SC": "Qatar Stars League",
    # ── Egyptian Premier ────────────────────────────────────────────────────
    "Al Ahly": "Egyptian Premier", "Zamalek": "Egyptian Premier",
    "Al Masry": "Egyptian Premier",
    # ── UAE Pro League ──────────────────────────────────────────────────────
    "Al Ain": "UAE Pro League", "Al Jazira": "UAE Pro League",
    "Al Wahda": "UAE Pro League", "Bani Yas": "UAE Pro League",
    # ── South African PSL ───────────────────────────────────────────────────
    "Mamelodi Sundowns": "South African PSL",
    "Orlando Pirates": "South African PSL",
    "Kaizer Chiefs": "South African PSL",
    "Cape Town City": "South African PSL",
    # ── J1 League ───────────────────────────────────────────────────────────
    "Urawa Red Diamonds": "J1 League",
    "Albirex Niigata": "J1 League",
    "Gamba Osaka": "J1 League",
    "Vissel Kobe": "J1 League",
    # ── K League ────────────────────────────────────────────────────────────
    "Jeonbuk Hyundai Motors": "K League 1",
    "Ulsan HD": "K League 1",
    # ── Jordanian / other Middle East ───────────────────────────────────────
    "Al Wihdat": "Jordanian Pro League",
    "Al Hussein": "Jordanian Pro League",
    "Al Shorta": "default",
    "Al Zawra'a": "default",
    "Al Bataeh": "UAE Pro League",
    # ── other / no club ─────────────────────────────────────────────────────
    "Auckland": "default",
    "Barnsley": "default",
    "Bari 1908": "default",
    "Birmingham City": "default",
    "Academia Puerto Cabello": "default",
    "Akron": "default",
    "Ashdod": "Israeli Premier",
    "Astana": "default",
    "Auckland": "default",
    "Barcelona Guayaquil": "default",
}

# Teams listed as clubs (national team players without club listed)
_NATIONAL_TEAM_NAMES = {
    "Mexico", "Japan", "USA", "Canada", "Brazil", "Argentina",
    "France", "England", "Germany", "Spain",
}


# ── Cache ────────────────────────────────────────────────────────────────────
_TEAM_STRENGTHS: dict = {}


def _league_quality(club: str) -> float:
    if not club or club in _NATIONAL_TEAM_NAMES:
        return _LEAGUE_QUALITY["default"]
    league = _CLUB_LEAGUE.get(club)
    if league:
        return _LEAGUE_QUALITY.get(league, _LEAGUE_QUALITY["default"])
    # Heuristic fallback: Saudi/Gulf clubs not in dict
    club_lower = club.lower()
    if any(x in club_lower for x in ("al ", "fc al", "al-")):
        return 0.62  # generic Middle East
    return _LEAGUE_QUALITY["default"]


def _load_excluded_players() -> dict:
    """Load team → set of excluded player name fragments from injuries.json (new per-player format)."""
    import json
    from datetime import date as _date
    path = DATA_DIR.parent / "injuries.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    today = _date.today().strftime("%Y-%m-%d")
    excluded = {}
    for team, val in raw.items():
        if team.startswith("_") or not isinstance(val, dict):
            continue
        names = [
            inj["player"] for inj in val.get("injuries", [])
            if inj.get("exclude") and inj.get("known_from", "9999-99-99") <= today
        ]
        if names:
            excluded[team] = {n.lower() for n in names}
    return excluded


def build_team_strengths(force: bool = False) -> dict:
    """
    Returns {canonical_team_name: {"attack": float, "defense": float}}
    where 1.0 = WC average.  Cached after first call.
    Players listed in injuries.json exclude_players are skipped.
    """
    global _TEAM_STRENGTHS
    if _TEAM_STRENGTHS and not force:
        return _TEAM_STRENGTHS

    squads_path = DATA_DIR / "squads.csv"
    per90_path = DATA_DIR / "per90_stats.csv"
    if not squads_path.exists() or not per90_path.exists():
        return {}

    excluded = _load_excluded_players()

    # Load per90 stats keyed by player_id
    per90: dict = {}
    with open(per90_path) as f:
        for row in csv.DictReader(f):
            pid = row["player_id"]
            try:
                per90[pid] = {
                    "minutes":          float(row["minutes"] or 0),
                    "goals_per90":      float(row["goals_per90"] or 0),
                    "assists_per90":    float(row["assists_per90"] or 0),
                    "shots_per90":      float(row["shots_per90"] or 0),
                    "tackles_per90":    float(row["tackles_per90"] or 0),
                    "inter_per90":      float(row["interceptions_per90"] or 0),
                    "clear_per90":      float(row["clearances_per90"] or 0),
                    "saves_per90":      float(row["saves_per90"] or 0),
                    "rating":           float(row["rating"]) if row["rating"] else None,
                }
            except (ValueError, KeyError):
                pass

    # Group players by team, skipping excluded injured players
    team_players: dict = defaultdict(list)
    with open(squads_path) as f:
        for row in csv.DictReader(f):
            pid = row["player_id"]
            team = _SQUAD_COUNTRY_FIX.get(row["country"], row["country"])
            player_name = row.get("player_name", "").lower()
            excl_set = excluded.get(team, set())
            if any(excl in player_name or player_name in excl for excl in excl_set):
                continue
            pos = row["position"]
            club = row["club"]
            stats = per90.get(pid, {})
            team_players[team].append({
                "pid": pid, "pos": pos, "club": club,
                "lq": _league_quality(club),
                **stats,
            })

    # Aggregate per team
    def weighted_mean(values_weights):
        vals = [(v, w) for v, w in values_weights if v is not None and w > 0]
        if not vals:
            return None
        total_w = sum(w for _, w in vals)
        return sum(v * w for v, w in vals) / total_w

    raw_attack = {}   # team → raw attack score
    raw_defense = {}  # team → raw defense score

    for team, players in team_players.items():
        atk_vw, def_vw = [], []
        for p in players:
            mins = p.get("minutes", 0)
            w = math.sqrt(max(mins, 0))  # weight by sqrt(minutes)
            if w == 0:
                continue
            lq = p["lq"]
            g90   = p.get("goals_per90", 0) or 0
            a90   = p.get("assists_per90", 0) or 0
            sh90  = p.get("shots_per90", 0) or 0
            tkl90 = p.get("tackles_per90", 0) or 0
            icp90 = p.get("inter_per90", 0) or 0
            clr90 = p.get("clear_per90", 0) or 0
            sv90  = p.get("saves_per90", 0) or 0

            pos = p["pos"]
            if pos in ("FW",):
                atk_score = (g90 * 3.0 + a90 * 1.0 + sh90 * 0.3) * lq
                atk_vw.append((atk_score, w))
            elif pos == "MF":
                atk_score = (g90 * 2.0 + a90 * 1.5 + sh90 * 0.2) * lq
                def_score = (tkl90 * 1.0 + icp90 * 1.0) * lq
                atk_vw.append((atk_score, w * 0.7))
                def_vw.append((def_score, w * 0.3))
            elif pos == "DF":
                def_score = (tkl90 * 1.2 + icp90 * 1.2 + clr90 * 0.4) * lq
                def_vw.append((def_score, w))
            elif pos == "GK":
                def_score = (sv90 * 2.0 + clr90 * 0.2) * lq
                def_vw.append((def_score, w))

        atk = weighted_mean(atk_vw)
        dfn = weighted_mean(def_vw)
        if atk is not None:
            raw_attack[team] = atk
        if dfn is not None:
            raw_defense[team] = dfn

    if not raw_attack:
        return {}

    # Normalize to mean = 1.0 across all WC teams
    atk_vals = list(raw_attack.values())
    def_vals = list(raw_defense.values())
    atk_mean = sum(atk_vals) / len(atk_vals)
    def_mean = sum(def_vals) / len(def_vals)

    _TEAM_STRENGTHS = {}
    for team in team_players:
        _TEAM_STRENGTHS[team] = {
            "attack":  raw_attack.get(team, atk_mean) / atk_mean,
            "defense": raw_defense.get(team, def_mean) / def_mean,
        }

    return _TEAM_STRENGTHS


def player_lambdas(home: str, away: str,
                   strengths: dict = None,
                   league_avg: float = 1.51,
                   home_bonus: float = 0.0) -> tuple:
    """
    Compute (lh, la) from player strength scores alone.
    Returns (None, None) if player data missing for either team.
    """
    strengths = strengths if strengths is not None else build_team_strengths()
    if not strengths:
        return None, None

    # Country code lookup (squads.csv uses country_code, we need canonical name)
    h_str = strengths.get(home) or _by_canonical(home, strengths)
    a_str = strengths.get(away) or _by_canonical(away, strengths)

    if h_str is None or a_str is None:
        return None, None

    h_atk = h_str["attack"] if isinstance(h_str, dict) else h_str
    a_atk = a_str["attack"] if isinstance(a_str, dict) else a_str
    h_def = h_str.get("defense", 1.0) if isinstance(h_str, dict) else 1.0
    a_def = a_str.get("defense", 1.0) if isinstance(a_str, dict) else 1.0
    lh = max(0.3, league_avg * h_atk * (1.0 / max(0.3, a_def)) + home_bonus)
    la = max(0.3, league_avg * a_atk * (1.0 / max(0.3, h_def)))
    return round(lh, 3), round(la, 3)


# squads.csv country name → our canonical name (only the mismatches)
_SQUAD_COUNTRY_FIX = {
    "Cape Verde Islands": "Cabo Verde",
    "Curacao": "Curaçao",
    "Côte d'Ivoire": "Ivory Coast",
    "Korea Republic": "South Korea",
    "Türkiye": "Turkey",
}

# country_code → canonical name mapping for squads.csv
_CC_TO_CANONICAL = {
    "ENG": "England", "FRA": "France", "GER": "Germany", "ESP": "Spain",
    "BRA": "Brazil", "ARG": "Argentina", "POR": "Portugal", "NED": "Netherlands",
    "BEL": "Belgium", "CRO": "Croatia", "URU": "Uruguay", "DEN": "Denmark",
    "SUI": "Switzerland", "SCO": "Scotland", "USA": "United States",
    "CAN": "Canada", "MEX": "Mexico", "JPN": "Japan", "KOR": "South Korea",
    "AUS": "Australia", "MAR": "Morocco", "SEN": "Senegal", "NGA": "Nigeria",
    "EGY": "Egypt", "TUN": "Tunisia", "ALG": "Algeria", "CMR": "Cameroon",
    "CIV": "Ivory Coast", "GHA": "Ghana", "ZAF": "South Africa",
    "COD": "DR Congo", "NOR": "Norway", "SWE": "Sweden", "AUT": "Austria",
    "TUR": "Turkey", "UZB": "Uzbekistan", "IRN": "Iran", "IRQ": "Iraq",
    "KSA": "Saudi Arabia", "JOR": "Jordan", "QAT": "Qatar", "ECU": "Ecuador",
    "COL": "Colombia", "PAR": "Paraguay", "CHL": "Chile", "BOL": "Bolivia",
    "VEN": "Venezuela", "PAN": "Panama", "HTI": "Haiti", "JAM": "Jamaica",
    "HON": "Honduras", "SLV": "El Salvador", "CRC": "Costa Rica",
    "CUW": "Curaçao", "CPV": "Cabo Verde", "NZL": "New Zealand",
    "BIH": "Bosnia and Herzegovina",
}

# Reverse: canonical → country_code (for lookup)
_CANONICAL_TO_CC = {v: k for k, v in _CC_TO_CANONICAL.items()}


def _by_canonical(name: str, strengths: dict):
    """Try to find team by country_code from canonical name."""
    cc = _CANONICAL_TO_CC.get(name)
    if cc and cc in strengths:
        return strengths[cc]
    # Try direct match on full name in strengths
    for key in strengths:
        if key and key.lower() == name.lower():
            return strengths[key]
    return None
