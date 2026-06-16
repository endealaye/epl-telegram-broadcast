import re
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from bot_config import TEAM_MAPPING
from store import supabase


WIKIPEDIA_SQUADS_URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
BBC_SQUADS_URL = "https://www.bbc.com/sport/football/articles/cvgz43lgn15o"
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
BBC_POSITION_MAP = {
    "goalkeepers": "GK",
    "defenders": "DF",
    "midfielders": "MF",
    "forwards": "FW",
}
BBC_ARTICLE_BASE = "https://www.bbc.com"


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


def _absolute_bbc_url(href):
    if not href:
        return ""
    if href.startswith("https://"):
        return href
    if href.startswith("/"):
        return f"{BBC_ARTICLE_BASE}{href}"
    return href


def fetch_bbc_world_cup_squad_links():
    response = requests.get(
        BBC_SQUADS_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    seen = set()

    for paragraph in soup.find_all("p"):
        text = re.sub(r"\s+", " ", paragraph.get_text(" ", strip=True)).strip()
        if ":" not in text:
            continue
        team_raw = text.split(":", 1)[0].strip()
        anchor = paragraph.find("a", href=True)
        if not team_raw or not anchor:
            continue
        href = _absolute_bbc_url(anchor["href"])
        if not href or href in seen:
            continue
        seen.add(href)
        links.append(
            {
                "team_name": _normalize_team_name(team_raw),
                "article_title": anchor.get_text(" ", strip=True),
                "source_url": href,
            }
        )
        if len(links) >= 48:
            break
    return links


def _article_meta(soup):
    title = ""
    description = ""
    published_at = None
    title_node = soup.find("meta", attrs={"property": "og:title"})
    description_node = soup.find("meta", attrs={"property": "og:description"})
    if title_node:
        title = title_node.get("content") or ""
    if description_node:
        description = description_node.get("content") or ""
    published = soup.find("meta", attrs={"property": "article:published_time"})
    if not published:
        json_ld = soup.find("script", attrs={"type": "application/ld+json"})
        if json_ld:
            match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', json_ld.get_text() or "")
            if match:
                published_at = match.group(1)
    else:
        published_at = published.get("content")
    return title, description, published_at


def _parse_bbc_player_list(text, team_name, position, source_url, fetched_at):
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
                "date_of_birth": None,
                "source_status": "single_source",
                "raw_payload": {
                    "source_name": "BBC Sport",
                    "source_url": source_url,
                    "fetched_at": fetched_at,
                },
            }
        )
    return players


def fetch_bbc_world_cup_squad_article(team_name, source_url):
    response = requests.get(
        source_url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title, description, published_at = _article_meta(soup)
    fetched_at = datetime.now(timezone.utc).isoformat()
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in soup.get_text("\n", strip=True).splitlines()
    ]
    players = []
    current_position = None
    for line in lines:
        label = line.rstrip(":").lower()
        if label in BBC_POSITION_MAP:
            current_position = BBC_POSITION_MAP[label]
            continue
        if current_position and line and not line.endswith(":"):
            if line in {"Related topics", "More on this story", "Shorts", "Top stories"}:
                current_position = None
                continue
            players.extend(_parse_bbc_player_list(line, team_name, current_position, source_url, fetched_at))
            current_position = None

    return {
        "team_name": team_name,
        "source_url": source_url,
        "title": title,
        "description": description,
        "published_at": published_at,
        "players": players,
    }


def fetch_bbc_world_cup_players():
    links = fetch_bbc_world_cup_squad_links()
    articles = []
    players = []
    failed = []
    for link in links:
        try:
            article = fetch_bbc_world_cup_squad_article(link["team_name"], link["source_url"])
            article["link_title"] = link.get("article_title")
            articles.append(article)
            players.extend(article["players"])
        except Exception as exc:
            failed.append({"team_name": link["team_name"], "source_url": link["source_url"], "error": str(exc)})
    return {
        "source_url": BBC_SQUADS_URL,
        "links": links,
        "articles": articles,
        "players": players,
        "failed": failed,
    }


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


def _fetch_all_world_cup_teams():
    if not supabase:
        return {}
    res = supabase.table("world_cup_teams").select("team_name,raw_payload").execute()
    return {row["team_name"]: row for row in res.data or [] if row.get("team_name")}


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


def _resolve_player_name(name_fragment, candidate_names):
    fragment_key = _name_key(name_fragment)
    if not fragment_key:
        return None
    exact_matches = []
    for candidate in candidate_names:
        candidate_key = _name_key(candidate)
        if fragment_key == candidate_key:
            return candidate
        if fragment_key in candidate_key.split():
            exact_matches.append(candidate)
    if len(exact_matches) == 1:
        return exact_matches[0]
    contained_matches = []
    for candidate in candidate_names:
        candidate_key = _name_key(candidate)
        if set(fragment_key.split()).issubset(set(candidate_key.split())):
            contained_matches.append(candidate)
    if len(contained_matches) == 1:
        return contained_matches[0]
    return None


def _find_existing_player(team_name, player_name, existing_by_team_key, existing_by_team):
    player_key = _name_key(player_name)
    if not player_key:
        return None
    exact = existing_by_team_key.get((team_name, player_key))
    if exact:
        return exact

    player_tokens = set(player_key.split())
    matches = []
    for existing in existing_by_team.get(team_name, []):
        existing_key = _name_key(existing["player_name"])
        existing_tokens = set(existing_key.split())
        if player_tokens.issubset(existing_tokens) or player_tokens.intersection(existing_tokens) == player_tokens:
            matches.append(existing)

    unique = {}
    for match in matches:
        unique[(match["team_name"], match["player_name"])] = match
    return next(iter(unique.values())) if len(unique) == 1 else None


def _split_candidate_names(value):
    clean = re.sub(r"^World Cup 2026:\s*", "", value or "", flags=re.IGNORECASE)
    clean = re.sub(
        r"\b(?:injured|forward|defender|midfielder|goalkeeper|winger|captain|veteran|striker|rangers)\b",
        " ",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s+", " ", clean).strip(" -:,.")
    parts = re.split(r",| and | & ", clean)
    return [part.strip(" -:,.") for part in parts if part.strip(" -:,.")]


def _capitalized_token_count(value):
    return len(re.findall(r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+\b", value or ""))


def _availability_from_bbc_article(article, candidate_names):
    text = " ".join(
        value
        for value in [article.get("title"), article.get("description"), article.get("link_title")]
        if value
    )
    lowered = text.lower()
    rows = []
    seen = set()

    def add_status(name, status, allow_unmatched=False):
        player_name = _resolve_player_name(name, candidate_names)
        if not player_name and allow_unmatched:
            clean_name = re.sub(r"\s+", " ", name or "").strip(" -:,.")
            if re.search(r"\b(players|clubs|squad|team|world cup)\b", clean_name, re.IGNORECASE):
                return
            if re.search(r"\b(picked|man utd|utd)\b", clean_name, re.IGNORECASE):
                return
            if article["team_name"].lower() in clean_name.lower():
                return
            name_tokens = re.findall(r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+", clean_name)
            if len(name_tokens) >= 2:
                player_name = " ".join(name_tokens[-2:])
        if not player_name:
            return
        key = (article["team_name"], player_name, status, article["source_url"])
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "team_name": article["team_name"],
                "player_name": player_name,
                "status": status,
                "note": text[:500],
                "source_name": "BBC Sport",
                "source_url": article["source_url"],
                "reported_at": article.get("published_at"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    for candidate in sorted(candidate_names, key=len, reverse=True):
        candidate_lower = candidate.lower()
        if candidate_lower in lowered:
            if re.search(r"\b(despite injury|injured .+? in squad)\b", text, re.IGNORECASE):
                add_status(candidate, "doubtful")

    for pattern in [
        r"([^.!?]+?)\s+to miss World Cup",
        r"\bno\s+(?!Real Madrid players\b)([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]+){1,3})\b",
        r"\bno place for\s+([^.!?]+?)(?:[.!?]|$)",
    ]:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            for name in _split_candidate_names(match.group(1)):
                add_status(name, "omitted", allow_unmatched=True)

    for match in re.finditer(r"([^.!?]+?)\s+(?:left out|omitted)\b", text, re.IGNORECASE):
        phrase = match.group(1).strip()
        if ":" in phrase:
            before_colon, after_colon = phrase.rsplit(":", 1)
            if 2 <= _capitalized_token_count(before_colon) <= 3:
                for name in _split_candidate_names(before_colon):
                    add_status(name, "omitted", allow_unmatched=True)
            if " but no " not in after_colon.lower() and _capitalized_token_count(after_colon) <= 8 and (
                "," in after_colon or " and " in after_colon.lower() or _capitalized_token_count(after_colon) <= 4
            ):
                for name in _split_candidate_names(after_colon):
                    add_status(name, "omitted", allow_unmatched=True)
        elif _capitalized_token_count(phrase) <= 4:
            for name in _split_candidate_names(phrase):
                add_status(name, "omitted", allow_unmatched=True)

    injured_left_out = re.search(r"\bInjured\s+(.+?)\s+(?:left out|omitted)\b", text, re.IGNORECASE)
    if injured_left_out:
        for name in _split_candidate_names(injured_left_out.group(1)):
            add_status(name, "omitted", allow_unmatched=True)

    despite_injury = re.search(r"(.+?)\s+named.+?despite injury", text, re.IGNORECASE)
    if despite_injury:
        for name in _split_candidate_names(despite_injury.group(1)):
            add_status(name, "doubtful")

    if "despite injury" in lowered:
        before = re.split(r"despite injury", text, flags=re.IGNORECASE)[0]
        for candidate in sorted(candidate_names, key=len, reverse=True):
            if candidate.lower() in before.lower():
                add_status(candidate, "doubtful")
                break

    injured_in_squad = re.search(r"\bInjured\s+(.+?)\s+in squad", text, re.IGNORECASE)
    if injured_in_squad:
        for name in _split_candidate_names(injured_in_squad.group(1)):
            add_status(name, "doubtful")

    return rows


def _fetch_existing_availability_keys():
    if not supabase:
        return set()
    rows = []
    start = 0
    while True:
        page = (
            supabase.table("world_cup_player_availability")
            .select("team_name,player_name,status,source_url")
            .range(start, start + 999)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000
    return {
        (row.get("team_name"), row.get("player_name"), row.get("status"), row.get("source_url"))
        for row in rows
    }


def refresh_world_cup_players_with_bbc():
    if not supabase:
        return {"teams_found": 0, "players_found": 0, "persisted": 0, "failed": []}

    fetched = fetch_bbc_world_cup_players()
    known_teams = _fetch_all_world_cup_teams()
    existing_players = _fetch_all_world_cup_players()
    existing_by_team_key = {
        (row["team_name"], _name_key(row["player_name"])): row
        for row in existing_players
    }
    existing_by_team = {}
    known_names_by_team = {}
    for row in existing_players:
        existing_by_team.setdefault(row["team_name"], []).append(row)
        known_names_by_team.setdefault(row["team_name"], set()).add(row["player_name"])

    payload_by_key = {}
    unmatched_bbc_players = []
    for player in fetched["players"]:
        team_name = player["team_name"]
        if team_name not in known_teams:
            continue
        existing = _find_existing_player(team_name, player["player_name"], existing_by_team_key, existing_by_team)
        if not existing:
            unmatched_bbc_players.append(
                {
                    "team_name": team_name,
                    "player_name": player["player_name"],
                    "position": player.get("position"),
                    "club": player.get("club"),
                    "source_url": (player.get("raw_payload") or {}).get("source_url"),
                }
            )
            continue

        raw_payload = dict(existing.get("raw_payload") or {})
        raw_payload["bbc_verification"] = {
            "status": "matched",
            "player_name": player["player_name"],
            "club": player.get("club"),
            "position": player.get("position"),
            "source_name": "BBC Sport",
            "source_url": (player.get("raw_payload") or {}).get("source_url"),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        row = {
            "player_name": existing["player_name"],
            "team_name": team_name,
            "position": existing.get("position") or player.get("position"),
            "club": existing.get("club") or player.get("club"),
            "date_of_birth": existing.get("date_of_birth"),
            "source_status": "confirmed",
            "raw_payload": raw_payload,
        }
        payload_by_key[(row["team_name"], _name_key(row["player_name"]))] = row

    payload = list(payload_by_key.values())
    confirmed = len(payload)
    inserted = 0
    persisted = 0
    if payload:
        res = supabase.table("world_cup_players").upsert(
            payload,
            on_conflict="team_name,player_name",
        ).execute()
        persisted = len(res.data or payload)

    team_payload = []
    for article in fetched["articles"]:
        team_name = article["team_name"]
        if team_name not in known_teams:
            continue
        raw_payload = dict((known_teams[team_name] or {}).get("raw_payload") or {})
        raw_payload["bbc_squad_article"] = {
            "status": "confirmed",
            "source_name": "BBC Sport",
            "source_url": article["source_url"],
            "title": article.get("title"),
            "players_found": len(article.get("players") or []),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
        team_payload.append(
            {
                "team_name": team_name,
                "source_status": "confirmed",
                "raw_payload": raw_payload,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    if team_payload:
        supabase.table("world_cup_teams").upsert(team_payload, on_conflict="team_name").execute()

    availability_rows = []
    for article in fetched["articles"]:
        team_name = article["team_name"]
        candidate_names = set(known_names_by_team.get(team_name, set()))
        candidate_names.update(player["player_name"] for player in article.get("players") or [])
        availability_rows.extend(_availability_from_bbc_article(article, candidate_names))

    existing_availability = _fetch_existing_availability_keys()
    new_availability = []
    for row in availability_rows:
        key = (row["team_name"], row["player_name"], row["status"], row["source_url"])
        if key not in existing_availability:
            new_availability.append(row)
            existing_availability.add(key)
    if new_availability:
        supabase.table("world_cup_player_availability").insert(new_availability).execute()

    return {
        "source_url": fetched["source_url"],
        "teams_found": len({article["team_name"] for article in fetched["articles"]}),
        "players_found": len(fetched["players"]),
        "confirmed_players": confirmed,
        "inserted_players": inserted,
        "persisted": persisted,
        "teams_confirmed": len(team_payload),
        "availability_rows": len(new_availability),
        "unmatched_bbc_players": len(unmatched_bbc_players),
        "unmatched_bbc_player_samples": unmatched_bbc_players[:25],
        "failed": fetched["failed"],
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
