import re

import requests
from bs4 import BeautifulSoup

from bot_config import (
    AMHARIC_TEAMS,
    BBC_SCORES_URL,
    BBC_SCORES_URL_TEMPLATE,
    SKY_SCORES_API_URL,
    TEAM_MAPPING,
    get_eat_today,
)
from commands import send_admin_alert, send_telegram_message
from store import has_live_window_matches, mark_match_state, supabase


class ScoreProvider:
    def get_scores(self):
        raise NotImplementedError


class BBCProvider(ScoreProvider):
    def get_scores(self):
        candidate_urls = [
            BBC_SCORES_URL_TEMPLATE.format(date=get_eat_today()),
            BBC_SCORES_URL,
        ]
        for url in candidate_urls:
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
                        })
                if scores:
                    return scores
            except Exception as e:
                print(f"BBCProvider error ({url}): {e}")
        return []


class SkySportsProvider(ScoreProvider):
    def get_scores(self):
        try:
            response = requests.get(SKY_SCORES_API_URL, timeout=10)
            response.raise_for_status()
            payload = response.json()
            scores = []
            for item in payload:
                match = item.get('match') or {}
                competition = (((match.get('competition') or {}).get('name') or {}).get('full') or "").strip()
                if competition != "Premier League":
                    continue

                teams = match.get('teams') or {}
                home = teams.get('home') or {}
                away = teams.get('away') or {}
                home_score = home.get('score') or {}
                away_score = away.get('score') or {}

                home_name = ((home.get('name') or {}).get('full') or "").strip()
                away_name = ((away.get('name') or {}).get('full') or "").strip()
                h_score = home_score.get('current')
                a_score = away_score.get('current')

                if not home_name or not away_name:
                    continue
                if h_score is None or a_score is None:
                    continue

                match_state = (match.get('matchState') or "").strip().lower()
                is_full_time = bool(match.get('isResult'))
                is_half_time = match_state in {"ht", "half-time", "halftime", "half time"}
                is_in_play = bool(match.get('isInPlay') or match.get('currentlyPlaying'))

                # Ignore pre-match fixtures (0-0 before kickoff) and only emit active/final states.
                if not (is_in_play or is_half_time or is_full_time):
                    continue

                status = "FT" if is_full_time else "HT" if is_half_time else "LIVE"
                scores.append({
                    'home': home_name,
                    'h_score': str(h_score),
                    'away': away_name,
                    'a_score': str(a_score),
                    'text': f"{home_name} {h_score}-{a_score} {away_name} {status}",
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
