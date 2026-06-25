CREATE TABLE IF NOT EXISTS fixtures (
    matchnumber BIGINT PRIMARY KEY,
    roundnumber INTEGER,
    dateutc TEXT,
    location TEXT,
    hometeam TEXT,
    awayteam TEXT,
    matchgroup TEXT,
    hometeamscore INTEGER,
    awayteamscore INTEGER,
    dateeat TEXT,
    season TEXT,
    broadcaststatus TEXT DEFAULT 'pending',
    last_broadcast_score TEXT,
    half_time_sent BOOLEAN NOT NULL DEFAULT FALSE,
    daily_sent BOOLEAN NOT NULL DEFAULT FALSE,
    reminder_sent BOOLEAN NOT NULL DEFAULT FALSE,
    live_final_sent BOOLEAN NOT NULL DEFAULT FALSE,
    result_sent BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS fixtures_dateeat_idx ON fixtures (dateeat);
CREATE INDEX IF NOT EXISTS fixtures_season_matchgroup_idx ON fixtures (season, matchgroup);
CREATE INDEX IF NOT EXISTS fixtures_hometeam_awayteam_idx ON fixtures (hometeam, awayteam);
CREATE INDEX IF NOT EXISTS fixtures_broadcaststatus_idx ON fixtures (broadcaststatus);
