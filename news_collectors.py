import html
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests


MEDIA_NS = {"media": "http://search.yahoo.com/mrss/"}
IMAGE_META_PATTERNS = [
    re.compile(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        re.IGNORECASE,
    ),
]
ARTICLE_IMAGE_PATTERNS = [
    re.compile(
        r'<img[^>]+src=["\']([^"\']+)["\'][^>]+(?:data-testid|class)=["\'][^"\']*(?:hero|lead|main)[^"\']*["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<img[^>]+(?:data-testid|class)=["\'][^"\']*(?:hero|lead|main)[^"\']*["\'][^>]+src=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
]
ARTICLE_BODY_PATTERNS = [
    re.compile(r'"articleBody":"(.*?)"', re.IGNORECASE | re.DOTALL),
]
PARAGRAPH_PATTERNS = [
    re.compile(r'<p[^>]+data-testid=["\']paragraph["\'][^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL),
    re.compile(r'<p[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL),
]
BOILERPLATE_PATTERNS = [
    re.compile(r"^BBC Homepage", re.IGNORECASE),
    re.compile(r"^Skip to content", re.IGNORECASE),
    re.compile(r"^Accessibility Help", re.IGNORECASE),
    re.compile(r"^Your account$", re.IGNORECASE),
    re.compile(r"^Home$", re.IGNORECASE),
    re.compile(r"^More menu$", re.IGNORECASE),
    re.compile(r"^Search BBC$", re.IGNORECASE),
    re.compile(r"^Close menu BBC Sport$", re.IGNORECASE),
    re.compile(r"^MenuHomeFootball", re.IGNORECASE),
    re.compile(r"^Full Sports A-Z", re.IGNORECASE),
    re.compile(r"^More from Sport", re.IGNORECASE),
    re.compile(r"^News Feeds$", re.IGNORECASE),
    re.compile(r"^Help & FAQs$", re.IGNORECASE),
    re.compile(r"^Scores & Fixtures$", re.IGNORECASE),
    re.compile(r"^Table$", re.IGNORECASE),
    re.compile(r"^Ask Me Anything$", re.IGNORECASE),
    re.compile(r"^Image source,", re.IGNORECASE),
    re.compile(r"^Image caption,", re.IGNORECASE),
    re.compile(r"^Published\d", re.IGNORECASE),
    re.compile(r"Comments$", re.IGNORECASE),
    re.compile(r"reporter\s*Published\s*\d+\s*hours?\s*ago\s*\d+\s*Comments", re.IGNORECASE),
]
BYLINE_PATTERN = re.compile(
    r"^[A-Z][A-Za-z\s'-]+reporter\s*Published\s*\d+\s*hours?\s*ago\s*\d+\s*Comments\s*",
    re.IGNORECASE,
)

BBC_FOOTBALL_SOURCE = {
    "source_key": "bbc_football_rss",
    "source_name": "BBC Sport Football",
    "source_url": "http://newsrss.bbc.co.uk/rss/sportonline_uk_edition/football/rss.xml",
}


def extract_tag_values(item_element):
    tags = []
    for category in item_element.findall("category"):
        if category.text:
            tags.append(category.text.strip())
    return tags


def extract_image_url(item_element):
    thumbnail = item_element.find("media:thumbnail", MEDIA_NS)
    if thumbnail is not None and thumbnail.get("url"):
        return thumbnail.get("url").strip()

    content = item_element.find("media:content", MEDIA_NS)
    if content is not None and content.get("url"):
        return content.get("url").strip()

    enclosure = item_element.find("enclosure")
    if enclosure is not None and enclosure.get("type", "").startswith("image/") and enclosure.get("url"):
        return enclosure.get("url").strip()

    return None


def clean_image_url(value, base_url):
    if not value:
        return None
    value = html.unescape(value).strip()
    if not value:
        return None
    return urljoin(base_url, value)


def strip_html(value):
    cleaned = re.sub(r"<[^>]+>", "", value or "")
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\\n", "\n").replace("\\\"", '"')
    return re.sub(r"\s+", " ", cleaned).strip()


def is_boilerplate_paragraph(paragraph):
    if not paragraph:
        return True
    if len(paragraph) < 40:
        return True
    return any(pattern.search(paragraph) for pattern in BOILERPLATE_PATTERNS)


def dedupe_story_blocks(blocks):
    unique_blocks = []
    seen_normalized = set()
    for block in blocks:
        normalized = re.sub(r"\s+", " ", block).strip().lower()
        if not normalized or normalized in seen_normalized:
            continue
        seen_normalized.add(normalized)
        unique_blocks.append(block)

    if len(unique_blocks) >= 2 and len(unique_blocks) % 2 == 0:
        midpoint = len(unique_blocks) // 2
        if unique_blocks[:midpoint] == unique_blocks[midpoint:]:
            return unique_blocks[:midpoint]

    return unique_blocks


def normalize_space(value):
    return re.sub(r"\s+", " ", value or "").strip()


def clean_story_text(story, title=None, summary=None):
    if not story:
        return None

    story = normalize_space(story)
    for prefix in (title, summary):
        normalized_prefix = normalize_space(prefix)
        if normalized_prefix and story.startswith(normalized_prefix):
            story = story[len(normalized_prefix):].strip(" :-")

    story = BYLINE_PATTERN.sub("", story).strip()
    story = re.sub(r"\s+", " ", story).strip()
    return story or None


def fetch_article_html(article_url, session):
    try:
        response = session.get(article_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return None, article_url
    return response.text, response.url


def extract_article_image_url(body, base_url):
    if not body:
        return None

    for pattern in IMAGE_META_PATTERNS:
        match = pattern.search(body)
        if match:
            return clean_image_url(match.group(1), base_url)

    for pattern in ARTICLE_IMAGE_PATTERNS:
        match = pattern.search(body)
        if match:
            return clean_image_url(match.group(1), base_url)

    return None


def extract_article_story(body, title=None, summary=None):
    if not body:
        return None

    for pattern in ARTICLE_BODY_PATTERNS:
        match = pattern.search(body)
        if match:
            story = clean_story_text(
                strip_html(match.group(1)),
                title=title,
                summary=summary,
            )
            if story and len(story) > 120 and not is_boilerplate_paragraph(story):
                return story

    paragraphs = []
    for pattern in PARAGRAPH_PATTERNS:
        matches = pattern.findall(body)
        for raw_paragraph in matches:
            paragraph = strip_html(raw_paragraph)
            if is_boilerplate_paragraph(paragraph):
                continue
            if paragraph not in paragraphs:
                paragraphs.append(paragraph)
        if len(paragraphs) >= 3:
            break

    paragraphs = dedupe_story_blocks(paragraphs)
    if paragraphs:
        return clean_story_text(
            "\n\n".join(paragraphs[:5]),
            title=title,
            summary=summary,
        )

    return None


def enrich_item_image(item, session):
    article_url = item.get("article_url")
    if not article_url:
        return item

    body, resolved_url = fetch_article_html(article_url, session)
    article_image_url = extract_article_image_url(body, resolved_url)
    if article_image_url:
        item["image_url"] = article_image_url
    story = extract_article_story(
        body,
        title=item.get("title"),
        summary=item.get("summary"),
    )
    if story:
        item["story"] = story

    return item


def fetch_bbc_football_rss():
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
            )
        }
    )

    response = session.get(BBC_FOOTBALL_SOURCE["source_url"], timeout=20)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    items = []
    for entry in root.findall("./channel/item"):
        items.append(
            {
                "title": (entry.findtext("title") or "").strip(),
                "summary": (entry.findtext("description") or "").strip(),
                "story": None,
                "article_url": (entry.findtext("link") or "").strip(),
                "image_url": extract_image_url(entry),
                "published_at": (entry.findtext("pubDate") or "").strip(),
                "author": (entry.findtext("author") or "").strip() or None,
                "language": "en",
                "topic_tags": extract_tag_values(entry),
            }
        )

    enriched_items = [None] * len(items)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(enrich_item_image, item, session): index
            for index, item in enumerate(items)
        }
        for future in as_completed(futures):
            enriched_items[futures[future]] = future.result()

    return BBC_FOOTBALL_SOURCE, enriched_items
