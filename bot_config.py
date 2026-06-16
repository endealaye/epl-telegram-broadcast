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
WORLD_CUP_JSON_URL = 'https://fixturedownload.com/feed/json/fifa-world-cup-2026'
CURRENT_EPL_SEASON = _clean_env('CURRENT_EPL_SEASON') or '2025-26'
WORLD_CUP_SEASON = _clean_env('WORLD_CUP_SEASON') or '2026'
BBC_SCORES_URL = 'https://www.bbc.com/sport/football/premier-league/scores-fixtures'
BBC_SCORES_URL_TEMPLATE = 'https://www.bbc.com/sport/football/scores-fixtures/{date}'
SKY_SCORES_URL_TEMPLATE = 'https://www.skysports.com/football-scores-fixtures/{date}'
SKY_SCORES_API_URL = 'https://www.skysports.com/api/football/live-scores'
TELEGRAM_BOT_TOKEN = _clean_env('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = _clean_env('TELEGRAM_CHAT_ID')
TELEGRAM_ADMIN_ID = _clean_env('TELEGRAM_ADMIN_ID')
SUPABASE_URL = _clean_env('SUPABASE_URL')
SUPABASE_KEY = _clean_env('SUPABASE_KEY')
RAPIDAPI_KEY = _clean_env('RAPIDAPI_KEY')
RAPIDAPI_HOST = _clean_env('RAPIDAPI_HOST')


def get_eat_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)


def get_eat_today():
    return get_eat_now().strftime('%Y-%m-%d')


def format_display_date(value):
    if not value:
        return ""
    for date_format in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, date_format).strftime("%d:%m:%y")
        except ValueError:
            continue
    return value


def parse_eat_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


TEAM_MAPPING = {
    "Atleti": "Atletico Madrid",
    "Atletico Madrid": "Atletico Madrid",
    "Atlético Madrid": "Atletico Madrid",
    "Atletico de Madrid": "Atletico Madrid",
    "Atlético de Madrid": "Atletico Madrid",
    "Bayern Munich": "Bayern München",
    "Bayern München": "Bayern München",
    "Manchester United": "Man Utd",
    "Paris": "Paris",
    "Paris Saint-Germain": "Paris",
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
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Cape Verde": "Cabo Verde",
    "Curacao": "Curaçao",
    "Czech Republic": "Czechia",
    "DR Congo": "Congo DR",
    "Democratic Republic of Congo": "Congo DR",
    "Iran": "IR Iran",
    "Ivory Coast": "Côte d'Ivoire",
    "South Korea": "Korea Republic",
    "Turkey": "Türkiye",
    "Türkiye": "Türkiye",
    "United States": "USA",
    "United States of America": "USA",
}


AMHARIC_TEAMS = {
    "Arsenal": "አርሰናል",
    "Atletico Madrid": "አትሌቲኮ ማድሪድ",
    "Aston Villa": "አስቶን ቪላ",
    "Bayern München": "ባየርን ሙኒክ",
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
    "Paris": "ፓሪስ ሳን ዠርመን",
    "Spurs": "ስፐርስ",
    "Sunderland": "ሰንደርላንድ",
    "West Ham": "ዌስትሃም",
    "Wolves": "ዉልቭስ",
    "Algeria": "አልጄሪያ",
    "Argentina": "አርጀንቲና",
    "Australia": "አውስትራሊያ",
    "Austria": "ኦስትሪያ",
    "Belgium": "ቤልጂየም",
    "Bosnia and Herzegovina": "ቦስኒያ እና ሄርዞጎቪና",
    "Brazil": "ብራዚል",
    "Cabo Verde": "ካቦ ቨርዴ",
    "Canada": "ካናዳ",
    "Colombia": "ኮሎምቢያ",
    "Congo DR": "ዲ.አር. ኮንጎ",
    "Croatia": "ክሮኤሽያ",
    "Curaçao": "ኩራሳዎ",
    "Czechia": "ቼክያ",
    "Côte d'Ivoire": "ኮት ዲቯር",
    "Ecuador": "ኢኳዶር",
    "Egypt": "ግብፅ",
    "England": "እንግሊዝ",
    "France": "ፈረንሳይ",
    "Germany": "ጀርመን",
    "Ghana": "ጋና",
    "Haiti": "ሀይቲ",
    "IR Iran": "ኢራን",
    "Iraq": "ኢራቅ",
    "Japan": "ጃፓን",
    "Jordan": "ዮርዳኖስ",
    "Korea Republic": "ደቡብ ኮሪያ",
    "Mexico": "ሜክሲኮ",
    "Morocco": "ሞሮኮ",
    "Netherlands": "ኔዘርላንድስ",
    "New Zealand": "ኒውዚላንድ",
    "Norway": "ኖርዌይ",
    "Panama": "ፓናማ",
    "Paraguay": "ፓራጓይ",
    "Portugal": "ፖርቱጋል",
    "Qatar": "ኳታር",
    "Saudi Arabia": "ሳዑዲ አረቢያ",
    "Scotland": "ስኮትላንድ",
    "Senegal": "ሴኔጋል",
    "South Africa": "ደቡብ አፍሪካ",
    "Spain": "ስፔን",
    "Sweden": "ስዊድን",
    "Switzerland": "ስዊዘርላንድ",
    "Tunisia": "ቱኒዚያ",
    "Türkiye": "ቱርክ",
    "USA": "አሜሪካ",
    "Uruguay": "ኡራጓይ",
    "Uzbekistan": "ኡዝቤኪስታን",
}


SHORT_AMHARIC_TEAMS = {
    "Bosnia and Herzegovina": "ቦስኒያ",
    "Côte d'Ivoire": "ኮት ዲቯር",
    "Korea Republic": "ደ. ኮሪያ",
    "New Zealand": "ኒውዚላንድ",
    "Saudi Arabia": "ሳዑዲ",
    "South Africa": "ደ. አፍሪካ",
}
