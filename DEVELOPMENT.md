# EPL Telegram Broadcast Production Guide

This document is the operational source of truth for the EPL Telegram Broadcast system in its current state.

## Purpose

The system publishes English Premier League updates to Telegram in Amharic using fixture data from FixtureDownload, live score scraping from public websites, and state stored in Supabase.

## System Overview

- Data sources:
  - FixtureDownload JSON feed for fixture schedules
  - BBC Sport live scores
  - Sky Sports live scores fallback
- Database:
  - Supabase Postgres for fixtures and bot state
- Delivery:
  - Telegram Bot API
- Automation:
  - GitHub Actions scheduled workflow
- Timezone:
  - Ethiopian Time (`EAT`, `UTC+3`) for all business logic

## Production Secrets

The following environment variables are required in production:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_ADMIN_ID`
- `SUPABASE_URL`
- `SUPABASE_KEY`

Notes:

- `TELEGRAM_CHAT_ID` is the default broadcast destination.
- `TELEGRAM_ADMIN_ID` is used for admin-only commands and alert routing.

## Required Supabase Schema

### Table: `fixtures`

The runtime expects the `fixtures` table to include at least these fields:

- `matchnumber`
- `roundnumber`
- `dateutc`
- `dateeat`
- `location`
- `hometeam`
- `awayteam`
- `matchgroup`
- `hometeamscore`
- `awayteamscore`
- `broadcaststatus`
- `last_broadcast_score`
- `half_time_sent`
- `daily_sent`
- `reminder_sent`
- `result_sent`

The repository includes [add_broadcast_state_columns.sql](/Users/nebiyou.yirga/Downloads/ft_dd/add_broadcast_state_columns.sql) for the new broadcast-state columns.

Expected semantics:

- `dateeat` stores the EAT-normalized kickoff datetime as a string.
- `broadcaststatus` remains a compatibility/status field for coarse state.
- `last_broadcast_score` prevents duplicate goal alerts.
- `half_time_sent` prevents duplicate half-time alerts.
- `daily_sent` prevents duplicate daily schedule posts.
- `reminder_sent` prevents duplicate reminder posts.
- `result_sent` prevents duplicate result posts and duplicate final-score sends.

### Table: `bot_state`

The runtime also expects a `bot_state` table with:

- `key`
- `value`

This is used to persist the Telegram `last_update_id` for command polling.

## Runtime Execution Model

The CLI entrypoint is `telegram_broadcast.py`.

Operational responsibilities are split across modules:

- `sync.py`
- `commands.py`
- `live.py`
- `broadcasts.py`
- shared config/state helpers in `bot_config.py` and `store.py`

Each invocation runs only the mode requested on the CLI:

- `refresh`
- `commands`
- `live`
- `daily`
- `reminders`
- `results`
- `heartbeat`

Important operational consequence:

- The modes are now isolated.
- Workflow orchestration determines which actions run together.

## Broadcast Modes

### `daily`

- Intended schedule: `08:00 EAT` / `05:00 UTC`
- Query: fixtures whose `dateeat` starts with today’s EAT date and `daily_sent` is false
- Output: grouped list of today’s fixtures in Amharic
- State change: updates selected rows to `daily_sent = true`

### `reminders`

- Intended schedule: every 30 minutes
- Query: fixtures starting within the next 60 minutes and `reminder_sent` is false
- Output: reminder message in Amharic
- State change: updates sent rows to `reminder_sent = true`

### `results`

- Intended schedule: every 30 minutes
- Query: today’s fixtures where score data exists and `result_sent` is false
- Output: consolidated results roundup in Amharic
- State change: updates sent rows to `result_sent = true`

### `live updates`

- Runs on every script invocation, not only on a dedicated live-update schedule
- Self-skips unless at least one fixture falls in the active window of `now - 30m` to `now + 4h`
- Reads scores from BBC first, then Sky Sports if BBC yields no usable matches
- Sends:
  - goal alerts when score changes
  - half-time alerts once per match
  - final-score alerts once per match

### `heartbeat`

- Sends a health/status message
- Can be triggered by CLI mode or by Telegram admin command

## GitHub Actions Schedule

The current workflow is `.github/workflows/broadcast.yml`.

Configured schedules:

- `0 5 * * *`
  - Runs at `05:00 UTC`, which is `08:00 EAT`
- `0 17 * * *`
  - Runs at `17:00 UTC`, which is `20:00 EAT`
- `*/30 * * * *`
  - Runs every 30 minutes

Current workflow behavior:

- `refresh` runs on the two daily refresh schedules and on manual dispatch.
- `commands` runs on the 30-minute schedule and on manual dispatch.
- `live` runs on the 30-minute schedule and on manual dispatch.
- The daily step runs on the `05:00 UTC` schedule and on manual dispatch.
- The reminders step runs on the 30-minute schedule and on manual dispatch.
- The results step runs on the 30-minute schedule and on manual dispatch.

This means the 05:00 UTC run executes:

- `refresh`
- `daily`

And the 30-minute schedule executes:

- `commands`
- `live`
- `reminders`
- `results`

## Manual Operations

Examples:

```bash
python3 telegram_broadcast.py refresh
python3 telegram_broadcast.py commands
python3 telegram_broadcast.py live
python3 telegram_broadcast.py daily
python3 telegram_broadcast.py reminders
python3 telegram_broadcast.py results
python3 telegram_broadcast.py heartbeat
```

Before manual execution, ensure the required environment variables are present or available through `.env`.

## Success Checks

After deployment or manual runs, verify:

- The GitHub Actions job completes successfully
- Telegram receives the expected message
- Supabase rows update as expected for `broadcaststatus`, `last_broadcast_score`, `half_time_sent`, `daily_sent`, `reminder_sent`, and `result_sent`
- The `bot_state` table contains a valid `last_update_id` after command polling

## Failure Handling

### Telegram failure

Symptoms:

- No message delivered
- Admin alert not delivered

Checks:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_ADMIN_ID`
- Workflow logs

### Supabase failure

Symptoms:

- No fixture reads or writes
- No state transitions
- Command polling state not persisted

Checks:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- Required tables and columns exist

### Live scraping failure

Symptoms:

- No live alerts despite matches being in progress

Checks:

- BBC page structure may have changed
- Sky Sports page structure may have changed
- Team names from scraper output must match `TEAM_MAPPING`

## Known Gaps

- There is no Goal provider implemented, despite earlier roadmap language that suggested one.
- `dateeat` is still stored as a string, so time-window logic depends on consistent formatting.
- The document reflects the current implementation, not an ideal future architecture.

## Recommended Next Changes

- Consider separating `commands` from broadcast-oriented schedules if Telegram polling latency becomes a problem.
- Replace string-based datetime storage with a native timestamp column if schema changes are acceptable.
- Add an explicit schema migration and keep this document aligned with it.
