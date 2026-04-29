from supabase import create_client, Client

# Configuration
SUPABASE_URL = "https://urqgbjtgrilgaltrmrmk.supabase.co"
SUPABASE_KEY = "sb_publishable_iVSr4QF92Ox-PRSaIUaLVA_c7j_xbOt"

def get_columns():
    try:
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
