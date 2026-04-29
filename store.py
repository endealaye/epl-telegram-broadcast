from datetime import timedelta

from supabase import Client, create_client

from bot_config import SUPABASE_KEY, SUPABASE_URL, get_eat_now, get_eat_today, parse_eat_datetime


supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_fixtures_for_dates(date_strings):
    if not supabase:
        return []

    fixtures = []
    seen_match_numbers = set()
    for date_string in date_strings:
        res = supabase.table('fixtures').select("*").ilike('dateeat', f'{date_string}%').execute()
        for fixture in res.data or []:
            match_number = fixture.get('matchnumber')
            if match_number in seen_match_numbers:
                continue
            fixtures.append(fixture)
            seen_match_numbers.add(match_number)
    return fixtures


def fixtures_in_window(start_dt, end_dt):
    date_strings = {start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d')}
    fixtures = fetch_fixtures_for_dates(sorted(date_strings))
    window_matches = []
    for fixture in fixtures:
        kickoff = parse_eat_datetime(fixture.get('dateeat'))
        if kickoff and start_dt <= kickoff <= end_dt:
            window_matches.append(fixture)
    return window_matches


def has_matches_today():
    return bool(fetch_fixtures_for_dates([get_eat_today()]))


def has_upcoming_matches(minutes=60):
    now = get_eat_now().replace(tzinfo=None)
    return bool(fixtures_in_window(now, now + timedelta(minutes=minutes)))


def has_live_window_matches():
    now = get_eat_now().replace(tzinfo=None)
    return bool(fixtures_in_window(now - timedelta(minutes=30), now + timedelta(hours=4)))


def has_pending_results():
    fixtures = fetch_fixtures_for_dates([get_eat_today()])
    return any(
        fixture.get('hometeamscore') is not None
        and fixture.get('awayteamscore') is not None
        and not fixture.get('result_sent')
        for fixture in fixtures
    )


def mark_match_state(match_number, **fields):
    if not supabase:
        return
    supabase.table('fixtures').update(fields).eq('matchnumber', match_number).execute()
