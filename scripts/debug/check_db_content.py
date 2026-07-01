from bot_config import SUPABASE_KEY, SUPABASE_URL
from supabase import create_client, Client

def check_db():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Fetch the first 5 rows to verify content
        res = supabase.table('fixtures').select('*').limit(5).execute()
        
        if res.data:
            print(f"Database accessed successfully! Found {len(res.data)} sample rows.")
            for row in res.data:
                print(row)
        else:
            print("Connected to database, but the 'fixtures' table is empty.")
            
    except Exception as e:
        print(f"Failed to access database: {e}")

if __name__ == '__main__':
    check_db()
