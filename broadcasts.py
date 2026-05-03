from collections import defaultdict
from datetime import datetime, timedelta, timezone
import uuid

from bot_config import AMHARIC_TEAMS, get_eat_now, get_eat_today, parse_eat_datetime
from commands import send_admin_alert, send_telegram_message
from standings import broadcast_standings
from store import (
    acquire_bot_lock,
    fetch_fixtures_for_dates,
    fixtures_in_window,
    get_bot_state_value,
    has_matches_today,
    has_pending_results,
    has_upcoming_matches,
    mark_match_state,
    release_bot_lock,
    set_bot_state_value,
    supabase,
)


def _format_kickoff_time_eat(match):
    dateeat = match.get("dateeat")
    kickoff = parse_eat_datetime(dateeat)
    if kickoff:
        return kickoff.strftime("%H:%M")

    dateutc = match.get("dateutc")
    if dateutc:
        try:
            dt_utc = datetime.strptime(dateutc, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=timezone.utc)
            return (dt_utc + timedelta(hours=3)).strftime("%H:%M")
        except ValueError:
            pass

    if dateeat and " " in dateeat:
        return dateeat.split(" ")[1][:5]
    return "??:??"


def _has_final_score(fixture):
    return fixture.get('hometeamscore') is not None and fixture.get('awayteamscore') is not None


def _results_date_scope():
    today = get_eat_today()
    yesterday = (get_eat_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return [yesterday, today]


def _should_send_standings_after_results(today_fixtures):
    if not today_fixtures:
        return False

    with_kickoff = []
    for fixture in today_fixtures:
        kickoff = parse_eat_datetime(fixture.get('dateeat'))
        if kickoff:
            with_kickoff.append((kickoff, fixture))

    if not with_kickoff:
        return all(_has_final_score(fixture) for fixture in today_fixtures)

    latest_kickoff = max(kickoff for kickoff, _ in with_kickoff)
    latest_matches = [fixture for kickoff, fixture in with_kickoff if kickoff == latest_kickoff]
    return bool(latest_matches) and all(_has_final_score(fixture) for fixture in latest_matches)


def broadcast_daily():
    try:
        if not supabase:
            return
        # Rule: clear unsent final scores before posting today's fixtures list.
        result_scope = _results_date_scope()
        if has_pending_results(date_strings=result_scope):
            broadcast_results(date_strings=result_scope)

        if not has_matches_today():
            print("Skip daily: no fixtures scheduled today.")
            return

        today = get_eat_today()
        matches = [m for m in fetch_fixtures_for_dates([today]) if not m.get('daily_sent')]
        if not matches:
            print("Skip daily: today's fixtures were already broadcast.")
            return

        time_groups = defaultdict(list)
        match_ids = []
        for match in matches:
            time = _format_kickoff_time_eat(match)
            home_am = AMHARIC_TEAMS.get(match['hometeam'], match['hometeam'])
            away_am = AMHARIC_TEAMS.get(match['awayteam'], match['awayteam'])
            time_groups[time].append(f"• {home_am} vs {away_am}")
            match_ids.append(match['matchnumber'])

        msg = f"📅 *የዛሬ የኢንግሊዝ ፕሪሚየር ሊግ ጨዋታዎች ({today})*\n\n"
        for time in sorted(time_groups.keys()):
            msg += f"⏰ *{time} EAT*\n" + "\n".join(time_groups[time]) + "\n\n"
        send_telegram_message(msg)
        supabase.table('fixtures').update({
            "daily_sent": True,
            "broadcaststatus": 'scheduled',
        }).in_('matchnumber', match_ids).execute()
    except Exception as e:
        error_msg = f"Daily broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)


def broadcast_reminders():
    try:
        if not supabase:
            return
        if not has_upcoming_matches():
            print("Skip reminders: no fixtures in the next 60 minutes.")
            return

        now = get_eat_now().replace(tzinfo=None)
        matches = [
            match for match in fixtures_in_window(now, now + timedelta(minutes=60))
            if not match.get('reminder_sent')
        ]
        if not matches:
            print("Skip reminders: all upcoming fixtures were already reminded.")
            return

        for match in matches:
            time = _format_kickoff_time_eat(match)
            home_am = AMHARIC_TEAMS.get(match['hometeam'], match['hometeam'])
            away_am = AMHARIC_TEAMS.get(match['awayteam'], match['awayteam'])
            msg = f"🔔 *የጨዋታ ማሳሰቢያ!*\n\n⏰ {time} EAT | {home_am} vs {away_am}\nተዘጋጁ! ⚽"
            send_telegram_message(msg)
            mark_match_state(match['matchnumber'], reminder_sent=True, broadcaststatus='reminded')
    except Exception as e:
        error_msg = f"Reminder broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)


def broadcast_results(date_strings=None):
    today = get_eat_today()
    if date_strings is None:
        date_strings = _results_date_scope()
    lock_key = f"lock:results:{today}"
    lock_owner = f"results:{uuid.uuid4()}"
    try:
        if not supabase:
            return
        if not acquire_bot_lock(lock_key=lock_key, owner=lock_owner, ttl_seconds=600):
            print("Skip results: another run currently holds the results lock.")
            return
        if not has_pending_results(date_strings=date_strings):
            print("Skip results: no completed fixtures awaiting a results post.")
            return

        results = [
            result for result in fetch_fixtures_for_dates(date_strings)
            if result.get('hometeamscore') is not None
            and result.get('awayteamscore') is not None
            and not result.get('result_sent')
        ]
        if not results:
            return

        results.sort(key=lambda item: item.get("dateeat") or "")
        msg = "🏁 *የጨዋታዎች ውጤት*\n\n"
        sent_ids = []
        for result in results:
            home_am = AMHARIC_TEAMS.get(result['hometeam'], result['hometeam'])
            away_am = AMHARIC_TEAMS.get(result['awayteam'], result['awayteam'])
            msg += f"• {home_am} {result['hometeamscore']} - {result['awayteamscore']} {away_am}\n"
            sent_ids.append(result['matchnumber'])

        send_telegram_message(msg)
        supabase.table('fixtures').update({
            "result_sent": True,
            "broadcaststatus": 'result_sent',
        }).in_('matchnumber', sent_ids).execute()

        refreshed_today = fetch_fixtures_for_dates([today])
        standings_sent_key = f"standings:auto:sent:{today}"
        standings_already_sent = bool(get_bot_state_value(standings_sent_key))
        if _should_send_standings_after_results(refreshed_today) and not standings_already_sent:
            standings_result = broadcast_standings(format_name="short")
            if standings_result.get("success"):
                set_bot_state_value(standings_sent_key, get_eat_now().isoformat())
    except Exception as e:
        error_msg = f"Results broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)
    finally:
        if supabase:
            release_bot_lock(lock_key=lock_key, owner=lock_owner)
