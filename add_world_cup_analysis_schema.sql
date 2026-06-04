ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS result_note TEXT;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS went_extra_time BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS went_penalties BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS home_penalties INTEGER;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS away_penalties INTEGER;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS winner_team TEXT;
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS source_status TEXT NOT NULL DEFAULT 'unverified'
    CHECK (source_status IN ('unverified', 'confirmed', 'mismatch', 'single_source'));
ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS source_notes TEXT;

CREATE TABLE IF NOT EXISTS world_cup_fixture_source_checks (
    matchnumber BIGINT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'mismatch', 'single_source')),
    mismatch_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_primary TEXT NOT NULL DEFAULT 'FixtureDownload',
    source_secondary TEXT NOT NULL DEFAULT 'OpenFootball',
    primary_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    secondary_payload JSONB,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS world_cup_teams (
    team_name TEXT PRIMARY KEY,
    group_name TEXT,
    name_am TEXT,
    short_name_am TEXT,
    flag_path TEXT,
    source_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (source_status IN ('unverified', 'confirmed', 'mismatch', 'single_source')),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS world_cup_players (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_name TEXT NOT NULL,
    team_name TEXT NOT NULL REFERENCES world_cup_teams(team_name) ON DELETE CASCADE,
    position TEXT,
    club TEXT,
    date_of_birth DATE,
    source_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (source_status IN ('unverified', 'confirmed', 'mismatch', 'single_source')),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (team_name, player_name)
);

CREATE TABLE IF NOT EXISTS world_cup_recent_matches (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_name TEXT NOT NULL REFERENCES world_cup_teams(team_name) ON DELETE CASCADE,
    match_date DATE NOT NULL,
    opponent TEXT NOT NULL,
    team_score INTEGER,
    opponent_score INTEGER,
    venue_type TEXT CHECK (venue_type IN ('home', 'away', 'neutral')),
    competition TEXT,
    source_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (source_status IN ('unverified', 'confirmed', 'mismatch', 'single_source')),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (team_name, match_date, opponent)
);

CREATE TABLE IF NOT EXISTS world_cup_player_availability (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_name TEXT NOT NULL REFERENCES world_cup_teams(team_name) ON DELETE CASCADE,
    player_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('available', 'doubtful', 'injured', 'suspended', 'omitted', 'unknown')),
    note TEXT,
    source_name TEXT,
    source_url TEXT,
    reported_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS world_cup_group_standings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    group_name TEXT NOT NULL,
    team_name TEXT NOT NULL REFERENCES world_cup_teams(team_name) ON DELETE CASCADE,
    played INTEGER NOT NULL DEFAULT 0,
    won INTEGER NOT NULL DEFAULT 0,
    drawn INTEGER NOT NULL DEFAULT 0,
    lost INTEGER NOT NULL DEFAULT 0,
    goals_for INTEGER NOT NULL DEFAULT 0,
    goals_against INTEGER NOT NULL DEFAULT 0,
    goal_difference INTEGER NOT NULL DEFAULT 0,
    points INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_name, team_name)
);

CREATE TABLE IF NOT EXISTS match_analysis (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    matchnumber BIGINT NOT NULL REFERENCES fixtures(matchnumber) ON DELETE CASCADE,
    analysis_type TEXT NOT NULL CHECK (analysis_type IN ('preview', 'recap', 'player_focus', 'availability')),
    language TEXT NOT NULL DEFAULT 'am',
    title TEXT,
    body TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'source_based'
        CHECK (confidence IN ('source_based', 'partial', 'speculative')),
    source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_status TEXT NOT NULL DEFAULT 'draft'
        CHECK (review_status IN ('draft', 'approved', 'published', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (matchnumber, analysis_type, language)
);

CREATE INDEX IF NOT EXISTS world_cup_teams_group_idx ON world_cup_teams (group_name);
CREATE INDEX IF NOT EXISTS world_cup_players_team_idx ON world_cup_players (team_name);
CREATE INDEX IF NOT EXISTS world_cup_recent_matches_team_date_idx ON world_cup_recent_matches (team_name, match_date DESC);
CREATE INDEX IF NOT EXISTS world_cup_availability_team_status_idx ON world_cup_player_availability (team_name, status);
CREATE INDEX IF NOT EXISTS world_cup_group_standings_group_idx ON world_cup_group_standings (group_name, points DESC, goal_difference DESC);
CREATE INDEX IF NOT EXISTS match_analysis_matchnumber_idx ON match_analysis (matchnumber);
CREATE INDEX IF NOT EXISTS fixtures_source_status_idx ON fixtures (source_status);
