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
    fetch_bbc_world_cup_rss,
    fetch_guardian_premier_league_rss,
    fetch_rss_source,
    fetch_sky_sports_football_rss,
    fetch_sky_sports_premier_league_rss,
    is_excluded_news_item,
)
from news_store import (
    build_source_title_key,
    canonical_article_url,
    get_news_items_by_article_urls,
    get_news_items_by_content_hashes,
    get_existing_news_items_for_sources,
    get_news_item,
    is_user_hidden,
    list_follow_up_requests,
    list_news_queue,
    mark_news_item,
    normalize_news_item,
    upsert_news_items,
    validate_status_transition,
)
from store import fetch_premier_league_clubs_for_season
from telegram_limits import (
    TELEGRAM_CAPTION_LIMIT,
    TELEGRAM_NEWS_CAPTION_TARGET,
    TELEGRAM_NEWS_MAX_LINES,
    compact_news_caption,
    telegram_limit_status,
)

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

TEAM_TAG_LABELS = {
    "club:arsenal": "Arsenal",
    "club:aston_villa": "AstonVilla",
    "club:bournemouth": "Bournemouth",
    "club:brentford": "Brentford",
    "club:brighton": "Brighton",
    "club:burnley": "Burnley",
    "club:chelsea": "Chelsea",
    "club:crystal_palace": "CrystalPalace",
    "club:everton": "Everton",
    "club:fulham": "Fulham",
    "club:leeds": "LeedsUnited",
    "club:liverpool": "Liverpool",
    "club:man_city": "ManchesterCity",
    "club:man_utd": "ManchesterUnited",
    "club:newcastle": "NewcastleUnited",
    "club:nottingham_forest": "NottinghamForest",
    "club:spurs": "Tottenham",
    "club:sunderland": "Sunderland",
    "club:west_ham": "WestHam",
    "club:wolves": "Wolves",
}

TEAM_TAG_CODES = {
    "club:arsenal": "ars",
    "club:aston_villa": "avl",
    "club:bournemouth": "bou",
    "club:brentford": "bre",
    "club:brighton": "bha",
    "club:burnley": "bur",
    "club:chelsea": "che",
    "club:crystal_palace": "cry",
    "club:everton": "eve",
    "club:fulham": "ful",
    "club:leeds": "lee",
    "club:liverpool": "liv",
    "club:man_city": "mci",
    "club:man_utd": "manu",
    "club:newcastle": "new",
    "club:nottingham_forest": "nfo",
    "club:spurs": "tot",
    "club:sunderland": "sun",
    "club:west_ham": "whu",
    "club:wolves": "wol",
}

UPDATE_TAG_LABELS = {
    "topic:injury": "InjuryUpdate",
    "topic:transfer": "TransferUpdate",
    "topic:manager": "ManagerUpdate",
    "topic:official": "OfficialUpdate",
    "topic:preview": "MatchPreview",
    "topic:result": "MatchUpdate",
    "topic:gossip": "TransferTalk",
    "format:lineup_update": "LineupUpdate",
    "format:pre_match": "MatchPreview",
    "format:post_match": "MatchUpdate",
    "fact:injury_update": "InjuryUpdate",
    "fact:scorers": "MatchUpdate",
    "fact:final_score": "MatchUpdate",
}

PLAYER_NAME_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")
PLAYER_NAME_EXCLUSIONS = {
    "Premier League",
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Conference League",
    "Aston Villa",
    "Nottingham Forest",
    "Crystal Palace",
    "Manchester City",
    "Manchester United",
    "Newcastle United",
    "Tottenham Hotspur",
    "West Ham",
    "Sky Sports",
    "BBC Sport",
    "The Guardian",
}


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


def _slug_hashtag(label):
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", label or "").strip()
    if not cleaned:
        return ""
    parts = cleaned.split()
    return "#" + "".join(part[:1].upper() + part[1:] for part in parts if part)


def _ordered_unique(values):
    seen = set()
    ordered = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _extract_league_hashtags(item):
    topic_tags = item.get("topic_tags") or []
    haystack = " ".join(
        [
            item.get("title") or "",
            item.get("summary") or "",
            item.get("story") or "",
        ]
    )
    tags = []
    if "competition:premier_league" in topic_tags or re.search(r"\bpremier league\b", haystack, re.IGNORECASE):
        tags.append("#PremierLeague")
    if "competition:world_cup" in topic_tags or re.search(r"\bfifa world cup\b|\bworld cup\b|\bworld cup qualifiers?\b", haystack, re.IGNORECASE):
        tags.append("#WorldCup")
    if re.search(r"\buefa champions league\b|\bchampions league\b", haystack, re.IGNORECASE):
        tags.append("#ChampionsLeague")
    if re.search(r"\buefa europa league\b|\beuropa league\b", haystack, re.IGNORECASE):
        tags.append("#EuropaLeague")
    if re.search(r"\buefa conference league\b|\bconference league\b", haystack, re.IGNORECASE):
        tags.append("#ConferenceLeague")
    return _ordered_unique(tags)


def _extract_team_hashtags(item):
    topic_tags = item.get("topic_tags") or []
    club_tags = [topic_tag for topic_tag in topic_tags if topic_tag in TEAM_TAG_LABELS]
    tags = []

    if len(club_tags) >= 2:
        home_code = TEAM_TAG_CODES.get(club_tags[0])
        away_code = TEAM_TAG_CODES.get(club_tags[1])
        if home_code and away_code:
            tags.append(f"#{home_code}vs{away_code}")

    for topic_tag in club_tags:
        label = TEAM_TAG_LABELS.get(topic_tag)
        if label:
            tags.append(_slug_hashtag(label))
    return _ordered_unique(tags)


def _extract_player_hashtags(item, max_players=3):
    raw_payload = item.get("raw_payload") or {}
    match_meta = raw_payload.get("match_metadata") or {}
    candidates = []

    for scorer in match_meta.get("scorers") or []:
        player = (scorer.get("player") or "").strip()
        if player:
            candidates.append(player)

    source_text = " ".join(
        [
            item.get("title") or "",
            item.get("summary") or "",
            item.get("story") or "",
        ]
    )
    for player_name in PLAYER_NAME_PATTERN.findall(source_text):
        if player_name in PLAYER_NAME_EXCLUSIONS:
            continue
        candidates.append(player_name)

    tags = []
    for player_name in _ordered_unique(candidates):
        hashtag = _slug_hashtag(player_name)
        if hashtag and hashtag not in tags:
            tags.append(hashtag)
        if len(tags) >= max_players:
            break
    return tags


def _extract_update_hashtags(item):
    topic_tags = item.get("topic_tags") or []
    tags = []
    for topic_tag in topic_tags:
        label = UPDATE_TAG_LABELS.get(topic_tag)
        if label:
            tags.append(_slug_hashtag(label))
    return _ordered_unique(tags)


def _build_news_hashtag_block(item):
    hashtags = []
    hashtags.extend(_extract_league_hashtags(item))
    hashtags.extend(_extract_team_hashtags(item))
    hashtags.extend(_extract_player_hashtags(item))
    hashtags.extend(_extract_update_hashtags(item))
    hashtags = _ordered_unique(hashtags)
    return " ".join(hashtags)


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
    raw_title = item.get("translated_title_am") or ""
    title = f"*{escape_telegram_markdown(raw_title)}*" if raw_title else ""
    story = escape_telegram_markdown(item.get("translated_story_am") or "")
    image_url = item.get("image_url") or ""
    source_name = escape_telegram_markdown(item.get("source_name") or "")
    source_line = f"Source: {source_name}" if source_name else ""
    hashtag_block = _build_news_hashtag_block(item)

    lines = []
    if title:
        lines.append(title)
        lines.append("━━━━━━━━━━━━━━━━━━━━")
    if story:
        lines.append(story)
    if source_line:
        if lines:
            lines.append("")
        lines.append(source_line)
    if hashtag_block:
        if lines:
            lines.append("")
        lines.append(hashtag_block)
    caption = "\n".join(lines)
    if len(caption) > TELEGRAM_CAPTION_LIMIT:
        title_block = title
        source_block = source_line
        hashtag_line = hashtag_block
        extra_length = 0
        if title_block:
            extra_length += len(title_block)
        if source_block:
            extra_length += len(source_block) + 2
        if hashtag_line:
            extra_length += len(hashtag_line) + 2
        story_budget = TELEGRAM_CAPTION_LIMIT - extra_length - 2
        trimmed_story = truncate_caption_body(story, max(story_budget, 0))
        lines = []
        if title_block:
            lines.append(title_block)
        if trimmed_story:
            lines.extend(["", trimmed_story])
        if source_block:
            lines.extend(["", source_block])
        if hashtag_line:
            lines.extend(["", hashtag_line])
        caption = "\n".join(lines)
    caption = compact_news_caption(caption, has_image=bool(image_url))
    limit_status = telegram_limit_status(
        caption,
        has_image=bool(image_url),
        target=TELEGRAM_NEWS_CAPTION_TARGET if image_url else None,
        max_lines=TELEGRAM_NEWS_MAX_LINES,
    )
    return {
        "image_url": image_url,
        "caption": caption,
        "limit_status": limit_status,
    }


def fetch_news_items():
    attempted_sources = []
    failed_sources = []
    collected_batches = []

    base_collectors = [
        ("bbc", fetch_bbc_football_rss),
        ("bbc_world_cup", fetch_bbc_world_cup_rss),
        ("guardian", fetch_guardian_premier_league_rss),
        ("sky_sports", fetch_sky_sports_premier_league_rss),
        ("sky_sports_football", fetch_sky_sports_football_rss),
    ]

    jobs = []
    for source_name, collector in base_collectors:
        attempted_sources.append(source_name)
        jobs.append((source_name, collector))

    active_clubs = fetch_premier_league_clubs_for_season()
    club_sources = [
        source_config
        for source_config in PREMIER_LEAGUE_CLUB_RSS_SOURCES
        if not active_clubs or source_config.get("source_name") in active_clubs
    ]

    for source_config in club_sources:
        source_key = source_config.get("source_key", "club_unknown")
        attempted_sources.append(source_key)
        jobs.append(
            (
                source_key,
                lambda cfg=source_config: fetch_rss_source(
                    cfg,
                    enrich=True,
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
    active_followups = list_follow_up_requests(status="active")

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
                    followups=active_followups,
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
        canonical_url = canonical_article_url(item.get("article_url"))
        item.setdefault("raw_payload", {})["canonical_article_url"] = canonical_url
        dedupe_key = canonical_url or item["content_hash"]
        existing_item = deduped_items.get(dedupe_key)
        if not existing_item or item.get("relevance_score", 0) > existing_item.get("relevance_score", 0):
            deduped_items[dedupe_key] = item

    existing_items = get_news_items_by_content_hashes(
        {item.get("content_hash") for item in deduped_items.values()}
    )
    existing_urls = get_news_items_by_article_urls(
        {item.get("article_url") for item in deduped_items.values()}
    )
    recent_items = get_existing_news_items_for_sources(
        {item.get("source_name") for item in deduped_items.values()}
    )
    recent_title_keys = set()
    hidden_title_keys = set()
    existing_canonical_urls = {
        canonical_article_url(url)
        for url in existing_urls
        if url
    }
    for row in recent_items:
        canonical_url = canonical_article_url(row.get("article_url"))
        if canonical_url:
            existing_canonical_urls.add(canonical_url)
        title_key = build_source_title_key(row.get("source_name"), row.get("title"))
        if not title_key:
            continue
        recent_title_keys.add(title_key)
        if is_user_hidden(row.get("notes")):
            hidden_title_keys.add(title_key)

    deduped_items = {
        dedupe_key: item
        for dedupe_key, item in deduped_items.items()
        if item.get("content_hash") not in existing_items
        and item.get("article_url") not in existing_urls
        and canonical_article_url(item.get("article_url")) not in existing_canonical_urls
        and not is_user_hidden((existing_items.get(item.get("content_hash")) or {}).get("notes"))
        and not is_user_hidden((existing_urls.get(item.get("article_url")) or {}).get("notes"))
        and build_source_title_key(item.get("source_name"), item.get("title")) not in hidden_title_keys
        and build_source_title_key(item.get("source_name"), item.get("title")) not in recent_title_keys
    }

    stored_items = upsert_news_items(list(deduped_items.values()))
    follow_up_match_count = sum(
        1
        for item in deduped_items.values()
        if ((item.get("raw_payload") or {}).get("follow_up_matches"))
    )
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
        "active_follow_up_count": len(active_followups),
        "follow_up_match_count": follow_up_match_count,
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
    payload["caption"] = compact_news_caption(payload["caption"], has_image=bool(payload["image_url"]))
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


def translate_news_item(item):
    \"\"\"
    Translates news title and story to Amharic following strict guidelines:
    - Bold title, short paragraph, <250 chars.
    - Natural sports phrasing.
    - Special handling for gossip/paper talk: create short briefs for each team.
    \"\"\"
    topic_tags = item.get("topic_tags") or []
    is_gossip = "topic:gossip" in topic_tags

    # This is a placeholder for an LLM API call
    # If is_gossip is True, the prompt would specifically ask for:
    # "This is a transfer gossip item. Create a concise Amharic summary (under 250 chars) 
    # that briefly highlights the situation for each team involved."
    
    if is_gossip:
        # Mock gossip translation
        return f"[Gossip Title]: {item['title']}", f"[Gossip Brief]: {item['story'][:150]}... (Team-specific briefs applied)"
    
    return f"[Translated Title]: {item['title']}", f"[Translated Story]: {item['story'][:200]}..."



def process_and_publish_news():
    \"\"\"
    End-to-end pipeline: Fetch -> Dedup (inside fetch) -> Translate -> Publish.
    \"\"\"
    fetch_result = fetch_news_items()
    queue = get_review_queue(limit=10)
    if not queue:
        return {"success": True, "processed": 0, "message": "No new news to process."}

    processed_count = 0
    for item in queue:
        try:
            translated_title, translated_story = translate_news_item(item)
            mark_review_item(
                item_id=item["id"],
                status="published",
                translated_title_am=translated_title,
                translated_story_am=translated_story
            )
            processed_count += 1
        except Exception as e:
            print(f"Failed to process item {item.get('id')}: {e}")

    return {
        "success": True,
        "processed": processed_count,
        "message": f"Processed and published {processed_count} news items."
    }
