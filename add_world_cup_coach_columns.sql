ALTER TABLE world_cup_teams ADD COLUMN IF NOT EXISTS coach_name TEXT;
ALTER TABLE world_cup_teams ADD COLUMN IF NOT EXISTS coach_source_name TEXT;
ALTER TABLE world_cup_teams ADD COLUMN IF NOT EXISTS coach_source_url TEXT;
ALTER TABLE world_cup_teams ADD COLUMN IF NOT EXISTS coach_verified_at TIMESTAMPTZ;
