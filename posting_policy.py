from datetime import timedelta

from bot_config import get_eat_now, get_eat_today, parse_eat_datetime
from store import fetch_fixtures_for_dates, fixture_competition_name


COMPETITION_PRIORITY = {
    "Premier League": 0,
    "UEFA Champions League": 1,
    "UEFA Europa League": 2,
    "UEFA Conference League": 3,
}


def _fixtures_for_policy_window(now=None):
    current = (now or get_eat_now()).replace(tzinfo=None)
    date_strings = sorted(
        {
            (current - timedelta(days=1)).strftime("%Y-%m-%d"),
            current.strftime("%Y-%m-%d"),
            (current + timedelta(days=1)).strftime("%Y-%m-%d"),
        }
    )
    fixtures = fetch_fixtures_for_dates(date_strings)
    return current, fixtures


def _kickoff_for_fixture(fixture):
    kickoff = parse_eat_datetime(fixture.get("dateeat"))
    return kickoff if kickoff else None


def classify_match_day(now=None):
    current, fixtures = _fixtures_for_policy_window(now=now)
    today = current.strftime("%Y-%m-%d")
    today_fixtures = []
    live_fixtures = []
    upcoming_fixtures = []
    completed_today = []

    for fixture in fixtures:
        kickoff = _kickoff_for_fixture(fixture)
        if not kickoff:
            continue
        if kickoff.strftime("%Y-%m-%d") != today:
            continue
        today_fixtures.append(fixture)

        if kickoff - timedelta(minutes=90) <= current <= kickoff + timedelta(hours=4):
            live_fixtures.append(fixture)
        elif current < kickoff:
            upcoming_fixtures.append(fixture)

        if fixture.get("hometeamscore") is not None and fixture.get("awayteamscore") is not None:
            completed_today.append(fixture)

    competitions = sorted(
        {fixture_competition_name(fixture) for fixture in today_fixtures},
        key=lambda name: (COMPETITION_PRIORITY.get(name, 99), name),
    )

    if live_fixtures:
        state = "live_match_day"
    elif upcoming_fixtures:
        state = "pre_match_day"
    elif completed_today:
        state = "post_match_day"
    else:
        state = "no_match_day"

    if len(today_fixtures) >= 6:
        slate = "heavy"
    elif len(today_fixtures) >= 3:
        slate = "normal"
    elif len(today_fixtures) >= 1:
        slate = "light"
    else:
        slate = "none"

    lead_fixture = None
    if today_fixtures:
        lead_fixture = sorted(
            today_fixtures,
            key=lambda fixture: (
                COMPETITION_PRIORITY.get(fixture_competition_name(fixture), 99),
                _kickoff_for_fixture(fixture) or current,
            ),
        )[0]

    return {
        "state": state,
        "today": get_eat_today(),
        "fixture_count": len(today_fixtures),
        "live_count": len(live_fixtures),
        "upcoming_count": len(upcoming_fixtures),
        "completed_count": len(completed_today),
        "slate": slate,
        "competitions": competitions,
        "lead_competition": fixture_competition_name(lead_fixture) if lead_fixture else None,
    }


def should_run_live(policy):
    return bool((policy or {}).get("live_count"))


def should_send_daily(policy):
    return bool((policy or {}).get("fixture_count"))


def should_send_reminders(policy):
    return bool((policy or {}).get("upcoming_count"))


def build_policy_summary(policy):
    if not policy:
        return "No policy state available."
    competitions = ", ".join(policy.get("competitions") or []) or "none"
    return (
        f"state={policy.get('state')} | fixtures={policy.get('fixture_count', 0)} | "
        f"live={policy.get('live_count', 0)} | upcoming={policy.get('upcoming_count', 0)} | "
        f"completed={policy.get('completed_count', 0)} | competitions={competitions}"
    )
