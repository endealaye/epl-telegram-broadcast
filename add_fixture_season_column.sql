ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS season TEXT;

UPDATE fixtures
SET season = '2025-26'
WHERE season IS NULL
  AND matchgroup IN (
    'Premier League',
    'UEFA Champions League',
    'UEFA Europa League',
    'UEFA Conference League'
  )
  AND dateeat >= '2025-08-01 00:00:00'
  AND dateeat < '2026-08-01 00:00:00';

UPDATE fixtures
SET season = '2026'
WHERE season IS NULL
  AND matchgroup ILIKE 'FIFA World Cup%';

CREATE INDEX IF NOT EXISTS fixtures_season_matchgroup_idx
ON fixtures (season, matchgroup);
