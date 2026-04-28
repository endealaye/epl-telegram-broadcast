import json
import sqlite3
import requests
import os
import re
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from collections import defaultdict
from supabase import create_client, Client

# Load .env file
def load_env():
    if os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID'):
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

# Timezone helper (EAT is UTC+3)
def get_eat_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)

def get_eat_today():
    return get_eat_now().strftime('%Y-%m-%d')

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

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def update_fixtures_from_json():
    if not supabase: return False
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
                except ValueError: pass
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

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def process_live_updates():
    """Scrapes current scores and sends live goal/HT/FT alerts."""
    if not supabase: return
    try:
        response = requests.get(BBC_SCORES_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for link in soup.find_all('a', href=re.compile(r'/sport/football/live/')):
            text = link.get_text(" ", strip=True)
            # Match pattern: "Home 1 , Away 0 at Full time" or "Home 1 , Away 0 (Half time)" etc.
            # We look for scores and the match status
            score_match = re.search(r'(.+?)\s+(\d+)\s*,\s*(.+?)\s+(\d+)', text)
            if score_match:
                home_raw, h_score, away_raw, a_score = score_match.groups()
                home_team = TEAM_MAPPING.get(home_raw.strip())
                away_team = TEAM_MAPPING.get(away_raw.strip())
                
                if not home_team or not away_team: continue
                
                current_score_str = f"{h_score}-{a_score}"
                is_full_time = "Full time" in text or "FT" in text
                is_half_time = "Half time" in text or "HT" in text
                
                # Fetch current state from DB
                res = supabase.table('fixtures').select('*').eq('hometeam', home_team).eq('awayteam', away_team).single().execute()
                if not res.data: continue
                db_match = res.data
                
                last_score = db_match.get('last_broadcast_score')
                
                # 1. Goal Alert (Only if not Full Time)
                if not is_full_time and current_score_str != last_score:
                    home_am = AMHARIC_TEAMS.get(home_team, home_team)
                    away_am = AMHARIC_TEAMS.get(away_team, away_team)
                    msg = f"⚽ *ጎል ተቆጠረ!*\n\n{home_am} {h_score} - {a_score} {away_am}"
                    send_telegram_message(msg)
                    supabase.table('fixtures').update({"last_broadcast_score": current_score_str}).eq('matchnumber', db_match['matchnumber']).execute()
                
                # 2. Half Time Alert
                if is_half_time and not db_match.get('half_time_sent'):
                    home_am = AMHARIC_TEAMS.get(home_team, home_team)
                    away_am = AMHARIC_TEAMS.get(away_team, away_team)
                    msg = f"⏸️ *የእረፍት ጊዜ ውጤት*\n\n{home_am} {h_score} - {a_score} {away_am}"
                    send_telegram_message(msg)
                    supabase.table('fixtures').update({"half_time_sent": True}).eq('matchnumber', db_match['matchnumber']).execute()
                
                # 3. Immediate Final Score
                if is_full_time and db_match.get('broadcaststatus') != 'result_sent':
                    home_am = AMHARIC_TEAMS.get(home_team, home_team)
                    away_am = AMHARIC_TEAMS.get(away_team, away_team)
                    msg = f"🏁 *የመጨረሻ ውጤት*\n{home_am} {h_score} - {a_score} {away_am}"
                    send_telegram_message(msg)
                    supabase.table('fixtures').update({"broadcaststatus": 'result_sent', 'hometeamscore': int(h_score), 'awayteamscore': int(a_score)}).eq('matchnumber', db_match['matchnumber']).execute()

    except Exception as e:
        print(f"Live update error: {e}")

def broadcast_daily():
    today = get_eat_today()
    if not supabase: return
    res = supabase.table('fixtures').select("*").ilike('dateeat', f'{today}%').execute()
    matches = res.data
    if matches:
        time_groups = defaultdict(list)
        match_ids = []
        for m in matches:
            time = m['dateeat'].split(' ')[1]
            home_am = AMHARIC_TEAMS.get(m['hometeam'], m['hometeam'])
            away_am = AMHARIC_TEAMS.get(m['awayteam'], m['awayteam'])
            time_groups[time].append(f"• {home_am} vs {away_am}")
            match_ids.append(m['matchnumber'])
        msg = f"📅 *የዛሬ የኢንግሊዝ ፕሪሚየር ሊግ ጨዋታዎች ({today})*\n\n"
        for time in sorted(time_groups.keys()):
            msg += f"⏰ *{time}*\n" + "\n".join(time_groups[time]) + "\n\n"
        send_telegram_message(msg)
        supabase.table('fixtures').update({"broadcaststatus": 'scheduled'}).in_('matchnumber', match_ids).execute()

def broadcast_reminders():
    now = get_eat_now()
    window_start = now.strftime('%Y-%m-%d %H:%M:%S')
    window_end = (now + timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S')
    if not supabase: return
    res = supabase.table('fixtures').select("*").gte('dateeat', window_start).lte('dateeat', window_end).or_('broadcaststatus.eq.pending,broadcaststatus.eq.scheduled').execute()
    matches = res.data
    for m in matches:
        time = m['dateeat'].split(' ')[1]
        home_am = AMHARIC_TEAMS.get(m['hometeam'], m['hometeam'])
        away_am = AMHARIC_TEAMS.get(m['awayteam'], m['awayteam'])
        msg = f"🔔 *የጨዋታ ማሳሰቢያ!*\n\n⏰ {time} | {home_am} vs {away_am}\nተዘጋጁ! ⚽"
        send_telegram_message(msg)
        supabase.table('fixtures').update({"broadcaststatus": 'reminded'}).eq('matchnumber', m['matchnumber']).execute()

def broadcast_results():
    """Consolidated roundup for the day."""
    today = get_eat_today()
    if not supabase: return
    res = supabase.table('fixtures').select("*").ilike('dateeat', f'{today}%').not_.eq('broadcaststatus', 'result_sent').not_.is_('hometeamscore', 'null').execute()
    results = res.data
    if not results: return
    msg = f"🏁 *የጨዋታዎች ውጤት ({today})*\n\n"
    sent_ids = []
    for r in results:
        home_am = AMHARIC_TEAMS.get(r['hometeam'], r['hometeam'])
        away_am = AMHARIC_TEAMS.get(r['awayteam'], r['awayteam'])
        msg += f"• {home_am} {r['hometeamscore']} - {r['awayteamscore']} {away_am}\n"
        sent_ids.append(r['matchnumber'])
    send_telegram_message(msg)
    supabase.table('fixtures').update({"broadcaststatus": 'result_sent'}).in_('matchnumber', sent_ids).execute()

if __name__ == '__main__':
    import sys
    update_fixtures_from_json()
    process_live_updates()
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == 'daily': broadcast_daily()
        elif mode == 'reminders': broadcast_reminders()
        elif mode == 'results': broadcast_results()
    else:
        print("Usage: python3 telegram_broadcast.py [daily|reminders|results]")
