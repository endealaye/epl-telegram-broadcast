from supabase import create_client, Client

# Configuration
SUPABASE_URL = "https://urqgbjtgrilgaltrmrmk.supabase.co"
SUPABASE_KEY = "sb_publishable_iVSr4QF92Ox-PRSaIUaLVA_c7j_xbOt"

def check_db():
    try:
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
