from store import fetch_fixtures_for_dates
from live import FIFAWorldCupProvider, SkySportsProvider, BBCProvider, _merged_scores
import json

def main():
    dates = ['2026-07-06', '2026-07-07']
    fixtures = fetch_fixtures_for_dates(dates)
    
    providers = [FIFAWorldCupProvider(), SkySportsProvider(), BBCProvider()]
    merged_scores = _merged_scores(providers)
    
    results = []
    for fixture in fixtures:
        home = fixture.get('hometeam')
        away = fixture.get('awayteam')
        date = fixture.get('date')
        
        for score in merged_scores:
            if score['mapped_home'] == home and score['mapped_away'] == away:
                results.append({
                    'date': date,
                    'home': home,
                    'away': away,
                    'score': score['score_key'],
                    'competition': score.get('competition'),
                    'status': score.get('text').split(' ')[-1] # Extract status like FT or LIVE
                })
    
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
