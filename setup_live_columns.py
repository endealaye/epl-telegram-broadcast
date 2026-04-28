import os
from supabase import create_client, Client

# Configuration
SUPABASE_URL = "https://urqgbjtgrilgaltrmrmk.supabase.co"
SUPABASE_KEY = "sb_publishable_iVSr4QF92Ox-PRSaIUaLVA_c7j_xbOt"

def add_live_columns():
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # We need to track the last score sent to avoid duplicate goal alerts
        # and we want to track if the half-time alert was sent.
        
        # Since we can't run raw SQL 'ALTER TABLE' via the basic Supabase client 
        # without a service role key/special setup, I will advise the user 
        # to run the SQL in the dashboard or I will try to use an RPC if available.
        # Actually, the best way is to give the user the SQL command.
        
        print("To enable live alerts, please run this SQL in your Supabase Dashboard:")
        print("-" * 30)
        print("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS last_broadcast_score TEXT;")
        print("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS half_time_sent BOOLEAN DEFAULT FALSE;")
        print("-" * 30)
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    add_live_columns()
