import json
from deep_translator import GoogleTranslator
from orchestrator import route_event_dict


class TranslationFailedError(Exception):
    """Raised when Amharic translation could not be produced after retries."""


def _check_translation(text, original_text):
    if text and ("Error 500" in text or "That’s an error" in text):
        raise ValueError("Translation service returned an error page")
    return text or original_text


def translate_to_amharic(text, context="news", max_attempts=2):
    """
    Translate text to Amharic using Google Translate.
    Returns the translated string or raises TranslationFailedError.
    """
    if text is None:
        return ""
    original_text = str(text)
    if not original_text.strip():
        return ""

    last_exc = None
    for attempt in range(1, max_attempts + 1):
        translator = GoogleTranslator(source="auto", target="am")
        try:
            translated = _check_translation(translator.translate(original_text), original_text)
            if translated == original_text:
                raise ValueError("Translator returned unchanged (untranslated) text")
            return translated
        except Exception as exc:
            last_exc = exc
            print(f"Translation attempt {attempt}/{max_attempts} failed: {exc}")

    raise TranslationFailedError(
        f"Translation failed after {max_attempts} attempts: {last_exc}"
    )


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
