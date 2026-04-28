import json
import sqlite3
import requests
import os
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# Load .env file
def load_env():
    # Only load from file if required variables are not already in environment (e.g. GitHub Actions)
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
DB_FILE = 'epl_2025.db'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

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

def update_fixtures_from_json():
    try:
        response = requests.get(JSON_URL)
        response.raise_for_status()
        data = response.json()

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fixtures (
                MatchNumber INTEGER PRIMARY KEY,
                RoundNumber INTEGER,
                DateUtc TEXT,
                Location TEXT,
                HomeTeam TEXT,
                AwayTeam TEXT,
                MatchGroup TEXT,
                HomeTeamScore INTEGER,
                AwayTeamScore INTEGER,
                DateEAT TEXT,
                BroadcastStatus TEXT DEFAULT 'pending'
            )
        ''')

        for match in data:
            utc_date = match.get('DateUtc')
            eat_date = None
            if utc_date:
                try:
                    dt = datetime.strptime(utc_date, '%Y-%m-%d %H:%M:%SZ')
                    eat_date = (dt + timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass

            cursor.execute('''
                INSERT OR REPLACE INTO fixtures 
                (MatchNumber, RoundNumber, DateUtc, Location, HomeTeam, AwayTeam, MatchGroup, HomeTeamScore, AwayTeamScore, DateEAT)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                match.get('MatchNumber'),
                match.get('RoundNumber'),
                utc_date,
                match.get('Location'),
                match.get('HomeTeam'),
                match.get('AwayTeam'),
                match.get('Group'),
                match.get('HomeTeamScore'),
                match.get('AwayTeamScore'),
                eat_date
            ))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating fixtures: {e}")
        return False

def scrape_bbc_scores():
    try:
        response = requests.get(BBC_SCORES_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        matches_found = 0
        for link in soup.find_all('a', href=re.compile(r'/sport/football/live/')):
            text = link.get_text(" ", strip=True)
            match = re.search(r'(.+?)\s+(\d+)\s*,\s*(.+?)\s+(\d+)\s+at\s+Full\s+time', text)
            if match:
                home_raw, home_score, away_raw, away_score = match.groups()
                home_team = TEAM_MAPPING.get(home_raw.strip())
                away_team = TEAM_MAPPING.get(away_raw.strip())
                
                if home_team and away_team:
                    cursor.execute('''
                        UPDATE fixtures 
                        SET HomeTeamScore = ?, AwayTeamScore = ? 
                        WHERE HomeTeam = ? AND AwayTeam = ?
                    ''', (home_score, away_score, home_team, away_team))
                    if cursor.rowcount > 0:
                        matches_found += 1
        
        conn.commit()
        conn.close()
        print(f"Scraped and updated {matches_found} match scores from BBC.")
        return True
    except Exception as e:
        print(f"Error scraping BBC scores: {e}")
        return False

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set. Printing to console instead:")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending telegram message: {e}")

def broadcast_daily():
    """Daily summary of matches."""
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT DateEAT, HomeTeam, AwayTeam, MatchNumber FROM fixtures WHERE DateEAT LIKE ?", (f'{today}%',))
    matches = cursor.fetchall()
    
    if matches:
        msg = f"📅 *Today's EPL Matches ({today})*\n\n"
        match_ids = []
        for m in matches:
            time = m[0].split(' ')[1]
            msg += f"⏰ {time} | {m[1]} vs {m[2]}\n"
            match_ids.append(m[3])
        
        send_telegram_message(msg)
        
        # Mark as scheduled
        cursor.execute(f"UPDATE fixtures SET BroadcastStatus = 'scheduled' WHERE MatchNumber IN ({','.join(map(str, match_ids))})")
        conn.commit()
    else:
        print("No matches today.")
    conn.close()

def broadcast_reminders():
    """Reminders for matches starting in the next 60 minutes."""
    now = datetime.now()
    window_start = now.strftime('%Y-%m-%d %H:%M:%S')
    window_end = (now + timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Matches starting in the next hour that haven't been reminded yet
    cursor.execute('''
        SELECT DateEAT, HomeTeam, AwayTeam, MatchNumber 
        FROM fixtures 
        WHERE DateEAT BETWEEN ? AND ? AND (BroadcastStatus = 'pending' OR BroadcastStatus = 'scheduled')
    ''', (window_start, window_end))
    
    matches = cursor.fetchall()
    for m in matches:
        time = m[0].split(' ')[1]
        msg = f"🔔 *Upcoming Match Alert!*\n\n⏰ {time} | {m[1]} vs {m[2]}\nGet ready! ⚽"
        send_telegram_message(msg)
        cursor.execute("UPDATE fixtures SET BroadcastStatus = 'reminded' WHERE MatchNumber = ?", (m[3],))
    
    conn.commit()
    conn.close()

def broadcast_results():
    """Broadcast final scores for matches that just finished today."""
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Only broadcast results for matches that happened TODAY and haven't been sent
    cursor.execute('''
        SELECT HomeTeam, AwayTeam, HomeTeamScore, AwayTeamScore, MatchNumber 
        FROM fixtures 
        WHERE DateEAT LIKE ? AND HomeTeamScore IS NOT NULL AND (BroadcastStatus != 'result_sent')
    ''', (f'{today}%',))
    
    results = cursor.fetchall()
    for r in results:
        msg = f"🏁 *Final Score*\n{r[0]} {r[2]} - {r[3]} {r[1]}"
        send_telegram_message(msg)
        cursor.execute("UPDATE fixtures SET BroadcastStatus = 'result_sent' WHERE MatchNumber = ?", (r[4],))
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    import sys
    update_fixtures_from_json()
    scrape_bbc_scores()
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == 'daily':
            broadcast_daily()
        elif mode == 'reminders':
            broadcast_reminders()
        elif mode == 'results':
            broadcast_results()
        else:
            print("Usage: python3 telegram_broadcast.py [daily|reminders|results]")
    else:
        print("Usage: python3 telegram_broadcast.py [daily|reminders|results]")
