import re
import requests
from bs4 import BeautifulSoup
from bot_config import BBC_SCORES_URL_TEMPLATE, SKY_SCORES_API_URL, TEAM_MAPPING
from live import FIFAWorldCupProvider, SkySportsProvider, BBCProvider

def fetch_bbc_for_date(date):
    url = BBC_SCORES_URL_TEMPLATE.format(date=date)
    try:
        response = requests.get(url, timeout=10)
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
                    'text': text,
                    'provider': 'BBC'
                })
        return scores
    except Exception as e:
        print(f"BBCProvider error ({url}): {e}")
        return []

def main():
    match_date = "2026-07-06"
    target_teams = {"Portugal", "Spain"}
    
    results = {}

    # FIFA
    fifa = FIFAWorldCupProvider()
    fifa_scores = fifa.get_scores()
    for s in (fifa_scores or []):
        home = TEAM_MAPPING.get(s['home'], s['home'])
        away = TEAM_MAPPING.get(s['away'], s['away'])
        if {home, away} == target_teams:
            results['FIFA'] = s

    # Sky
    sky = SkySportsProvider()
    sky_scores = sky.get_scores()
    for s in (sky_scores or []):
        home = TEAM_MAPPING.get(s['home'], s['home'])
        away = TEAM_MAPPING.get(s['away'], s['away'])
        if {home, away} == target_teams:
            results['Sky'] = s

    # BBC
    bbc_scores = fetch_bbc_for_date(match_date)
    for s in bbc_scores:
        home = TEAM_MAPPING.get(s['home'], s['home'])
        away = TEAM_MAPPING.get(s['away'], s['away'])
        if {home, away} == target_teams:
            results['BBC'] = s

    import json
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
