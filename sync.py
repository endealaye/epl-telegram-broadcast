import html
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from bot_config import BBC_SCORES_URL_TEMPLATE, JSON_URL, TEAM_MAPPING, get_eat_now, get_eat_today
from store import supabase


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


def _sky_result_overrides_for_date(date_string):
    url = f"https://www.skysports.com/football-scores-fixtures/{date_string}"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

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
        if competition_name != "Premier League":
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
        overrides[(mapped_home, mapped_away)] = (int(home_score), int(away_score))

    return overrides


def _apply_sky_result_overrides(date_string):
    if not supabase:
        return 0
    overrides = _sky_result_overrides_for_date(date_string)
    updated = 0
    for (home_team, away_team), (home_score, away_score) in overrides.items():
        res = (
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
            .execute()
        )
        rows = res.data or []
        updated += len(rows)
    return updated


def update_fixtures_from_json():
    if not supabase:
        return False
    try:
        response = requests.get(JSON_URL)
        response.raise_for_status()
        data = response.json()
        for match in data:
            utc_date = match.get('DateUtc')
            eat_date = None
            if utc_date:
                try:
                    dt = datetime.strptime(utc_date, '%Y-%m-%d %H:%M:%SZ').replace(tzinfo=timezone.utc)
                    eat_date = (dt + timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass
            supabase.table('fixtures').upsert({
                "matchnumber": match.get('MatchNumber'),
                "roundnumber": match.get('RoundNumber'),
                "dateutc": utc_date,
                "location": match.get('Location'),
                "hometeam": match.get('HomeTeam'),
                "awayteam": match.get('AwayTeam'),
                "matchgroup": match.get('Group'),
                "hometeamscore": match.get('HomeTeamScore'),
                "awayteamscore": match.get('AwayTeamScore'),
                "dateeat": eat_date,
            }).execute()
        # Prioritize BBC kickoff times and normalize them to EAT for near-term fixtures.
        today = get_eat_today()
        tomorrow = (get_eat_now() + timedelta(days=1)).strftime("%Y-%m-%d")
        for date_string in {today, tomorrow}:
            try:
                updated = _apply_bbc_kickoff_overrides(date_string)
                if updated:
                    print(f"Applied BBC kickoff override for {updated} fixture rows on {date_string}.")
            except Exception as bbc_exc:
                print(f"BBC kickoff override skipped for {date_string}: {bbc_exc}")
        yesterday = (get_eat_now() - timedelta(days=1)).strftime("%Y-%m-%d")
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
