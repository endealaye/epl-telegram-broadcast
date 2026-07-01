from bot_config import SUPABASE_KEY, SUPABASE_URL
from supabase import create_client, Client

def mark_non_may_sent():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Update all rows where dateeat does NOT contain '-05-' (May)
        # Note: .not_.ilike is used for "NOT LIKE"
        res = supabase.table('fixtures').update({"broadcaststatus": "result_sent"}).not_.ilike('dateeat', '%-05-%').execute()
        
        print(f"Successfully updated matches. Records affected: {len(res.data)}")
        
    except Exception as e:
        print(f"Error updating status: {e}")

if __name__ == '__main__':
    mark_non_may_sent()
