from datetime import datetime, timezone

from store import supabase


COACH_SOURCE_NAME = "Current public coach audit"

WORLD_CUP_COACHES = {
    "Algeria": ("Vladimir Petkovic", "https://en.wikipedia.org/wiki/Algeria_national_football_team"),
    "Argentina": ("Lionel Scaloni", "https://en.wikipedia.org/wiki/Argentina_national_football_team"),
    "Australia": ("Tony Popovic", "https://en.wikipedia.org/wiki/Australia_national_football_team"),
    "Austria": ("Ralf Rangnick", "https://en.wikipedia.org/wiki/Austria_national_football_team"),
    "Belgium": ("Rudi Garcia", "https://en.wikipedia.org/wiki/Belgium_national_football_team"),
    "Bosnia and Herzegovina": ("Sergej Barbarez", "https://en.wikipedia.org/wiki/Bosnia_and_Herzegovina_national_football_team"),
    "Brazil": ("Carlo Ancelotti", "https://en.wikipedia.org/wiki/Brazil_national_football_team"),
    "Cabo Verde": ("Bubista", "https://en.wikipedia.org/wiki/Cape_Verde_national_football_team"),
    "Canada": ("Jesse Marsch", "https://en.wikipedia.org/wiki/Canada_men%27s_national_soccer_team"),
    "Colombia": ("Nestor Lorenzo", "https://en.wikipedia.org/wiki/Colombia_national_football_team"),
    "Congo DR": ("Sebastien Desabre", "https://en.wikipedia.org/wiki/DR_Congo_national_football_team"),
    "Côte d'Ivoire": ("Emerse Fae", "https://en.wikipedia.org/wiki/Ivory_Coast_national_football_team"),
    "Croatia": ("Zlatko Dalic", "https://en.wikipedia.org/wiki/Croatia_national_football_team"),
    "Curaçao": ("Dick Advocaat", "https://en.wikipedia.org/wiki/Cura%C3%A7ao_national_football_team"),
    "Czechia": ("Miroslav Koubek", "https://en.wikipedia.org/wiki/Czech_Republic_national_football_team"),
    "Ecuador": ("Sebastian Beccacece", "https://en.wikipedia.org/wiki/Ecuador_national_football_team"),
    "Egypt": ("Hossam Hassan", "https://en.wikipedia.org/wiki/Egypt_national_football_team"),
    "England": ("Thomas Tuchel", "https://en.wikipedia.org/wiki/England_national_football_team"),
    "France": ("Didier Deschamps", "https://en.wikipedia.org/wiki/France_national_football_team"),
    "Germany": ("Julian Nagelsmann", "https://en.wikipedia.org/wiki/Germany_national_football_team"),
    "Ghana": ("Carlos Queiroz", "https://en.wikipedia.org/wiki/Ghana_national_football_team"),
    "Haiti": ("Sebastien Migne", "https://en.wikipedia.org/wiki/Haiti_national_football_team"),
    "IR Iran": ("Amir Ghalenoei", "https://en.wikipedia.org/wiki/Iran_national_football_team"),
    "Iraq": ("Jesus Casas", "https://en.wikipedia.org/wiki/Iraq_national_football_team"),
    "Japan": ("Hajime Moriyasu", "https://en.wikipedia.org/wiki/Japan_national_football_team"),
    "Jordan": ("Jamal Sellami", "https://en.wikipedia.org/wiki/Jordan_national_football_team"),
    "Korea Republic": ("Hong Myung-bo", "https://en.wikipedia.org/wiki/South_Korea_national_football_team"),
    "Mexico": ("Javier Aguirre", "https://en.wikipedia.org/wiki/Mexico_national_football_team"),
    "Morocco": ("Mohamed Ouahbi", "https://en.wikipedia.org/wiki/Morocco_national_football_team"),
    "Netherlands": ("Ronald Koeman", "https://en.wikipedia.org/wiki/Netherlands_national_football_team"),
    "New Zealand": ("Darren Bazeley", "https://en.wikipedia.org/wiki/New_Zealand_national_football_team"),
    "Norway": ("Stale Solbakken", "https://en.wikipedia.org/wiki/Norway_national_football_team"),
    "Panama": ("Thomas Christiansen", "https://en.wikipedia.org/wiki/Panama_national_football_team"),
    "Paraguay": ("Gustavo Alfaro", "https://en.wikipedia.org/wiki/Paraguay_national_football_team"),
    "Portugal": ("Roberto Martinez", "https://en.wikipedia.org/wiki/Portugal_national_football_team"),
    "Qatar": ("Julen Lopetegui", "https://en.wikipedia.org/wiki/Qatar_national_football_team"),
    "Saudi Arabia": ("Herve Renard", "https://en.wikipedia.org/wiki/Saudi_Arabia_national_football_team"),
    "Scotland": ("Steve Clarke", "https://en.wikipedia.org/wiki/Scotland_national_football_team"),
    "Senegal": ("Pape Thiaw", "https://en.wikipedia.org/wiki/Senegal_national_football_team"),
    "South Africa": ("Hugo Broos", "https://en.wikipedia.org/wiki/South_Africa_national_soccer_team"),
    "Spain": ("Luis de la Fuente", "https://en.wikipedia.org/wiki/Spain_national_football_team"),
    "Sweden": ("Graham Potter", "https://en.wikipedia.org/wiki/Sweden_national_football_team"),
    "Switzerland": ("Murat Yakin", "https://en.wikipedia.org/wiki/Switzerland_national_football_team"),
    "Tunisia": ("Sabri Lamouchi", "https://en.wikipedia.org/wiki/Tunisia_national_football_team"),
    "Türkiye": ("Vincenzo Montella", "https://en.wikipedia.org/wiki/Turkey_national_football_team"),
    "Uruguay": ("Marcelo Bielsa", "https://en.wikipedia.org/wiki/Uruguay_national_football_team"),
    "USA": ("Mauricio Pochettino", "https://en.wikipedia.org/wiki/United_States_men%27s_national_soccer_team"),
    "Uzbekistan": ("Fabio Cannavaro", "https://en.wikipedia.org/wiki/Uzbekistan_national_football_team"),
}


def update_world_cup_coaches():
    if not supabase:
        return {"updated": 0, "missing_teams": sorted(WORLD_CUP_COACHES)}

    existing = (
        supabase.table("world_cup_teams")
        .select("team_name,raw_payload")
        .execute()
        .data
        or []
    )
    existing_by_team = {row["team_name"]: row for row in existing if row.get("team_name")}
    now = datetime.now(timezone.utc).isoformat()
    column_payload = []
    raw_payload_updates = []
    missing_teams = []

    for team_name, (coach_name, source_url) in WORLD_CUP_COACHES.items():
        existing_row = existing_by_team.get(team_name)
        if not existing_row:
            missing_teams.append(team_name)
            continue
        raw_payload = dict(existing_row.get("raw_payload") or {})
        raw_payload["coach"] = {
            "name": coach_name,
            "source_name": COACH_SOURCE_NAME,
            "source_url": source_url,
            "verified_at": now,
        }
        column_payload.append(
            {
                "team_name": team_name,
                "coach_name": coach_name,
                "coach_source_name": COACH_SOURCE_NAME,
                "coach_source_url": source_url,
                "coach_verified_at": now,
                "raw_payload": raw_payload,
                "updated_at": now,
            }
        )
        raw_payload_updates.append(
            {
                "team_name": team_name,
                "raw_payload": raw_payload,
                "updated_at": now,
            }
        )

    columns_updated = False
    if column_payload:
        try:
            supabase.table("world_cup_teams").upsert(column_payload, on_conflict="team_name").execute()
            columns_updated = True
        except Exception as exc:
            if "coach_name" not in str(exc):
                raise
            supabase.table("world_cup_teams").upsert(raw_payload_updates, on_conflict="team_name").execute()

    return {
        "updated": len(column_payload),
        "columns_updated": columns_updated,
        "stored_in_raw_payload": not columns_updated,
        "missing_teams": sorted(missing_teams),
    }


if __name__ == "__main__":
    print(update_world_cup_coaches())
