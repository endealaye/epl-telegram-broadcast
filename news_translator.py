import os
import time

from orchestrator import route_event_dict

NEWS_ITEM_DELAY_SECONDS = float(os.getenv("NEWS_ITEM_DELAY_SECONDS", "2"))


def process_automated_news():
    """Fetch new items, then publish a small queue of items that already have Amharic.

    Machine translation was removed. Items without an Amharic title and story are
    not fetched into the publish queue, so they can't block translated items.
    """
    from news_pipeline import fetch_news_items, mark_review_item, get_review_queue

    fetch_result = fetch_news_items()
    limit = max(1, int(os.getenv("NEWS_PUBLISH_BATCH_SIZE", os.getenv("NEWS_TRANSLATION_BATCH_SIZE", "12"))))
    queue = get_review_queue(limit=limit, require_translation=True)
    processed = 0
    failed = 0

    for index, item in enumerate(queue):
        try:
            mark_review_item(
                item_id=item["id"],
                status="published",
                translated_title_am=item["translated_title_am"].strip(),
                translated_story_am=item["translated_story_am"].strip(),
            )
            processed += 1
        except Exception as exc:
            failed += 1
            print(f"Failed to publish item {item.get('id')}: {exc}")
        finally:
            if index < len(queue) - 1:
                time.sleep(NEWS_ITEM_DELAY_SECONDS)

    return {
        "success": True,
        "processed": processed,
        "failed": failed,
        "fetched": fetch_result.get("stored_count", 0),
        "stopped_reason": None,
        "message": (
            f"Fetched {fetch_result.get('stored_count', 0)} items, published {processed}, "
            f"{failed} failed and left in queue."
        ),
    }


def process_next_news():
    print("Fetching next translated news item from queue...")
    queue_result = route_event_dict({
        "intent": "news_queue",
        "payload": {"limit": 1},
        "source": "news_translator_agent",
        "locale": "am",
    })

    items = queue_result.data.get("items") if queue_result.success else None
    item = next(
        (i for i in (items or []) if (i.get("translated_title_am") or "").strip() and (i.get("translated_story_am") or "").strip()),
        None,
    )
    if not item:
        print("No translated news items found in the queue.")
        return

    item_id = item["id"]
    print(f"Publishing Item ID: {item_id}")
    mark_result = route_event_dict({
        "intent": "news_mark",
        "payload": {
            "item_id": item_id,
            "status": "published",
            "translated_title_am": item["translated_title_am"],
            "translated_story_am": item["translated_story_am"],
        },
        "source": "news_translator_agent",
        "locale": "am",
    })
    print(
        f"Published item {item_id}."
        if mark_result.success
        else f"Failed to publish item {item_id}: {mark_result.message}"
    )


if __name__ == "__main__":
    process_next_news()
