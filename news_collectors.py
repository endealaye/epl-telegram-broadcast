import html
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests


RSS_NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "atom": "http://www.w3.org/2005/Atom",
}
MEDIA_NS = {"media": RSS_NS["media"]}
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
NAV_NOISE_PATTERNS = [
    re.compile(r"addEventListener\s*\(", re.IGNORECASE),
    re.compile(r"DOMContentLoaded", re.IGNORECASE),
    re.compile(r"The Guardian - Back to home", re.IGNORECASE),
    re.compile(r"USUS edition|UK edition|Australia edition|Europe edition|International edition", re.IGNORECASE),
    re.compile(r"Show moreHide expanded menu", re.IGNORECASE),
    re.compile(r"Search input", re.IGNORECASE),
    re.compile(r"View all News|View all Opinion|View all Sport|View all Culture|View all Lifestyle", re.IGNORECASE),
]
EXCLUDED_NEWS_PATTERNS = [
    re.compile(r"\bwomen(?:'s|s)?\b", re.IGNORECASE),
    re.compile(r"\bwsl\b", re.IGNORECASE),
    re.compile(r"\buwcl\b", re.IGNORECASE),
    re.compile(r"\blionesses\b", re.IGNORECASE),
    re.compile(r"\bunder[\s-]?21s?\b", re.IGNORECASE),
    re.compile(r"\bu[\s-]?21s?\b", re.IGNORECASE),
    re.compile(r"\bunder[\s-]?(?:1[0-9]|2[0-3])s?\b", re.IGNORECASE),
    re.compile(r"\bu[\s-]?(?:1[0-9]|2[0-3])s?\b", re.IGNORECASE),
    re.compile(r"\bpl2\b", re.IGNORECASE),
    re.compile(r"\bpremier league 2\b", re.IGNORECASE),
    re.compile(r"\bacademy\b", re.IGNORECASE),
    re.compile(r"\bdevelopment squad\b", re.IGNORECASE),
    re.compile(r"\byouth team\b", re.IGNORECASE),
    re.compile(r"\bjunior\b", re.IGNORECASE),
    re.compile(r"\bretail\b", re.IGNORECASE),
    re.compile(r"\bclub shop\b", re.IGNORECASE),
    re.compile(r"\bshop\b", re.IGNORECASE),
    re.compile(r"\bstore\b", re.IGNORECASE),
    re.compile(r"\bmerch(?:andise)?\b", re.IGNORECASE),
    re.compile(r"\bseason tickets?\b", re.IGNORECASE),
    re.compile(r"\bmembership\b", re.IGNORECASE),
    re.compile(r"\bhospitality\b", re.IGNORECASE),
    re.compile(r"\bstadium tour\b", re.IGNORECASE),
    re.compile(r"\bavailable now\b", re.IGNORECASE),
    re.compile(r"/retail[-/]", re.IGNORECASE),
]
BYLINE_PATTERN = re.compile(
    r"^[A-Z][A-Za-z\s'-]+reporter\s*Published\s*\d+\s*hours?\s*ago\s*\d+\s*Comments\s*",
    re.IGNORECASE,
)

BBC_FOOTBALL_SOURCE = {
    "source_key": "bbc_football_rss",
    "source_name": "BBC Sport Football",
    "source_url": "https://feeds.bbci.co.uk/sport/football/rss.xml",
}

RSS_CONNECT_TIMEOUT = float(os.getenv("NEWS_RSS_CONNECT_TIMEOUT", "5"))
RSS_READ_TIMEOUT = float(os.getenv("NEWS_RSS_READ_TIMEOUT", "10"))
RSS_TIMEOUT = (RSS_CONNECT_TIMEOUT, RSS_READ_TIMEOUT)
RSS_MAX_ITEMS_CORE = int(os.getenv("NEWS_RSS_MAX_ITEMS_CORE", "12"))
RSS_MAX_ITEMS_CLUB = int(os.getenv("NEWS_RSS_MAX_ITEMS_CLUB", "6"))
NEWS_ENRICH_MAX_WORKERS = int(os.getenv("NEWS_ENRICH_MAX_WORKERS", "2"))
NEWS_ARTICLE_TIMEOUT = (float(os.getenv("NEWS_ARTICLE_CONNECT_TIMEOUT", "5")), float(os.getenv("NEWS_ARTICLE_READ_TIMEOUT", "10")))
NEWS_ARTICLE_MAX_BYTES = int(os.getenv("NEWS_ARTICLE_MAX_BYTES", str(1_200_000)))
NEWS_ARTICLE_CHUNK_SIZE = int(os.getenv("NEWS_ARTICLE_CHUNK_SIZE", str(64 * 1024)))

GUARDIAN_PREMIER_LEAGUE_SOURCE = {
    "source_key": "guardian_premier_league_rss",
    "source_name": "The Guardian Premier League",
    "source_url": "https://www.theguardian.com/football/premierleague/rss",
}

SKY_SPORTS_PREMIER_LEAGUE_SOURCE = {
    "source_key": "sky_sports_premier_league_rss",
    "source_name": "Sky Sports Premier League",
    "source_url": "https://www.skysports.com/rss/11661",
}

PREMIER_LEAGUE_CLUB_RSS_SOURCES = [
    {"source_key": "club_arsenal_rss", "source_name": "Arsenal", "source_url": "https://www.arsenal.com/rss.xml"},
    {"source_key": "club_aston_villa_rss", "source_name": "Aston Villa", "source_url": "https://www.avfc.co.uk/rss.xml"},
    {"source_key": "club_bournemouth_rss", "source_name": "Bournemouth", "source_url": "https://www.afcb.co.uk/rss.xml"},
    {"source_key": "club_brighton_rss", "source_name": "Brighton", "source_url": "https://www.brightonandhovealbion.com/rss"},
    {"source_key": "club_burnley_rss", "source_name": "Burnley", "source_url": "https://www.burnleyfootballclub.com/rss.xml"},
    {"source_key": "club_crystal_palace_rss", "source_name": "Crystal Palace", "source_url": "https://www.cpfc.co.uk/rss.xml"},
    {"source_key": "club_everton_rss", "source_name": "Everton", "source_url": "https://www.evertonfc.com/rss.xml"},
    {"source_key": "club_fulham_rss", "source_name": "Fulham", "source_url": "https://www.fulhamfc.com/rss.xml"},
    {"source_key": "club_manchester_united_rss", "source_name": "Manchester United", "source_url": "https://www.manutd.com/rss"},
    {"source_key": "club_nottingham_forest_rss", "source_name": "Nottingham Forest", "source_url": "https://www.nottinghamforest.co.uk/rss.xml"},
    {"source_key": "club_sunderland_rss", "source_name": "Sunderland", "source_url": "https://www.safc.com/rss.xml"},
    {"source_key": "club_wolves_rss", "source_name": "Wolves", "source_url": "https://www.wolves.co.uk/news/rss"},
]


def extract_tag_values(item_element):
    tags = []
    for category in item_element.findall("category"):
        value = (category.text or "").strip()
        if not value:
            value = (category.get("term") or "").strip()
        if value:
            tags.append(value)
    for category in item_element.findall("atom:category", RSS_NS):
        value = (category.get("term") or "").strip() or (category.text or "").strip()
        if value:
            tags.append(value)
    return tags


def element_text(element):
    if element is None:
        return ""
    text = "".join(element.itertext())
    return (text or "").strip()


def get_text_candidates(item_element, paths):
    values = []
    for path in paths:
        node = item_element.find(path, RSS_NS)
        if node is not None:
            raw = element_text(node)
            if raw:
                values.append(raw)
        direct = (item_element.findtext(path, default="", namespaces=RSS_NS) or "").strip()
        if direct:
            values.append(direct)
    return values


def normalize_text_candidate(value):
    return strip_html(value)


def extract_entry_link(item_element):
    direct_link = (item_element.findtext("link") or "").strip()
    if direct_link:
        return direct_link

    atom_link = item_element.find("atom:link", RSS_NS)
    if atom_link is None:
        atom_link = item_element.find("link")
    if atom_link is not None:
        href = (atom_link.get("href") or "").strip()
        if href:
            return href
    return ""


def extract_entry_author(item_element):
    candidates = get_text_candidates(
        item_element,
        [
            "author",
            "dc:creator",
            "{http://purl.org/dc/elements/1.1/}creator",
            "atom:author/atom:name",
            "author/name",
        ],
    )
    for candidate in candidates:
        normalized = normalize_text_candidate(candidate)
        if normalized:
            return normalized
    return None


def extract_summary_and_story(item_element):
    summary_candidates = get_text_candidates(
        item_element,
        [
            "description",
            "summary",
            "atom:summary",
            "media:description",
        ],
    )
    content_candidates = get_text_candidates(
        item_element,
        [
            "content:encoded",
            "{http://purl.org/rss/1.0/modules/content/}encoded",
            "content",
            "atom:content",
        ],
    )

    summary = None
    for candidate in summary_candidates:
        cleaned = normalize_text_candidate(candidate)
        if is_navigation_or_script_noise(cleaned):
            continue
        if cleaned:
            summary = cleaned
            break

    story = None
    for candidate in content_candidates:
        cleaned = normalize_text_candidate(candidate)
        if is_navigation_or_script_noise(cleaned):
            continue
        if cleaned:
            story = cleaned
            break

    if not summary and story:
        summary = story
    if summary and story and story == summary:
        story = None
    return summary or "", story


def extract_image_url(item_element):
    candidates = []
    for node in item_element.findall("media:content", MEDIA_NS):
        url = (node.get("url") or "").strip()
        if not url:
            continue
        width = node.get("width")
        try:
            width_value = int(width) if width else 0
        except (TypeError, ValueError):
            width_value = 0
        candidates.append((width_value, url))

    for node in item_element.findall("media:thumbnail", MEDIA_NS):
        url = (node.get("url") or "").strip()
        if not url:
            continue
        width = node.get("width")
        try:
            width_value = int(width) if width else 0
        except (TypeError, ValueError):
            width_value = 0
        candidates.append((width_value, url))

    enclosure = item_element.find("enclosure")
    if enclosure is not None and enclosure.get("type", "").startswith("image/") and enclosure.get("url"):
        candidates.append((0, enclosure.get("url").strip()))

    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates[0][1]


def clean_image_url(value, base_url):
    if not value:
        return None
    value = html.unescape(value).strip()
    if not value:
        return None
    return urljoin(base_url, value)


def upscale_image_url(url):
    if not url:
        return url

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    # Guardian/Source images often expose size via query params.
    if "guim.co.uk" in host or "guardian" in host:
        for key in ("width", "w", "fit"):
            if key in query:
                query.pop(key, None)
        query["width"] = "1200"
        query["quality"] = query.get("quality", "85")
        return urlunparse(parsed._replace(query=urlencode(query)))

    # Generic thumbnail path upsizing (e.g. .../300x200/... -> .../1200x800/...)
    bigger = re.sub(r"/(\d{2,4})x(\d{2,4})/", "/1200x800/", path)
    if bigger != path:
        return urlunparse(parsed._replace(path=bigger))

    return url


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


def is_navigation_or_script_noise(text):
    content = normalize_space(text)
    if not content:
        return True
    matches = sum(1 for pattern in NAV_NOISE_PATTERNS if pattern.search(content))
    return matches >= 2


def is_excluded_news_item(item):
    title = item.get("title") or ""
    summary = item.get("summary") or ""
    story = item.get("story") or ""
    article_url = item.get("article_url") or ""
    topic_tags = item.get("topic_tags") or []
    tags_text = " ".join(str(tag) for tag in topic_tags)
    corpus = " ".join([title, summary, story, article_url, tags_text])
    return any(pattern.search(corpus) for pattern in EXCLUDED_NEWS_PATTERNS)


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
    if is_navigation_or_script_noise(story):
        return None
    return story or None


def fetch_article_html(article_url, session):
    try:
        response = session.get(article_url, timeout=NEWS_ARTICLE_TIMEOUT, stream=True)
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and "text/html" not in content_type:
            response.close()
            return None, article_url
        body = bytearray()
        for chunk in response.iter_content(chunk_size=NEWS_ARTICLE_CHUNK_SIZE):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) >= NEWS_ARTICLE_MAX_BYTES:
                break
        response.close()
    except requests.RequestException:
        return None, article_url
    return body.decode(response.encoding or "utf-8", errors="ignore"), response.url


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
            if is_navigation_or_script_noise(paragraph):
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
        item["image_url"] = upscale_image_url(article_image_url)
    elif item.get("image_url"):
        item["image_url"] = upscale_image_url(item["image_url"])
    story = extract_article_story(
        body,
        title=item.get("title"),
        summary=item.get("summary"),
    )
    if story:
        item["story"] = story

    return item


def _build_rss_items(root, max_items=None):
    items = []

    entries = root.findall("./channel/item")
    if not entries:
        entries = root.findall("./item")
    if not entries:
        entries = root.findall("./{http://www.w3.org/2005/Atom}entry")
    if not entries:
        entries = root.findall("./entry")

    for entry in entries:
        summary, story = extract_summary_and_story(entry)
        title_candidates = get_text_candidates(entry, ["title", "atom:title"])
        published_candidates = get_text_candidates(
            entry,
            [
                "pubDate",
                "atom:published",
                "atom:updated",
                "updated",
                "dc:date",
            ],
        )
        title = ""
        for candidate in title_candidates:
            cleaned = normalize_text_candidate(candidate)
            if cleaned:
                title = cleaned
                break

        item = {
            "title": title,
            "summary": summary,
            "story": story,
            "article_url": extract_entry_link(entry),
            "image_url": upscale_image_url(extract_image_url(entry)),
            "published_at": published_candidates[0] if published_candidates else "",
            "author": extract_entry_author(entry),
            "language": "en",
            "topic_tags": extract_tag_values(entry),
        }
        if is_excluded_news_item(item):
            continue
        items.append(item)
        if max_items and len(items) >= max_items:
            break
    return items


def _fetch_rss_source(source_config, enrich=True, max_items=None):
    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
                )
            }
        )

        response = session.get(source_config["source_url"], timeout=RSS_TIMEOUT)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        items = _build_rss_items(root, max_items=max_items)

        if not enrich or not items:
            return source_config, items

        enriched_items = [None] * len(items)
        max_workers = max(1, min(NEWS_ENRICH_MAX_WORKERS, len(items)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(enrich_item_image, item, session): index
                for index, item in enumerate(items)
            }
            for future in as_completed(futures):
                enriched_items[futures[future]] = future.result()

        return source_config, enriched_items


def fetch_bbc_football_rss():
    return _fetch_rss_source(BBC_FOOTBALL_SOURCE, enrich=True, max_items=RSS_MAX_ITEMS_CORE)


def fetch_guardian_premier_league_rss():
    return _fetch_rss_source(GUARDIAN_PREMIER_LEAGUE_SOURCE, enrich=True, max_items=RSS_MAX_ITEMS_CORE)


def fetch_sky_sports_premier_league_rss():
    return _fetch_rss_source(SKY_SPORTS_PREMIER_LEAGUE_SOURCE, enrich=False, max_items=RSS_MAX_ITEMS_CORE)


def fetch_rss_source(source_config, enrich=False, max_items=None):
    return _fetch_rss_source(source_config, enrich=enrich, max_items=max_items)


def fetch_premier_league_club_rss_feeds():
    results = []
    for source_config in PREMIER_LEAGUE_CLUB_RSS_SOURCES:
        try:
            results.append(_fetch_rss_source(source_config, enrich=False, max_items=RSS_MAX_ITEMS_CLUB))
        except Exception:
            continue
    return results
