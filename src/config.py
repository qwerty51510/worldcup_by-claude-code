FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
POLYMARKET_BASE = "https://gamma-api.polymarket.com"
WORLD_CUP_COMPETITION_ID = 2000

DEFAULT_CALIBRATION = {
    "ah_weight": 1.0,
    "ou_weight": 1.0,
    "sharp_money_multiplier": 0.85,
    "incentive_boost": 0.15,
    "climate_penalty": 0.05,
    "age_decay_threshold": 29.5,
    "version": "1.0",
    "last_updated": "2026-06-22",
}

BRIER_RESET_THRESHOLD = 0.25

# FIFA World Rankings June 2026 — lower number = stronger team
# Used to seed lambda when no odds data is available
FIFA_RANKINGS = {
    "Argentina": 1, "France": 2, "England": 3, "Spain": 4,
    "Portugal": 5, "Belgium": 6, "Brazil": 7, "Netherlands": 8,
    "Germany": 9, "Croatia": 10, "Italy": 11, "Morocco": 12,
    "Uruguay": 13, "Denmark": 14, "Switzerland": 15, "United States": 16,
    "Mexico": 17, "Senegal": 18, "Japan": 19, "Iran": 20,
    "Colombia": 21, "South Korea": 22, "Australia": 23, "Canada": 24,
    "Norway": 25, "Austria": 26, "Poland": 27, "Sweden": 28,
    "Ukraine": 29, "Ecuador": 30, "Tunisia": 31, "Qatar": 32,
    "Saudi Arabia": 33, "Ghana": 34, "Cameroon": 35, "Egypt": 36,
    "Algeria": 37, "Nigeria": 38, "Scotland": 39, "Turkey": 40,
    "Türkiye": 40, "Czech Republic": 41, "Czechia": 41,
    "DR Congo": 42, "Ivory Coast": 43, "Côte d'Ivoire": 43,
    "New Zealand": 44, "Paraguay": 45, "Bolivia": 46,
    "Peru": 47, "Venezuela": 48, "Costa Rica": 49, "Jamaica": 50,
    "Panama": 51, "Honduras": 52, "El Salvador": 53,
    "Iraq": 54, "Jordan": 55, "South Africa": 56,
    "Uganda": 57, "Zambia": 58, "Tanzania": 59, "Zimbabwe": 60,
    "Cape Verde": 61, "Cabo Verde": 61,
    "Uzbekistan": 62, "Haiti": 63, "Bosnia and Herzegovina": 64,
    "Bosnia Herzegovina": 64, "Curaçao": 65,
}

BASE_LAMBDA = 1.2  # average goals per game for a median-ranked team (rank ~33)
