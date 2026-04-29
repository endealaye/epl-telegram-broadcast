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
SKY_SCORES_URL = 'https://www.skysports.com/premier-league/scores'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_ADMIN_ID = os.getenv('TELEGRAM_ADMIN_ID')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Timezone helper (EAT is UTC+3)
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

def fetch_fixtures_for_dates(date_strings):
    if not supabase:
        return []

    fixtures = []
    seen_match_numbers = set()
    for date_string in date_strings:
        res = supabase.table('fixtures').select("*").ilike('dateeat', f'{date_string}%').execute()
        for fixture in res.data or []:
            match_number = fixture.get('matchnumber')
            if match_number in seen_match_numbers:
                continue
            fixtures.append(fixture)
            seen_match_numbers.add(match_number)
    return fixtures

def fixtures_in_window(start_dt, end_dt):
    date_strings = {start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d')}
    fixtures = fetch_fixtures_for_dates(sorted(date_strings))
    window_matches = []
    for fixture in fixtures:
        kickoff = parse_eat_datetime(fixture.get('dateeat'))
        if kickoff and start_dt <= kickoff <= end_dt:
            window_matches.append(fixture)
    return window_matches

def has_matches_today():
    return bool(fetch_fixtures_for_dates([get_eat_today()]))

def has_upcoming_matches(minutes=60):
    now = get_eat_now().replace(tzinfo=None)
    return bool(fixtures_in_window(now, now + timedelta(minutes=minutes)))

def has_live_window_matches():
    now = get_eat_now().replace(tzinfo=None)
    return bool(fixtures_in_window(now - timedelta(minutes=30), now + timedelta(hours=4)))

def has_pending_results():
    fixtures = fetch_fixtures_for_dates([get_eat_today()])
    return any(
        fixture.get('hometeamscore') is not None
        and fixture.get('awayteamscore') is not None
        and not fixture.get('result_sent')
        for fixture in fixtures
    )

def mark_match_state(match_number, **fields):
    if not supabase:
        return
    supabase.table('fixtures').update(fields).eq('matchnumber', match_number).execute()

def update_fixtures_from_json():
    if not supabase:
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

def send_telegram_message(message, chat_id=None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target_chat, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def send_admin_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_ID:
        print(f"Admin Alert: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_ADMIN_ID, "text": f"⚠️ *System Alert*\n\n{message}", "parse_mode": "Markdown"}
    requests.post(url, json=payload)

class ScoreProvider:
    def get_scores(self):
        raise NotImplementedError

class BBCProvider(ScoreProvider):
    def get_scores(self):
        try:
            response = requests.get(BBC_SCORES_URL, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            scores = []
            for link in soup.find_all('a', href=re.compile(r'/sport/football/live/')):
                text = link.get_text(" ", strip=True)
                score_match = re.search(r'(.+?)\s+(\d+)\s*,\s*(.+?)\s+(\d+)', text)
                if score_match:
                    home_raw, h_score, away_raw, a_score = score_match.groups()
                    scores.append({
                        'home': home_raw.strip(),
                        'h_score': h_score,
                        'away': away_raw.strip(),
                        'a_score': a_score,
                        'text': text
                    })
            return scores
        except Exception as e:
            print(f"BBCProvider error: {e}")
            return None

class SkySportsProvider(ScoreProvider):
    def get_scores(self):
        try:
            response = requests.get(SKY_SCORES_URL, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            scores = []
            # Sky Sports usually uses a specific structure for scores
            # This is a simplified implementation; Sky's layout changes often
            for match_div in soup.find_all('div', class_=re.compile(r'score-box|match-score')):
                text = match_div.get_text(" ", strip=True)
                score_match = re.search(r'(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)', text)
                if score_match:
                    home, h_score, a_score, away = score_match.groups()
                    scores.append({
                        'home': home.strip(),
                        'h_score': h_score,
                        'away': away.strip(),
                        'a_score': a_score,
                        'text': text
                    })
            return scores
        except Exception as e:
            print(f"SkySportsProvider error: {e}")
            return None

def broadcast_heartbeat(chat_id=None):
    """Sends a health check message. If chat_id is provided, sends to that user."""
    try:
        now = get_eat_now()
        msg = f"✅ *System Heartbeat*\n\nBot is running normally.\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')} EAT"
        if chat_id:
            send_telegram_message(msg, chat_id=chat_id)
        else:
            send_admin_alert(msg.replace("⚠️ *System Alert*", "✅ *System Status*"))
    except Exception as e:
        print(f"Heartbeat error: {e}")

def process_commands():
    """Polls for Telegram commands and responds to them."""
    if not supabase or not TELEGRAM_BOT_TOKEN:
        return
    try:
        # Get last update ID from Supabase
        res = supabase.table('bot_state').select('value').eq('key', 'last_update_id').single().execute()
        last_update_id = int(res.data['value']) if res.data else 0
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"offset": last_update_id + 1, "timeout": 10}
        response = requests.get(url, params=params).json()
        
        if not response.get('ok'):
            return
        
        updates = response.get('result', [])
        for update in updates:
            msg = update.get('message')
            if not msg:
                continue
            
            chat_id = msg['chat']['id']
            text = msg.get('text', '')
            
            # Only respond to admin
            if str(chat_id) != str(TELEGRAM_ADMIN_ID):
                continue
            
            if text == '/heartbeat':
                broadcast_heartbeat(chat_id=chat_id)
            elif text == '/status':
                send_telegram_message("✅ *Bot Status*: Online\n🕒 *Next run*: Every 30m", chat_id=chat_id)
            
            last_update_id = update['update_id']
        
        # Save last update ID
        if updates:
            supabase.table('bot_state').upsert({"key": 'last_update_id', "value": str(last_update_id)}).execute()
            
    except Exception as e:
        print(f"Command processing error: {e}")




def process_live_updates():
    """Scrapes current scores using multiple providers and sends live goal/HT/FT alerts."""
    if not supabase:
        return
    if not has_live_window_matches():
        print("Skip live: no fixtures in the active live window.")
        return
    
    providers = [BBCProvider(), SkySportsProvider()]
    all_scores = []
    
    for provider in providers:
        scores = provider.get_scores()
        if scores:
            all_scores = scores
            break
            
    if not all_scores:
        return

    try:
        for match_data in all_scores:
            text = match_data['text']
            h_score = match_data['h_score']
            a_score = match_data['a_score']
            home_raw = match_data['home']
            away_raw = match_data['away']
            
            home_team = TEAM_MAPPING.get(home_raw)
            away_team = TEAM_MAPPING.get(away_raw)
            
            if not home_team or not away_team:
                continue
            
            current_score_str = f"{h_score}-{a_score}"
            is_full_time = "Full time" in text or "FT" in text or "Full-time" in text
            is_half_time = "Half time" in text or "HT" in text or "Half-time" in text
            
            # Fetch current state from DB
            res = supabase.table('fixtures').select('*').eq('hometeam', home_team).eq('awayteam', away_team).single().execute()
            if not res.data:
                continue
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
            if is_full_time and not db_match.get('result_sent'):
                home_am = AMHARIC_TEAMS.get(home_team, home_team)
                away_am = AMHARIC_TEAMS.get(away_team, away_team)
                msg = f"🏁 *የመጨረሻ ውጤት*\n{home_am} {h_score} - {a_score} {away_am}"
                send_telegram_message(msg)
                mark_match_state(
                    db_match['matchnumber'],
                    result_sent=True,
                    broadcaststatus='result_sent',
                    hometeamscore=int(h_score),
                    awayteamscore=int(a_score),
                )
                
    except Exception as e:
        error_msg = f"Live update processing error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)

def broadcast_daily():
    try:
        if not supabase:
            return
        if not has_matches_today():
            print("Skip daily: no fixtures scheduled today.")
            return

        today = get_eat_today()
        matches = [
            m for m in fetch_fixtures_for_dates([today])
            if not m.get('daily_sent')
        ]
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
            supabase.table('fixtures').update({
                "daily_sent": True,
                "broadcaststatus": 'scheduled',
            }).in_('matchnumber', match_ids).execute()
        else:
            print("Skip daily: today's fixtures were already broadcast.")
    except Exception as e:
        error_msg = f"Daily broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)

def broadcast_reminders():
    try:
        if not supabase:
            return
        if not has_upcoming_matches():
            print("Skip reminders: no fixtures in the next 60 minutes.")
            return

        now = get_eat_now().replace(tzinfo=None)
        matches = [
            m for m in fixtures_in_window(now, now + timedelta(minutes=60))
            if not m.get('reminder_sent')
        ]
        for m in matches:
            time = m['dateeat'].split(' ')[1]
            home_am = AMHARIC_TEAMS.get(m['hometeam'], m['hometeam'])
            away_am = AMHARIC_TEAMS.get(m['awayteam'], m['awayteam'])
            msg = f"🔔 *የጨዋታ ማሳሰቢያ!*\n\n⏰ {time} | {home_am} vs {away_am}\nተዘጋጁ! ⚽"
            send_telegram_message(msg)
            mark_match_state(
                m['matchnumber'],
                reminder_sent=True,
                broadcaststatus='reminded',
            )
        if not matches:
            print("Skip reminders: all upcoming fixtures were already reminded.")
    except Exception as e:
        error_msg = f"Reminder broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)

def broadcast_results():
    """Consolidated roundup for the day."""
    try:
        if not supabase:
            return
        if not has_pending_results():
            print("Skip results: no completed fixtures awaiting a results post.")
            return

        today = get_eat_today()
        results = [
            r for r in fetch_fixtures_for_dates([today])
            if r.get('hometeamscore') is not None
            and r.get('awayteamscore') is not None
            and not r.get('result_sent')
        ]
        if not results:
            return
        msg = f"🏁 *የጨዋታዎች ውጤት ({today})*\n\n"
        sent_ids = []
        for r in results:
            home_am = AMHARIC_TEAMS.get(r['hometeam'], r['hometeam'])
            away_am = AMHARIC_TEAMS.get(r['awayteam'], r['awayteam'])
            msg += f"• {home_am} {r['hometeamscore']} - {r['awayteamscore']} {away_am}\n"
            sent_ids.append(r['matchnumber'])
        send_telegram_message(msg)
        supabase.table('fixtures').update({
            "result_sent": True,
            "broadcaststatus": 'result_sent',
        }).in_('matchnumber', sent_ids).execute()
    except Exception as e:
        error_msg = f"Results broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)

def print_usage():
    print(
        "Usage: python3 telegram_broadcast.py "
        "[refresh|commands|live|daily|reminders|results|heartbeat]"
    )

if __name__ == '__main__':
    import sys
    if len(sys.argv) <= 1:
        print_usage()
    else:
        mode = sys.argv[1]
        if mode == 'refresh':
            update_fixtures_from_json()
        elif mode == 'commands':
            process_commands()
        elif mode == 'live':
            process_live_updates()
        elif mode == 'daily':
            broadcast_daily()
        elif mode == 'reminders':
            broadcast_reminders()
        elif mode == 'results':
            broadcast_results()
        elif mode == 'heartbeat':
            broadcast_heartbeat()
        else:
            print_usage()
