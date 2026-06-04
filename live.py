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
from sync import sky_result_overrides_for_date
from store import (
    fetch_fixtures_for_dates,
    fixture_competition_name,
    get_bot_state_value,
    has_live_window_matches,
    is_in_live_polling_window,
    is_premier_league_fixture,
    mark_match_state,
    set_bot_state_value,
    supabase,
)


LIVE_COMPETITIONS = {
    "Premier League",
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Conference League",
    "FIFA World Cup",
    "World Cup",
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


def _parse_status(text):
    is_full_time = "Full time" in text or "FT" in text or "Full-time" in text
    is_half_time = "Half time" in text or "HT" in text or "Half-time" in text
    return is_full_time, is_half_time


def _status_rank(match_data):
    is_full_time, is_half_time = _parse_status(match_data.get("text", ""))
    if is_full_time:
        return 3
    if is_half_time:
        return 2
    return 1


def _merged_scores(providers):
    merged = {}
    for provider in providers:
        scores = provider.get_scores() or []
        for match_data in scores:
            home_team = TEAM_MAPPING.get(match_data['home'], match_data['home'])
            away_team = TEAM_MAPPING.get(match_data['away'], match_data['away'])

            competition_name = (match_data.get('competition') or "").strip()
            current_score_str = f"{match_data['h_score']}-{match_data['a_score']}"
            key = (home_team, away_team, competition_name or "")
            candidate = {
                **match_data,
                "mapped_home": home_team,
                "mapped_away": away_team,
                "score_key": current_score_str,
            }

            existing = merged.get(key)
            if not existing:
                merged[key] = candidate
                continue

            if _status_rank(candidate) > _status_rank(existing):
                merged[key] = candidate
                continue

            if (
                _status_rank(candidate) == _status_rank(existing)
                and not existing.get("competition")
                and candidate.get("competition")
            ):
                merged[key] = candidate
    return list(merged.values())


def _find_db_match(home_team, away_team, competition_name, now):
    res = supabase.table('fixtures').select('*').eq('hometeam', home_team).eq('awayteam', away_team).execute()
    matches = res.data or []
    for candidate in matches:
        candidate_competition = fixture_competition_name(candidate)
        competition_matches = (
            not competition_name
            or candidate_competition == competition_name
            or (
                competition_name in {"FIFA World Cup", "World Cup"}
                and candidate_competition.startswith("FIFA World Cup")
            )
        )
        if (
            is_in_live_polling_window(candidate, now=now)
            and competition_matches
        ):
            return candidate
    for candidate in matches:
        kickoff = parse_eat_datetime(candidate.get('dateeat'))
        candidate_competition = fixture_competition_name(candidate)
        competition_matches = (
            not competition_name
            or candidate_competition == competition_name
            or (
                competition_name in {"FIFA World Cup", "World Cup"}
                and candidate_competition.startswith("FIFA World Cup")
            )
        )
        if (
            kickoff
            and kickoff.date() == now.date()
            and competition_matches
        ):
            return candidate
    return None


def _send_full_time_message(db_match, h_score, a_score):
    competition_title, home_am, away_am = _format_match_title(db_match)
    msg = (
        f"🏁 *የመጨረሻ ውጤት*\n\n"
        f"🏆 {competition_title}\n"
        f"{home_am} {h_score} - {a_score} {away_am}"
    )
    send_telegram_message(msg)


def _finalize_match(db_match, h_score, a_score, send_message=True):
    if send_message:
        _send_full_time_message(db_match, h_score, a_score)
    mark_match_state(
        db_match['matchnumber'],
        broadcaststatus='live_final_sent',
        hometeamscore=int(h_score),
        awayteamscore=int(a_score),
        last_broadcast_score=f"{h_score}-{a_score}",
    )


def _should_send_standings_after_results(today_fixtures):
    premier_league_fixtures = [fixture for fixture in today_fixtures if is_premier_league_fixture(fixture)]
    if not premier_league_fixtures:
        return False

    with_kickoff = []
    for fixture in premier_league_fixtures:
        kickoff = parse_eat_datetime(fixture.get('dateeat'))
        if kickoff:
            with_kickoff.append((kickoff, fixture))

    if not with_kickoff:
        return all(
            fixture.get('hometeamscore') is not None and fixture.get('awayteamscore') is not None
            for fixture in premier_league_fixtures
        )

    latest_kickoff = max(kickoff for kickoff, _ in with_kickoff)
    latest_matches = [fixture for kickoff, fixture in with_kickoff if kickoff == latest_kickoff]
    return bool(latest_matches) and all(
        fixture.get('hometeamscore') is not None and fixture.get('awayteamscore') is not None
        for fixture in latest_matches
    )

def _reconcile_overdue_matches(score_map, now):
    date_strings = sorted(
        {
            (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
        }
    )
    dated_result_overrides = {}
    for date_string in date_strings:
        try:
            dated_result_overrides.update(sky_result_overrides_for_date(date_string, competitions=LIVE_COMPETITIONS))
        except Exception as exc:
            print(f"Sky dated result fallback failed for {date_string}: {exc}")

    for db_match in supabase.table('fixtures').select('*').in_('matchgroup', list(LIVE_COMPETITIONS)).execute().data or []:
        kickoff = parse_eat_datetime(db_match.get('dateeat'))
        if not kickoff or kickoff.strftime("%Y-%m-%d") not in date_strings:
            continue
        if db_match.get('result_sent'):
            continue
        if db_match.get('hometeamscore') is not None or db_match.get('awayteamscore') is not None:
            continue
        if kickoff > now - timedelta(hours=2):
            continue

        competition_name = fixture_competition_name(db_match)
        dated_override = dated_result_overrides.get(
            (db_match.get('hometeam'), db_match.get('awayteam'), competition_name)
        )
        if dated_override:
            h_score, a_score = dated_override
            _finalize_match(db_match, h_score, a_score, send_message=not db_match.get('result_sent'))
            continue

        score_entry = score_map.get((db_match.get('hometeam'), db_match.get('awayteam'), competition_name))
        if score_entry:
            is_full_time, _ = _parse_status(score_entry.get('text', ''))
            if is_full_time or kickoff <= now - timedelta(hours=4):
                _finalize_match(db_match, score_entry['h_score'], score_entry['a_score'], send_message=not db_match.get('result_sent'))
                continue

        fallback_score = db_match.get('last_broadcast_score') or ""
        if kickoff <= now - timedelta(hours=4) and re.fullmatch(r"\d+-\d+", fallback_score):
            h_score, a_score = fallback_score.split("-", 1)
            _finalize_match(db_match, h_score, a_score, send_message=not db_match.get('result_sent'))


def process_live_updates():
    if not supabase:
        return
    providers = [SkySportsProvider(), BBCProvider()]
    now = get_eat_now().replace(tzinfo=None)
    all_scores = _merged_scores(providers)
    score_map = {
        (item["mapped_home"], item["mapped_away"], (item.get("competition") or "").strip()): item
        for item in all_scores
    }
    _reconcile_overdue_matches(score_map, now)

    if not has_live_window_matches():
        print("Skip live: no fixtures in the active live window.")
        return

    if not all_scores:
        return

    try:
        for match_data in all_scores:
            text = match_data['text']
            h_score = match_data['h_score']
            a_score = match_data['a_score']
            competition_name = (match_data.get('competition') or "").strip()
            home_team = match_data['mapped_home']
            away_team = match_data['mapped_away']

            current_score_str = f"{h_score}-{a_score}"
            is_full_time, is_half_time = _parse_status(text)
            score_total = int(h_score) + int(a_score)

            db_match = _find_db_match(home_team, away_team, competition_name, now)
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
                _finalize_match(db_match, h_score, a_score)
    except Exception as e:
        error_msg = f"Live update processing error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)
