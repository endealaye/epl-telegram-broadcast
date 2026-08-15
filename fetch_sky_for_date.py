import requests
from bs4 import BeautifulSoup
import re
from bot_config import SKY_SCORES_URL_TEMPLATE

def fetch_sky_for_date(date):
    url = SKY_SCORES_URL_TEMPLATE.format(date=date)
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        # Sky Sports fixtures page structure is different from the API.
        # I'll look for any text containing "Portugal" and "Spain" and a score.
        page_text = soup.get_text()
        print(f"Page content snippet: {page_text[:2000]}")
        
        # Look for a pattern like Portugal 0-1 Spain or Spain 1-0 Portugal
        # This is a crude search, but let's see.
        matches = re.findall(r'(Portugal\s*(\d+)\s*-\s*(\d+)\s*Spain|Spain\s*(\d+)\s*-\s*(\d+)\s*Portugal)', page_text)
        return matches
    except Exception as e:
        print(f"SkySportsProvider error ({url}): {e}")
        return []

if __name__ == "__main__":
    print(fetch_sky_for_date("2026-07-06"))
