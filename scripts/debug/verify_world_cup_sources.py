import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from bot_config import AMHARIC_TEAMS, SHORT_AMHARIC_TEAMS, TEAM_MAPPING, WORLD_CUP_JSON_URL
from standings import _resolve_logo_path
from store import supabase


OPENFOOTBALL_WORLD_CUP_URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
)
REPO_ROOT = Path(__file__).resolve().parent


def normalize_team_name(name):
    value = (name or "").strip()
    value = value.replace("&", "and")
    value = re.sub(r"\s*/\s*", "", value)
    value = re.sub(r"\s+", " ", value)
    mapped = TEAM_MAPPING.get(value, value)
    return mapped.lower()


def normalize_placeholder(name):
    value = (name or "").strip()
    value = value.replace("/", "")
    return re.sub(r"\s+", "", value).lower()


def parse_fixture_download_datetime(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_openfootball_datetime(match):
    time_text = match.get("time") or ""
    parsed = re.match(r"^(\d{1,2}):(\d{2})\s+UTC([+-]\d{1,2})$", time_text)
    if not parsed:
        raise ValueError(f"Unsupported OpenFootball time: {time_text}")
    hour, minute, offset = parsed.groups()
    local = datetime.strptime(
        f"{match.get('date')} {int(hour):02d}:{minute}",
        "%Y-%m-%d %H:%M",
    )
    offset_tz = timezone(timedelta(hours=int(offset)))
    return local.replace(tzinfo=offset_tz).astimezone(timezone.utc)


def fixture_download_rows():
    response = requests.get(WORLD_CUP_JSON_URL, timeout=20)
    response.raise_for_status()
    rows = {}
    for match in response.json():
        match_number = int(match["MatchNumber"])
        rows[match_number] = {
            "dateutc": parse_fixture_download_datetime(match["DateUtc"]),
            "home": normalize_team_name(match.get("HomeTeam")),
            "away": normalize_team_name(match.get("AwayTeam")),
            "home_placeholder": normalize_placeholder(match.get("HomeTeam")),
            "away_placeholder": normalize_placeholder(match.get("AwayTeam")),
            "group": (match.get("Group") or "").strip(),
            "raw": match,
        }
    return rows


def openfootball_rows():
    response = requests.get(OPENFOOTBALL_WORLD_CUP_URL, timeout=20)
    response.raise_for_status()
    rows = {}
    synthetic_group_number = 0
    for match in response.json().get("matches") or []:
        match_number = match.get("num")
        if match_number is None:
            round_name = (match.get("round") or "").strip().lower()
            if round_name == "match for third place":
                match_number = 103
            elif round_name == "final":
                match_number = 104
            else:
                synthetic_group_number += 1
                match_number = synthetic_group_number
        match_number = int(match_number)
        rows[match_number] = {
            "dateutc": parse_openfootball_datetime(match),
            "home": normalize_team_name(match.get("team1")),
            "away": normalize_team_name(match.get("team2")),
            "home_placeholder": normalize_placeholder(match.get("team1")),
            "away_placeholder": normalize_placeholder(match.get("team2")),
            "group": (match.get("group") or "").strip(),
            "raw": match,
        }
    return rows


def group_match_key(row):
    return (
        row["dateutc"],
        row["home"],
        row["away"],
        row["group"],
    )


def group_identity_key(row):
    return (
        row["home"],
        row["away"],
        row["group"],
    )


def is_known_group_match(row):
    return bool(row["group"])


def teams_match(primary, secondary, side):
    primary_team = primary[f"{side}"]
    secondary_team = secondary[f"{side}"]
    if primary_team == secondary_team:
        return True
    return primary[f"{side}_placeholder"] == secondary[f"{side}_placeholder"]


def compare_sources():
    fixture_download = fixture_download_rows()
    openfootball = openfootball_rows()

    fd_group_keys = {
        group_identity_key(row): row
        for row in fixture_download.values()
        if is_known_group_match(row)
    }
    of_group_keys = {
        group_identity_key(row): row
        for row in openfootball.values()
        if is_known_group_match(row)
    }

    mismatches = []
    for key in sorted(set(fd_group_keys) - set(of_group_keys)):
        mismatches.append((None, "group_missing_from_openfootball", fd_group_keys[key], None))
    for key in sorted(set(of_group_keys) - set(fd_group_keys)):
        mismatches.append((None, "group_missing_from_fixture_download", None, of_group_keys[key]))
    for key in sorted(set(fd_group_keys) & set(of_group_keys)):
        fd = fd_group_keys[key]
        of = of_group_keys[key]
        if fd["dateutc"] != of["dateutc"]:
            mismatches.append((fd["raw"].get("MatchNumber"), "group_dateutc", fd, of))

    knockout_numbers = sorted(
        number
        for number, row in fixture_download.items()
        if not is_known_group_match(row)
    )
    for match_number in knockout_numbers:
        fd = fixture_download.get(match_number)
        of = openfootball.get(match_number)
        if not fd or not of:
            mismatches.append((match_number, "missing", fd, of))
            continue
        checks = {
            "dateutc": fd["dateutc"] == of["dateutc"],
            "home": fd["home_placeholder"] == "tobeannounced" or teams_match(fd, of, "home"),
            "away": fd["away_placeholder"] == "tobeannounced" or teams_match(fd, of, "away"),
            "group": fd["group"] == of["group"],
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            mismatches.append((match_number, ",".join(failed), fd, of))
    return fixture_download, openfootball, mismatches


def json_safe_payload(payload):
    return json.loads(json.dumps(payload or {}, ensure_ascii=False, default=str))


def build_check_rows(fixture_download, openfootball, mismatches):
    mismatch_by_matchnumber = {}
    for match_number, reason, fd, of in mismatches:
        if match_number is None and fd:
            match_number = fd["raw"].get("MatchNumber")
        if match_number is None:
            continue
        mismatch_by_matchnumber.setdefault(int(match_number), []).append(reason)

    rows = []
    for match_number, fd in sorted(fixture_download.items()):
        of = openfootball.get(match_number)
        reasons = mismatch_by_matchnumber.get(match_number, [])
        status = "mismatch" if reasons else "confirmed"
        if not of:
            status = "single_source"
            reasons = reasons or ["missing_secondary_source"]
        rows.append(
            {
                "matchnumber": int(match_number),
                "status": status,
                "mismatch_reasons": reasons,
                "source_primary": "FixtureDownload",
                "source_secondary": "OpenFootball",
                "primary_payload": json_safe_payload(fd["raw"]),
                "secondary_payload": json_safe_payload(of["raw"]) if of else None,
            }
        )
    return rows


def build_team_rows(fixture_download):
    teams = {}
    for row in fixture_download.values():
        group_name = row.get("group")
        if not group_name:
            continue
        for side, raw_field in (("home", "HomeTeam"), ("away", "AwayTeam")):
            raw_name = row["raw"].get(raw_field)
            team_name = TEAM_MAPPING.get(raw_name, raw_name)
            if not team_name or re.match(r"^(?:\d|to be announced)", team_name, re.IGNORECASE):
                continue
            logo_path = _resolve_logo_path({"team": team_name, "team_display": team_name})
            teams[team_name] = {
                "team_name": team_name,
                "group_name": group_name,
                "name_am": AMHARIC_TEAMS.get(team_name),
                "short_name_am": SHORT_AMHARIC_TEAMS.get(team_name) or AMHARIC_TEAMS.get(team_name),
                "flag_path": str(logo_path.relative_to(REPO_ROOT)) if logo_path else None,
                "source_status": "confirmed",
                "raw_payload": {"source": "FixtureDownload", "group": group_name},
            }
    return list(teams.values())


def persist_source_checks(fixture_download, openfootball, mismatches):
    if not supabase:
        raise RuntimeError("Supabase is not configured.")

    check_rows = build_check_rows(fixture_download, openfootball, mismatches)
    team_rows = build_team_rows(fixture_download)

    supabase.table("world_cup_fixture_source_checks").upsert(check_rows, on_conflict="matchnumber").execute()
    supabase.table("world_cup_teams").upsert(team_rows, on_conflict="team_name").execute()

    for row in check_rows:
        notes = ", ".join(row["mismatch_reasons"]) if row["mismatch_reasons"] else None
        supabase.table("fixtures").update(
            {
                "source_status": row["status"],
                "source_notes": notes,
            }
        ).eq("matchnumber", 2_026_000 + row["matchnumber"]).execute()

    return {"source_checks": len(check_rows), "teams": len(team_rows)}


def main():
    parser = argparse.ArgumentParser(description="Compare World Cup fixtures from two free sources.")
    parser.add_argument("--persist", action="store_true", help="Write source checks and teams to Supabase.")
    args = parser.parse_args()

    fixture_download, openfootball, mismatches = compare_sources()
    confirmed_group_count = sum(1 for row in fixture_download.values() if is_known_group_match(row))
    knockout_count = len(fixture_download) - confirmed_group_count
    print(f"FixtureDownload matches: {len(fixture_download)}")
    print(f"OpenFootball matches: {len(openfootball)}")
    print(f"Confirmed group-stage matches: {confirmed_group_count}")
    print(f"Knockout/placeholders: {knockout_count}")
    print(f"Mismatches: {len(mismatches)}")
    for match_number, reason, fd, of in mismatches:
        print(f"\nMatch {match_number}: {reason}")
        print(f"  FixtureDownload: {fd['raw'] if fd else None}")
        print(f"  OpenFootball: {of['raw'] if of else None}")

    if args.persist:
        result = persist_source_checks(fixture_download, openfootball, mismatches)
        print(f"\nPersisted source checks: {result['source_checks']}")
        print(f"Persisted teams: {result['teams']}")


if __name__ == "__main__":
    main()
