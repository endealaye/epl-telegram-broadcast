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

    # A feed outage must not stop already-translated rows from publishing.
    fetch_error = None
    try:
        fetch_result = fetch_news_items()
    except Exception as exc:
        fetch_error = f"{type(exc).__name__}: {exc}"
        print(f"News fetch failed, publishing the existing queue anyway: {fetch_error}")
        fetch_result = {}
    from tts_service import enable_story_media_cache
    enable_story_media_cache()  # merged video reuses each story's narration
    limit = max(1, int(os.getenv("NEWS_PUBLISH_BATCH_SIZE", os.getenv("NEWS_TRANSLATION_BATCH_SIZE", "12"))))
    queue = get_review_queue(limit=limit, require_translation=True)
    processed = 0
    failed = 0
    published_ids = []

    for index, item in enumerate(queue):
        try:
            published = mark_review_item(
                item_id=item["id"],
                status="published",
                translated_title_am=item["translated_title_am"].strip(),
                translated_story_am=item["translated_story_am"].strip(),
            )
            if not published:
                raise RuntimeError(f"Item {item['id']} was not recorded as published.")
            processed += 1
            published_ids.append(item["id"])
        except Exception as exc:
            failed += 1
            print(f"Failed to publish item {item.get('id')}: {exc}")
        finally:
            if index < len(queue) - 1:
                time.sleep(NEWS_ITEM_DELAY_SECONDS)

    # One merged video per run, sent to Telegram. Telegram is already done, so this must
    # never raise or change the run's result.
    merged_video = None
    if published_ids:
        try:
            from youtube_digest import build_and_send_batch_telegram
            merged_video = build_and_send_batch_telegram(published_ids)
            print(f"Merged video: {merged_video}")
        except Exception as exc:
            print(f"Merged video failed: {exc!r}")
        finally:
            from tts_service import clear_story_media_cache
            clear_story_media_cache()

    return {
        "success": True,
        "processed": processed,
        "failed": failed,
        "fetched": fetch_result.get("stored_count", 0),
        "stopped_reason": None,
        "fetch_error": fetch_error,
        "merged_video": merged_video,
        "message": (
            f"Fetched {fetch_result.get('stored_count', 0)} items, published {processed}, "
            f"{failed} failed and left in queue."
            + (f" Fetch failed: {fetch_error}." if fetch_error else "")
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
