import re
import tempfile
from io import BytesIO
import os
from pathlib import Path

import requests
from PIL import Image

from commands import send_telegram_message, send_telegram_photo_file
from news_collectors import (
    PREMIER_LEAGUE_CLUB_RSS_SOURCES,
    fetch_bbc_football_rss,
    fetch_guardian_premier_league_rss,
    fetch_rss_source,
    fetch_sky_sports_premier_league_rss,
)
from news_store import (
    get_news_item,
    list_news_queue,
    mark_news_item,
    normalize_news_item,
    upsert_news_items,
    validate_status_transition,
)

TELEGRAM_CAPTION_LIMIT = 1024
WATERMARK_MARGIN_RATIO = 0.04
WATERMARK_WIDTH_RATIO = 0.24
WATERMARK_MAX_WIDTH = 320
WATERMARK_MIN_WIDTH = 120
NEWS_IMAGE_MAX_BYTES = int(os.getenv("NEWS_IMAGE_MAX_BYTES", str(8 * 1024 * 1024)))
NEWS_IMAGE_MAX_PIXELS = int(os.getenv("NEWS_IMAGE_MAX_PIXELS", str(40_000_000)))
NEWS_IMAGE_TIMEOUT = (8, 20)
NEWS_IMAGE_CHUNK_SIZE = 64 * 1024
WATERMARK_ASSET_CANDIDATES = (
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
    y = height - target_height - margin
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

    for source_name, collector in base_collectors:
        attempted_sources.append(source_name)
        try:
            source, raw_items = collector()
            if raw_items:
                collected_batches.append((source, raw_items))
        except Exception as exc:
            failed_sources.append({"source": source_name, "error": str(exc)})

    for source_config in PREMIER_LEAGUE_CLUB_RSS_SOURCES:
        source_key = source_config.get("source_key", "club_unknown")
        attempted_sources.append(source_key)
        try:
            source, raw_items = fetch_rss_source(source_config, enrich=False)
            if raw_items:
                collected_batches.append((source, raw_items))
        except Exception as exc:
            failed_sources.append({"source": source_key, "error": str(exc)})

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
        normalized_items.extend(
            [
                normalize_news_item(
                    source_key=source["source_key"],
                    source_name=source["source_name"],
                    source_url=source["source_url"],
                    item=item,
                )
                for item in raw_items
                if item.get("article_url") and item.get("title")
            ]
        )

    primary_source = source_breakdown[0] if source_breakdown else {}

    deduped_items = {}
    for item in normalized_items:
        deduped_items[item["content_hash"]] = item

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
):
    status = (status or "").strip().lower()
    if status != "published":
        return mark_news_item(
            item_id=item_id,
            status=status,
            translated_title_am=translated_title_am,
            translated_story_am=translated_story_am,
            notes=notes,
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
        "translated_title_am": final_title,
        "translated_story_am": final_story,
    })
    if payload["image_url"]:
        temp_path = create_watermarked_image(payload["image_url"])
        try:
            sent = send_telegram_photo_file(temp_path, payload["caption"])
        finally:
            temp_path.unlink(missing_ok=True)
    else:
        sent = send_telegram_message(payload["caption"])
    if not sent:
        raise RuntimeError("Telegram delivery failed. Check bot configuration.")
    return mark_news_item(
        item_id=item_id,
        status=status,
        translated_title_am=final_title,
        translated_story_am=final_story,
        notes=notes,
    )
