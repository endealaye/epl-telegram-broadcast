import json
import requests
import os
import re
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from collections import defaultdict
from supabase import create_client, Client

def load_env():
    # Only load from file if required variables are not already in environment (e.g. GitHub Actions)
    if os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID') and os.getenv('SUPABASE_URL'):
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

# Configuration
JSON_URL = 'https://fixturedownload.com/feed/json/epl-2025'
BBC_SCORES_URL = 'https://www.bbc.com/sport/football/premier-league/scores-fixtures'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Validate critical config
missing = []
if not TELEGRAM_BOT_TOKEN: missing.append('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_CHAT_ID: missing.append('TELEGRAM_CHAT_ID')
if not SUPABASE_URL: missing.append('SUPABASE_URL')
if not SUPABASE_KEY: missing.append('SUPABASE_KEY')

if missing:
    print(f"CRITICAL ERROR: Missing environment variables: {', '.join(missing)}")
    # Exit with non-zero code so GitHub Actions marks the run as failed
    import sys
    sys.exit(1)


# Timezone helper (EAT is UTC+3)
def get_eat_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)

def get_eat_today():
    return get_eat_now().strftime('%Y-%m-%d')

# Team name mapping: BBC Name -> Database Name
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
    "Chelsea": "Chelsea"
}

# Amharic Transliterations: Database Name -> Amharic Name
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
    "Wolves": "ዉልቭስ"
}

# Supabase Client
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def update_fixtures_from_json():
    if not supabase:
        print("Supabase not configured. Skipping update.")
        return False
    try:
        response = requests.get(JSON_URL)
        response.raise_for_status()
        data = response.json()

        for match in data:
            utc_date = match.get('DateUtc')
            eat_date = None
            if utc_date:
                try:
                    dt = datetime.strptime(utc_date, '%Y-%m-%d %H:%M:%SZ').replace(tzinfo=timezone.utc)
                    eat_date = (dt + timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass

            # Upsert into Supabase
            supabase.table('fixtures').upsert({
                "MatchNumber": match.get('MatchNumber'),
                "RoundNumber": match.get('RoundNumber'),
                "DateUtc": utc_date,
                "Location": match.get('Location'),
                "HomeTeam": match.get('HomeTeam'),
                "AwayTeam": match.get('AwayTeam'),
                "MatchGroup": match.get('Group'),
                "HomeTeamScore": match.get('HomeTeamScore'),
                "AwayTeamScore": match.get('AwayTeamScore'),
                "DateEAT": eat_date
            }).execute()
        return True
    except Exception as e:
        print(f"Error updating fixtures: {e}")
        return False

def scrape_scores():
    if not supabase: return False
    
    # Start with BBC
    success = scrape_bbc()
    # Future: if not success: success = scrape_sky() etc.
    return success

def scrape_bbc():
    try:
        url = 'https://www.bbc.com/sport/football/premier-league/scores-fixtures'
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        matches_updated = 0
        for link in soup.find_all('a', href=re.compile(r'/sport/football/live/')):
            text = link.get_text(" ", strip=True)
            match_data = re.search(r'(.+?)\s+(\d+)\s*,\s*(.+?)\s+(\d+)\s+at\s+Full\s+time', text)
            if match_data:
                home_raw, home_score, away_raw, away_score = match_data.groups()
                home_team = TEAM_MAPPING.get(home_raw.strip())
                away_team = TEAM_MAPPING.get(away_raw.strip())
                
                if home_team and away_team:
                    supabase.table('fixtures').update({
                        "HomeTeamScore": int(home_score),
                        "AwayTeamScore": int(away_score)
                    }).eq("HomeTeam", home_team).eq("AwayTeam", away_team).execute()
                    matches_updated += 1
        
        print(f"Scraped {matches_updated} scores from BBC.")
        return True
    except Exception as e:
        print(f"BBC Scraper Error: {e}")
        return False

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def broadcast_daily():
    today = get_eat_today()
    if not supabase: return
    
    res = supabase.table('fixtures').select("*").ilike('DateEAT', f'{today}%').execute()
    matches = res.data
    
    if matches:
        time_groups = defaultdict(list)
        match_ids = []
        for m in matches:
            time = m['DateEAT'].split(' ')[1]
            home_am = AMHARIC_TEAMS.get(m['HomeTeam'], m['HomeTeam'])
            away_am = AMHARIC_TEAMS.get(m['AwayTeam'], m['AwayTeam'])
            time_groups[time].append(f"• {home_am} vs {away_am}")
            match_ids.append(m['MatchNumber'])
        
        msg = f"✅ *System Online*\n📅 *የዛሬ የኢንግሊዝ ፕሪሚየር ሊግ ጨዋታዎች ({today})*\n\n"
        for time in sorted(time_groups.keys()):
            msg += f"⏰ *{time}*\n" + "\n".join(time_groups[time]) + "\n\n"
        
        send_telegram_message(msg)
        supabase.table('fixtures').update({"BroadcastStatus": 'scheduled'}).in_('MatchNumber', match_ids).execute()
    else:
        print("No matches today.")

def broadcast_reminders():
    now = get_eat_now()
    window_start = now.strftime('%Y-%m-%d %H:%M:%S')
    window_end = (now + timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S')
    
    if not supabase: return
    
    res = supabase.table('fixtures').select("*").gte('DateEAT', window_start).lte('DateEAT', window_end).or_('BroadcastStatus.eq.pending,BroadcastStatus.eq.scheduled').execute()
    matches = res.data
    
    for m in matches:
        time = m['DateEAT'].split(' ')[1]
        home_am = AMHARIC_TEAMS.get(m['HomeTeam'], m['HomeTeam'])
        away_am = AMHARIC_TEAMS.get(m['AwayTeam'], m['AwayTeam'])
        msg = f"🔔 *የጨዋታ ማሳሰቢያ!*\n\n⏰ {time} | {home_am} vs {away_am}\nተዘጋጁ! ⚽"
        send_telegram_message(msg)
        supabase.table('fixtures').update({"BroadcastStatus": 'reminded'}).eq('MatchNumber', m['MatchNumber']).execute()

def broadcast_results():
    today = get_eat_today()
    if not supabase: return
    
    res = supabase.table('fixtures').select("*").ilike('DateEAT', f'{today}%').not_.eq('BroadcastStatus', 'result_sent').not_.is_('HomeTeamScore', 'null').execute()
    results = res.data
    
    if not results:
        print("No new results.")
        return

    msg = f"🏁 *የጨዋታዎች ውጤት ({today})*\n\n"
    sent_ids = []
    for r in results:
        home_am = AMHARIC_TEAMS.get(r['HomeTeam'], r['HomeTeam'])
        away_am = AMHARIC_TEAMS.get(r['AwayTeam'], r['AwayTeam'])
        msg += f"• {home_am} {r['HomeTeamScore']} - {r['AwayTeamScore']} {away_am}\n"
        sent_ids.append(r['MatchNumber'])
    
    send_telegram_message(msg)
    supabase.table('fixtures').update({"BroadcastStatus": 'result_sent'}).in_('MatchNumber', sent_ids).execute()

if __name__ == '__main__':
    import sys
    update_fixtures_from_json()
    scrape_scores()
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == 'daily': broadcast_daily()
        elif mode == 'reminders': broadcast_reminders()
        elif mode == 'results': broadcast_results()
    else:
        print("Usage: python3 telegram_broadcast.py [daily|reminders|results]")
