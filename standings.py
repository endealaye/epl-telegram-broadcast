import os
from collections import defaultdict
from functools import cmp_to_key

import requests

from bot_config import AMHARIC_TEAMS, TEAM_MAPPING
from commands import send_admin_alert, send_telegram_message
from store import supabase

OFFICIAL_STANDINGS_API_BASE = os.getenv(
    "PL_STANDINGS_API_BASE",
    "https://sdp-prem-prod.premier-league-prod.pulselive.com/api",
)
OFFICIAL_COMPETITION_ID = os.getenv("PL_STANDINGS_COMPETITION_ID", "8")
OFFICIAL_SEASON_ID = os.getenv("PL_STANDINGS_SEASON_ID", "2025")
DEFAULT_STANDINGS_FORMAT = os.getenv("PL_STANDINGS_FORMAT", "short").strip().lower()


def normalize_team_name(name):
    if not name:
        return ""
    return TEAM_MAPPING.get(name, name)


def parse_score(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_official_standings(
    competition_id=OFFICIAL_COMPETITION_ID,
    season_id=OFFICIAL_SEASON_ID,
    live=False,
):
    url = (
        f"{OFFICIAL_STANDINGS_API_BASE}/v5/competitions/{competition_id}"
        f"/seasons/{season_id}/standings"
    )
    response = requests.get(
        url,
        params={"live": str(bool(live)).lower()},
        timeout=25,
    )
    response.raise_for_status()
    return response.json()


def parse_official_standings(payload):
    tables = payload.get("tables") or []
    if not tables:
        return []
    entries = tables[0].get("entries") or []
    rows = []
    for entry in entries:
        team_info = entry.get("team") or {}
        overall = entry.get("overall") or {}
        team_short = (team_info.get("shortName") or "").strip()
        team_name = (team_info.get("name") or "").strip() or team_short
        team_key = normalize_team_name(team_short or team_name)
        rows.append(
            {
                "team": team_key or team_name,
                "team_display": team_name,
                "played": int(overall.get("played") or 0),
                "won": int(overall.get("won") or 0),
                "drawn": int(overall.get("drawn") or 0),
                "lost": int(overall.get("lost") or 0),
                "gf": int(overall.get("goalsFor") or 0),
                "ga": int(overall.get("goalsAgainst") or 0),
                "gd": int(overall.get("goalsFor") or 0) - int(overall.get("goalsAgainst") or 0),
                "points": int(overall.get("points") or 0),
                "position": int(overall.get("position") or 0),
            }
        )
    rows.sort(key=lambda row: row["position"])
    return rows


def fetch_completed_fixtures():
    if not supabase:
        return []
    query = supabase.table("fixtures").select(
        "hometeam,awayteam,hometeamscore,awayteamscore,dateeat"
    )
    try:
        season_start_year = int(OFFICIAL_SEASON_ID)
        season_start = f"{season_start_year}-08-01 00:00:00"
        season_end = f"{season_start_year + 1}-08-01 00:00:00"
        query = query.gte("dateeat", season_start).lt("dateeat", season_end)
    except (TypeError, ValueError):
        pass

    res = query.execute()
    completed = []
    for row in res.data or []:
        home = normalize_team_name(row.get("hometeam"))
        away = normalize_team_name(row.get("awayteam"))
        home_score = parse_score(row.get("hometeamscore"))
        away_score = parse_score(row.get("awayteamscore"))
        if not home or not away or home_score is None or away_score is None:
            continue
        completed.append(
            {
                "home": home,
                "away": away,
                "home_score": home_score,
                "away_score": away_score,
            }
        )
    return completed


def init_row(team):
    return {
        "team": team,
        "played": 0,
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "gf": 0,
        "ga": 0,
        "gd": 0,
        "points": 0,
    }


def update_row(row, scored, conceded):
    row["played"] += 1
    row["gf"] += scored
    row["ga"] += conceded
    if scored > conceded:
        row["won"] += 1
        row["points"] += 3
    elif scored == conceded:
        row["drawn"] += 1
        row["points"] += 1
    else:
        row["lost"] += 1


def base_sort_key(row):
    return (-row["points"], -row["gd"], -row["gf"], row["team"])


def h2h_stats(fixtures, tie_group):
    teams = {row["team"] for row in tie_group}
    stats = {team: {"points": 0, "away_goals": 0} for team in teams}
    for match in fixtures:
        home = match["home"]
        away = match["away"]
        if home not in teams or away not in teams:
            continue

        home_score = match["home_score"]
        away_score = match["away_score"]

        if home_score > away_score:
            stats[home]["points"] += 3
        elif home_score < away_score:
            stats[away]["points"] += 3
        else:
            stats[home]["points"] += 1
            stats[away]["points"] += 1

        stats[away]["away_goals"] += away_score
    return stats


def resolve_tie_group(fixtures, tie_group):
    stats = h2h_stats(fixtures, tie_group)

    def compare(a, b):
        a_stats = stats[a["team"]]
        b_stats = stats[b["team"]]
        if a_stats["points"] != b_stats["points"]:
            return -1 if a_stats["points"] > b_stats["points"] else 1
        if a_stats["away_goals"] != b_stats["away_goals"]:
            return -1 if a_stats["away_goals"] > b_stats["away_goals"] else 1
        return -1 if a["team"] < b["team"] else (1 if a["team"] > b["team"] else 0)

    return sorted(tie_group, key=cmp_to_key(compare))


def compute_standings(fixtures):
    table = defaultdict(dict)
    for match in fixtures:
        home = match["home"]
        away = match["away"]
        if home not in table:
            table[home] = init_row(home)
        if away not in table:
            table[away] = init_row(away)

        update_row(table[home], match["home_score"], match["away_score"])
        update_row(table[away], match["away_score"], match["home_score"])

    rows = list(table.values())
    for row in rows:
        row["gd"] = row["gf"] - row["ga"]

    rows.sort(key=base_sort_key)

    resolved = []
    idx = 0
    while idx < len(rows):
        current = rows[idx]
        tie_group = [current]
        next_idx = idx + 1
        while next_idx < len(rows):
            candidate = rows[next_idx]
            if (
                candidate["points"] == current["points"]
                and candidate["gd"] == current["gd"]
                and candidate["gf"] == current["gf"]
            ):
                tie_group.append(candidate)
                next_idx += 1
                continue
            break

        if len(tie_group) > 1:
            resolved.extend(resolve_tie_group(fixtures, tie_group))
        else:
            resolved.extend(tie_group)
        idx = next_idx

    for position, row in enumerate(resolved, start=1):
        row["position"] = position
    return resolved


def format_row(row):
    team_key = row.get("team") or ""
    team_display = row.get("team_display") or team_key
    team_am = AMHARIC_TEAMS.get(team_key, AMHARIC_TEAMS.get(team_display, team_display))
    gd_text = f"+{row['gd']}" if row["gd"] >= 0 else str(row["gd"])
    return (
        f"{row['position']:>2}. {team_am} ({team_display}) "
        f"{row['played']}ጨ {row['points']}ነጥብ "
        f"GD {gd_text} GF {row['gf']}"
    )


def format_short_row(row):
    team_key = row.get("team") or ""
    team_display = row.get("team_display") or team_key
    team_am = AMHARIC_TEAMS.get(team_key, AMHARIC_TEAMS.get(team_display, team_display))
    gd_text = f"+{row['gd']}" if row["gd"] >= 0 else str(row["gd"])
    return (
        f"{row['position']:>2}. {team_am} ({team_display}) "
        f"P {row['played']} W {row['won']} GD {gd_text} Pts {row['points']}"
    )


def format_team_cell(name, width=18):
    label = " ".join((name or "").split())
    if len(label) > width:
        return f"{label[:width - 3]}..."
    return label.ljust(width)


def format_short_table(rows):
    team_width = 18
    header = f"{'Pos':>3}  {'Team':<{team_width}}  {'P':>2} {'W':>2} {'GD':>4} {'Pts':>3}"
    divider = "-" * len(header)
    lines = [header, divider]
    for row in rows:
        team_key = row.get("team") or ""
        team_display = row.get("team_display") or team_key
        team_display = AMHARIC_TEAMS.get(team_key, AMHARIC_TEAMS.get(team_display, team_display))
        gd_text = f"{int(row['gd']):+d}"
        lines.append(
            f"{int(row['position']):>3}  {format_team_cell(team_display, team_width)}  "
            f"{int(row['played']):>2} {int(row['won']):>2} {gd_text:>4} {int(row['points']):>3}"
        )
    return "\n".join(lines)


def resolve_standings_format(format_name):
    value = (format_name or DEFAULT_STANDINGS_FORMAT or "short").strip().lower()
    if value in {"short", "s", "compact"}:
        return "short"
    return "full"


def format_standings_message(rows, source_label=None, matchweek=None, format_name=None):
    style = resolve_standings_format(format_name)
    header = "📊 *የፕሪሚየር ሊግ ደረጃ ሰንጠረዥ*"
    lines = [header, ""]
    if matchweek:
        lines.append(f"Matchweek: {matchweek}")
    if source_label and style != "short":
        lines.append(f"Source: {source_label}")
    if style != "short":
        lines.append(f"Format: {style}")
    if matchweek or (source_label and style != "short"):
        lines.append("")
    if style == "short":
        lines.append("```")
        lines.append(format_short_table(rows))
        lines.append("```")
    else:
        for row in rows:
            lines.append(format_row(row))
    lines.append("")
    lines.append("_Tie-break order: Points, GD, GF, H2H points, H2H away goals._")
    return "\n".join(lines)


def broadcast_standings(format_name=None):
    try:
        standings = []
        source = None
        matchweek = None
        fallback_reason = None

        try:
            official_payload = fetch_official_standings()
            standings = parse_official_standings(official_payload)
            matchweek = official_payload.get("matchweek")
            source = "premierleague.com official API"
        except Exception as official_exc:
            fallback_reason = str(official_exc)

        if not standings:
            fixtures = fetch_completed_fixtures()
            if fixtures:
                standings = compute_standings(fixtures)
                source = "local fixtures fallback"
            else:
                return {
                    "success": False,
                    "skipped": True,
                    "message": "Skip standings: no data from official API or local fixtures.",
                    "data": {
                        "source": "none",
                        "fallback_error": fallback_reason,
                    },
                }

        resolved_format = resolve_standings_format(format_name)
        message = format_standings_message(
            standings,
            source_label=source,
            matchweek=matchweek,
            format_name=resolved_format,
        )
        sent = send_telegram_message(message)
        if not sent:
            raise RuntimeError("Telegram delivery failed. Check bot configuration.")
        return {
            "success": True,
            "skipped": False,
            "message": f"Standings sent for {len(standings)} teams.",
            "data": {
                "teams": len(standings),
                "source": source,
                "matchweek": matchweek,
                "leader": standings[0]["team"] if standings else None,
                "fallback_error": fallback_reason,
                "format": resolved_format,
            },
        }
    except Exception as exc:
        error_msg = f"Standings broadcast error: {exc}"
        print(error_msg)
        try:
            send_admin_alert(error_msg)
        except Exception as alert_exc:
            print(f"Admin alert failed: {alert_exc}")
        return {
            "success": False,
            "skipped": False,
            "message": error_msg,
            "data": {},
        }
