import os
from supabase import create_client, Client

SUPABASE_URL = "https://urqgbjtgrilgaltrmrmk.supabase.co"
SUPABASE_KEY = "sb_publishable_iVSr4QF92Ox-PRSaIUaLVA_c7j_xbOt"

def debug_table():
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Try a very simple select to see if the table is found
        res = supabase.table('fixtures').select('MatchNumber').limit(1).execute()
        print("Table exists and is accessible.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    debug_table()
