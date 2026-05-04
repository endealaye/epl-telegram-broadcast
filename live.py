import re
from datetime import timedelta

import requests
from bs4 import BeautifulSoup

from bot_config import (
    AMHARIC_TEAMS,
    BBC_SCORES_URL,
    BBC_SCORES_URL_TEMPLATE,
    SKY_SCORES_API_URL,
    TEAM_MAPPING,
    get_eat_now,
    get_eat_today,
    parse_eat_datetime,
)
from commands import send_admin_alert, send_telegram_message
from store import fixture_competition_name, has_live_window_matches, mark_match_state, supabase


LIVE_COMPETITIONS = {
    "Premier League",
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Conference League",
}


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
                            'competition': None,
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
                if competition not in LIVE_COMPETITIONS:
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
                    'competition': competition,
                })
            return scores
        except Exception as e:
            print(f"SkySportsProvider error: {e}")
            return None


def _format_match_title(fixture):
    competition = fixture_competition_name(fixture)
    home_team = fixture.get("hometeam") or ""
    away_team = fixture.get("awayteam") or ""
    home_am = AMHARIC_TEAMS.get(home_team, home_team)
    away_am = AMHARIC_TEAMS.get(away_team, away_team)
    return competition, home_am, away_am


def process_live_updates():
    if not supabase:
        return
    if not has_live_window_matches():
        print("Skip live: no fixtures in the active live window.")
        return

    providers = [SkySportsProvider(), BBCProvider()]
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
            competition_name = (match_data.get('competition') or "").strip()
            home_team = TEAM_MAPPING.get(match_data['home'])
            away_team = TEAM_MAPPING.get(match_data['away'])

            if not home_team or not away_team:
                continue

            current_score_str = f"{h_score}-{a_score}"
            is_full_time = "Full time" in text or "FT" in text or "Full-time" in text
            is_half_time = "Half time" in text or "HT" in text or "Half-time" in text
            score_total = int(h_score) + int(a_score)

            res = supabase.table('fixtures').select('*').eq('hometeam', home_team).eq('awayteam', away_team).execute()
            matches = res.data or []
            now = get_eat_now().replace(tzinfo=None)
            window_start = now - timedelta(hours=3)
            window_end = now + timedelta(hours=4)
            db_match = None
            for candidate in matches:
                kickoff = parse_eat_datetime(candidate.get('dateeat'))
                candidate_competition = fixture_competition_name(candidate)
                if (
                    kickoff
                    and window_start <= kickoff <= window_end
                    and (not competition_name or candidate_competition == competition_name)
                ):
                    db_match = candidate
                    break
            if not db_match and matches:
                for candidate in matches:
                    kickoff = parse_eat_datetime(candidate.get('dateeat'))
                    candidate_competition = fixture_competition_name(candidate)
                    if (
                        kickoff
                        and kickoff.date() == now.date()
                        and (not competition_name or candidate_competition == competition_name)
                    ):
                        db_match = candidate
                        break
            if not db_match:
                continue
            last_score = db_match.get('last_broadcast_score')
            competition_title, home_am, away_am = _format_match_title(db_match)

            if not is_full_time and current_score_str != last_score and score_total > 0:
                msg = (
                    f"⚽ *ጎል ተቆጠረ!*\n\n"
                    f"🏆 {competition_title}\n"
                    f"{home_am} {h_score} - {a_score} {away_am}"
                )
                send_telegram_message(msg)
                mark_match_state(db_match['matchnumber'], last_broadcast_score=current_score_str)

            if is_half_time and not db_match.get('half_time_sent'):
                msg = (
                    f"⏸️ *የእረፍት ጊዜ ውጤት*\n\n"
                    f"🏆 {competition_title}\n"
                    f"{home_am} {h_score} - {a_score} {away_am}"
                )
                send_telegram_message(msg)
                mark_match_state(db_match['matchnumber'], half_time_sent=True)

            if is_full_time and not db_match.get('result_sent'):
                msg = (
                    f"🏁 *የመጨረሻ ውጤት*\n\n"
                    f"🏆 {competition_title}\n"
                    f"{home_am} {h_score} - {a_score} {away_am}"
                )
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
