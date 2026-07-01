# Debug & One-Off Scripts

These are standalone utilities for database inspection, testing, and data migration.
They are not part of the core broadcast system and should not be imported by production code.

- `check_columns.py` - Inspect fixtures table schema
- `test_supabase.py` - Verify Supabase connection
- `get_may_matches.py` - Query May fixtures
- etc.

Run individually with `python3 <script_name.py>` when needed.
