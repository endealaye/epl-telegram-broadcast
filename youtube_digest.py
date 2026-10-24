"""
Merged YouTube videos: several broadcast stories joined into one long video.

Entry points share one builder:
- build_and_send_pending_batches_telegram(): every published story not yet in a
  video (video_batch_id empty), merged into ONE video per fetch, minimum 3 stories
  in total, no maximum. Sorted Premier League, Champions League, Europa League,
  other; each non-empty section opens with a spoken/on-screen intro. Called at the
  end of process_automated_news and by the manual `telegram_broadcast.py telegram-digest`.
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
    "la_liga": "ላ ሊጋ",
    "serie_a": "ሴሪ ኤ",
    "bundesliga": "ቡንደስሊጋ",
}
_CATEGORY_ORDER = [
    "champions_league", "europa_league", "conference_league", "world_cup",
    "la_liga", "serie_a", "bundesliga", "premier_league",
]


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


# One merged video per fetch, stories sorted into these sections in this order.
# A section with no stories is left out entirely (no intro either).
# Conference League, World Cup and anything else fall under "other".
SECTION_ORDER = [
    "premier_league", "champions_league", "europa_league",
    "la_liga", "serie_a", "bundesliga", "other",
]
SECTION_LABELS_AM = {
    "premier_league": "ፕሪሚየር ሊግ",
    "champions_league": "ቻምፒየንስ ሊግ",
    "europa_league": "ዩሮፓ ሊግ",
    "la_liga": "ላ ሊጋ",
    "serie_a": "ሴሪ ኤ",
    "bundesliga": "ቡንደስሊጋ",
    "other": "ሌሎች የእግር ኳስ ዜናዎች",
}
_NUMBER_WORDS_AM = {
    1: "አንድ", 2: "ሁለት", 3: "ሦስት", 4: "አራት", 5: "አምስት", 6: "ስድስት", 7: "ሰባት",
    8: "ስምንት", 9: "ዘጠኝ", 10: "አስር", 11: "አስራ አንድ", 12: "አስራ ሁለት",
    13: "አስራ ሦስት", 14: "አስራ አራት", 15: "አስራ አምስት", 16: "አስራ ስድስት",
    17: "አስራ ሰባት", 18: "አስራ ስምንት", 19: "አስራ ዘጠኝ", 20: "ሃያ",
}


def story_section(item):
    """Section a story is sorted into inside the single merged video."""
    category = story_category(item)
    return category if category in SECTION_ORDER else "other"


def group_by_section(items):
    """Ordered [(section, [items])] for the sections that have stories.
    Order inside a section is the broadcast order of `items`."""
    buckets = {}
    for item in items:
        buckets.setdefault(story_section(item), []).append(item)
    return [(section, buckets[section]) for section in SECTION_ORDER if buckets.get(section)]


def section_intro_text(section, count):
    """What the narrator says before a section: 'the next N stories are about X'."""
    label = SECTION_LABELS_AM[section]
    if count == 1:
        return f"የሚቀጥለው ዜና ስለ {label} ነው።" if section != "other" else "የሚቀጥለው ዜና ሌላ የእግር ኳስ ዜና ነው።"
    number = _NUMBER_WORDS_AM.get(count, str(count))
    if section == "other":
        return f"የሚቀጥሉት {number} ዜናዎች ሌሎች የእግር ኳስ ዜናዎች ናቸው።"
    return f"የሚቀጥሉት {number} ዜናዎች ስለ {label} ናቸው።"


def _make_section_card(section, count, out_path):
    """1920x1080 title card shown while the section intro is spoken."""
    from PIL import Image, ImageDraw

    from standings import _load_font  # lazy: pulls in the Ethiopic font loader

    from league_logos import load_league_logo

    width, height = 1920, 1080
    image = Image.new("RGB", (width, height), (14, 22, 33))
    draw = ImageDraw.Draw(image)
    label = SECTION_LABELS_AM[section]
    sub = f"{_NUMBER_WORDS_AM.get(count, count)} ዜና" if count == 1 else f"{_NUMBER_WORDS_AM.get(count, count)} ዜናዎች"
    # The league's logo replaces the text label; with no logo (or the "other" section) keep the text.
    logo = load_league_logo(section, 640, 440)
    if logo is not None:
        # White plate so dark logos stay readable on the dark card.
        pad = 36
        plate_w, plate_h = logo.width + 2 * pad, logo.height + 2 * pad
        px, py = (width - plate_w) // 2, 170
        draw.rounded_rectangle((px, py, px + plate_w, py + plate_h), radius=36, fill=(255, 255, 255))
        image.paste(logo, (px + pad, py + pad), logo)
        lines = ((sub, 80, py + plate_h + 70, (170, 190, 215)),)
    else:
        lines = ((label, 150, 400, (255, 255, 255)), (sub, 80, 620, (170, 190, 215)))
    for text, size, y, color in lines:
        font = _load_font(size, bold=True)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((width - (box[2] - box[0])) / 2 - box[0], y), text, font=font, fill=color)
    image.save(out_path, "PNG")
    return out_path
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


def _render_section_intro(section, count, index, work_dir):
    """Clip announcing a section ('the next N stories are about X'), voiced and on a
    title card. Returns (clip_path, seconds) or None if it could not be made; a
    missing intro never blocks the stories themselves."""
    from tts_service import synthesize_announcement

    audio_path = card_path = None
    try:
        audio_path = synthesize_announcement(section_intro_text(section, count))
        if not audio_path:
            raise RuntimeError("no audio produced")
        card_path = _make_section_card(section, count, work_dir / f"card_{index:02d}.png")
        clip_path = work_dir / f"intro_{index:02d}.mp4"
        render_news_video(audio_path, clip_path, image_path=card_path)
        return clip_path, media_duration(clip_path)
    except Exception as exc:
        print(f"Merged video: no intro for section {section}: {exc!r}")
        return None
    finally:
        for temp in (audio_path, card_path):
            if temp:
                Path(temp).unlink(missing_ok=True)


def _render_and_upload(items, title, dry_run=False, destination="youtube", chat_id=None, sectioned=False):
    """Render each story, join them, then upload to YouTube or send to Telegram.
    With sectioned=True the stories are sorted Premier League, Champions League,
    Europa League, other, and each non-empty section starts with a spoken and
    on-screen intro giving its story count. Returns a result dict."""
    from news_pipeline import create_watermarked_image, send_admin_alert  # heavy import, kept lazy

    work_dir = Path(tempfile.mkdtemp(prefix="yt_digest_"))
    clips, chapters_input, used_ids = [], [], []
    sections = group_by_section(items) if sectioned else [(None, items)]
    last_item = [i for _, group in sections for i in group][-1]
    clip_index = 0
    try:
        for section, group in sections:
            section_clips, section_chapters, section_ids = [], [], []
            for item in group:
                clip_index += 1
                is_last = item is last_item
                image_path = audio_path = None
                cached = get_cached_story_media(item["id"])  # set when this run just published the story
                try:
                    if cached:
                        # Reuse the narration and image from publishing: no new TTS, no re-download.
                        body_audio, image_path = cached
                        audio_path = with_signature(body_audio) if is_last else body_audio
                    else:
                        image_path = create_watermarked_image(item["image_url"], category=story_category(item))
                        audio_path = synthesize_news_audio(
                            item["translated_title_am"], item["translated_story_am"], signature=is_last
                        )
                    if not audio_path:
                        raise RuntimeError("no audio produced")
                    clip_path = work_dir / f"clip_{clip_index:02d}.mp4"
                    render_news_video(audio_path, clip_path, image_path=image_path)
                    section_clips.append(clip_path)
                    section_chapters.append((item["translated_title_am"], media_duration(clip_path)))
                    section_ids.append(item["id"])
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
            if not section_clips:
                continue  # every story in this section failed: no intro for an empty section
            if section:
                # The count is of stories that actually rendered, so the narrator never overpromises.
                intro = _render_section_intro(section, len(section_clips), clip_index, work_dir)
                if intro:
                    clips.append(intro[0])
                    chapters_input.append((SECTION_LABELS_AM[section], intro[1]))
            clips.extend(section_clips)
            chapters_input.extend(section_chapters)
            used_ids.extend(section_ids)

        if not clips:
            return {"success": False, "items": 0, "message": "No clips could be rendered."}

        merged_path = work_dir / "merged.mp4"
        concat_videos(clips, merged_path)
        total_seconds = media_duration(merged_path)

        if destination == "telegram":
            result = _send_merged_to_telegram(
                merged_path, title, build_chapters(chapters_input),
                len(used_ids), total_seconds, chat_id,
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
                "success": True, "dry_run": True, "items": len(used_ids),
                "seconds": round(total_seconds), "file": str(kept),
                "title": title, "description": description,
            }

        result = upload_news_video(merged_path, title, description)
        try:
            send_admin_alert(
                f"YouTube merged video ({result['privacy']}, {len(used_ids)} stories, "
                f"{_timestamp(total_seconds)}): {result['url']}"
            )
        except Exception as alert_exc:
            print(f"Could not send merged-video admin alert: {alert_exc!r}")
        return {
            "success": True, "items": len(used_ids), "seconds": round(total_seconds),
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
    """Usable stories (image + Amharic text) in broadcast order, grouped by category.
    Kept for callers that want the per-category split; the cron uses one video."""
    groups = {}
    for item in select_items(rows, max_items=0):  # no cap: every story goes into a video
        groups.setdefault(story_category(item), []).append(item)
    return groups


def build_and_send_pending_batches_telegram(chat_id=None, min_items=MIN_MERGED_STORIES):
    """Merge every published story that is not yet in a video into ONE video.

    Stories are sorted Premier League, Champions League, Europa League, then other
    football news. Each section that has stories opens with a spoken and on-screen
    intro ('the next N stories are about X'); a section with none is skipped.

    If fewer than min_items usable stories are pending in total, nothing is made and
    they wait for the next fetch. Stories are stamped with video_batch_id only after
    the video is sent, so a failed merge is retried on the next run.
    Best-effort: callers wrap this so it can never affect publishing."""
    from bot_config import TELEGRAM_CHAT_ID
    from commands import send_admin_alert

    target = chat_id or os.getenv("MERGED_VIDEO_CHAT_ID", "").strip() or TELEGRAM_CHAT_ID
    if not target:
        return {"success": False, "message": "No Telegram chat: set TELEGRAM_CHAT_ID or MERGED_VIDEO_CHAT_ID."}

    min_items = max(MIN_MERGED_STORIES, min_items)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=PENDING_LOOKBACK_HOURS)
    items = select_items(list_unmerged_published_news(since.isoformat()), max_items=0)
    if not items:
        return {"success": True, "videos": [], "waiting": {}, "skipped": "no unmerged stories."}
    if len(items) < min_items:
        return {"success": True, "videos": [], "waiting": {"all": len(items)}}

    local = now.astimezone(EAT)
    stamp = local.strftime("%d %b %Y %H:%M")
    batch_id = local.strftime("%Y%m%d-%H%M")
    sections = {section: len(group) for section, group in group_by_section(items)}
    result = _render_and_upload(
        items, f"{DIGEST_TITLE} | {stamp}", destination="telegram", chat_id=target, sectioned=True
    )
    videos = []
    if result.get("success") and result.get("item_ids"):
        if not set_video_batch_id(result["item_ids"], batch_id):
            # The video is already out; without the stamp these stories would be
            # merged again, so tell the admin rather than hide it.
            try:
                send_admin_alert(f"Merged video {batch_id} was sent but video_batch_id could not be saved.")
            except Exception as alert_exc:
                print(f"Could not send batch-stamp alert: {alert_exc!r}")
        videos.append({"batch_id": batch_id, "items": len(result["item_ids"]), "sections": sections})
    else:
        try:
            send_admin_alert(f"Merged video was not sent: {result.get('message', result)}")
        except Exception as alert_exc:
            print(f"Could not send merged-video failure alert: {alert_exc!r}")
    return {"success": True, "videos": videos, "waiting": {}}


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
