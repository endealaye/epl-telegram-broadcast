import os
from datetime import datetime, timedelta, timezone


def _clean_env(name):
    value = os.getenv(name)
    return value.strip() if isinstance(value, str) else value


def load_env():
    if _clean_env('TELEGRAM_BOT_TOKEN') and _clean_env('TELEGRAM_CHAT_ID'):
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value.strip("'\"")


load_env()

JSON_URL = 'https://fixturedownload.com/feed/json/epl-2025'
BBC_SCORES_URL = 'https://www.bbc.com/sport/football/premier-league/scores-fixtures'
SKY_SCORES_URL = 'https://www.skysports.com/premier-league/scores'
TELEGRAM_BOT_TOKEN = _clean_env('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = _clean_env('TELEGRAM_CHAT_ID')
TELEGRAM_ADMIN_ID = _clean_env('TELEGRAM_ADMIN_ID')
SUPABASE_URL = _clean_env('SUPABASE_URL')
SUPABASE_KEY = _clean_env('SUPABASE_KEY')


def get_eat_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)


def get_eat_today():
    return get_eat_now().strftime('%Y-%m-%d')


def parse_eat_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


TEAM_MAPPING = {
    "Manchester United": "Man Utd",
    "Brentford": "Brentford",
    "Fulham": "Fulham",
    "Aston Villa": "Aston Villa",
    "Liverpool": "Liverpool",
    "Crystal Palace": "Crystal Palace",
    "West Ham United": "West Ham",
    "Everton": "Everton",
    "Wolverhampton Wanderers": "Wolves",
    "Tottenham Hotspur": "Spurs",
    "Arsenal": "Arsenal",
    "Newcastle United": "Newcastle",
    "Sunderland": "Sunderland",
    "Nottingham Forest": "Nott'm Forest",
    "AFC Bournemouth": "Bournemouth",
    "Leeds United": "Leeds",
    "Burnley": "Burnley",
    "Manchester City": "Man City",
    "Brighton & Hove Albion": "Brighton",
    "Chelsea": "Chelsea",
}


AMHARIC_TEAMS = {
    "Arsenal": "አርሰናል",
    "Aston Villa": "አስቶን ቪላ",
    "Bournemouth": "ቦርንሙዝ",
    "Brentford": "ብሬንትፎርድ",
    "Brighton": "ብራይተን",
    "Burnley": "በርንሌይ",
    "Chelsea": "ቼልሲ",
    "Crystal Palace": "ክሪስታል ፓላስ",
    "Everton": "ኤቨርተን",
    "Fulham": "ፉልሃም",
    "Leeds": "ሊድስ",
    "Liverpool": "ሊቨርፑል",
    "Man City": "ማንቸስተር ሲቲ",
    "Man Utd": "ማንቸስተር ዩናይትድ",
    "Newcastle": "ኒውካስል",
    "Nott'm Forest": "ኖቲንግሃም ፎረስት",
    "Spurs": "ስፐርስ",
    "Sunderland": "ሰንደርላንድ",
    "West Ham": "ዌስትሃም",
    "Wolves": "ዉልቭስ",
}
