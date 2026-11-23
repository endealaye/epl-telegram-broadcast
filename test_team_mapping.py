"""Guards against feed team names that don't resolve to our fixtures table names.

Hull, Coventry and Ipswich were missing from TEAM_MAPPING, so live scores for their
matches were never matched. Run: python test_team_mapping.py
"""
from bot_config import AMHARIC_TEAMS, TEAM_MAPPING

# Names as stored in the fixtures table (Premier League, 2026-27).
FIXTURE_NAMES = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea",
    "Coventry", "Crystal Palace", "Everton", "Fulham", "Hull", "Ipswich", "Leeds",
    "Liverpool", "Man City", "Man Utd", "Newcastle", "Nott'm Forest", "Spurs",
    "Sunderland",
]

# Names the live providers (Sky, BBC, FixtureDownload) have been seen to use.
FEED_NAMES = {
    "Hull City": "Hull",
    "Hull City AFC": "Hull",
    "Coventry City": "Coventry",
    "Ipswich Town": "Ipswich",
    "Brighton and Hove Albion": "Brighton",
    "Brighton & Hove Albion": "Brighton",
}


def test_every_fixture_name_is_a_mapping_value():
    missing = [n for n in FIXTURE_NAMES if n not in TEAM_MAPPING.values()]
    assert not missing, f"Not in TEAM_MAPPING values: {missing}"


def test_feed_names_resolve():
    bad = {k: TEAM_MAPPING.get(k) for k, v in FEED_NAMES.items() if TEAM_MAPPING.get(k) != v}
    assert not bad, f"Unmapped feed names: {bad}"


def test_every_fixture_name_has_amharic():
    missing = [n for n in FIXTURE_NAMES if n not in AMHARIC_TEAMS]
    assert not missing, f"No Amharic name: {missing}"


if __name__ == "__main__":
    for fn in (
        test_every_fixture_name_is_a_mapping_value,
        test_feed_names_resolve,
        test_every_fixture_name_has_amharic,
    ):
        fn()
        print("ok", fn.__name__)
