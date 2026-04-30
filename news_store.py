import hashlib
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from store import supabase


PREMIER_LEAGUE_CLUBS = {
    "arsenal": "club:arsenal",
    "aston villa": "club:aston_villa",
    "bournemouth": "club:bournemouth",
    "brentford": "club:brentford",
    "brighton": "club:brighton",
    "burnley": "club:burnley",
    "chelsea": "club:chelsea",
    "crystal palace": "club:crystal_palace",
    "everton": "club:everton",
    "fulham": "club:fulham",
    "leeds": "club:leeds",
    "liverpool": "club:liverpool",
    "man city": "club:man_city",
    "manchester city": "club:man_city",
    "man utd": "club:man_utd",
    "manchester united": "club:man_utd",
    "newcastle": "club:newcastle",
    "nott'm forest": "club:nottingham_forest",
    "nottingham forest": "club:nottingham_forest",
    "spurs": "club:spurs",
    "tottenham": "club:spurs",
    "sunderland": "club:sunderland",
    "west ham": "club:west_ham",
    "wolves": "club:wolves",
}

TOPIC_PATTERNS = {
    "topic:transfer": [r"\btransfer\b", r"\bsigning\b", r"\bdeal\b"],
    "topic:injury": [r"\binjury\b", r"\binjured\b", r"\brecovery\b"],
    "topic:manager": [r"\bmanager\b", r"\bcoach\b", r"\bsacked\b", r"\bappointment\b"],
    "topic:preview": [r"\bpreview\b", r"\blook ahead\b", r"\bteam news\b"],
    "topic:result": [r"\bresult\b", r"\bwin\b", r"\bdraw\b", r"\bloss\b", r"\brelegation\b"],
    "topic:official": [r"\bconfirmed\b", r"\bannounce\b", r"\bapproved\b"],
    "topic:gossip": [r"\bgossip\b", r"\blikely\b", r"\bmonitoring\b", r"\btarget\b"],
}

WOMENS_FOOTBALL_PATTERNS = [
    r"\bwomen('?s)?\b",
    r"\bwsl\b",
    r"\bwomen super league\b",
    r"\bwomen's super league\b",
    r"\blionesses\b",
    r"\bwomen'?s euros\b",
    r"\bwomen'?s champions league\b",
    r"\bbarclays wsl\b",
    r"\bmillie bright\b",
    r"\bjess fishlock\b",
]

INCLUDE_TERMS = [
    "premier league",
    *PREMIER_LEAGUE_CLUBS.keys(),
]

EXCLUDE_PATTERNS = [
    r"\bscottish\b",
    r"\bchampionship\b",
    r"\bleague one\b",
    r"\bleague two\b",
    r"\bpodcast\b",
    r"\bquiz\b",
    r"\bask me anything\b",
]

ALLOWED_REVIEW_STATUSES = {
    "filtered",
    "approved",
    "translated",
    "published",
    "rejected",
}

ALLOWED_STATUS_TRANSITIONS = {
    "filtered": {"filtered", "approved", "translated", "rejected"},
    "approved": {"approved", "translated", "published", "rejected"},
    "translated": {"translated", "approved", "published", "rejected"},
    "rejected": {"rejected", "filtered", "approved", "translated"},
    "published": {"published"},
}
MAX_SUMMARY_LENGTH = 500


def normalize_review_status(status):
    return (status or "").strip().lower()


def validate_review_status(status):
    normalized = normalize_review_status(status)
    if normalized not in ALLOWED_REVIEW_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_REVIEW_STATUSES))
        raise ValueError(f"Invalid review status '{status}'. Allowed values: {allowed}.")
    return normalized


def validate_status_transition(current_status, target_status):
    current = normalize_review_status(current_status)
    target = validate_review_status(target_status)
    if not current:
        return target
    allowed_targets = ALLOWED_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed_targets:
        raise ValueError(f"Invalid status transition: '{current_status}' -> '{target_status}'.")
    return target


def parse_rss_datetime(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError):
        return None


def build_content_hash(source_key, article_url):
    raw = f"{source_key}|{article_url}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_news_haystack(title, summary, story=None):
    return f"{title or ''} {summary or ''} {story or ''}".lower()


def derive_topic_tags(title, summary, story=None):
    haystack = build_news_haystack(title, summary, story)
    tags = set()

    if "premier league" in haystack:
        tags.add("competition:premier_league")

    for term, tag in PREMIER_LEAGUE_CLUBS.items():
        if term in haystack:
            tags.add(tag)

    for tag, patterns in TOPIC_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, haystack):
                tags.add(tag)
                break

    return sorted(tags)


def should_include_item(title, summary, article_url, story=None):
    haystack = build_news_haystack(title, summary, story)
    article_url = (article_url or "").lower()

    if "/videos/" in article_url:
        return False

    if any(re.search(pattern, haystack) for pattern in WOMENS_FOOTBALL_PATTERNS):
        return False

    if any(re.search(pattern, haystack) for pattern in EXCLUDE_PATTERNS):
        return False

    return any(term in haystack for term in INCLUDE_TERMS)


def compute_relevance_score(title, summary, topic_tags, story=None):
    haystack = build_news_haystack(title, summary, story)
    score = 0
    if "competition:premier_league" in topic_tags:
        score += 5
    score += sum(3 for tag in topic_tags if tag.startswith("club:"))
    score += sum(2 for tag in topic_tags if tag.startswith("topic:") and tag != "topic:gossip")
    if "topic:gossip" in topic_tags:
        score += 1
    if "breaking" in haystack:
        score += 2
    return score


def sanitize_copy_text(value):
    raw = html.unescape(value or "")
    if not raw:
        return ""
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = raw.replace("\xa0", " ")
    return re.sub(r"\s+", " ", raw).strip()


def normalize_summary(summary, story):
    cleaned_summary = sanitize_copy_text(summary)
    if not cleaned_summary:
        cleaned_summary = sanitize_copy_text(story)
    if len(cleaned_summary) > MAX_SUMMARY_LENGTH:
        trimmed = cleaned_summary[:MAX_SUMMARY_LENGTH].rsplit(" ", 1)[0].strip()
        cleaned_summary = f"{trimmed}…" if trimmed else cleaned_summary[:MAX_SUMMARY_LENGTH]
    return cleaned_summary


def normalize_news_item(source_key, source_name, source_url, item):
    article_url = (item.get("article_url") or "").strip()
    raw_summary = item.get("summary") or ""
    raw_story = item.get("story") or raw_summary
    summary = normalize_summary(raw_summary, raw_story)
    story = sanitize_copy_text(raw_story) or summary
    title = sanitize_copy_text(item.get("title") or "")
    derived_tags = derive_topic_tags(title, summary, story)
    review_status = "filtered" if should_include_item(title, summary, article_url, story) else "rejected"
    return {
        "source_key": source_key,
        "source_name": source_name,
        "source_url": source_url,
        "article_url": article_url,
        "image_url": item.get("image_url"),
        "title": title,
        "summary": summary,
        "story": story,
        "author": item.get("author"),
        "published_at": parse_rss_datetime(item.get("published_at")),
        "language": item.get("language", "en"),
        "topic_tags": derived_tags,
        "review_status": review_status,
        "relevance_score": compute_relevance_score(title, summary, derived_tags, story),
        "cluster_key": item.get("cluster_key"),
        "translated_title_am": None,
        "translated_story_am": None,
        "notes": None,
        "content_hash": build_content_hash(source_key, article_url),
        "raw_payload": item,
    }


def upsert_news_items(items):
    if not supabase or not items:
        return []
    res = supabase.table("news_items").upsert(items, on_conflict="content_hash").execute()
    return res.data or []


def list_news_queue(statuses=None, limit=20):
    if not supabase:
        return []
    query = supabase.table("news_items").select(
        "id,source_name,title,summary,story,article_url,image_url,published_at,review_status,relevance_score,"
        "topic_tags,translated_title_am,translated_story_am,notes"
    ).order("published_at", desc=True).limit(limit)
    if statuses:
        query = query.in_("review_status", statuses)
    res = query.execute()
    return res.data or []


def get_news_item(item_id):
    if not supabase:
        return None
    res = supabase.table("news_items").select(
        "id,source_name,source_url,article_url,image_url,title,summary,story,author,published_at,review_status,"
        "relevance_score,topic_tags,translated_title_am,translated_story_am,notes"
    ).eq("id", item_id).limit(1).execute()
    rows = res.data or []
    return rows[0] if rows else None


def mark_news_item(
    item_id,
    status,
    translated_title_am=None,
    translated_story_am=None,
    notes=None,
):
    if not supabase:
        return None

    status = validate_review_status(status)
    current_item = get_news_item(item_id)
    if not current_item:
        return None
    status = validate_status_transition(current_item.get("review_status"), status)

    payload = {
        "review_status": status,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    if translated_title_am is not None:
        payload["translated_title_am"] = translated_title_am
    if translated_story_am is not None:
        payload["translated_story_am"] = translated_story_am
    if notes is not None:
        payload["notes"] = notes

    res = supabase.table("news_items").update(payload).eq("id", item_id).execute()
    rows = res.data or []
    return rows[0] if rows else None


def delete_news_item(item_id):
    if not supabase:
        return False

    res = supabase.table("news_items").delete().eq("id", item_id).execute()
    return bool(res.data)
