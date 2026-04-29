import re

import requests
from bs4 import BeautifulSoup

from bot_config import AMHARIC_TEAMS, BBC_SCORES_URL, SKY_SCORES_URL, TEAM_MAPPING
from commands import send_admin_alert, send_telegram_message
from store import has_live_window_matches, mark_match_state, supabase


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
                        'text': text,
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
                        'text': text,
                    })
            return scores
        except Exception as e:
            print(f"SkySportsProvider error: {e}")
            return None


def process_live_updates():
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
            home_team = TEAM_MAPPING.get(match_data['home'])
            away_team = TEAM_MAPPING.get(match_data['away'])

            if not home_team or not away_team:
                continue

            current_score_str = f"{h_score}-{a_score}"
            is_full_time = "Full time" in text or "FT" in text or "Full-time" in text
            is_half_time = "Half time" in text or "HT" in text or "Half-time" in text

            res = supabase.table('fixtures').select('*').eq('hometeam', home_team).eq('awayteam', away_team).single().execute()
            if not res.data:
                continue
            db_match = res.data
            last_score = db_match.get('last_broadcast_score')

            if not is_full_time and current_score_str != last_score:
                home_am = AMHARIC_TEAMS.get(home_team, home_team)
                away_am = AMHARIC_TEAMS.get(away_team, away_team)
                msg = f"⚽ *ጎል ተቆጠረ!*\n\n{home_am} {h_score} - {a_score} {away_am}"
                send_telegram_message(msg)
                mark_match_state(db_match['matchnumber'], last_broadcast_score=current_score_str)

            if is_half_time and not db_match.get('half_time_sent'):
                home_am = AMHARIC_TEAMS.get(home_team, home_team)
                away_am = AMHARIC_TEAMS.get(away_team, away_team)
                msg = f"⏸️ *የእረፍት ጊዜ ውጤት*\n\n{home_am} {h_score} - {a_score} {away_am}"
                send_telegram_message(msg)
                mark_match_state(db_match['matchnumber'], half_time_sent=True)

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
