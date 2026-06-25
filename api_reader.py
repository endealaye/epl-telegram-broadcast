import requests

def get_match_events(match_id):
    """
    Fetches match events (goals, etc.) for a specific World Cup match
    using the WorldCup26.ir API.
    """
    # WorldCup26.ir API endpoint structure
    url = f"https://worldcup26.ir/api/matches/{match_id}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Check if events exist in the payload
        events = data.get("events", [])
        goals = [e for e in events if e.get("type") == "goal"]
        
        return goals
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

if __name__ == "__main__":
    # Example: France vs Senegal match ID (using a placeholder based on API structure)
    # The API structure usually maps match numbers to their IDs.
    # I will fetch a list of matches first to find the correct ID for Match #2026017
    
    list_url = "https://worldcup26.ir/api/matches"
    response = requests.get(list_url, timeout=10)
    matches = response.json()
    
    match_id = None
    for m in matches:
        if m.get("match_number") == 2026017:
            match_id = m.get("id")
            break
            
    if match_id:
        print(f"Found match ID: {match_id}. Fetching events...")
        goals = get_match_events(match_id)
        
        if goals:
            print("\n--- Goal Scorers ---")
            for goal in goals:
                print(f"{goal.get('minute')}' ⚽ {goal.get('player_name')} ({goal.get('team_name')})")
        else:
            print("No goals found for this match.")
    else:
        print("Match not found in the WorldCup26.ir API.")
