from collections import Counter, defaultdict
from datetime import datetime, timezone

from store import supabase


FIFA_SQUADS_CONFIRMED_URL = "https://www.fifa.com/en/articles/fifa-world-cup-2026-squads-confirmed"
FIFA_ALL_SQUAD_ANNOUNCEMENTS_URL = (
    "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/"
    "articles/all-world-cup-squad-announcements"
)
EXPECTED_TEAMS = 48
EXPECTED_PLAYERS_PER_TEAM = 26
EXPECTED_TOTAL_PLAYERS = EXPECTED_TEAMS * EXPECTED_PLAYERS_PER_TEAM


def _fetch_all_players():
    if not supabase:
        return []
    rows = []
    start = 0
    page_size = 1000
    while True:
        page = (
            supabase.table("world_cup_players")
            .select("player_name,team_name,position,club,date_of_birth,source_status,raw_payload")
            .range(start, start + page_size - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows


def audit_world_cup_squads(update_metadata=True):
    players = _fetch_all_players()
    counts = Counter(row["team_name"] for row in players)
    rows_by_team = defaultdict(list)
    for row in players:
        rows_by_team[row["team_name"]].append(row)

    incomplete_teams = {
        team_name: count
        for team_name, count in sorted(counts.items())
        if count != EXPECTED_PLAYERS_PER_TEAM
    }
    complete_teams = sorted(
        team_name
        for team_name, count in counts.items()
        if count == EXPECTED_PLAYERS_PER_TEAM
    )

    updated_players = 0
    if update_metadata and supabase:
        verified_at = datetime.now(timezone.utc).isoformat()
        payload = []
        for player in players:
            team_name = player["team_name"]
            team_count = counts[team_name]
            raw_payload = dict(player.get("raw_payload") or {})
            raw_payload["fifa_official_reference"] = {
                "status": "team_count_complete" if team_count == EXPECTED_PLAYERS_PER_TEAM else "local_roster_incomplete",
                "team_player_count": team_count,
                "expected_team_player_count": EXPECTED_PLAYERS_PER_TEAM,
                "expected_total_players": EXPECTED_TOTAL_PLAYERS,
                "source_name": "FIFA",
                "source_url": FIFA_SQUADS_CONFIRMED_URL,
                "squad_hub_url": FIFA_ALL_SQUAD_ANNOUNCEMENTS_URL,
                "verified_at": verified_at,
            }
            payload.append(
                {
                    "player_name": player["player_name"],
                    "team_name": team_name,
                    "position": player.get("position"),
                    "club": player.get("club"),
                    "date_of_birth": player.get("date_of_birth"),
                    "source_status": player.get("source_status") or "single_source",
                    "raw_payload": raw_payload,
                }
            )

        if payload:
            res = supabase.table("world_cup_players").upsert(
                payload,
                on_conflict="team_name,player_name",
            ).execute()
            updated_players = len(res.data or payload)

    return {
        "expected_teams": EXPECTED_TEAMS,
        "expected_players_per_team": EXPECTED_PLAYERS_PER_TEAM,
        "expected_total_players": EXPECTED_TOTAL_PLAYERS,
        "local_teams": len(counts),
        "local_total_players": len(players),
        "complete_teams": len(complete_teams),
        "incomplete_teams": incomplete_teams,
        "missing_players": EXPECTED_TOTAL_PLAYERS - len(players),
        "updated_players": updated_players,
        "source_urls": [
            FIFA_SQUADS_CONFIRMED_URL,
            FIFA_ALL_SQUAD_ANNOUNCEMENTS_URL,
        ],
    }
