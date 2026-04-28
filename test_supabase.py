import os
from supabase import create_client, Client

# Configuration
SUPABASE_URL = "https://urqgbjtgrilgaltrmrmk.supabase.co"
SUPABASE_KEY = "sb_publishable_iVSr4QF92Ox-PRSaIUaLVA_c7j_xbOt"

def test_connection():
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Try to fetch a count of the fixtures table
        res = supabase.table('fixtures').select('*', count='exact').execute()
        print(f"Connection successful! Total rows in fixtures: {res.count}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == '__main__':
    test_connection()
