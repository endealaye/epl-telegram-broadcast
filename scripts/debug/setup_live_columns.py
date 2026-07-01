from bot_config import SUPABASE_KEY, SUPABASE_URL
from supabase import create_client

def add_live_columns():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # We need to track the last score sent to avoid duplicate goal alerts
        # and we want to track if the half-time alert was sent.
        
        # Since we can't run raw SQL 'ALTER TABLE' via the basic Supabase client 
        # without a service role key/special setup, I will advise the user 
        # to run the SQL in the dashboard or I will try to use an RPC if available.
        # Actually, the best way is to give the user the SQL command.
        
        print("To enable intelligent broadcast state, run this SQL in your Supabase Dashboard:")
        print("-" * 30)
        print("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS last_broadcast_score TEXT;")
        print("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS half_time_sent BOOLEAN DEFAULT FALSE;")
        print("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS daily_sent BOOLEAN DEFAULT FALSE;")
        print("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS reminder_sent BOOLEAN DEFAULT FALSE;")
        print("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS live_final_sent BOOLEAN DEFAULT FALSE;")
        print("ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS result_sent BOOLEAN DEFAULT FALSE;")
        print("-" * 30)
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    add_live_columns()
