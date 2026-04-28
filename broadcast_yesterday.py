import sqlite3
import requests
import os
from datetime import datetime, timedelta

def load_env():
    env_path = '.env'
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value.strip("'\"")

load_env()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
DB_FILE = 'epl_2025.db'

# Calculate yesterday's date
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("SELECT HomeTeam, HomeTeamScore, AwayTeamScore, AwayTeam FROM fixtures WHERE DateEAT LIKE ? AND HomeTeamScore IS NOT NULL", (f'{yesterday}%',))
results = cursor.fetchall()
conn.close()

if not results:
    print(f"No results found for yesterday ({yesterday}).")
else:
    for r in results:
        msg = f"🏁 *Final Score (Yesterday)*\n{r[0]} {r[1]} - {r[2]} {r[3]}"
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        response = requests.post(url, json=payload)
        print(f"Sent {r[0]} vs {r[3]}: {response.status_code}")
