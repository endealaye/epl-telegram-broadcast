
import json
from orchestrator import route_event_dict

def translate_to_amharic(text, context="news"):
    \"\"\"
    Placeholder for translation logic.
    In a real production environment, this would call an LLM API (e.g., OpenAI, Gemini).
    \"\"\"
    # This is a mock translation. In reality, this function should call an LLM API.
    return f"[TRANSLATED TO AMHARIC]: {text}"

def process_next_news():
    # 1. Fetch the next item from the queue
    print("Fetching next news item from queue...")
    queue_result = route_event_dict({
        "intent": "news_queue",
        "payload": {"limit": 1},
        "source": "news_translator_agent",
        "locale": "am"
    })

    if not queue_result.success or not queue_result.data.get("items"):
        print("No news items found in the queue.")
        return

    item = queue_result.data["items"][0]
    item_id = item["id"]
    title = item["title"]
    story = item["story"]

    print(f"Processing Item ID: {item_id}")
    print(f"Original Title: {title}")

    # 2. Translate
    print("Translating title and story...")
    translated_title = translate_to_amharic(title)
    translated_story = translate_to_amharic(story)

    # 3. Mark as published
    print("Marking as published...")
    mark_result = route_event_dict({
        "intent": "news_mark",
        "payload": {
            "item_id": item_id,
            "status": "published",
            "translated_title_am": translated_title,
            "translated_story_am": translated_story,
        },
        "source": "news_translator_agent",
        "locale": "am"
    })

    if mark_result.success:
        print(f"Successfully processed and published item {item_id}.")
    else:
        print(f"Failed to publish item {item_id}: {mark_result.message}")

if __name__ == "__main__":
    process_next_news()
