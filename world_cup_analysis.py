from datetime import datetime, timedelta, timezone

from bot_config import AMHARIC_TEAMS, SHORT_AMHARIC_TEAMS
from bot_config import TELEGRAM_ADMIN_ID
from commands import send_telegram_message
from store import get_bot_state_value, set_bot_state_value, supabase
from telegram_limits import (
    TELEGRAM_ANALYSIS_CAPTION_TARGET,
    TELEGRAM_ANALYSIS_MAX_LINES,
    compact_analysis_text,
    telegram_limit_status,
)
from world_cup_form import fetch_team_recent_form
from world_cup_squad_audit import FIFA_ALL_SQUAD_ANNOUNCEMENTS_URL, FIFA_SQUADS_CONFIRMED_URL
from world_cup_standings import WORLD_CUP_MATCHNUMBER_MAX, WORLD_CUP_MATCHNUMBER_MIN


SKY_SQUADS_URL = (
    "https://www.skysports.com/football/news/11095/13543070/"
    "world-cup-2026-squad-lists-england-scotland-brazil-usa-spain-france-"
    "germany-netherlands-argentina-portugal-and-more/"
)
WIKIPEDIA_SQUADS_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
QUALIFIER_SOURCE_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_qualification"
FIXTURE_SOURCE_URLS = [
    "https://fixturedownload.com/feed/json/fifa-world-cup-2026",
    "https://github.com/openfootball/worldcup.json",
]
HOST_TEAMS_WITHOUT_QUALIFIER_FORM = {"Canada", "Mexico", "USA"}
KEY_POSITION_ORDER = {"FW": 0, "MF": 1, "DF": 2, "GK": 3}
VALID_REVIEW_STATUSES = {"draft", "approved", "published", "rejected"}
ANALYSIS_REVIEW_WINDOW_HOURS = 8
ANALYSIS_PUBLISH_WINDOW_MINUTES = 90


def _team_am(team_name, short=False):
    if short:
        return SHORT_AMHARIC_TEAMS.get(team_name) or AMHARIC_TEAMS.get(team_name, team_name)
    return AMHARIC_TEAMS.get(team_name, team_name)


def _group_name(matchgroup):
    return (matchgroup or "").replace("FIFA World Cup - ", "")


def _fixture_title(fixture):
    return f"{_team_am(fixture['hometeam'], short=True)} vs {_team_am(fixture['awayteam'], short=True)} - ቅድመ ጨዋታ እይታ"


def _fixture_kickoff(fixture):
    dateeat = fixture.get("dateeat") or ""
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(dateeat, date_format)
            return parsed.strftime("%Y-%m-%d %H:%M EAT")
        except ValueError:
            continue
    return dateeat


def _parse_fixture_kickoff(fixture):
    dateeat = fixture.get("dateeat") or ""
    try:
        return datetime.strptime(dateeat, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _fetch_group_fixtures():
    if not supabase:
        return []
    res = (
        supabase.table("fixtures")
        .select("matchnumber,hometeam,awayteam,matchgroup,dateeat,source_status,source_notes")
        .gte("matchnumber", WORLD_CUP_MATCHNUMBER_MIN)
        .lte("matchnumber", WORLD_CUP_MATCHNUMBER_MAX)
        .like("matchgroup", "FIFA World Cup - Group %")
        .order("matchnumber")
        .execute()
    )
    return res.data or []


def _fetch_existing_analysis():
    if not supabase:
        return {}
    res = (
        supabase.table("match_analysis")
        .select("matchnumber,review_status,body")
        .eq("analysis_type", "preview")
        .eq("language", "am")
        .execute()
    )
    return {row["matchnumber"]: row for row in res.data or []}


def _fetch_analysis_rows(status):
    if not supabase:
        return []
    res = (
        supabase.table("match_analysis")
        .select("matchnumber,title,body,confidence,review_status,updated_at,source_urls")
        .eq("analysis_type", "preview")
        .eq("language", "am")
        .eq("review_status", status)
        .execute()
    )
    return res.data or []


def _fetch_world_cup_fixture_map():
    return {
        fixture["matchnumber"]: fixture
        for fixture in _fetch_group_fixtures()
        if fixture.get("matchnumber") is not None
    }


def _analysis_with_fixtures(status, *, now=None, window=None):
    current = (now or datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
    fixture_map = _fetch_world_cup_fixture_map()
    items = []
    for row in _fetch_analysis_rows(status):
        fixture = fixture_map.get(row.get("matchnumber"))
        kickoff = _parse_fixture_kickoff(fixture or {})
        if not fixture or not kickoff:
            continue
        if kickoff < current:
            continue
        if window and kickoff > current + window:
            continue
        items.append({**row, "fixture": fixture, "kickoff": kickoff})
    return sorted(items, key=lambda item: (item["kickoff"], item.get("matchnumber") or 0))


def _analysis_item_label(item):
    fixture = item.get("fixture") or {}
    kickoff = item.get("kickoff")
    kickoff_text = kickoff.strftime("%Y-%m-%d %H:%M EAT") if kickoff else _fixture_kickoff(fixture)
    return (
        f"#{item.get('matchnumber')} "
        f"{fixture.get('hometeam')} vs {fixture.get('awayteam')} "
        f"({kickoff_text})"
    )


def _fetch_availability_map():
    if not supabase:
        return {}
    res = (
        supabase.table("world_cup_player_availability")
        .select("team_name,player_name,status,note,source_url,reported_at")
        .in_("status", ["injured", "suspended", "doubtful"])
        .execute()
    )
    availability = {}
    for row in res.data or []:
        availability.setdefault(row["team_name"], {})[row["player_name"]] = row
    return availability


def _fetch_team_story_map():
    if not supabase:
        return {}
    res = (
        supabase.table("world_cup_teams")
        .select("team_name,raw_payload")
        .execute()
    )
    teams = {}
    for row in res.data or []:
        coach = ((row.get("raw_payload") or {}).get("coach") or {})
        teams[row["team_name"]] = {
            "coach_name": coach.get("name"),
            "coach_source_url": coach.get("source_url"),
        }
    return teams


def _player_caps(player):
    raw = player.get("raw_payload") or {}
    try:
        return int(raw.get("caps") or 0)
    except (TypeError, ValueError):
        return 0


def _player_sort_key(player):
    return (
        KEY_POSITION_ORDER.get(player.get("position") or "", 9),
        -_player_caps(player),
        player.get("player_name") or "",
    )


def _fetch_players_to_watch(team_name, availability, limit=2):
    if not supabase:
        return []
    unavailable = availability.get(team_name, {})
    res = (
        supabase.table("world_cup_players")
        .select("player_name,position,source_status,raw_payload")
        .eq("team_name", team_name)
        .execute()
    )
    players = []
    for player in res.data or []:
        status = (unavailable.get(player["player_name"]) or {}).get("status")
        if status in {"injured", "suspended"}:
            continue
        players.append(player)
    players.sort(key=_player_sort_key)
    return players[:limit]


def _format_player(player):
    raw = player.get("raw_payload") or {}
    shirt = raw.get("shirt_number")
    prefix = f"#{shirt} " if shirt else ""
    return f"{prefix}{player.get('player_name')}"


def _form_sentence(team_name, form):
    team = _team_am(team_name, short=True)
    if form["played"] <= 0:
        if team_name in HOST_TEAMS_WITHOUT_QUALIFIER_FORM:
            return f"{team} አዘጋጅ ቡድን ስለሆነች የማጣሪያ ፎርም መረጃ የለውም።"
        return f"{team} የቅርብ ጊዜ ማጣሪያ ፎርም መረጃ አልተገኘለትም።"
    return (
        f"{team} በመጨረሻዎቹ {form['played']} የማጣሪያ ጨዋታዎች "
        f"{form['won']} አሸንፎ፣ {form['drawn']} አቻ ወጥቶ፣ {form['lost']} ተሸንፏል። "
        f"ጎል {form['goals_for']}-{form['goals_against']}።"
    )


def _edge_line(home_team, away_team, home_form, away_form):
    if home_form["played"] < 3 or away_form["played"] < 3:
        return "⚖️ ትንሽ ብልጫ: ግልጽ አይደለም"

    home_score = (home_form["won"] * 3) + home_form["drawn"]
    away_score = (away_form["won"] * 3) + away_form["drawn"]
    home_gd = home_form["goals_for"] - home_form["goals_against"]
    away_gd = away_form["goals_for"] - away_form["goals_against"]
    if home_score >= away_score + 4 and home_gd > away_gd:
        return f"⚖️ ትንሽ ብልጫ: {_team_am(home_team, short=True)} በፎርም"
    if away_score >= home_score + 4 and away_gd > home_gd:
        return f"⚖️ ትንሽ ብልጫ: {_team_am(away_team, short=True)} በፎርም"
    return "⚖️ ትንሽ ብልጫ: ግልጽ አይደለም"


def _confidence(fixture, home_form, away_form):
    if fixture.get("source_status") == "mismatch":
        return "speculative"
    if home_form["played"] >= 3 and away_form["played"] >= 3:
        return "source_based"
    return "partial"


def _confidence_am(confidence):
    return {
        "source_based": "መረጃ ላይ የተመሰረተ",
        "partial": "ከፊል",
        "speculative": "ደካማ",
    }.get(confidence, "ከፊል")


def _availability_note(team_name, availability):
    rows = availability.get(team_name, {})
    unavailable = [name for name, row in rows.items() if row.get("status") in {"injured", "suspended"}]
    doubtful = [name for name, row in rows.items() if row.get("status") == "doubtful"]
    notes = []
    if unavailable:
        notes.append(f"{', '.join(unavailable[:2])} አይገኙም")
    if doubtful:
        notes.append(f"{', '.join(doubtful[:2])} ጤናው ጥያቄ ላይ ነው")
    if not notes:
        return None
    return f"{_team_am(team_name, short=True)}: {'፤ '.join(notes)}።"


def _coach_line(home_team, away_team, team_story):
    home_coach = (team_story.get(home_team) or {}).get("coach_name")
    away_coach = (team_story.get(away_team) or {}).get("coach_name")
    if not home_coach and not away_coach:
        return None
    parts = []
    if home_coach:
        parts.append(f"{_team_am(home_team, short=True)}: {home_coach}")
    if away_coach:
        parts.append(f"{_team_am(away_team, short=True)}: {away_coach}")
    return "🧠 አሰልጣኞች: " + " | ".join(parts)


def _coach_source_urls(home_team, away_team, team_story):
    urls = []
    for team_name in [home_team, away_team]:
        source_url = (team_story.get(team_name) or {}).get("coach_source_url")
        if source_url and source_url not in urls:
            urls.append(source_url)
    return urls


def build_preview(fixture, availability, team_story=None):
    team_story = team_story or {}
    home = fixture["hometeam"]
    away = fixture["awayteam"]
    group = _group_name(fixture.get("matchgroup"))
    home_form = fetch_team_recent_form(home)
    away_form = fetch_team_recent_form(away)
    home_players = _fetch_players_to_watch(home, availability)
    away_players = _fetch_players_to_watch(away, availability)
    confidence = _confidence(fixture, home_form, away_form)

    lines = [
        f"🏆 {group}",
        f"🕘 {_fixture_kickoff(fixture)}",
        "",
        "📊 ቅድመ ጨዋታ እይታ",
    ]
    coach_line = _coach_line(home, away, team_story)
    if coach_line:
        lines.append(coach_line)
    lines.extend(
        [
            _form_sentence(home, home_form),
            _form_sentence(away, away_form),
            "",
            "👀 ሊታዩ የሚገባቸው",
        ]
    )
    for player in home_players:
        lines.append(f"{_team_am(home, short=True)}: {_format_player(player)}")
    for player in away_players:
        lines.append(f"{_team_am(away, short=True)}: {_format_player(player)}")

    availability_notes = [
        note
        for note in (_availability_note(home, availability), _availability_note(away, availability))
        if note
    ]
    if availability_notes:
        lines.extend(["", "🚑 የተጫዋቾች ሁኔታ", *availability_notes])

    data_note = "📌 መረጃ: ጨዋታ/ስኳድ ተረጋግጧል፤ ፎርም ከማጣሪያ ጨዋታዎች ነው።"
    if fixture.get("source_status") == "mismatch":
        data_note = "📌 መረጃ: የጨዋታ ምንጮች ልዩነት አለ፤ ከመላክ በፊት ይፈትሹ።"

    lines.extend(
        [
            "",
            _edge_line(home, away, home_form, away_form),
            f"🔒 እርግጠኝነት: {_confidence_am(confidence)}",
            data_note,
        ]
    )
    body = compact_analysis_text("\n".join(lines), has_image=True)
    return {
        "title": _fixture_title(fixture),
        "body": body,
        "confidence": confidence,
        "source_urls": [
            *FIXTURE_SOURCE_URLS,
            FIFA_SQUADS_CONFIRMED_URL,
            FIFA_ALL_SQUAD_ANNOUNCEMENTS_URL,
            WIKIPEDIA_SQUADS_URL,
            SKY_SQUADS_URL,
            QUALIFIER_SOURCE_URL,
            *_coach_source_urls(home, away, team_story),
        ],
        "limit_status": telegram_limit_status(
            body,
            has_image=True,
            target=TELEGRAM_ANALYSIS_CAPTION_TARGET,
            max_lines=TELEGRAM_ANALYSIS_MAX_LINES,
        ),
    }


def generate_group_stage_previews():
    if not supabase:
        return {"generated": 0, "skipped": 0, "items": []}

    fixtures = _fetch_group_fixtures()
    existing = _fetch_existing_analysis()
    availability = _fetch_availability_map()
    team_story = _fetch_team_story_map()
    payload = []
    items = []
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()

    for fixture in fixtures:
        current = existing.get(fixture["matchnumber"])
        if current and current.get("review_status") in {"approved", "published"}:
            skipped += 1
            continue
        preview = build_preview(fixture, availability, team_story=team_story)
        row = {
            "matchnumber": fixture["matchnumber"],
            "analysis_type": "preview",
            "language": "am",
            "title": preview["title"],
            "body": preview["body"],
            "confidence": preview["confidence"],
            "source_urls": preview["source_urls"],
            "review_status": "draft",
            "updated_at": now,
        }
        payload.append(row)
        items.append(
            {
                "matchnumber": fixture["matchnumber"],
                "title": preview["title"],
                "confidence": preview["confidence"],
                "limit_status": preview["limit_status"],
                "source_status": fixture.get("source_status"),
            }
        )

    if payload:
        supabase.table("match_analysis").upsert(
            payload,
            on_conflict="matchnumber,analysis_type,language",
        ).execute()

    return {
        "generated": len(payload),
        "skipped": skipped,
        "fixtures": len(fixtures),
        "items": items,
    }


def list_analysis_queue(limit=20, status="draft"):
    if not supabase:
        return []
    res = (
        supabase.table("match_analysis")
        .select("matchnumber,title,body,confidence,review_status,updated_at,source_urls")
        .eq("analysis_type", "preview")
        .eq("language", "am")
        .eq("review_status", status)
        .order("matchnumber")
        .limit(limit)
        .execute()
    )
    items = []
    for row in res.data or []:
        limit_status = telegram_limit_status(
            row.get("body") or "",
            has_image=True,
            target=TELEGRAM_ANALYSIS_CAPTION_TARGET,
            max_lines=TELEGRAM_ANALYSIS_MAX_LINES,
        )
        items.append({**row, "limit_status": limit_status})
    return items


def mark_analysis_preview(matchnumber, status):
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"Invalid review status: {status}")
    if not supabase:
        return None
    res = (
        supabase.table("match_analysis")
        .update({"review_status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("matchnumber", int(matchnumber))
        .eq("analysis_type", "preview")
        .eq("language", "am")
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def send_analysis_review_reminder(window_hours=ANALYSIS_REVIEW_WINDOW_HOURS):
    if not supabase:
        return {"sent": False, "count": 0, "items": []}

    items = _analysis_with_fixtures(
        "draft",
        window=timedelta(hours=int(window_hours)),
    )
    if not items:
        return {"sent": False, "count": 0, "items": []}

    matchnumbers = [str(item.get("matchnumber")) for item in items]
    marker = ",".join(matchnumbers)
    state_key = "world_cup_analysis_review_reminder_last"
    if get_bot_state_value(state_key) == marker:
        return {
            "sent": False,
            "skipped": True,
            "count": len(items),
            "items": [_analysis_item_label(item) for item in items],
        }

    lines = [
        "📝 *World Cup analysis review needed*",
        "",
        f"Pending previews in the next {int(window_hours)} hours:",
    ]
    lines.extend(f"• `{_analysis_item_label(item)}`" for item in items[:12])
    if len(items) > 12:
        lines.append(f"• …and {len(items) - 12} more")
    lines.extend(
        [
            "",
            "Approve with:",
            "`python3 telegram_broadcast.py world-cup-analysis-mark <matchnumber> approved`",
        ]
    )

    sent = send_telegram_message("\n".join(lines), chat_id=TELEGRAM_ADMIN_ID)
    if sent:
        set_bot_state_value(state_key, marker)
    return {
        "sent": bool(sent),
        "count": len(items),
        "items": [_analysis_item_label(item) for item in items],
    }


def publish_due_analysis(window_minutes=ANALYSIS_PUBLISH_WINDOW_MINUTES):
    if not supabase:
        return {"published": 0, "items": []}

    items = _analysis_with_fixtures(
        "approved",
        window=timedelta(minutes=int(window_minutes)),
    )
    published = []
    for item in items:
        title = item.get("title") or _fixture_title(item["fixture"])
        body = item.get("body") or ""
        message = f"*{title}*\n\n{body}".strip()
        if not send_telegram_message(message):
            continue
        updated = mark_analysis_preview(item["matchnumber"], "published")
        if updated:
            published.append(_analysis_item_label(item))

    return {"published": len(published), "items": published}
