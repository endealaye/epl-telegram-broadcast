import hashlib
import html
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from store import get_bot_state_value, set_bot_state_value, supabase


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

MATCH_CLASSIFICATION_PATTERNS = {
    "lineup_update": [
        r"\bstarting xi\b",
        r"\bstarting line-?up\b",
        r"\bline-?ups?\b",
        r"\bxi confirmed\b",
    ],
    "pre_match": [
        r"\bpreview\b",
        r"\bpredicted line-?up\b",
        r"\bprediction\b",
        r"\blook ahead\b",
        r"\bclash\b",
        r"\bvs\b",
        r"\bteam news\b",
    ],
    "post_match": [
        r"\bmatch report\b",
        r"\breport\b",
        r"\bhighlights\b",
        r"\bfull[- ]time\b",
        r"\bresult\b",
        r"\bwins?\b",
        r"\bdraw\b",
        r"\bloses?\b",
    ],
}

PREDICTION_PATTERNS = [
    re.compile(r"((?:prediction|predicts?|predicted)\s*[:\-]?\s*[^.?!]+)", re.IGNORECASE),
    re.compile(r"([A-Z][A-Za-z'&.\- ]+\s+\d+\s*[-–]\s*\d+\s+[A-Z][A-Za-z'&.\- ]+)", re.IGNORECASE),
]

SCORELINE_PATTERN = re.compile(
    r"([A-Z][A-Za-z'&.\- ]+?)\s+(\d+)\s*[-–]\s*(\d+)\s+([A-Z][A-Za-z'&.\- ]+)"
)
SCORER_MINUTE_PATTERNS = [
    re.compile(r"([A-Z][A-Za-z'’.\-]+(?:\s+[A-Z][A-Za-z'’.\-]+)?)\s*\((\d{1,3}(?:\+\d{1,2})?)\)"),
    re.compile(r"([A-Z][A-Za-z'’.\-]+(?:\s+[A-Z][A-Za-z'’.\-]+)?)\s+(?:scored|netted|struck)\s+(?:in\s+)?the\s+(\d{1,3})(?:st|nd|rd|th)?\s+minute", re.IGNORECASE),
]
INJURY_SENTENCE_PATTERN = re.compile(
    r"([^.!?]*(?:injur(?:y|ed)|forced off|stretchered off|substituted with an injury)[^.!?]*[.!?]?)",
    re.IGNORECASE,
)

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
    "filtered": {"filtered", "approved", "translated", "published", "rejected"},
    "approved": {"approved", "translated", "published", "rejected"},
    "translated": {"translated", "approved", "published", "rejected"},
    "rejected": {"rejected", "filtered", "approved", "translated"},
    "published": {"published"},
}
MAX_SUMMARY_LENGTH = 500
USER_HIDDEN_NOTE_PREFIX = "hidden_by_user:"
TITLE_DEDUPE_WINDOW_DAYS = 14
FOLLOW_UPS_STATE_KEY = "news_followups"


def _safe_execute(query, default=None, context="news_store"):
    try:
        return query.execute()
    except Exception as exc:
        print(f"News store query failed ({context}): {exc}")
        return default


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


def is_user_hidden(notes):
    return USER_HIDDEN_NOTE_PREFIX in ((notes or "").strip().lower())


def append_note_marker(notes, marker):
    base_notes = (notes or "").strip()
    if marker in base_notes:
        return base_notes
    if not base_notes:
        return marker
    return f"{base_notes} | {marker}"


def normalize_title_key(title):
    normalized = sanitize_copy_text(title or "").lower()
    normalized = re.sub(r"[^a-z0-9\s]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def build_source_title_key(source_name, title):
    source = (source_name or "").strip().lower()
    title_key = normalize_title_key(title)
    if not source or not title_key:
        return ""
    return f"{source}|{title_key}"


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


def derive_topic_tags(title, summary, story=None, image_url=None):
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

    match_metadata = extract_match_metadata(title, summary, story, image_url=image_url)
    match_type = match_metadata.get("match_type")
    if match_type and match_type != "other":
        tags.add(f"format:{match_type}")
    if match_metadata.get("has_lineup_image"):
        tags.add("fact:lineup_image")
    if match_metadata.get("final_score"):
        tags.add("fact:final_score")
    if match_metadata.get("scorers"):
        tags.add("fact:scorers")
    if match_metadata.get("injury_update"):
        tags.add("fact:injury_update")

    return sorted(tags)


def _extract_sentence_match(text, patterns):
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        for pattern in patterns:
            match = pattern.search(sentence)
            if match:
                return sanitize_copy_text(match.group(1))
    return None


def _extract_scoreline(text):
    match = SCORELINE_PATTERN.search(text or "")
    if not match:
        return None
    home, home_score, away_score, away = match.groups()
    away = re.sub(r"\b(match report|report|highlights|live|preview)\b.*$", "", away, flags=re.IGNORECASE).strip(" -:")
    return {
        "home": sanitize_copy_text(home),
        "home_score": int(home_score),
        "away_score": int(away_score),
        "away": sanitize_copy_text(away),
    }


def _extract_scorers(text):
    scorers = []
    seen = set()
    for pattern in SCORER_MINUTE_PATTERNS:
        for match in pattern.finditer(text or ""):
            scorer = sanitize_copy_text(match.group(1))
            minute = sanitize_copy_text(match.group(2))
            key = (scorer.lower(), minute)
            if not scorer or key in seen:
                continue
            seen.add(key)
            scorers.append({"player": scorer, "minute": minute})
    return scorers[:8]


def _classify_match_type(title, summary, story, image_url=None):
    title_text = title or ""
    summary_text = summary or ""
    story_text = story or ""
    text = " ".join([title_text, summary_text, story_text])
    if (
        image_url
        and any(re.search(pattern, title_text, re.IGNORECASE) for pattern in MATCH_CLASSIFICATION_PATTERNS["lineup_update"])
    ):
        return "lineup_update"
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in MATCH_CLASSIFICATION_PATTERNS["pre_match"]):
        return "pre_match"
    if _extract_scoreline(title_text) or _extract_scoreline(story_text):
        return "post_match"
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in MATCH_CLASSIFICATION_PATTERNS["post_match"]):
        return "post_match"
    return "other"


def extract_match_metadata(title, summary, story=None, image_url=None):
    text = " ".join([title or "", summary or "", story or ""]).strip()
    match_type = _classify_match_type(title, summary, story, image_url=image_url)
    prediction = None
    if match_type == "pre_match":
        prediction = (
            _extract_sentence_match(summary or "", PREDICTION_PATTERNS)
            or _extract_sentence_match(story or "", PREDICTION_PATTERNS)
            or _extract_sentence_match(title or "", PREDICTION_PATTERNS)
        )
    final_score = None
    if match_type == "post_match":
        final_score = _extract_scoreline(title or "") or _extract_scoreline(story or "") or _extract_scoreline(summary or "")
    scorers = _extract_scorers(text) if match_type == "post_match" else []
    injury_match = INJURY_SENTENCE_PATTERN.search(text)
    injury_update = sanitize_copy_text(injury_match.group(1)) if injury_match else None
    return {
        "match_type": match_type,
        "prediction": prediction,
        "has_lineup_image": bool(image_url) and match_type == "lineup_update",
        "final_score": final_score,
        "scorers": scorers,
        "injury_update": injury_update,
    }


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
    if any(tag.startswith("format:") for tag in topic_tags):
        score += 2
    if "fact:scorers" in topic_tags or "fact:lineup_image" in topic_tags:
        score += 1
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
    match_metadata = extract_match_metadata(title, summary, story, image_url=item.get("image_url"))
    derived_tags = derive_topic_tags(title, summary, story, image_url=item.get("image_url"))
    review_status = "filtered" if should_include_item(title, summary, article_url, story) else "rejected"
    raw_payload = dict(item or {})
    raw_payload["match_metadata"] = match_metadata
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
        "raw_payload": raw_payload,
    }


def upsert_news_items(items):
    if not supabase or not items:
        return []
    res = _safe_execute(
        supabase.table("news_items").upsert(items, on_conflict="content_hash"),
        default=None,
        context="upsert_news_items",
    )
    if res is None:
        return []
    return res.data or []


def get_news_items_by_content_hashes(content_hashes):
    if not supabase or not content_hashes:
        return {}

    rows = []
    batch_size = 200
    hashes = list(content_hashes)
    for start in range(0, len(hashes), batch_size):
        batch = hashes[start:start + batch_size]
        res = _safe_execute(
            supabase.table("news_items").select(
                "id,content_hash,review_status,notes"
            ).in_("content_hash", batch),
            default=None,
            context="get_news_items_by_content_hashes",
        )
        if res and res.data:
            rows.extend(res.data)

    return {
        row["content_hash"]: row
        for row in rows
        if row.get("content_hash")
    }


def get_news_items_by_article_urls(article_urls):
    if not supabase or not article_urls:
        return {}

    rows = []
    batch_size = 100
    urls = [url for url in article_urls if url]
    for start in range(0, len(urls), batch_size):
        batch = urls[start:start + batch_size]
        res = _safe_execute(
            supabase.table("news_items").select(
                "id,article_url,review_status,notes"
            ).in_("article_url", batch),
            default=None,
            context="get_news_items_by_article_urls",
        )
        if res and res.data:
            rows.extend(res.data)

    return {
        row["article_url"]: row
        for row in rows
        if row.get("article_url")
    }


def get_existing_news_items_for_sources(source_names, days_back=TITLE_DEDUPE_WINDOW_DAYS):
    if not supabase or not source_names:
        return []

    rows = []
    batch_size = 20
    names = sorted({name for name in source_names if name})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days_back)))).isoformat()
    for start in range(0, len(names), batch_size):
        batch = names[start:start + batch_size]
        res = _safe_execute(
            supabase.table("news_items").select(
                "id,source_name,title,review_status,notes,fetched_at,published_at"
            ).in_("source_name", batch).gte("fetched_at", cutoff),
            default=None,
            context="get_existing_news_items_for_sources",
        )
        if res and res.data:
            rows.extend(res.data)
    return rows


def list_news_queue(statuses=None, limit=20):
    if not supabase:
        return []
    query = supabase.table("news_items").select(
        "id,source_name,title,summary,story,article_url,image_url,published_at,review_status,relevance_score,"
        "topic_tags,translated_title_am,translated_story_am,notes,raw_payload"
    ).order("published_at", desc=True).limit(limit)
    if statuses:
        query = query.in_("review_status", statuses)
    res = _safe_execute(query, default=None, context="list_news_queue")
    if res is None:
        return []
    return res.data or []


def list_news_queue_preview(statuses=None, limit=20):
    if not supabase:
        return []
    query = supabase.table("news_items").select(
        "id,source_name,title,summary,article_url,image_url,published_at,review_status,relevance_score,"
        "topic_tags,translated_title_am,notes"
    ).order("published_at", desc=True).limit(limit)
    if statuses:
        query = query.in_("review_status", statuses)
    res = _safe_execute(query, default=None, context="list_news_queue_preview")
    if res is None:
        return []
    return res.data or []


def get_news_item(item_id):
    if not supabase:
        return None
    res = _safe_execute(
        supabase.table("news_items").select(
            "id,source_name,source_url,article_url,image_url,title,summary,story,author,published_at,review_status,"
            "relevance_score,topic_tags,translated_title_am,translated_story_am,notes,raw_payload"
        ).eq("id", item_id).limit(1),
        default=None,
        context=f"get_news_item:{item_id}",
    )
    if res is None:
        return None
    rows = res.data or []
    return rows[0] if rows else None


def mark_news_item(
    item_id,
    status,
    translated_title_am=None,
    translated_story_am=None,
    notes=None,
    image_url=None,
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
    if status == "published":
        posted_stamp = f"posted_to_telegram:{datetime.now(timezone.utc).isoformat()}"
        base_notes = payload.get("notes")
        if base_notes is None:
            base_notes = current_item.get("notes")
        base_notes = (base_notes or "").strip()
        if "posted_to_telegram:" not in base_notes:
            payload["notes"] = f"{base_notes} | {posted_stamp}".strip(" |")
    if image_url is not None:
        payload["image_url"] = image_url

    res = _safe_execute(
        supabase.table("news_items").update(payload).eq("id", item_id),
        default=None,
        context=f"mark_news_item:{item_id}",
    )
    if res is None:
        return None
    rows = res.data or []
    return rows[0] if rows else None


def delete_news_item(item_id):
    current_item = get_news_item(item_id)
    if not current_item:
        return False

    hidden_stamp = f"{USER_HIDDEN_NOTE_PREFIX}{datetime.now(timezone.utc).isoformat()}"
    notes = append_note_marker(current_item.get("notes"), hidden_stamp)
    res = _safe_execute(
        supabase.table("news_items").update(
            {
                "review_status": "rejected",
                "notes": notes,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", item_id),
        default=None,
        context=f"delete_news_item:{item_id}",
    )
    if res is None:
        return False
    return bool(res.data)


def _load_follow_up_requests():
    raw_value = get_bot_state_value(FOLLOW_UPS_STATE_KEY)
    if not raw_value:
        return []
    try:
        payload = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    normalized = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        request_id = (item.get("id") or "").strip()
        if not request_id:
            continue
        normalized.append(
            {
                "id": request_id,
                "subject": (item.get("subject") or "").strip(),
                "target_name": (item.get("target_name") or "").strip(),
                "request_type": (item.get("request_type") or "general_follow_up").strip(),
                "details": (item.get("details") or "").strip(),
                "linked_item_id": item.get("linked_item_id"),
                "status": (item.get("status") or "active").strip(),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )
    return normalized


def _save_follow_up_requests(items):
    return set_bot_state_value(FOLLOW_UPS_STATE_KEY, json.dumps(items))


def list_follow_up_requests(status=None):
    items = _load_follow_up_requests()
    items.sort(key=lambda row: ((row.get("status") != "active"), row.get("updated_at") or "", row.get("created_at") or ""), reverse=True)
    if status:
        return [item for item in items if item.get("status") == status]
    return items


def create_follow_up_request(subject, request_type="general_follow_up", target_name=None, details=None, linked_item_id=None):
    cleaned_subject = (subject or "").strip()
    if not cleaned_subject:
        raise ValueError("Follow-up subject is required.")

    now = datetime.now(timezone.utc).isoformat()
    items = _load_follow_up_requests()
    items.append(
        {
            "id": str(uuid.uuid4()),
            "subject": cleaned_subject,
            "target_name": (target_name or "").strip(),
            "request_type": (request_type or "general_follow_up").strip(),
            "details": (details or "").strip(),
            "linked_item_id": int(linked_item_id) if linked_item_id else None,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
    )
    _save_follow_up_requests(items)
    return items[-1]


def update_follow_up_request(request_id, *, status=None, delete=False):
    items = _load_follow_up_requests()
    updated = None
    kept = []
    for item in items:
        if item.get("id") != request_id:
            kept.append(item)
            continue
        if delete:
            updated = item
            continue
        if status:
            item["status"] = status.strip()
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        kept.append(item)
        updated = item
    if updated is None:
        return None
    _save_follow_up_requests(kept)
    return updated
