from bot_config import SUPABASE_KEY, SUPABASE_URL
from supabase import create_client, Client

def get_may_matches():
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY")
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Query for matches in May. Using ilike for the DateEAT column (lowercase).
        res = supabase.table('fixtures').select('dateeat, hometeam, awayteam').ilike('dateeat', '%-05-%').order('dateeat').execute()
        
        matches = res.data
        if not matches:
            print("No matches found for May.")
            return
            
        print(f"Found {len(matches)} matches in May:\n")
        print(f"{'Date (EAT)':<20} | {'Home Team':<20} | {'Away Team':<20}")
        print("-" * 65)
        for m in matches:
            date = m['dateeat'].split(' ')[0] if m['dateeat'] else "N/A"
            time = m['dateeat'].split(' ')[1] if m['dateeat'] and ' ' in m['dateeat'] else ""
            print(f"{date + ' ' + time:<20} | {m['hometeam']:<20} | {m['awayteam']:<20}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    get_may_matches()
