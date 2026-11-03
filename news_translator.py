import os
import time

from orchestrator import route_event_dict

NEWS_ITEM_DELAY_SECONDS = float(os.getenv("NEWS_ITEM_DELAY_SECONDS", "2"))
MIN_VIDEO_STORIES = 3  # same floor as youtube_digest.MIN_MERGED_STORIES


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
        try:  # keep the failure readable without Actions logs
            import json
            import traceback
            from datetime import datetime, timezone
            from store import set_bot_state_value

            set_bot_state_value(
                "news_fetch_last_error",
                json.dumps(
                    {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "error": fetch_error[:500],
                        "traceback": traceback.format_exc()[-1500:],
                    }
                ),
            )
        except Exception as record_exc:
            print(f"Could not record fetch error: {record_exc}")
    from tts_service import clear_story_media_cache, enable_story_media_cache

    # One run publishes up to NEWS_PUBLISH_BATCHES_PER_RUN batches of
    # NEWS_PUBLISH_BATCH_SIZE stories (2 x 12 by default). Each batch gets its own
    # merged video; a batch with fewer than MIN_MERGED_STORIES published stories is
    # still published to Telegram but gets no video.
    batch_size = max(1, int(os.getenv("NEWS_PUBLISH_BATCH_SIZE", os.getenv("NEWS_TRANSLATION_BATCH_SIZE", "12"))))
    batches_per_run = max(1, int(os.getenv("NEWS_PUBLISH_BATCHES_PER_RUN", "2")))
    queue = get_review_queue(limit=batch_size * batches_per_run, require_translation=True)
    batches = [queue[i:i + batch_size] for i in range(0, len(queue), batch_size)]

    processed = 0
    failed = 0
    published_ids = []
    videos = []
    skipped_videos = []

    for batch_number, batch in enumerate(batches, start=1):
        batch_ids = []
        enable_story_media_cache()  # the batch video reuses each story's narration
        try:
            for index, item in enumerate(batch):
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
                    batch_ids.append(item["id"])
                except Exception as exc:
                    failed += 1
                    print(f"Failed to publish item {item.get('id')}: {exc}")
                finally:
                    if index < len(batch) - 1:
                        time.sleep(NEWS_ITEM_DELAY_SECONDS)
            published_ids.extend(batch_ids)

            # One merged video per batch, sent to Telegram: Premier League, Champions
            # League, Europa League, then other news, each section introduced by a
            # spoken count. Telegram is already done, so this must never raise or
            # change the run's result.
            if len(batch_ids) < MIN_VIDEO_STORIES:
                if batch_ids:
                    skipped_videos.append({"batch": batch_number, "ids": batch_ids})
                    print(f"Batch {batch_number}: {len(batch_ids)} stories published, fewer than 3, no video.")
                continue
            try:
                from youtube_digest import build_and_send_pending_batches_telegram
                result = build_and_send_pending_batches_telegram(
                    item_ids=batch_ids, batch_suffix=f"-{batch_number}"
                )
                videos.append(result)
                print(f"Merged video (batch {batch_number}): {result}")
            except Exception as exc:
                print(f"Merged video failed (batch {batch_number}): {exc!r}")
        finally:
            clear_story_media_cache()

    return {
        "success": True,
        "processed": processed,
        "failed": failed,
        "fetched": fetch_result.get("stored_count", 0),
        "stopped_reason": None,
        "fetch_error": fetch_error,
        "merged_videos": videos,
        "batches_without_video": skipped_videos,
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
