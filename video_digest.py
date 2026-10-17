"""
Merged video digest: several broadcast stories joined into one long video and
sent to Telegram.

Run it by hand with `telegram_broadcast.py telegram-digest` (or the "Video
Digest (manual)" workflow). Stories are re-rendered from the stored Amharic
text (TTS + image), so nothing has to be kept between workflow runs.
"""
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_store import list_published_news_since
from tts_service import concat_videos, media_duration, render_news_video, synthesize_news_audio

DIGEST_MAX_ITEMS = int(os.getenv("VIDEO_DIGEST_MAX_ITEMS", "25"))
DIGEST_WINDOW_HOURS = 24
EAT = timezone(timedelta(hours=3))
DIGEST_TITLE = "የፕሪሚየር ሊግ ዜና ማጠቃለያ"
# Telegram's bot API rejects uploads over 50 MB.
TELEGRAM_VIDEO_LIMIT_BYTES = 49 * 1024 * 1024


def _window_start(now):
    return now - timedelta(hours=DIGEST_WINDOW_HOURS)


def _timestamp(seconds):
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def build_chapters(titles_and_durations):
    """Chapter list, one line per story; the first stamp is 0:00."""
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


def _render_and_send(items, title, chat_id):
    """Render each story, join them, and send the result to Telegram.
    Returns a result dict."""
    from news_pipeline import create_watermarked_image  # heavy import, kept lazy

    work_dir = Path(tempfile.mkdtemp(prefix="video_digest_"))
    clips, chapters_input = [], []
    try:
        for index, item in enumerate(items):
            is_last = index == len(items) - 1
            image_path = audio_path = None
            try:
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
            except Exception as exc:
                print(f"Merged video: skipping item {item.get('id')}: {exc!r}")
            finally:
                for temp in (image_path, audio_path):
                    if temp:
                        Path(temp).unlink(missing_ok=True)

        if not clips:
            return {"success": False, "items": 0, "message": "No clips could be rendered."}

        merged_path = work_dir / "merged.mp4"
        concat_videos(clips, merged_path)
        total_seconds = media_duration(merged_path)

        return _send_merged_to_telegram(
            merged_path, title, build_chapters(chapters_input),
            len(clips), total_seconds, chat_id,
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_and_send_digest_telegram(chat_id=None):
    """Merge the last 24 hours of broadcast stories and send them to Telegram.
    Goes to the news channel (TELEGRAM_CHAT_ID, where the news posts and their
    videos go) unless MERGED_VIDEO_CHAT_ID / chat_id says otherwise. A re-run
    covers the same window, so it can be repeated safely."""
    from bot_config import TELEGRAM_CHAT_ID

    target = chat_id or os.getenv("MERGED_VIDEO_CHAT_ID", "").strip() or TELEGRAM_CHAT_ID
    if not target:
        return {"success": False, "message": "No Telegram chat: set TELEGRAM_CHAT_ID or MERGED_VIDEO_CHAT_ID."}

    now = datetime.now(timezone.utc)
    items = select_items(list_published_news_since(_window_start(now).isoformat(), limit=60))
    if len(items) < 2:
        return {"success": True, "items": len(items), "message": "Fewer than 2 usable stories (need image and Amharic text)."}

    date_label = now.astimezone(EAT).strftime("%d %b %Y %H:%M")
    return _render_and_send(items, f"{DIGEST_TITLE} | {date_label}", chat_id=target)
