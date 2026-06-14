import json
import os
from datetime import datetime, timedelta, timezone

from supabase import Client, ClientOptions, create_client

from bot_config import CURRENT_EPL_SEASON, SUPABASE_KEY, SUPABASE_URL, get_eat_now, get_eat_today, parse_eat_datetime


supabase: Client = None
SUPABASE_DB_TIMEOUT_SECONDS = float(os.getenv("SUPABASE_DB_TIMEOUT_SECONDS", "8"))
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_KEY,
        options=ClientOptions(postgrest_client_timeout=SUPABASE_DB_TIMEOUT_SECONDS),
    )

LIVE_POLLING_WINDOW_MINUTES = int(os.getenv("LIVE_POLLING_WINDOW_MINUTES", "105"))
KNOCKOUT_LIVE_POLLING_WINDOW_MINUTES = int(os.getenv("KNOCKOUT_LIVE_POLLING_WINDOW_MINUTES", "165"))

def _safe_execute(query, default=None, context="supabase"):
    try:
        return query.execute()
    except Exception as exc:
        print(f"Supabase query failed ({context}): {exc}")
        return default


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_bot_state_value(key):
    if not supabase:
        return None
    res = _safe_execute(
        supabase.table('bot_state').select('key,value').eq('key', key).limit(1),
        default=None,
        context=f"bot_state.get:{key}",
    )
    if res is None:
        return None
    rows = res.data or []
    return rows[0].get('value') if rows else None


def set_bot_state_value(key, value):
    if not supabase:
        return False
    res = _safe_execute(
        supabase.table('bot_state').upsert(
            {"key": key, "value": value},
            on_conflict="key",
        ),
        default=None,
        context=f"bot_state.set:{key}",
    )
    return res is not None


def _parse_lock_value(raw_value):
    if not raw_value:
        return None
    try:
        payload = json.loads(raw_value)
    except (TypeError, ValueError):
        return None
    owner = payload.get("owner")
    expires_at = _parse_iso_datetime(payload.get("expires_at"))
    if not owner or not expires_at:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return {"owner": owner, "expires_at": expires_at}


def acquire_bot_lock(lock_key, owner, ttl_seconds=300):
    if not supabase:
        return False

    now = datetime.now(timezone.utc)
    existing = _parse_lock_value(get_bot_state_value(lock_key))
    if existing and existing["owner"] != owner and existing["expires_at"] > now:
        return False

    expires_at = now + timedelta(seconds=max(30, int(ttl_seconds)))
    lock_payload = json.dumps(
        {
            "owner": owner,
            "expires_at": expires_at.isoformat(),
        }
    )
    set_bot_state_value(lock_key, lock_payload)

    confirmed = _parse_lock_value(get_bot_state_value(lock_key))
    return bool(confirmed and confirmed["owner"] == owner and confirmed["expires_at"] > now)


def release_bot_lock(lock_key, owner):
    if not supabase:
        return False

    current = _parse_lock_value(get_bot_state_value(lock_key))
    if current and current["owner"] != owner:
        return False

    expired_payload = json.dumps(
        {
            "owner": owner,
            "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        }
    )
    return set_bot_state_value(lock_key, expired_payload)


def fetch_fixtures_for_dates(date_strings):
    if not supabase:
        return []

    fixtures = []
    seen_match_numbers = set()
    for date_string in date_strings:
        res = _safe_execute(
            supabase.table('fixtures').select("*").ilike('dateeat', f'{date_string}%'),
            default=None,
            context=f"fixtures.fetch:{date_string}",
        )
        if res is None:
            continue
        for fixture in res.data or []:
            match_number = fixture.get('matchnumber')
            if match_number in seen_match_numbers:
                continue
            fixtures.append(fixture)
            seen_match_numbers.add(match_number)
    return fixtures


def fixture_competition_name(fixture):
    if not fixture:
        return ""
    return (fixture.get("matchgroup") or "Premier League").strip()


def season_start_year(season):
    label = (season or "").strip()
    if not label:
        return None
    try:
        return int(label.split("-", 1)[0])
    except ValueError:
        return None


def season_date_bounds(season):
    start_year = season_start_year(season)
    if start_year is None:
        return None, None
    return f"{start_year}-08-01 00:00:00", f"{start_year + 1}-08-01 00:00:00"


def fetch_premier_league_clubs_for_season(season=None):
    if not supabase:
        return set()

    target_season = season or CURRENT_EPL_SEASON
    rows = []
    res = _safe_execute(
        supabase.table("fixtures")
        .select("hometeam,awayteam")
        .eq("matchgroup", "Premier League")
        .eq("season", target_season),
        default=None,
        context=f"fixtures.clubs.season:{target_season}",
    )
    if res is not None:
        rows = res.data or []
    else:
        start_date, end_date = season_date_bounds(target_season)
        query = (
            supabase.table("fixtures")
            .select("hometeam,awayteam")
            .eq("matchgroup", "Premier League")
        )
        if start_date and end_date:
            query = query.gte("dateeat", start_date).lt("dateeat", end_date)
        fallback = _safe_execute(
            query,
            default=None,
            context=f"fixtures.clubs.date_fallback:{target_season}",
        )
        rows = (fallback.data or []) if fallback is not None else []

    clubs = set()
    for row in rows:
        if row.get("hometeam"):
            clubs.add(row["hometeam"])
        if row.get("awayteam"):
            clubs.add(row["awayteam"])
    return clubs


def is_premier_league_fixture(fixture):
    return fixture_competition_name(fixture) == "Premier League"


def is_world_cup_fixture(fixture):
    return fixture_competition_name(fixture).startswith("FIFA World Cup")


def is_world_cup_group_fixture(fixture):
    return fixture_competition_name(fixture).startswith("FIFA World Cup - Group ")


def fixture_allows_extra_time(fixture):
    return is_world_cup_fixture(fixture) and not is_world_cup_group_fixture(fixture)


def fixture_live_window_minutes(fixture):
    if fixture_allows_extra_time(fixture):
        return max(120, KNOCKOUT_LIVE_POLLING_WINDOW_MINUTES)
    return max(90, LIVE_POLLING_WINDOW_MINUTES)


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


def is_in_live_polling_window(fixture, now=None, window_minutes=LIVE_POLLING_WINDOW_MINUTES):
    current = (now or get_eat_now()).replace(tzinfo=None)
    kickoff = parse_eat_datetime(fixture.get('dateeat'))
    if not kickoff:
        return False
    configured_window = max(int(window_minutes), fixture_live_window_minutes(fixture))
    return kickoff <= current <= kickoff + timedelta(minutes=configured_window)


def has_live_window_matches():
    today = get_eat_today()
    tomorrow = (get_eat_now() + timedelta(days=1)).strftime('%Y-%m-%d')
    fixtures = fetch_fixtures_for_dates([today, tomorrow])
    now = get_eat_now().replace(tzinfo=None)
    return any(is_in_live_polling_window(fixture, now=now) for fixture in fixtures)


def has_pending_results(date_strings=None):
    if date_strings is None:
        today = get_eat_today()
        yesterday = (get_eat_now() - timedelta(days=1)).strftime('%Y-%m-%d')
        date_strings = [yesterday, today]

    fixtures = fetch_fixtures_for_dates(date_strings)
    return any(
        fixture.get('hometeamscore') is not None
        and fixture.get('awayteamscore') is not None
        and not fixture.get('result_sent')
        for fixture in fixtures
    )


def mark_match_state(match_number, **fields):
    if not supabase:
        return
    _safe_execute(
        supabase.table('fixtures').update(fields).eq('matchnumber', match_number),
        default=None,
        context=f"fixtures.update:{match_number}",
    )
