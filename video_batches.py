"""
Pure helpers for category-based merged videos (no Supabase, ffmpeg or Telegram imports,
so they can be tested on their own).

Rules:
- Stories are grouped by category (competition), one video per category.
- A category needs at least MIN_MERGED_STORIES stories; fewer wait for the next run.
- No maximum number of stories per video. A video is only split when the rendered
  file would exceed the Telegram upload limit, and then by file size, never by count.
"""
import math
import os
from datetime import timedelta, timezone

# Hard floor: neither an env var nor a caller can lower it.
MIN_MERGED_STORIES = 3

POOL_WINDOW_HOURS = int(os.getenv("VIDEO_POOL_WINDOW_HOURS", "72"))

EAT = timezone(timedelta(hours=3))

PREMIER_LEAGUE = "premier_league"
CHAMPIONS_LEAGUE = "champions_league"
EUROPA_LEAGUE = "europa_league"
WORLD_CUP = "world_cup"
GENERAL = "general"

CATEGORY_ORDER = [PREMIER_LEAGUE, CHAMPIONS_LEAGUE, EUROPA_LEAGUE, WORLD_CUP, GENERAL]

CATEGORY_TITLES = {
    PREMIER_LEAGUE: "የፕሪሚየር ሊግ ዜና ማጠቃለያ",
    CHAMPIONS_LEAGUE: "የቻምፒየንስ ሊግ ዜና ማጠቃለያ",
    EUROPA_LEAGUE: "የኢሮፓ ሊግ ዜና ማጠቃለያ",
    WORLD_CUP: "የዓለም ዋንጫ ዜና ማጠቃለያ",
    GENERAL: "የእግር ኳስ ዜና ማጠቃለያ",
}

_TAG_CATEGORIES = [
    ("competition:champions_league", CHAMPIONS_LEAGUE),
    ("competition:europa_league", EUROPA_LEAGUE),
    ("competition:world_cup", WORLD_CUP),
    ("competition:premier_league", PREMIER_LEAGUE),
]

_SOURCE_KEY_CATEGORIES = [
    ("champions_league", CHAMPIONS_LEAGUE),
    ("europa_league", EUROPA_LEAGUE),
    ("world_cup", WORLD_CUP),
    ("premier_league", PREMIER_LEAGUE),
]


def story_category(item):
    """Category of one story.

    1. The `competition:` tag in topic_tags.
    2. Otherwise the source feed (a Guardian Champions League report can carry no
       competition tag, so the source is the reliable fallback).
    3. Transfer gossip counts as Premier League.
    4. Anything else is general football news.
    """
    tags = item.get("topic_tags") or []
    for tag, category in _TAG_CATEGORIES:
        if tag in tags:
            return category
    source_key = (item.get("source_key") or "").lower()
    for fragment, category in _SOURCE_KEY_CATEGORIES:
        if fragment in source_key:
            return category
    if "topic:gossip" in tags:
        return PREMIER_LEAGUE
    return GENERAL


def group_by_category(items):
    """{category: [items]} in CATEGORY_ORDER, keeping each category's item order."""
    groups = {}
    for item in items:
        groups.setdefault(story_category(item), []).append(item)
    return {category: groups[category] for category in CATEGORY_ORDER if category in groups}


def split_by_size(sizes, budget):
    """Split clip sizes (bytes, in play order) into the fewest balanced consecutive
    parts that each fit under `budget`. Returns lists of indexes. Everything fits ->
    one part holding every index. Order is never changed and no story is dropped."""
    total = sum(sizes)
    if not sizes:
        return []
    if total <= budget:
        return [list(range(len(sizes)))]
    count = math.ceil(total / budget)
    target = total / count
    parts, current, current_size = [], [], 0
    for index, size in enumerate(sizes):
        current.append(index)
        current_size += size
        parts_left = count - len(parts) - 1
        clips_left = len(sizes) - index - 1
        if parts_left > 0 and current_size >= target and clips_left >= parts_left:
            parts.append(current)
            current, current_size = [], 0
    if current:
        parts.append(current)
    return parts


def batch_id(now, category):
    """Stamp written to news_items.video_batch_id, e.g. 20261022-0540-champions_league."""
    return f"{now.astimezone(EAT).strftime('%Y%m%d-%H%M')}-{category}"
