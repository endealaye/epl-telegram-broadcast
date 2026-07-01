from bot_config import SUPABASE_KEY, SUPABASE_URL
from supabase import create_client, Client

def test_connection():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Try to fetch a count of the fixtures table
        res = supabase.table('fixtures').select('*', count='exact').execute()
        print(f"Connection successful! Total rows in fixtures: {res.count}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == '__main__':
    test_connection()
