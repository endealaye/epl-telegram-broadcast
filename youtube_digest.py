"""
Merged YouTube videos: several broadcast stories joined into one long video.

Two entry points share one builder:
- build_and_upload_batch(item_ids): the stories published by one translation
  run (called at the end of process_automated_news).
- build_and_upload_digest(): everything broadcast since the last digest
  (manual / optional nightly run: `telegram_broadcast.py youtube-digest`).

Stories are re-rendered from the stored Amharic text (TTS + image), so nothing
has to be kept between workflow runs.
"""
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from news_store import get_news_item, list_published_news_since
from store import get_bot_state_value, set_bot_state_value
from tts_service import concat_videos, media_duration, render_news_video, synthesize_news_audio
from youtube_uploader import upload_news_video, youtube_enabled

DIGEST_STATE_KEY = "youtube_digest_last_run"
DIGEST_MAX_ITEMS = int(os.getenv("YOUTUBE_DIGEST_MAX_ITEMS", "25"))
# A "merge" of one story is just a landscape copy of its Short, so skip it.
BATCH_MIN_ITEMS = int(os.getenv("YOUTUBE_BATCH_MIN_ITEMS", "2"))
DIGEST_DEFAULT_WINDOW_HOURS = 24
DIGEST_MAX_WINDOW_HOURS = 48
EAT = timezone(timedelta(hours=3))
DIGEST_TITLE = "የፕሪሚየር ሊግ ዜና ማጠቃለያ"


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


def _render_and_upload(items, title, dry_run=False):
    """Render each story, join them, upload. Returns a result dict."""
    from news_pipeline import create_watermarked_image, send_admin_alert  # heavy import, kept lazy

    work_dir = Path(tempfile.mkdtemp(prefix="yt_digest_"))
    clips, chapters_input, used_ids = [], [], []
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
                used_ids.append(item["id"])
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

    rows = [row for row in (get_news_item(i) for i in item_ids) if row]
    items = select_items(rows)
    if len(items) < min_items:
        return {"success": True, "skipped": f"only {len(items)} usable stories (minimum {min_items})."}

    stamp = datetime.now(timezone.utc).astimezone(EAT).strftime("%d %b %Y %H:%M")
    return _render_and_upload(items, f"{DIGEST_TITLE} | {stamp}")


def build_and_upload_digest(dry_run=False):
    """Everything broadcast since the last digest (manual or scheduled run)."""
    if not dry_run and not youtube_enabled():
        return {"success": True, "skipped": "YouTube credentials not configured."}

    now = datetime.now(timezone.utc)
    since = _window_start(now)
    items = select_items(list_published_news_since(since.isoformat(), limit=60))
    if not items:
        return {"success": True, "items": 0, "message": "No stories to include."}

    date_label = now.astimezone(EAT).strftime("%d %b %Y")
    result = _render_and_upload(items, f"{DIGEST_TITLE} | {date_label}", dry_run=dry_run)
    if result.get("success") and not dry_run:
        set_bot_state_value(DIGEST_STATE_KEY, now.isoformat())
    return result
