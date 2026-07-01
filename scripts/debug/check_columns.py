from bot_config import SUPABASE_KEY, SUPABASE_URL
from supabase import create_client, Client

def get_columns():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        res = supabase.table('fixtures').select('*').limit(1).execute()
        
        if res.data and len(res.data) > 0:
            columns = res.data[0].keys()
            print(f"Columns in 'fixtures' table: {', '.join(columns)}")
        else:
            print("Table is empty or not found. Could not retrieve columns.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    get_columns()
