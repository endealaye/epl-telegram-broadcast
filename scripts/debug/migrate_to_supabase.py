import sqlite3
from supabase import create_client, Client

from bot_config import CURRENT_EPL_SEASON, SUPABASE_KEY, SUPABASE_URL

LOCAL_DB_FILE = 'epl_2025.db'


def infer_fixture_season(row):
    matchgroup = (row.get("matchgroup") or "").strip()
    if matchgroup == "Premier League" or not matchgroup:
        return CURRENT_EPL_SEASON
    return CURRENT_EPL_SEASON

def migrate():
    # Initialize Supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Migration failed: missing SUPABASE_URL or SUPABASE_KEY in environment.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Connect to local SQLite
    try:
        conn = sqlite3.connect(LOCAL_DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Fetch all data
        cursor.execute("SELECT * FROM fixtures")
        rows = cursor.fetchall()
        
        if not rows:
            print("No data found in local database to migrate.")
            return
            
        print(f"Found {len(rows)} rows to migrate...")
        
        # Prepare data for Supabase upsert with lowercase keys
        data_to_push = []
        for row in rows:
            # Convert SQLite CamelCase keys to Supabase lowercase keys
            lowered_row = {k.lower(): row[k] for k in row.keys()}
            lowered_row.setdefault("season", infer_fixture_season(lowered_row))
            data_to_push.append(lowered_row)
            
        # Push to Supabase in chunks to avoid payload size limits
        chunk_size = 100
        for i in range(0, len(data_to_push), chunk_size):
            chunk = data_to_push[i:i + chunk_size]
            supabase.table('fixtures').upsert(chunk).execute()
            print(f"Migrated rows {i+1} to {min(i + chunk_size, len(data_to_push))}...")
            
        print(f"Successfully migrated {len(rows)} rows to Supabase.")
        
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    migrate()
