import json
import sqlite3
import requests
import os
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# Load .env file
def load_env():
    env_path = '.env'
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
                DateEAT TEXT
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
        
        # Find all match elements. Looking at the BBC structure, 
        # match summaries are often in <a> tags within <li>.
        matches_found = 0
        for link in soup.find_all('a', href=re.compile(r'/sport/football/live/')):
            text = link.get_text(" ", strip=True)
            # Expected format: "HomeTeam Score , AwayTeam Score at Full time"
            # Example: "Manchester United 2 , Brentford 1 at Full time"
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

def broadcast_today_matches():
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT DateEAT, HomeTeam, AwayTeam FROM fixtures WHERE DateEAT LIKE ?", (f'{today}%',))
    matches = cursor.fetchall()
    conn.close()

    if matches:
        msg = f"📅 *Today's EPL Matches ({today})*\n\n"
        for m in matches:
            time = m[0].split(' ')[1]
            msg += f"⏰ {time} | {m[1]} vs {m[2]}\n"
        send_telegram_message(msg)
    else:
        print("No matches today.")

def broadcast_results():
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT HomeTeam, AwayTeam, HomeTeamScore, AwayTeamScore FROM fixtures WHERE DateEAT LIKE ? AND HomeTeamScore IS NOT NULL", (f'{today}%',))
    results = cursor.fetchall()
    conn.close()

    if not results:
        print("No results to broadcast for today.")
        return

    # To avoid spamming, you might want to track which results were already sent.
    # For now, we broadcast all today's results.
    for r in results:
        msg = f"🏁 *Final Score*\n{r[0]} {r[2]} - {r[3]} {r[1]}"
        send_telegram_message(msg)

if __name__ == '__main__':
    import sys
    # Always try to update fixtures first, then scrape for scores
    update_fixtures_from_json()
    scrape_bbc_scores()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == 'daily':
            broadcast_today_matches()
        elif sys.argv[1] == 'results':
            broadcast_results()
    else:
        print("Usage: python3 telegram_broadcast.py [daily|results]")
