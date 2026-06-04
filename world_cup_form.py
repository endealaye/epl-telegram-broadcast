import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urldefrag

import requests
from bs4 import BeautifulSoup

from bot_config import TEAM_MAPPING
from store import supabase


QUALIFIER_SOURCES = [
    {
        "name": "Wikipedia CONMEBOL World Cup qualification",
        "competition": "2026 FIFA World Cup qualification - CONMEBOL",
        "url": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_qualification_(CONMEBOL)",
        "page_marker": "CONMEBOL",
    },
    {
        "name": "Wikipedia CAF World Cup qualification",
        "competition": "2026 FIFA World Cup qualification - CAF",
        "url": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_qualification_(CAF)",
        "page_marker": "CAF",
    },
    {
        "name": "Wikipedia AFC World Cup qualification",
        "competition": "2026 FIFA World Cup qualification - AFC",
        "url": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_qualification_(AFC)",
        "page_marker": "AFC",
    },
    {
        "name": "Wikipedia CONCACAF World Cup qualification",
        "competition": "2026 FIFA World Cup qualification - CONCACAF",
        "url": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_qualification_(CONCACAF)",
        "page_marker": "CONCACAF",
    },
    {
        "name": "Wikipedia UEFA World Cup qualification",
        "competition": "2026 FIFA World Cup qualification - UEFA",
        "url": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_qualification_(UEFA)",
        "page_marker": "UEFA",
    },
    {
        "name": "Wikipedia OFC World Cup qualification",
        "competition": "2026 FIFA World Cup qualification - OFC",
        "url": "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_qualification_(OFC)",
        "page_marker": "OFC",
    },
]

USER_AGENT = "GatangaFootballBot/1.0 (zero-budget football analysis)"
SCORE_PATTERN = re.compile(r"(\d+)\s*[–-]\s*(\d+)")
RELATED_PAGE_PATTERN = re.compile(r"/wiki/2026_FIFA_World_Cup_qualification_%E2%80%93_")


def _normalize_team_name(name):
    clean = re.sub(r"\s+", " ", name or "").strip()
    return TEAM_MAPPING.get(clean, clean)


def _clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def _team_from_cell(cell):
    if not cell:
        return ""
    link = cell.find("a", href=re.compile(r"_national_football_team"))
    if link:
        return _normalize_team_name(link.get_text(" ", strip=True))
    return _normalize_team_name(cell.get_text(" ", strip=True))


def _parse_score(value):
    match = SCORE_PATTERN.search(value or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _parse_footballbox(box, source):
    date_node = box.find(class_="bday")
    if not date_node:
        return None
    match_date = _clean_text(date_node.get_text())

    home = _team_from_cell(box.find(class_="fhome"))
    away = _team_from_cell(box.find(class_="faway"))
    score = _parse_score(_clean_text(box.find(class_="fscore").get_text(" ", strip=True)) if box.find(class_="fscore") else "")
    if not home or not away or not score:
        return None

    venue = _clean_text(box.find(class_="fright").get_text(" ", strip=True)) if box.find(class_="fright") else ""
    return {
        "match_date": match_date,
        "home_team": home,
        "away_team": away,
        "home_score": score[0],
        "away_score": score[1],
        "competition": source["competition"],
        "source_name": source["name"],
        "source_url": source["url"],
        "raw_payload": {
            "box_id": box.get("id"),
            "score_text": _clean_text(box.find(class_="fscore").get_text(" ", strip=True)) if box.find(class_="fscore") else "",
            "venue_text": venue,
            "source_name": source["name"],
            "source_url": source["url"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _fetch_soup(url):
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def _discover_related_pages(soup, source):
    urls = {source["url"]}
    marker = f"_{source['page_marker']}_"
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not RELATED_PAGE_PATTERN.search(href):
            continue
        if marker not in href:
            continue
        url = urldefrag(urljoin("https://en.wikipedia.org", href))[0]
        urls.add(url)
    return sorted(urls)


def fetch_qualifier_matches():
    matches = []
    seen_boxes = set()
    for source in QUALIFIER_SOURCES:
        root_soup = _fetch_soup(source["url"])
        for page_url in _discover_related_pages(root_soup, source):
            page_source = {**source, "url": page_url}
            soup = root_soup if page_url == source["url"] else _fetch_soup(page_url)
            for box in soup.find_all(class_="footballbox"):
                parsed = _parse_footballbox(box, page_source)
                if not parsed:
                    continue
                key = (
                    parsed["match_date"],
                    parsed["home_team"],
                    parsed["away_team"],
                    parsed["home_score"],
                    parsed["away_score"],
                    parsed["competition"],
                )
                if key in seen_boxes:
                    continue
                seen_boxes.add(key)
                matches.append(parsed)
    return matches


def _fetch_known_world_cup_team_names():
    if not supabase:
        return set()
    res = supabase.table("world_cup_teams").select("team_name").execute()
    return {row["team_name"] for row in res.data or [] if row.get("team_name")}


def _rows_for_match(match, known_teams):
    rows = []
    home = match["home_team"]
    away = match["away_team"]
    if home in known_teams:
        rows.append(
            {
                "team_name": home,
                "match_date": match["match_date"],
                "opponent": away,
                "team_score": match["home_score"],
                "opponent_score": match["away_score"],
                "venue_type": "home",
                "competition": match["competition"],
                "source_status": "single_source",
                "raw_payload": match["raw_payload"],
            }
        )
    if away in known_teams:
        rows.append(
            {
                "team_name": away,
                "match_date": match["match_date"],
                "opponent": home,
                "team_score": match["away_score"],
                "opponent_score": match["home_score"],
                "venue_type": "away",
                "competition": match["competition"],
                "source_status": "single_source",
                "raw_payload": match["raw_payload"],
            }
        )
    return rows


def persist_qualifier_form(matches):
    if not supabase:
        return {"persisted": 0, "teams_with_rows": 0, "teams_missing_rows": []}

    known_teams = _fetch_known_world_cup_team_names()
    rows = []
    for match in matches:
        rows.extend(_rows_for_match(match, known_teams))

    persisted = 0
    if rows:
        res = supabase.table("world_cup_recent_matches").upsert(
            rows,
            on_conflict="team_name,match_date,opponent",
        ).execute()
        persisted = len(res.data or rows)

    teams_with_rows = {row["team_name"] for row in rows}
    return {
        "persisted": persisted,
        "teams_with_rows": len(teams_with_rows),
        "teams_missing_rows": sorted(known_teams - teams_with_rows),
    }


def summarize_recent_form(rows, limit=5):
    recent = sorted(rows, key=lambda row: row.get("match_date") or "", reverse=True)[:limit]
    summary = {
        "played": len(recent),
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "goals_for": 0,
        "goals_against": 0,
        "matches": recent,
    }
    for row in recent:
        scored = row.get("team_score")
        conceded = row.get("opponent_score")
        if scored is None or conceded is None:
            continue
        summary["goals_for"] += scored
        summary["goals_against"] += conceded
        if scored > conceded:
            summary["won"] += 1
        elif scored < conceded:
            summary["lost"] += 1
        else:
            summary["drawn"] += 1
    return summary


def fetch_team_recent_form(team_name, limit=5):
    if not supabase:
        return summarize_recent_form([], limit=limit)
    rows = (
        supabase.table("world_cup_recent_matches")
        .select("team_name,match_date,opponent,team_score,opponent_score,venue_type,competition,source_status")
        .eq("team_name", team_name)
        .order("match_date", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return summarize_recent_form(rows, limit=limit)


def refresh_world_cup_qualifier_form():
    matches = fetch_qualifier_matches()
    result = persist_qualifier_form(matches)
    return {
        "matches_found": len(matches),
        "sources": len(QUALIFIER_SOURCES),
        **result,
    }
