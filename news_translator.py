import os
import time

from deep_translator import MyMemoryTranslator
from orchestrator import route_event_dict


class TranslationFailedError(Exception):
    """Raised when Amharic translation could not be produced after retries."""


class TranslationRateLimitedError(TranslationFailedError):
    """Raised when MyMemory rate-limits the request."""


TRANSLATION_DELIMITER = "NEWS_TRANSLATION_SEPARATOR_7F3A9C"
TRANSLATION_ITEM_DELAY_SECONDS = float(os.getenv("TRANSLATION_ITEM_DELAY_SECONDS", "2"))
TRANSLATION_RETRY_DELAY_SECONDS = float(os.getenv("TRANSLATION_RETRY_DELAY_SECONDS", "30"))


def _check_translation(text, original_text):
    if text and ("Error 500" in text or "That’s an error" in text):
        raise ValueError("Translation service returned an error page")
    return text or original_text


def _is_rate_limit_error(exc):
    message = str(exc).lower()
    return any(term in message for term in ("too many requests", "rate limit", "429", "quota"))


def _translate_batch(texts, max_attempts=2):
    """Translate several strings with one MyMemory request."""
    originals = [str(text or "") for text in texts]
    if not any(value.strip() for value in originals):
        return originals

    combined = f"\n\n{TRANSLATION_DELIMITER}\n\n".join(originals)
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            translator = MyMemoryTranslator(source="en-GB", target="am-ET")
            translated = translator.translate(combined)
            if not translated:
                raise ValueError("Translator returned an empty response")

            parts = translated.split(TRANSLATION_DELIMITER)
            if len(parts) != len(originals):
                raise ValueError("Translator changed or removed the batch delimiter")

            checked = [
                _check_translation(value.strip(), original)
                for value, original in zip(parts, originals)
            ]
            for value, original in zip(checked, originals):
                if original.strip() and value.strip() == original.strip():
                    raise ValueError("Translator returned unchanged (untranslated) text")
            return checked
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts:
                if _is_rate_limit_error(exc):
                    raise TranslationRateLimitedError(str(exc)) from exc
                break
            delay = TRANSLATION_RETRY_DELAY_SECONDS * attempt
            print(f"Translation attempt {attempt}/{max_attempts} failed: {exc}; sleeping {delay:.1f}s.")
            time.sleep(delay)

    raise TranslationFailedError(
        f"Translation failed after {max_attempts} attempts: {last_exc}"
    )


def translate_to_amharic(text, context="news", max_attempts=2):
    return _translate_batch([text], max_attempts=max_attempts)[0]


def translate_news_item(item, max_attempts=2):
    """Translate title, story, and summary with one paced MyMemory request."""
    return tuple(
        _translate_batch(
            [item.get("title"), item.get("story"), item.get("summary")],
            max_attempts=max_attempts,
        )
    )


def process_automated_news():
    """Fetch and publish a small, rate-limited queue of news items."""
    from news_pipeline import fetch_news_items, mark_review_item, get_review_queue

    fetch_result = fetch_news_items()
    limit = max(1, int(os.getenv("NEWS_TRANSLATION_BATCH_SIZE", "12")))
    queue = get_review_queue(limit=limit)
    processed = 0
    failed = 0
    stopped_reason = None

    for index, item in enumerate(queue):
        try:
            translated_title, translated_story, highlight = translate_news_item(item)
            mark_review_item(
                item_id=item["id"],
                status="published",
                translated_title_am=translated_title,
                translated_story_am=translated_story,
                highlight_am=highlight,
            )
            processed += 1
        except TranslationRateLimitedError as exc:
            failed += 1
            stopped_reason = f"Translation rate limited for item {item.get('id')}: {exc}"
            print(f"Stopping news publish run: {stopped_reason}")
            break
        except Exception as exc:
            failed += 1
            print(f"Failed to process item {item.get('id')}: {exc}")
        finally:
            if index < len(queue) - 1:
                time.sleep(TRANSLATION_ITEM_DELAY_SECONDS)

    success = not stopped_reason
    return {
        "success": success,
        "processed": processed,
        "failed": failed,
        "fetched": fetch_result.get("stored_count", 0),
        "stopped_reason": stopped_reason,
        "message": (
            f"Fetched {fetch_result.get('stored_count', 0)} items, published {processed}, "
            f"{failed} left in queue for retry."
            + (f" Stopped early: {stopped_reason}" if stopped_reason else "")
        ),
    }


def process_next_news():
    print("Fetching next news item from queue...")
    queue_result = route_event_dict({
        "intent": "news_queue",
        "payload": {"limit": 1},
        "source": "news_translator_agent",
        "locale": "am",
    })

    if not queue_result.success or not queue_result.data.get("items"):
        print("No news items found in the queue.")
        return

    item = queue_result.data["items"][0]
    item_id = item["id"]
    print(f"Processing Item ID: {item_id}")
    translated_title, translated_story, _ = translate_news_item(item)
    mark_result = route_event_dict({
        "intent": "news_mark",
        "payload": {
            "item_id": item_id,
            "status": "published",
            "translated_title_am": translated_title,
            "translated_story_am": translated_story,
        },
        "source": "news_translator_agent",
        "locale": "am",
    })
    print(
        f"Successfully processed and published item {item_id}."
        if mark_result.success
        else f"Failed to publish item {item_id}: {mark_result.message}"
    )


if __name__ == "__main__":
    process_next_news()
