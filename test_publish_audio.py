from news_pipeline import mark_review_item

item_id = 13926
title_am = "የሙከራ ዜና፡ የድምፅ መልዕክት ስራ ላይ ነው"
story_am = "ይህ የድምፅ ሙከራ ነው። ቦቱ አሁን ዜናዎችን በድምፅ መላክ ይችላል።"
highlight_am = "የድምፅ ሙከራ"

print(f"Attempting to publish item {item_id} with audio...")
try:
    mark_review_item(
        item_id=item_id,
        status="published",
        translated_title_am=title_am,
        translated_story_am=story_am,
        highlight_am=highlight_am
    )
    print("Successfully published and audio sent!")
except Exception as e:
    print(f"Error publishing: {e}")
