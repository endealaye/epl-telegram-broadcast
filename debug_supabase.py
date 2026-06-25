from bot_config import SUPABASE_KEY, SUPABASE_URL
from supabase import create_client, Client

def debug_table():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Try a very simple select to see if the table is found
        supabase.table('fixtures').select('MatchNumber').limit(1).execute()
        print("Table exists and is accessible.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    debug_table()
