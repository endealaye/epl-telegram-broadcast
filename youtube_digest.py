"""
Merged YouTube videos: several broadcast stories joined into one long video.

Entry points share one builder:
- build_and_send_pending_batches_telegram(): every published story not yet in a
  video (video_batch_id empty), one video per category, minimum 3 stories each,
  no maximum. Called at the end of process_automated_news and by the manual
  `telegram_broadcast.py telegram-digest`.
- build_and_upload_digest(): everything broadcast since the last digest, as one
  YouTube video (manual / optional nightly run: `telegram_broadcast.py youtube-digest`).

Stories are re-rendered from the stored Amharic text (TTS + image), so nothing
has to be kept between workflow runs.
"""
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_store import (
    get_news_item,
    list_published_news_since,
    list_unmerged_published_news,
    set_video_batch_id,
)
from store import get_bot_state_value, set_bot_state_value
from tts_service import (
    concat_videos,
    get_cached_story_media,
    media_duration,
    render_news_video,
    synthesize_news_audio,
    with_signature,
)
from youtube_uploader import upload_news_video, youtube_enabled

DIGEST_STATE_KEY = "youtube_digest_last_run"
DIGEST_MAX_ITEMS = int(os.getenv("YOUTUBE_DIGEST_MAX_ITEMS", "25"))
# Hard floor: a merged video never has fewer than this many usable stories
# (image + Amharic text). Neither the env var nor a caller's min_items can lower it.
MIN_MERGED_STORIES = 3
BATCH_MIN_ITEMS = max(MIN_MERGED_STORIES, int(os.getenv("YOUTUBE_BATCH_MIN_ITEMS", str(MIN_MERGED_STORIES))))
DIGEST_DEFAULT_WINDOW_HOURS = 24
DIGEST_MAX_WINDOW_HOURS = 48
EAT = timezone(timedelta(hours=3))
DIGEST_TITLE = "የፕሪሚየር ሊግ ዜና ማጠቃለያ"
# Published stories that never made it into a video are only picked up again for
# this long, so old rows can't resurface in a fresh video.
PENDING_LOOKBACK_HOURS = 48

# Merged videos are grouped by category (competition) to give the stories some
# flavour. Order matters: the first match wins when a story carries several tags.
CATEGORY_LABELS_AM = {
    "premier_league": None,  # uses DIGEST_TITLE
    "champions_league": "ቻምፒየንስ ሊግ",
    "europa_league": "ዩሮፓ ሊግ",
    "conference_league": "ኮንፈረንስ ሊግ",
    "world_cup": "የዓለም ዋንጫ",
}
_CATEGORY_ORDER = ["champions_league", "europa_league", "conference_league", "world_cup", "premier_league"]


def story_category(item):
    """Category a story is grouped under for merged videos.

    Uses the competition tag, then the feed it came from. Everything else,
    including transfer rumours (gossip), counts as Premier League."""
    tags = {str(t) for t in (item.get("topic_tags") or [])}
    for category in _CATEGORY_ORDER:
        if f"competition:{category}" in tags:
            return category
    source = (item.get("source_key") or "").lower()
    for category in _CATEGORY_ORDER:
        if category in source:
            return category
    return "premier_league"


def category_title(category, stamp):
    label = CATEGORY_LABELS_AM.get(category)
    if not label:
        return f"{DIGEST_TITLE} | {stamp}"
    return f"{label} ዜና ማጠቃለያ | {stamp}"
# Telegram's bot API rejects uploads over 50 MB.
TELEGRAM_VIDEO_LIMIT_BYTES = 49 * 1024 * 1024


def _window_start(now):
    raw = get_bot_state_value(DIGEST_STATE_KEY)
    earliest = now - timedelta(hours=DIGEST_MAX_WINDOW_HOURS)
    if raw:
        try:
            last = datetime.fromisoformat(raw)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return max(last, earliest)
        except ValueError:
            pass
    return now - timedelta(hours=DIGEST_DEFAULT_WINDOW_HOURS)


def _timestamp(seconds):
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def build_chapters(titles_and_durations):
    """YouTube chapters: first stamp must be 0:00. Returns description lines."""
    lines, elapsed = [], 0.0
    for title, duration in titles_and_durations:
        lines.append(f"{_timestamp(elapsed)} {title}")
        elapsed += duration
    return lines


def select_items(items, max_items=DIGEST_MAX_ITEMS):
    """Every usable story (image + Amharic text) in the order it was broadcast.
    Only if there are more than max_items (a runtime/length cap) are the oldest
    dropped. No relevance ranking: the stored score is a crude keyword count."""
    usable = [
        i for i in items
        if i.get("image_url") and i.get("translated_title_am") and i.get("translated_story_am")
    ]
    ordered = sorted(usable, key=lambda i: i.get("reviewed_at") or "")
    return ordered[-max_items:] if max_items > 0 else ordered


def _send_merged_to_telegram(merged_path, title, chapter_lines, story_count, total_seconds, chat_id):
    """Send the merged video (then its chapter list) to a Telegram chat."""
    from commands import send_telegram_message, send_telegram_video_file

    size = Path(merged_path).stat().st_size
    if size > TELEGRAM_VIDEO_LIMIT_BYTES:
        return {
            "success": False, "items": story_count, "seconds": round(total_seconds),
            "message": f"Merged video is {size // (1024 * 1024)} MB, over Telegram's 50 MB limit.",
        }
    caption = f"{title}\n{story_count} stories, {_timestamp(total_seconds)}"
    if not send_telegram_video_file(merged_path, caption=caption[:1000], chat_id=chat_id):
        return {"success": False, "items": story_count, "message": "Telegram send failed (token or chat id missing)."}
    send_telegram_message("\n".join(chapter_lines)[:4000], chat_id=chat_id, parse_mode=None)
    return {
        "success": True, "items": story_count, "seconds": round(total_seconds),
        "destination": "telegram", "chat_id": str(chat_id), "size_mb": round(size / (1024 * 1024), 1),
    }


def _render_and_upload(items, title, dry_run=False, destination="youtube", chat_id=None):
    """Render each story, join them, then upload to YouTube or send to Telegram.
    Returns a result dict."""
    from news_pipeline import create_watermarked_image, send_admin_alert  # heavy import, kept lazy

    work_dir = Path(tempfile.mkdtemp(prefix="yt_digest_"))
    clips, chapters_input, used_ids = [], [], []
    try:
        for index, item in enumerate(items):
            is_last = index == len(items) - 1
            image_path = audio_path = None
            cached = get_cached_story_media(item["id"])  # set when this run just published the story
            try:
                if cached:
                    # Reuse the narration and image from publishing: no new TTS, no re-download.
                    body_audio, image_path = cached
                    audio_path = with_signature(body_audio) if is_last else body_audio
                else:
                    image_path = create_watermarked_image(item["image_url"])
                    audio_path = synthesize_news_audio(
                        item["translated_title_am"], item["translated_story_am"], signature=is_last
                    )
                if not audio_path:
                    raise RuntimeError("no audio produced")
                clip_path = work_dir / f"clip_{index:02d}.mp4"
                render_news_video(audio_path, clip_path, image_path=image_path)
                clips.append(clip_path)
                chapters_input.append((item["translated_title_am"], media_duration(clip_path)))
                used_ids.append(item["id"])
            except Exception as exc:
                print(f"Merged video: skipping item {item.get('id')}: {exc!r}")
            finally:
                # Cached files stay until the run's cache is cleared; only delete what we made here.
                if cached:
                    if is_last and audio_path:
                        Path(audio_path).unlink(missing_ok=True)  # the signed copy
                else:
                    for temp in (image_path, audio_path):
                        if temp:
                            Path(temp).unlink(missing_ok=True)

        if not clips:
            return {"success": False, "items": 0, "message": "No clips could be rendered."}

        merged_path = work_dir / "merged.mp4"
        concat_videos(clips, merged_path)
        total_seconds = media_duration(merged_path)

        if destination == "telegram":
            result = _send_merged_to_telegram(
                merged_path, title, build_chapters(chapters_input),
                len(clips), total_seconds, chat_id,
            )
            result["item_ids"] = used_ids
            return result

        sources = sorted({i.get("source_name") for i in items if i.get("source_name")})
        description = "\n".join(
            build_chapters(chapters_input)
            + [""]
            + ([f"Sources: {', '.join(sources)}"] if sources else [])
            + ["Narration is AI-generated (synthetic voice). Text is machine-translated.",
               "#EPL #PremierLeague"]
        )

        if dry_run:
            kept = work_dir.parent / "yt_digest_dry_run.mp4"
            shutil.copy(merged_path, kept)
            return {
                "success": True, "dry_run": True, "items": len(clips),
                "seconds": round(total_seconds), "file": str(kept),
                "title": title, "description": description,
            }

        result = upload_news_video(merged_path, title, description)
        try:
            send_admin_alert(
                f"YouTube merged video ({result['privacy']}, {len(clips)} stories, "
                f"{_timestamp(total_seconds)}): {result['url']}"
            )
        except Exception as alert_exc:
            print(f"Could not send merged-video admin alert: {alert_exc!r}")
        return {
            "success": True, "items": len(clips), "seconds": round(total_seconds),
            "url": result["url"], "privacy": result["privacy"], "item_ids": used_ids,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_and_upload_batch(item_ids, min_items=BATCH_MIN_ITEMS):
    """Merge the stories published by one translation run into a single video.
    Best-effort: callers wrap this so it can never affect publishing."""
    if not item_ids or not youtube_enabled():
        return {"success": True, "skipped": "nothing to merge or YouTube not configured."}

    min_items = max(min_items, MIN_MERGED_STORIES)
    rows = [row for row in (get_news_item(i) for i in item_ids) if row]
    items = select_items(rows)
    if len(items) < min_items:
        return {"success": True, "skipped": f"only {len(items)} usable stories (minimum {min_items})."}

    stamp = datetime.now(timezone.utc).astimezone(EAT).strftime("%d %b %Y %H:%M")
    return _render_and_upload(items, f"{DIGEST_TITLE} | {stamp}")


def build_and_send_batch_telegram(item_ids, min_items=BATCH_MIN_ITEMS, chat_id=None):
    """Merge the stories published by one translation run into a single video and
    send it to Telegram (the news channel unless MERGED_VIDEO_CHAT_ID / chat_id
    says otherwise). No YouTube needed. Best-effort: callers wrap this so it can
    never affect publishing, but a failed merge alerts the admin."""
    from bot_config import TELEGRAM_CHAT_ID
    from commands import send_admin_alert

    if not item_ids:
        return {"success": True, "skipped": "nothing to merge."}
    target = chat_id or os.getenv("MERGED_VIDEO_CHAT_ID", "").strip() or TELEGRAM_CHAT_ID
    if not target:
        return {"success": False, "message": "No Telegram chat: set TELEGRAM_CHAT_ID or MERGED_VIDEO_CHAT_ID."}

    min_items = max(min_items, MIN_MERGED_STORIES)
    rows = [row for row in (get_news_item(i) for i in item_ids) if row]
    items = select_items(rows)
    if len(items) < min_items:
        return {"success": True, "skipped": f"only {len(items)} usable stories (minimum {min_items})."}

    stamp = datetime.now(timezone.utc).astimezone(EAT).strftime("%d %b %Y %H:%M")
    result = _render_and_upload(
        items, f"{DIGEST_TITLE} | {stamp}", destination="telegram", chat_id=target
    )
    if not result.get("success"):
        try:
            send_admin_alert(f"Merged video was not sent: {result.get('message', result)}")
        except Exception as alert_exc:
            print(f"Could not send merged-video failure alert: {alert_exc!r}")
    return result


def group_pending_by_category(rows):
    """Usable stories (image + Amharic text) in broadcast order, grouped by category."""
    groups = {}
    for item in select_items(rows, max_items=0):  # no cap: every story goes into a video
        groups.setdefault(story_category(item), []).append(item)
    return groups


def build_and_send_pending_batches_telegram(chat_id=None, min_items=MIN_MERGED_STORIES):
    """Merge every published story that is not yet in a video, one video per category.

    A category with fewer than min_items usable stories is left alone and waits for
    a later run to reach the minimum. Stories are stamped with video_batch_id only
    after their video is sent, so a failed merge is retried on the next run.
    Best-effort: callers wrap this so it can never affect publishing."""
    from bot_config import TELEGRAM_CHAT_ID
    from commands import send_admin_alert

    target = chat_id or os.getenv("MERGED_VIDEO_CHAT_ID", "").strip() or TELEGRAM_CHAT_ID
    if not target:
        return {"success": False, "message": "No Telegram chat: set TELEGRAM_CHAT_ID or MERGED_VIDEO_CHAT_ID."}

    min_items = max(1, min_items)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=PENDING_LOOKBACK_HOURS)
    groups = group_pending_by_category(list_unmerged_published_news(since.isoformat()))
    if not groups:
        return {"success": True, "videos": [], "waiting": {}, "skipped": "no unmerged stories."}

    local = now.astimezone(EAT)
    stamp = local.strftime("%d %b %Y %H:%M")
    videos, waiting = [], {}
    for category in _CATEGORY_ORDER:
        items = groups.get(category)
        if not items:
            continue
        if len(items) < min_items:
            waiting[category] = len(items)
            continue
        batch_id = f"{local.strftime('%Y%m%d-%H%M')}-{category}"
        result = _render_and_upload(
            items, category_title(category, stamp), destination="telegram", chat_id=target
        )
        if result.get("success") and result.get("item_ids"):
            if not set_video_batch_id(result["item_ids"], batch_id):
                # The video is already out; without the stamp these stories would be
                # merged again, so tell the admin rather than hide it.
                try:
                    send_admin_alert(f"Merged video {batch_id} was sent but video_batch_id could not be saved.")
                except Exception as alert_exc:
                    print(f"Could not send batch-stamp alert: {alert_exc!r}")
            videos.append({"category": category, "batch_id": batch_id, "items": len(result["item_ids"])})
        else:
            try:
                send_admin_alert(f"Merged video ({category}) was not sent: {result.get('message', result)}")
            except Exception as alert_exc:
                print(f"Could not send merged-video failure alert: {alert_exc!r}")
    return {"success": True, "videos": videos, "waiting": waiting}


def build_and_upload_digest(dry_run=False):
    """Everything broadcast since the last digest (manual or scheduled run)."""
    if not dry_run and not youtube_enabled():
        return {"success": True, "skipped": "YouTube credentials not configured."}

    now = datetime.now(timezone.utc)
    since = _window_start(now)
    items = select_items(list_published_news_since(since.isoformat(), limit=60))
    if len(items) < MIN_MERGED_STORIES:
        return {
            "success": True, "items": len(items),
            "message": f"Fewer than {MIN_MERGED_STORIES} usable stories (need image and Amharic text).",
        }

    date_label = now.astimezone(EAT).strftime("%d %b %Y")
    result = _render_and_upload(items, f"{DIGEST_TITLE} | {date_label}", dry_run=dry_run)
    if result.get("success") and not dry_run:
        set_bot_state_value(DIGEST_STATE_KEY, now.isoformat())
    return result


def build_and_send_digest_telegram(chat_id=None):
    """Manual run: merge every published story not yet in a video, one video per
    category, and send them to Telegram (the news channel unless
    MERGED_VIDEO_CHAT_ID / chat_id says otherwise). Same path as the cron, so
    stories are stamped with video_batch_id and never merged twice."""
    return build_and_send_pending_batches_telegram(chat_id=chat_id)
