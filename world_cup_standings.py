from collections import defaultdict
from functools import cmp_to_key

from bot_config import AMHARIC_TEAMS, SHORT_AMHARIC_TEAMS
from store import supabase


WORLD_CUP_MATCHNUMBER_MIN = 2_026_001
WORLD_CUP_MATCHNUMBER_MAX = 2_026_104


def _team_display_am(team_name):
    return SHORT_AMHARIC_TEAMS.get(team_name) or AMHARIC_TEAMS.get(team_name, team_name)


def _empty_row(group_name, team_name):
    return {
        "group_name": group_name,
        "team_name": team_name,
        "played": 0,
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "goals_for": 0,
        "goals_against": 0,
        "goal_difference": 0,
        "points": 0,
    }


def _apply_result(row, scored, conceded):
    row["played"] += 1
    row["goals_for"] += scored
    row["goals_against"] += conceded
    row["goal_difference"] = row["goals_for"] - row["goals_against"]
    if scored > conceded:
        row["won"] += 1
        row["points"] += 3
    elif scored < conceded:
        row["lost"] += 1
    else:
        row["drawn"] += 1
        row["points"] += 1


def _base_sort_key(row):
    return (
        -row["points"],
        -row["goal_difference"],
        -row["goals_for"],
        row["team_name"],
    )


def _head_to_head_stats(matches, teams):
    stats = {team: {"points": 0, "goal_difference": 0, "goals_for": 0} for team in teams}
    for match in matches:
        home = match["hometeam"]
        away = match["awayteam"]
        if home not in teams or away not in teams:
            continue
        home_score = match.get("hometeamscore")
        away_score = match.get("awayteamscore")
        if home_score is None or away_score is None:
            continue

        stats[home]["goals_for"] += home_score
        stats[home]["goal_difference"] += home_score - away_score
        stats[away]["goals_for"] += away_score
        stats[away]["goal_difference"] += away_score - home_score
        if home_score > away_score:
            stats[home]["points"] += 3
        elif home_score < away_score:
            stats[away]["points"] += 3
        else:
            stats[home]["points"] += 1
            stats[away]["points"] += 1
    return stats


def _resolve_tie(matches, tied_rows):
    teams = {row["team_name"] for row in tied_rows}
    h2h = _head_to_head_stats(matches, teams)

    def compare(left, right):
        left_stats = h2h[left["team_name"]]
        right_stats = h2h[right["team_name"]]
        for field in ("points", "goal_difference", "goals_for"):
            if left_stats[field] != right_stats[field]:
                return -1 if left_stats[field] > right_stats[field] else 1
        return -1 if left["team_name"] < right["team_name"] else (1 if left["team_name"] > right["team_name"] else 0)

    return sorted(tied_rows, key=cmp_to_key(compare))


def compute_group_standings(fixtures, teams):
    groups = defaultdict(dict)
    matches_by_group = defaultdict(list)

    for team in teams:
        group_name = team.get("group_name")
        team_name = team.get("team_name")
        if not group_name or not team_name:
            continue
        groups[group_name][team_name] = _empty_row(group_name, team_name)

    for fixture in fixtures:
        group_name = fixture.get("matchgroup")
        if not group_name or not group_name.startswith("FIFA World Cup - Group "):
            continue
        group_name = group_name.replace("FIFA World Cup - ", "")
        home = fixture.get("hometeam")
        away = fixture.get("awayteam")
        if not home or not away:
            continue
        groups[group_name].setdefault(home, _empty_row(group_name, home))
        groups[group_name].setdefault(away, _empty_row(group_name, away))
        matches_by_group[group_name].append(fixture)

        home_score = fixture.get("hometeamscore")
        away_score = fixture.get("awayteamscore")
        if home_score is None or away_score is None:
            continue
        _apply_result(groups[group_name][home], int(home_score), int(away_score))
        _apply_result(groups[group_name][away], int(away_score), int(home_score))

    ordered = {}
    for group_name, rows_by_team in groups.items():
        rows = sorted(rows_by_team.values(), key=_base_sort_key)
        resolved = []
        index = 0
        while index < len(rows):
            current = rows[index]
            tied = [current]
            next_index = index + 1
            while next_index < len(rows):
                candidate = rows[next_index]
                if (
                    candidate["points"] == current["points"]
                    and candidate["goal_difference"] == current["goal_difference"]
                    and candidate["goals_for"] == current["goals_for"]
                ):
                    tied.append(candidate)
                    next_index += 1
                    continue
                break
            if len(tied) > 1:
                resolved.extend(_resolve_tie(matches_by_group[group_name], tied))
            else:
                resolved.extend(tied)
            index = next_index
        ordered[group_name] = resolved
    return ordered


def fetch_world_cup_group_fixtures():
    if not supabase:
        return []
    res = (
        supabase.table("fixtures")
        .select("matchnumber,hometeam,awayteam,hometeamscore,awayteamscore,matchgroup,dateeat")
        .gte("matchnumber", WORLD_CUP_MATCHNUMBER_MIN)
        .lte("matchnumber", WORLD_CUP_MATCHNUMBER_MAX)
        .like("matchgroup", "FIFA World Cup - Group %")
        .execute()
    )
    return res.data or []


def fetch_world_cup_teams():
    if not supabase:
        return []
    res = supabase.table("world_cup_teams").select("team_name,group_name").execute()
    return res.data or []


def persist_group_standings(grouped_rows):
    if not supabase:
        return 0
    payload = []
    for rows in grouped_rows.values():
        payload.extend(rows)
    if not payload:
        return 0
    res = supabase.table("world_cup_group_standings").upsert(
        payload,
        on_conflict="group_name,team_name",
    ).execute()
    return len(res.data or payload)


def refresh_world_cup_group_standings():
    fixtures = fetch_world_cup_group_fixtures()
    teams = fetch_world_cup_teams()
    grouped = compute_group_standings(fixtures, teams)
    persisted = persist_group_standings(grouped)
    return {
        "groups": len(grouped),
        "teams": sum(len(rows) for rows in grouped.values()),
        "persisted": persisted,
    }


def format_group_standings_text(grouped_rows):
    lines = ["🏆 የዓለም ዋንጫ የምድብ ሰንጠረዥ", ""]
    for group_name in sorted(grouped_rows):
        lines.append(f"{group_name}")
        for position, row in enumerate(grouped_rows[group_name], start=1):
            team = _team_display_am(row["team_name"])
            lines.append(
                f"{position}. {team}  "
                f"{row['played']}ጨ  {row['won']}-{row['drawn']}-{row['lost']}  "
                f"{row['goal_difference']:+d}  {row['points']}ነ"
            )
        lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
