import re
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from bot_config import TEAM_MAPPING
from store import supabase


WIKIPEDIA_SQUADS_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
SKY_SQUADS_URL = (
    "https://www.skysports.com/football/news/11095/13543070/"
    "world-cup-2026-squad-lists-england-scotland-brazil-usa-spain-france-"
    "germany-netherlands-argentina-portugal-and-more/"
)
USER_AGENT = "GatangaFootballBot/1.0 (zero-budget football analysis)"
POSITION_PATTERN = re.compile(r"\b(GK|DF|MF|FW)\b")
DATE_PATTERN = re.compile(r"\(\s*(\d{4}-\d{2}-\d{2})\s*\)")
CAPTAIN_PATTERN = re.compile(r"\s*\(\s*captain\s*\)\s*", re.IGNORECASE)
SKY_SECTION_PATTERN = re.compile(r"^(Goalkeepers|Defenders|Midfielders|Forwards)\s*:", re.IGNORECASE)
SKY_POSITION_MAP = {
    "goalkeepers": "GK",
    "defenders": "DF",
    "midfielders": "MF",
    "forwards": "FW",
}


def _normalize_team_name(name):
    clean = re.sub(r"\s+", " ", name or "").strip()
    return TEAM_MAPPING.get(clean, clean)


def _clean_cell_text(cell):
    for sup in cell.find_all("sup"):
        sup.decompose()
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()


def _clean_player_name(value):
    clean = CAPTAIN_PATTERN.sub("", value or "")
    return re.sub(r"\s+", " ", clean).strip()


def _name_key(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = ascii_text.lower().replace("-", " ")
    ascii_text = re.sub(r"[^a-z0-9 ]+", " ", ascii_text)
    tokens = [token for token in ascii_text.split() if token]
    return " ".join(sorted(tokens))


def _parse_position(value):
    match = POSITION_PATTERN.search(value or "")
    return match.group(1) if match else (value or "").strip() or None


def _parse_date_of_birth(value):
    match = DATE_PATTERN.search(value or "")
    return match.group(1) if match else None


def _parse_squad_table(table, team_name, fetched_at):
    rows = []
    headers = [_clean_cell_text(cell).lower() for cell in table.find_all("tr")[0].find_all(["th", "td"])]
    header_index = {header: index for index, header in enumerate(headers)}

    required = {"no.", "pos.", "player", "date of birth (age)", "club"}
    if not required.issubset(header_index):
        return rows

    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["th", "td"])
        if len(cells) < len(headers):
            continue
        values = [_clean_cell_text(cell) for cell in cells]
        player_name = _clean_player_name(values[header_index["player"]])
        if not player_name:
            continue

        date_text = values[header_index["date of birth (age)"]]
        raw_payload = {
            "shirt_number": values[header_index["no."]],
            "position_raw": values[header_index["pos."]],
            "date_of_birth_raw": date_text,
            "caps": values[header_index["caps"]] if "caps" in header_index else None,
            "goals": values[header_index["goals"]] if "goals" in header_index else None,
            "source_name": "Wikipedia",
            "source_url": WIKIPEDIA_SQUADS_URL,
            "fetched_at": fetched_at,
        }
        rows.append(
            {
                "player_name": player_name,
                "team_name": team_name,
                "position": _parse_position(values[header_index["pos."]]),
                "club": values[header_index["club"]] or None,
                "date_of_birth": _parse_date_of_birth(date_text),
                "source_status": "single_source",
                "raw_payload": raw_payload,
            }
        )
    return rows


def fetch_wikipedia_world_cup_players():
    response = requests.get(
        WIKIPEDIA_SQUADS_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    fetched_at = datetime.now(timezone.utc).isoformat()
    players = []
    teams_seen = set()

    for heading in soup.find_all("h3"):
        team_name = _normalize_team_name(heading.get_text(" ", strip=True))
        table = heading.find_next("table", class_="wikitable")
        if not team_name or table is None:
            continue
        team_players = _parse_squad_table(table, team_name, fetched_at)
        if not team_players:
            continue
        players.extend(team_players)
        teams_seen.add(team_name)

    return {
        "source_url": WIKIPEDIA_SQUADS_URL,
        "teams": sorted(teams_seen),
        "players": players,
    }


def _parse_sky_player_list(text, team_name, position):
    players = []
    for item in text.split(","):
        clean = re.sub(r"\s+", " ", item).strip().rstrip(".")
        if not clean:
            continue
        match = re.match(r"^(?P<name>.+?)\s*\((?P<club>[^)]+)\)$", clean)
        if match:
            player_name = _clean_player_name(match.group("name"))
            club = match.group("club").strip()
        else:
            player_name = _clean_player_name(clean)
            club = None
        if not player_name:
            continue
        players.append(
            {
                "team_name": team_name,
                "player_name": player_name,
                "position": position,
                "club": club,
                "source_name": "Sky Sports",
                "source_url": SKY_SQUADS_URL,
            }
        )
    return players


def fetch_sky_world_cup_players():
    response = requests.get(
        SKY_SQUADS_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    teams = {}
    for heading in soup.find_all("h3"):
        team_name = _normalize_team_name(heading.get_text(" ", strip=True))
        if not team_name or team_name in {"Also See:", "Around Sky"}:
            continue

        players = []
        node = heading
        while True:
            node = node.find_next_sibling()
            if node is None or node.name in {"h2", "h3"}:
                break
            if node.name != "p":
                continue
            text = node.get_text(" ", strip=True)
            section_match = SKY_SECTION_PATTERN.match(text)
            if not section_match:
                continue
            label = section_match.group(1).lower()
            position = SKY_POSITION_MAP[label]
            player_text = SKY_SECTION_PATTERN.sub("", text, count=1).strip()
            players.extend(_parse_sky_player_list(player_text, team_name, position))

        if players:
            teams[team_name] = players
    return teams


def _fetch_known_world_cup_team_names():
    if not supabase:
        return set()
    res = supabase.table("world_cup_teams").select("team_name").execute()
    return {row["team_name"] for row in res.data or [] if row.get("team_name")}


def _fetch_all_world_cup_players():
    rows = []
    start = 0
    page_size = 1000
    while True:
        res = (
            supabase.table("world_cup_players")
            .select("player_name,team_name,position,club,date_of_birth,source_status,raw_payload")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows


def persist_world_cup_players(players):
    if not supabase or not players:
        return {"persisted": 0, "skipped": len(players), "missing_teams": []}

    known_teams = _fetch_known_world_cup_team_names()
    payload = []
    missing_teams = set()
    for player in players:
        if player["team_name"] not in known_teams:
            missing_teams.add(player["team_name"])
            continue
        payload.append(player)

    persisted = 0
    if payload:
        res = supabase.table("world_cup_players").upsert(
            payload,
            on_conflict="team_name,player_name",
        ).execute()
        persisted = len(res.data or payload)

    return {
        "persisted": persisted,
        "skipped": len(players) - len(payload),
        "missing_teams": sorted(missing_teams),
    }


def verify_world_cup_players_with_sky():
    if not supabase:
        return {"confirmed": 0, "single_source": 0, "sky_only": 0, "teams_verified": 0}

    sky_by_team = fetch_sky_world_cup_players()
    existing = _fetch_all_world_cup_players()

    sky_indexes = {
        team: {_name_key(player["player_name"]): player for player in players}
        for team, players in sky_by_team.items()
    }
    wiki_keys_by_team = {}
    payload = []
    confirmed = 0
    single_source = 0

    for player in existing:
        team_name = player["team_name"]
        player_key = _name_key(player["player_name"])
        wiki_keys_by_team.setdefault(team_name, set()).add(player_key)
        sky_match = sky_indexes.get(team_name, {}).get(player_key)
        raw_payload = dict(player.get("raw_payload") or {})

        if sky_match:
            status = "confirmed"
            confirmed += 1
            raw_payload["sky_verification"] = {
                "status": "matched",
                "player_name": sky_match["player_name"],
                "club": sky_match["club"],
                "position": sky_match["position"],
                "source_name": sky_match["source_name"],
                "source_url": sky_match["source_url"],
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            status = "single_source"
            single_source += 1
            raw_payload["sky_verification"] = {
                "status": "not_found",
                "source_name": "Sky Sports",
                "source_url": SKY_SQUADS_URL,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }

        payload.append(
            {
                "player_name": player["player_name"],
                "team_name": team_name,
                "position": player.get("position"),
                "club": player.get("club"),
                "date_of_birth": player.get("date_of_birth"),
                "source_status": status,
                "raw_payload": raw_payload,
            }
        )

    if payload:
        supabase.table("world_cup_players").upsert(
            payload,
            on_conflict="team_name,player_name",
        ).execute()

    sky_only = 0
    for team_name, players in sky_by_team.items():
        wiki_keys = wiki_keys_by_team.get(team_name, set())
        sky_only += sum(1 for player in players if _name_key(player["player_name"]) not in wiki_keys)

    return {
        "confirmed": confirmed,
        "single_source": single_source,
        "sky_only": sky_only,
        "teams_verified": len(sky_by_team),
        "source_url": SKY_SQUADS_URL,
    }


def refresh_world_cup_players():
    fetched = fetch_wikipedia_world_cup_players()
    persist_result = persist_world_cup_players(fetched["players"])
    verification = verify_world_cup_players_with_sky()
    return {
        "source_url": fetched["source_url"],
        "teams_found": len(fetched["teams"]),
        "players_found": len(fetched["players"]),
        "verification": verification,
        **persist_result,
    }
