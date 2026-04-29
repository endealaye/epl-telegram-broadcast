from collections import defaultdict
from datetime import timedelta

from bot_config import AMHARIC_TEAMS, get_eat_now, get_eat_today
from commands import send_admin_alert, send_telegram_message
from store import (
    fetch_fixtures_for_dates,
    fixtures_in_window,
    has_matches_today,
    has_pending_results,
    has_upcoming_matches,
    mark_match_state,
    supabase,
)


def broadcast_daily():
    try:
        if not supabase:
            return
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
            time = match['dateeat'].split(' ')[1]
            home_am = AMHARIC_TEAMS.get(match['hometeam'], match['hometeam'])
            away_am = AMHARIC_TEAMS.get(match['awayteam'], match['awayteam'])
            time_groups[time].append(f"• {home_am} vs {away_am}")
            match_ids.append(match['matchnumber'])

        msg = f"📅 *የዛሬ የኢንግሊዝ ፕሪሚየር ሊግ ጨዋታዎች ({today})*\n\n"
        for time in sorted(time_groups.keys()):
            msg += f"⏰ *{time}*\n" + "\n".join(time_groups[time]) + "\n\n"
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
            time = match['dateeat'].split(' ')[1]
            home_am = AMHARIC_TEAMS.get(match['hometeam'], match['hometeam'])
            away_am = AMHARIC_TEAMS.get(match['awayteam'], match['awayteam'])
            msg = f"🔔 *የጨዋታ ማሳሰቢያ!*\n\n⏰ {time} | {home_am} vs {away_am}\nተዘጋጁ! ⚽"
            send_telegram_message(msg)
            mark_match_state(match['matchnumber'], reminder_sent=True, broadcaststatus='reminded')
    except Exception as e:
        error_msg = f"Reminder broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)


def broadcast_results():
    try:
        if not supabase:
            return
        if not has_pending_results():
            print("Skip results: no completed fixtures awaiting a results post.")
            return

        today = get_eat_today()
        results = [
            result for result in fetch_fixtures_for_dates([today])
            if result.get('hometeamscore') is not None
            and result.get('awayteamscore') is not None
            and not result.get('result_sent')
        ]
        if not results:
            return

        msg = f"🏁 *የጨዋታዎች ውጤት ({today})*\n\n"
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
    except Exception as e:
        error_msg = f"Results broadcast error: {e}"
        print(error_msg)
        send_admin_alert(error_msg)
