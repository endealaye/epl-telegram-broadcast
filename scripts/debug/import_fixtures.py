import json
import sqlite3

from bot_config import CURRENT_EPL_SEASON

JSON_FILE = '/Users/nebiyou.yirga/.local/share/opencode/tool-output/tool_dd2cae36d001zQycuMDzSx0Bop'
DB_FILE = 'epl_2025.db'

def main():
    with open(JSON_FILE, 'r') as f:
        data = json.load(f)

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
            Season TEXT,
            HomeTeamScore INTEGER,
            AwayTeamScore INTEGER
        )
    ''')
    try:
        cursor.execute("ALTER TABLE fixtures ADD COLUMN Season TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise

    for match in data:
        cursor.execute('''
            INSERT OR REPLACE INTO fixtures 
            (MatchNumber, RoundNumber, DateUtc, Location, HomeTeam, AwayTeam, MatchGroup, Season, HomeTeamScore, AwayTeamScore)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            match.get('MatchNumber'),
            match.get('RoundNumber'),
            match.get('DateUtc'),
            match.get('Location'),
            match.get('HomeTeam'),
            match.get('AwayTeam'),
            match.get('Group'),
            CURRENT_EPL_SEASON,
            match.get('HomeTeamScore'),
            match.get('AwayTeamScore')
        ))

    conn.commit()
    conn.close()
    print(f"Successfully imported {len(data)} matches into {DB_FILE}")

if __name__ == '__main__':
    main()
