from datetime import datetime, timedelta, timezone

import requests

from bot_config import JSON_URL
from store import supabase


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
                "DateEAT": eat_date,
            }).execute()
        return True
    except Exception as e:
        print(f"Error updating fixtures: {e}")
        return False
