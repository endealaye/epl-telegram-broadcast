import html
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


from bot_config import (
    BBC_SCORES_URL_TEMPLATE,
    CURRENT_EPL_SEASON,
    JSON_URL,
    TEAM_MAPPING,
    WORLD_CUP_SEASON,
    WORLD_CUP_JSON_URL,
    get_eat_now,
    get_eat_today,
)
from store import supabase


WORLD_CUP_MATCHNUMBER_OFFSET = 2_026_000
WORLD_CUP_COMPETITION_NAME = "FIFA World Cup"
EUROPEAN_COMPETITIONS = {
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Conference League",
}

WORLD_CUP_RESULT_COMPETITIONS = {"FIFA World Cup", "World Cup"}
RESULT_COMPETITIONS = {"Premier League", *EUROPEAN_COMPETITIONS, *WORLD_CUP_RESULT_COMPETITIONS}
UEFA_UCL_FIXTURES_ARTICLE_URL = (
    "https://www.uefa.com/uefachampionsleague/news/"
    "029c-1e9a2f63fe2d-ebf9ad643892-1000--2025-26-champions-league-all-the-league-phase-fixtures/"
)
UEFA_UEL_FIXTURES_ARTICLE_URL = (
    "https://www.uefa.com/api/v1/linkrules/article/"
    "029c-1e9ad67620f2-05c31d01f0f4-1000/"
)
UEFA_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


def _upsert_fixture_rows(rows):
    if not supabase or not rows:
        return 0
    try:
        res = supabase.table("fixtures").upsert(rows).execute()
        return len(res.data or rows)
    except Exception as exc:
        message = str(exc).lower()
        if "season" not in message or "column" not in message:
            raise
        fallback_rows = []
        for row in rows:
            fallback = dict(row)
            fallback.pop("season", None)
            fallback_rows.append(fallback)
        print("Fixture season column missing; upserting without season. Run add_fixture_season_column.sql.")
        res = supabase.table("fixtures").upsert(fallback_rows).execute()
        return len(res.data or fallback_rows)


def _to_eat_datetime(date_string, uk_time_string):
    dt_uk = datetime.strptime(f"{date_string} {uk_time_string}", "%Y-%m-%d %H:%M").replace(
        tzinfo=ZoneInfo("Europe/London")
    )
    return dt_uk.astimezone(ZoneInfo("Africa/Addis_Ababa")).strftime("%Y-%m-%d %H:%M:%S")


def _bbc_kickoff_overrides_for_date(date_string):
    url = BBC_SCORES_URL_TEMPLATE.format(date=date_string)
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    overrides = {}
    for link in soup.find_all("a", href=re.compile(r"/sport/football/live/")):
        text = link.get_text(" ", strip=True)
        match = re.search(r"(.+?) versus (.+?) kick off (\d{2}:\d{2})", text, re.IGNORECASE)
        if not match:
            continue
        home_raw, away_raw, uk_time = [part.strip() for part in match.groups()]
        home_team = TEAM_MAPPING.get(home_raw, home_raw)
        away_team = TEAM_MAPPING.get(away_raw, away_raw)
        # Keep only teams we can map into our fixtures table naming.
        if home_team not in TEAM_MAPPING.values() or away_team not in TEAM_MAPPING.values():
            continue
        overrides[(home_team, away_team)] = _to_eat_datetime(date_string, uk_time)
    return overrides


def _apply_bbc_kickoff_overrides(date_string):
    if not supabase:
        return 0
    overrides = _bbc_kickoff_overrides_for_date(date_string)
    updated = 0
    for (home_team, away_team), dateeat in overrides.items():
        res = (
            supabase.table("fixtures")
            .update({"dateeat": dateeat})
            .eq("hometeam", home_team)
            .eq("awayteam", away_team)
            .ilike("dateeat", f"{date_string}%")
            .execute()
        )
        rows = res.data or []
        updated += len(rows)
    return updated


def sky_result_overrides_for_date(date_string, competitions=None):
    url = f"https://www.skysports.com/football-scores-fixtures/{date_string}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    allowed = set(competitions or RESULT_COMPETITIONS)
    overrides = {}
    for node in soup.find_all(attrs={"data-state": True}):
        raw_payload = node.get("data-state")
        if not raw_payload:
            continue
        try:
            payload = json.loads(html.unescape(raw_payload))
        except Exception:
            continue

        competition_name = (
            ((payload.get("competition") or {}).get("name") or {}).get("full") or ""
        ).strip()
        if competition_name not in allowed:
            continue
        if not payload.get("isResult"):
            continue

        teams = payload.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        home_name = ((home.get("name") or {}).get("full") or "").strip()
        away_name = ((away.get("name") or {}).get("full") or "").strip()
        home_score = (home.get("score") or {}).get("current")
        away_score = (away.get("score") or {}).get("current")
        if not home_name or not away_name or home_score is None or away_score is None:
            continue

        mapped_home = TEAM_MAPPING.get(home_name, home_name)
        mapped_away = TEAM_MAPPING.get(away_name, away_name)
        overrides[(mapped_home, mapped_away, competition_name)] = (int(home_score), int(away_score))

    return overrides


def _apply_sky_result_overrides(date_string):
    if not supabase:
        return 0
    overrides = sky_result_overrides_for_date(date_string)
    updated = 0
    for (home_team, away_team, competition_name), (home_score, away_score) in overrides.items():
        query = (
            supabase.table("fixtures")
            .update(
                {
                    "hometeamscore": home_score,
                    "awayteamscore": away_score,
                }
            )
            .eq("hometeam", home_team)
            .eq("awayteam", away_team)
            .ilike("dateeat", f"{date_string}%")
        )
        if competition_name in WORLD_CUP_RESULT_COMPETITIONS:
            query = query.ilike("matchgroup", f"{WORLD_CUP_COMPETITION_NAME}%")
        else:
            query = query.eq("matchgroup", competition_name)
        res = query.execute()
        rows = res.data or []
        updated += len(rows)
    return updated


def _sky_competition_fixtures_for_date(date_string, competitions=None):
    url = f"https://www.skysports.com/football-scores-fixtures/{date_string}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    allowed = set(competitions or EUROPEAN_COMPETITIONS)
    fixtures = []
    tracked_teams = set(TEAM_MAPPING.values())
    for node in soup.find_all(attrs={"data-state": True}):
        raw_payload = node.get("data-state")
        if not raw_payload:
            continue
        try:
            payload = json.loads(html.unescape(raw_payload))
        except Exception:
            continue

        competition = payload.get("competition") or {}
        competition_name = (((competition.get("name") or {}).get("full")) or "").strip()
        if competition_name not in allowed:
            continue

        teams = payload.get("teams") or {}
        home = teams.get("home") or {}
        away = teams.get("away") or {}
        home_name = ((home.get("name") or {}).get("full") or "").strip()
        away_name = ((away.get("name") or {}).get("full") or "").strip()
        if not home_name or not away_name:
            continue

        mapped_home = TEAM_MAPPING.get(home_name, home_name)
        mapped_away = TEAM_MAPPING.get(away_name, away_name)
        if mapped_home not in tracked_teams and mapped_away not in tracked_teams:
            continue

        start = payload.get("start") or {}
        uk_time = (start.get("time") or "").strip()
        if not uk_time:
            continue

        dateeat = _to_eat_datetime(date_string, uk_time)
        round_name = ((((competition.get("round") or {}).get("name")) or {}).get("full") or "").strip()
        match_id = payload.get("id")
        if match_id is None:
            continue

        fixtures.append(
            {
                "matchnumber": int(match_id),
                "roundnumber": None,
                "dateutc": None,
                "location": None,
                "hometeam": mapped_home,
                "awayteam": mapped_away,
                "matchgroup": competition_name,
                "hometeamscore": None,
                "awayteamscore": None,
                "dateeat": dateeat,
                "season": CURRENT_EPL_SEASON,
                "roundlabel": None,
            }
        )
    return fixtures


def _upsert_sky_competition_fixtures_for_date(date_string, competitions=None):
    if not supabase:
        return 0
    fixtures = _sky_competition_fixtures_for_date(date_string, competitions=competitions)
    if not fixtures:
        return 0

    payload = []
    for fixture in fixtures:
        row = dict(fixture)
        row.pop("roundlabel", None)
        payload.append(row)

    return _upsert_fixture_rows(payload)


def _season_year_for_date(month):
    return 2025 if month >= 7 else 2026


def _parse_uefa_article_date(date_text):
    cleaned = re.sub(r"\s+", " ", (date_text or "").strip())
    match = re.match(r"^[A-Za-z]+\s+(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?$", cleaned)
    if not match:
        return None

    day = int(match.group(1))
    month_name = match.group(2)
    year_raw = match.group(3)
    try:
        month = datetime.strptime(month_name, "%B").month
    except ValueError:
        return None

    year = int(year_raw) if year_raw else _season_year_for_date(month)
    return datetime(year, month, day).date()


def _uefa_default_dateeat(date_string, text):
    explicit = re.search(r"\((\d{1,2}:\d{2})\s*CET\)", text)
    if explicit:
        return _to_eat_datetime(date_string, explicit.group(1))
    return f"{date_string} 22:00:00"


def _parse_uefa_match_text(text):
    normalized = re.sub(r"\s+", " ", text).strip()
    result_match = re.match(r"^(.*?)\s+(\d+)-(\d+)\s+(.*?)(?:\s+\(.*)?$", normalized)
    if result_match:
        home_name, home_score, away_score, away_name = result_match.groups()
        return {
            "home": home_name.strip(),
            "away": away_name.strip(),
            "home_score": int(home_score),
            "away_score": int(away_score),
        }

    fixture_match = re.match(r"^(.*?)\s+vs\s+(.*?)(?:\s+\(.*)?$", normalized)
    if fixture_match:
        home_name, away_name = fixture_match.groups()
        return {
            "home": home_name.strip(),
            "away": away_name.strip(),
            "home_score": None,
            "away_score": None,
        }
    return None


def _uefa_article_fixtures_for_date(date_string, article_url, competition_name):
    html_text = None
    try:
        response = requests.get(article_url, headers=UEFA_REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
        html_text = response.text
    except Exception:
        curl_result = subprocess.run(
            ["curl", "-L", article_url],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        html_text = curl_result.stdout

    soup = BeautifulSoup(html_text, "html.parser")

    fixtures = []
    target_date = datetime.strptime(date_string, "%Y-%m-%d").date()
    for paragraph in soup.find_all("p"):
        strong = paragraph.find("b")
        if not strong:
            continue

        paragraph_date = _parse_uefa_article_date(strong.get_text(" ", strip=True))
        if paragraph_date != target_date:
            continue

        paragraph_text = paragraph.get_text(" ", strip=True)
        for anchor in paragraph.find_all("a", href=True):
            match = re.search(r"/match/(\d+)", anchor["href"])
            if not match:
                continue
            parsed = _parse_uefa_match_text(anchor.get_text(" ", strip=True))
            if not parsed:
                continue

            home_team = TEAM_MAPPING.get(parsed["home"], parsed["home"])
            away_team = TEAM_MAPPING.get(parsed["away"], parsed["away"])
            fixtures.append(
                {
                    "matchnumber": int(match.group(1)),
                    "roundnumber": None,
                    "dateutc": None,
                    "location": None,
                    "hometeam": home_team,
                    "awayteam": away_team,
                    "matchgroup": competition_name,
                    "hometeamscore": parsed["home_score"],
                    "awayteamscore": parsed["away_score"],
                    "dateeat": _uefa_default_dateeat(date_string, paragraph_text),
                    "season": CURRENT_EPL_SEASON,
                    "roundlabel": None,
                }
            )
    return fixtures


def _uefa_ucl_article_fixtures_for_date(date_string):
    return _uefa_article_fixtures_for_date(
        date_string,
        UEFA_UCL_FIXTURES_ARTICLE_URL,
        "UEFA Champions League",
    )


def _uefa_uel_article_fixtures_for_date(date_string):
    return _uefa_article_fixtures_for_date(
        date_string,
        UEFA_UEL_FIXTURES_ARTICLE_URL,
        "UEFA Europa League",
    )


def _upsert_uefa_ucl_article_fixtures_for_date(date_string):
    if not supabase:
        return 0
    fixtures = _uefa_ucl_article_fixtures_for_date(date_string)
    if not fixtures:
        return 0
    payload = []
    for fixture in fixtures:
        row = dict(fixture)
        row.pop("roundlabel", None)
        payload.append(row)
    return _upsert_fixture_rows(payload)


def _upsert_uefa_uel_article_fixtures_for_date(date_string):
    if not supabase:
        return 0
    fixtures = _uefa_uel_article_fixtures_for_date(date_string)
    if not fixtures:
        return 0
    payload = []
    for fixture in fixtures:
        row = dict(fixture)
        row.pop("roundlabel", None)
        payload.append(row)
    return _upsert_fixture_rows(payload)


def _fixture_download_dateeat(utc_date):
    if not utc_date:
        return None
    try:
        dt = datetime.strptime(utc_date, '%Y-%m-%d %H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (dt + timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')


def _world_cup_round_label(match):
    group = match.get("Group")
    if group:
        return f"{WORLD_CUP_COMPETITION_NAME} - {group}"

    round_number = match.get("RoundNumber")
    return {
        4: f"{WORLD_CUP_COMPETITION_NAME} - Round of 32",
        5: f"{WORLD_CUP_COMPETITION_NAME} - Round of 16",
        6: f"{WORLD_CUP_COMPETITION_NAME} - Quarter-finals",
        7: f"{WORLD_CUP_COMPETITION_NAME} - Semi-finals",
        8: f"{WORLD_CUP_COMPETITION_NAME} - Finals",
    }.get(round_number, WORLD_CUP_COMPETITION_NAME)


def _world_cup_fixture_rows(data):
    rows = []
    for match in data:
        match_number = match.get("MatchNumber")
        if match_number is None:
            continue
        rows.append(
            {
                "matchnumber": WORLD_CUP_MATCHNUMBER_OFFSET + int(match_number),
                "roundnumber": match.get("RoundNumber"),
                "dateutc": match.get("DateUtc"),
                "location": match.get("Location"),
                "hometeam": match.get("HomeTeam"),
                "awayteam": match.get("AwayTeam"),
                "matchgroup": _world_cup_round_label(match),
                "hometeamscore": match.get("HomeTeamScore"),
                "awayteamscore": match.get("AwayTeamScore"),
                "dateeat": _fixture_download_dateeat(match.get("DateUtc")),
                "season": WORLD_CUP_SEASON,
            }
        )
    return rows


def upsert_world_cup_fixtures():
    if not supabase:
        return 0
    response = requests.get(WORLD_CUP_JSON_URL, timeout=20)
    response.raise_for_status()
    rows = _world_cup_fixture_rows(response.json())
    if not rows:
        return 0
    return _upsert_fixture_rows(rows)


def update_fixtures_from_json():
    if not supabase:
        return False
    try:
        response = requests.get(JSON_URL)
        response.raise_for_status()
        data = response.json()
        rows = []
        for match in data:
            utc_date = match.get('DateUtc')
            eat_date = _fixture_download_dateeat(utc_date)
            rows.append({
                "matchnumber": match.get('MatchNumber'),
                "roundnumber": match.get('RoundNumber'),
                "dateutc": utc_date,
                "location": match.get('Location'),
                "hometeam": match.get('HomeTeam'),
                "awayteam": match.get('AwayTeam'),
                "matchgroup": match.get('Group') or "Premier League",
                "hometeamscore": match.get('HomeTeamScore'),
                "awayteamscore": match.get('AwayTeamScore'),
                "dateeat": eat_date,
                "season": CURRENT_EPL_SEASON,
            })
        _upsert_fixture_rows(rows)
        try:
            updated = upsert_world_cup_fixtures()
            if updated:
                print(f"Upserted {updated} FIFA World Cup rows from FixtureDownload.")
        except Exception as world_cup_exc:
            print(f"FIFA World Cup sync skipped: {world_cup_exc}")
        yesterday = (get_eat_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        today = get_eat_today()
        tomorrow = (get_eat_now() + timedelta(days=1)).strftime("%Y-%m-%d")
        for date_string in {yesterday, today, tomorrow}:
            try:
                updated = _upsert_uefa_ucl_article_fixtures_for_date(date_string)
                if updated:
                    print(f"Upserted {updated} UEFA Champions League rows from UEFA.com on {date_string}.")
            except Exception as ucl_exc:
                print(f"UEFA Champions League sync skipped for {date_string}: {ucl_exc}")
            try:
                updated = _upsert_uefa_uel_article_fixtures_for_date(date_string)
                if updated:
                    print(f"Upserted {updated} UEFA Europa League rows from UEFA.com on {date_string}.")
            except Exception as uel_exc:
                print(f"UEFA Europa League sync skipped for {date_string}: {uel_exc}")

        for date_string in {today, tomorrow}:
            try:
                updated = _upsert_sky_competition_fixtures_for_date(
                    date_string,
                    competitions={"UEFA Conference League"},
                )
                if updated:
                    print(f"Upserted {updated} tracked European fixture rows on {date_string}.")
            except Exception as comp_exc:
                print(f"European fixture sync skipped for {date_string}: {comp_exc}")
        # Prioritize BBC kickoff times and normalize them to EAT for near-term fixtures.
        for date_string in {today, tomorrow}:
            try:
                updated = _apply_bbc_kickoff_overrides(date_string)
                if updated:
                    print(f"Applied BBC kickoff override for {updated} fixture rows on {date_string}.")
            except Exception as bbc_exc:
                print(f"BBC kickoff override skipped for {date_string}: {bbc_exc}")
        for date_string in {yesterday, today}:
            try:
                updated = _apply_sky_result_overrides(date_string)
                if updated:
                    print(f"Applied Sky result override for {updated} fixture rows on {date_string}.")
            except Exception as sky_exc:
                print(f"Sky result override skipped for {date_string}: {sky_exc}")
        return True
    except Exception as e:
        print(f"Error updating fixtures: {e}")
        return False