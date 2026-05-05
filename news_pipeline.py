from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import tempfile
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from commands import send_telegram_message, send_telegram_photo, send_telegram_photo_file
from news_collectors import (
    PREMIER_LEAGUE_CLUB_RSS_SOURCES,
    RSS_MAX_ITEMS_CLUB,
    fetch_bbc_football_rss,
    fetch_guardian_premier_league_rss,
    fetch_rss_source,
    fetch_sky_sports_premier_league_rss,
    is_excluded_news_item,
)
from news_store import (
    build_source_title_key,
    get_news_items_by_article_urls,
    get_news_items_by_content_hashes,
    get_existing_news_items_for_sources,
    get_news_item,
    is_user_hidden,
    list_news_queue,
    mark_news_item,
    normalize_news_item,
    upsert_news_items,
    validate_status_transition,
)

TELEGRAM_CAPTION_LIMIT = 1024
WATERMARK_MARGIN_RATIO = 0.04
WATERMARK_WIDTH_RATIO = 0.108
WATERMARK_MAX_WIDTH = 320
WATERMARK_MIN_WIDTH = 120
WATERMARK_BG_ALPHA = int(os.getenv("WATERMARK_BG_ALPHA", "96"))
WATERMARK_BG_PADDING = int(os.getenv("WATERMARK_BG_PADDING", "10"))
WATERMARK_BG_RADIUS = int(os.getenv("WATERMARK_BG_RADIUS", "8"))
NEWS_IMAGE_MAX_BYTES = int(os.getenv("NEWS_IMAGE_MAX_BYTES", str(8 * 1024 * 1024)))
NEWS_IMAGE_MAX_PIXELS = int(os.getenv("NEWS_IMAGE_MAX_PIXELS", str(40_000_000)))
NEWS_IMAGE_TIMEOUT = (8, 20)
NEWS_IMAGE_CHUNK_SIZE = 64 * 1024
NEWS_FETCH_MAX_WORKERS = int(os.getenv("NEWS_FETCH_MAX_WORKERS", "2"))
MIN_NEWS_COPY_LENGTH = int(os.getenv("NEWS_MIN_COPY_LENGTH", "40"))
WATERMARK_ASSET_CANDIDATES = (
    "6a8.svg",
    "6a8fac6a-36e3-4c29-a527-b216530317a6.png",
    "gatanga_watermark.svg",
    "gatanga_watermark_clean.png",
    "gatanga_watermark.svg.svg.png",
)


def resolve_watermark_asset():
    base_path = Path(__file__).resolve().parent
    for filename in WATERMARK_ASSET_CANDIDATES:
        candidate = base_path / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Watermark asset not found. Checked: "
        + ", ".join(str(Path(__file__).resolve().parent / name) for name in WATERMARK_ASSET_CANDIDATES)
    )


def load_watermark_image(asset_path):
    if asset_path.suffix.lower() == ".svg":
        try:
            import cairosvg
        except Exception:
            for fallback_name in WATERMARK_ASSET_CANDIDATES:
                if fallback_name.endswith(".svg"):
                    continue
                fallback_path = Path(__file__).resolve().parent / fallback_name
                if fallback_path.exists():
                    with Image.open(fallback_path) as fallback_image:
                        return fallback_image.convert("RGBA")
            raise RuntimeError(
                "SVG watermark found but cairosvg is not installed and no raster fallback is available."
            )

        rendered_png = cairosvg.svg2png(url=str(asset_path))
        with Image.open(BytesIO(rendered_png)) as watermark_image:
            return watermark_image.convert("RGBA")

    with Image.open(asset_path) as watermark_image:
        return watermark_image.convert("RGBA")


def escape_telegram_markdown(text):
    return re.sub(r"([_*\\[\\]()~`>#+\\-=|{}.!])", r"\\\1", text or "")


def truncate_caption_body(text, max_length):
    if len(text) <= max_length:
        return text
    if max_length <= 1:
        return text[:max_length]
    return text[: max_length - 1].rstrip() + "…"


def build_watermark_overlay(width, height):
    watermark_asset_path = resolve_watermark_asset()

    overlay = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    margin = max(24, int(width * WATERMARK_MARGIN_RATIO))
    watermark = load_watermark_image(watermark_asset_path)

    target_width = min(max(int(width * WATERMARK_WIDTH_RATIO), WATERMARK_MIN_WIDTH), WATERMARK_MAX_WIDTH)
    scale = target_width / watermark.width
    target_height = max(1, int(watermark.height * scale))
    watermark = watermark.resize((target_width, target_height), Image.LANCZOS)

    x = width - target_width - margin
    y = margin

    # Improve contrast for light watermarks over bright source images.
    bg_x0 = x - WATERMARK_BG_PADDING
    bg_y0 = y - WATERMARK_BG_PADDING
    bg_x1 = x + target_width + WATERMARK_BG_PADDING
    bg_y1 = y + target_height + WATERMARK_BG_PADDING
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (bg_x0, bg_y0, bg_x1, bg_y1),
        radius=WATERMARK_BG_RADIUS,
        fill=(0, 0, 0, max(0, min(255, WATERMARK_BG_ALPHA))),
    )
    overlay.alpha_composite(watermark, (x, y))
    return overlay


def create_watermarked_image(image_url):
    response = requests.get(image_url, timeout=NEWS_IMAGE_TIMEOUT, stream=True)
    response.raise_for_status()

    content_type = (response.headers.get("Content-Type") or "").lower()
    if not content_type.startswith("image/"):
        raise ValueError(f"Unsupported content type for image: {content_type or 'unknown'}")

    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            parsed_length = int(content_length)
        except (TypeError, ValueError):
            parsed_length = None
        if parsed_length and parsed_length > NEWS_IMAGE_MAX_BYTES:
            raise ValueError("Image is too large to process.")

    image_bytes = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=NEWS_IMAGE_CHUNK_SIZE):
            if not chunk:
                continue
            image_bytes.extend(chunk)
            if len(image_bytes) > NEWS_IMAGE_MAX_BYTES:
                raise ValueError("Image is too large to process.")
    finally:
        response.close()

    with Image.open(BytesIO(bytes(image_bytes))) as original:
        width, height = original.size
        if width <= 0 or height <= 0:
            raise ValueError("Invalid image dimensions.")
        if width * height > NEWS_IMAGE_MAX_PIXELS:
            raise ValueError("Image dimensions are too large to process.")
        base = original.convert("RGBA")

    overlay = build_watermark_overlay(*base.size)
    watermarked = Image.alpha_composite(base, overlay).convert("RGB")

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    temp_path = Path(temp_file.name)
    temp_file.close()
    watermarked.save(temp_path, format="JPEG", quality=92, optimize=True)
    return temp_path


def format_news_broadcast(item):
    title = escape_telegram_markdown(item.get("translated_title_am") or item.get("title") or "")
    story = escape_telegram_markdown(item.get("translated_story_am") or "")
    source_name = escape_telegram_markdown(item.get("source_name") or "")
    image_url = item.get("image_url") or ""

    lines = [f"📰 *{title}*"]
    if story:
        lines.extend(["", story])
    if source_name:
        lines.extend(["", f"ምንጭ: {source_name}"])
    caption = "\n".join(lines)
    if len(caption) > TELEGRAM_CAPTION_LIMIT:
        source_line = f"\n\nምንጭ: {source_name}" if source_name else ""
        title_block = f"📰 *{title}*"
        story_budget = TELEGRAM_CAPTION_LIMIT - len(title_block) - len(source_line) - 2
        trimmed_story = truncate_caption_body(story, max(story_budget, 0))
        lines = [title_block]
        if trimmed_story:
            lines.extend(["", trimmed_story])
        if source_name:
            lines.extend(["", f"ምንጭ: {source_name}"])
        caption = "\n".join(lines)
    return {
        "image_url": image_url,
        "caption": caption,
    }


def fetch_news_items():
    attempted_sources = []
    failed_sources = []
    collected_batches = []

    base_collectors = [
        ("bbc", fetch_bbc_football_rss),
        ("guardian", fetch_guardian_premier_league_rss),
        ("sky_sports", fetch_sky_sports_premier_league_rss),
    ]

    jobs = []
    for source_name, collector in base_collectors:
        attempted_sources.append(source_name)
        jobs.append((source_name, collector))

    for source_config in PREMIER_LEAGUE_CLUB_RSS_SOURCES:
        source_key = source_config.get("source_key", "club_unknown")
        attempted_sources.append(source_key)
        jobs.append(
            (
                source_key,
                lambda cfg=source_config: fetch_rss_source(
                    cfg,
                    enrich=False,
                    max_items=RSS_MAX_ITEMS_CLUB,
                ),
            )
        )

    max_workers = max(1, min(NEWS_FETCH_MAX_WORKERS, len(jobs) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(job_fn): source_name
            for source_name, job_fn in jobs
        }
        for future in as_completed(future_map):
            source_name = future_map[future]
            try:
                source, raw_items = future.result()
                if raw_items:
                    collected_batches.append((source, raw_items))
            except Exception as exc:
                failed_sources.append({"source": source_name, "error": str(exc)})

    if not collected_batches:
        raise RuntimeError("All news sources failed or returned no items.")

    source_breakdown = []
    normalized_items = []
    fetched_total = 0

    for source, raw_items in collected_batches:
        fetched_total += len(raw_items)
        source_breakdown.append(
            {
                "source_key": source.get("source_key"),
                "source_name": source.get("source_name"),
                "source_url": source.get("source_url"),
                "fetched_count": len(raw_items),
            }
        )
        for item in raw_items:
            title = (item.get("title") or "").strip()
            article_url = (item.get("article_url") or "").strip()
            summary = (item.get("summary") or "").strip()
            story = (item.get("story") or "").strip()
            best_copy = story if len(story) >= len(summary) else summary
            if not title or not article_url:
                continue
            if is_excluded_news_item(item):
                continue
            if len(best_copy) < MIN_NEWS_COPY_LENGTH:
                continue
            normalized_items.append(
                normalize_news_item(
                    source_key=source["source_key"],
                    source_name=source["source_name"],
                    source_url=source["source_url"],
                    item=item,
                )
            )

    # New fetches only need reviewable items; rejected feed junk should be dropped here.
    normalized_items = [item for item in normalized_items if item.get("review_status") == "filtered"]

    bbc_source = next(
        (row for row in source_breakdown if row.get("source_key") == "bbc_football_rss"),
        None,
    )
    primary_source = bbc_source or (source_breakdown[0] if source_breakdown else {})

    deduped_items = {}
    for item in normalized_items:
        deduped_items[item["content_hash"]] = item

    existing_items = get_news_items_by_content_hashes(deduped_items.keys())
    existing_urls = get_news_items_by_article_urls(
        {item.get("article_url") for item in deduped_items.values()}
    )
    recent_items = get_existing_news_items_for_sources(
        {item.get("source_name") for item in deduped_items.values()}
    )
    recent_title_keys = set()
    hidden_title_keys = set()
    for row in recent_items:
        title_key = build_source_title_key(row.get("source_name"), row.get("title"))
        if not title_key:
            continue
        recent_title_keys.add(title_key)
        if is_user_hidden(row.get("notes")):
            hidden_title_keys.add(title_key)

    deduped_items = {
        content_hash: item
        for content_hash, item in deduped_items.items()
        if content_hash not in existing_items
        and item.get("article_url") not in existing_urls
        and not is_user_hidden((existing_items.get(content_hash) or {}).get("notes"))
        and not is_user_hidden((existing_urls.get(item.get("article_url")) or {}).get("notes"))
        and build_source_title_key(item.get("source_name"), item.get("title")) not in hidden_title_keys
        and build_source_title_key(item.get("source_name"), item.get("title")) not in recent_title_keys
    }

    stored_items = upsert_news_items(list(deduped_items.values()))
    return {
        "source": {
            "source_key": primary_source.get("source_key"),
            "source_name": primary_source.get("source_name"),
            "source_url": primary_source.get("source_url"),
        },
        "source_breakdown": source_breakdown,
        "attempted_sources": attempted_sources,
        "failed_sources": failed_sources,
        "fallback_used": any(
            row.get("source_key") != "bbc_football_rss"
            for row in source_breakdown
        ),
        "fetched_count": fetched_total,
        "normalized_count": len(normalized_items),
        "deduped_count": len(deduped_items),
        "stored_count": len(stored_items),
    }


def get_review_queue(limit=20):
    return list_news_queue(statuses=["filtered", "approved", "translated"], limit=limit)


def mark_review_item(
    item_id,
    status,
    translated_title_am=None,
    translated_story_am=None,
    notes=None,
    image_url=None,
):
    status = (status or "").strip().lower()
    if status != "published":
        return mark_news_item(
            item_id=item_id,
            status=status,
            translated_title_am=translated_title_am,
            translated_story_am=translated_story_am,
            notes=notes,
            image_url=image_url,
        )

    item = get_news_item(item_id)
    if not item:
        raise ValueError("News item not found.")
    if item.get("review_status") == "published":
        raise ValueError("News item is already published.")
    validate_status_transition(item.get("review_status"), status)

    final_title = translated_title_am if translated_title_am is not None else item.get("translated_title_am")
    final_story = translated_story_am if translated_story_am is not None else item.get("translated_story_am")
    if not final_title or not final_story:
        raise ValueError("Publishing requires both an Amharic title and story.")

    payload = format_news_broadcast({
        **item,
        "image_url": image_url if image_url is not None else item.get("image_url"),
        "translated_title_am": final_title,
        "translated_story_am": final_story,
    })
    sent_message = None
    if payload["image_url"]:
        temp_path = None
        try:
            temp_path = create_watermarked_image(payload["image_url"])
            sent_message = send_telegram_photo_file(temp_path, payload["caption"], return_message=True)
        except Exception as exc:
            print(f"Watermark render/upload failed for item {item_id}: {exc}")
            try:
                sent_message = send_telegram_photo(payload["image_url"], payload["caption"], return_message=True)
            except Exception as photo_exc:
                print(f"Direct photo send failed for item {item_id}: {photo_exc}")
                sent_message = send_telegram_message(payload["caption"], return_message=True)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    else:
        sent_message = send_telegram_message(payload["caption"], return_message=True)
    if not sent_message:
        raise RuntimeError("Telegram delivery failed. Check bot configuration.")
    return mark_news_item(
        item_id=item_id,
        status=status,
        translated_title_am=final_title,
        translated_story_am=final_story,
        notes=notes,
        image_url=image_url,
    )
