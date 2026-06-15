from datetime import datetime, timezone

from commands import send_telegram_message
from store import supabase


VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_REVIEW_STATUSES = {"draft", "published", "rejected"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _message_id(sent_message):
    if not isinstance(sent_message, dict):
        return None
    message_id = sent_message.get("message_id")
    return int(message_id) if message_id is not None else None


def get_match_prediction(matchnumber, language="am"):
    if not supabase:
        return None
    res = (
        supabase.table("match_predictions")
        .select("*")
        .eq("matchnumber", int(matchnumber))
        .eq("language", language)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def save_match_prediction(
    matchnumber,
    predicted_home_score,
    predicted_away_score,
    prediction_text,
    confidence="medium",
    source_context=None,
    language="am",
):
    if confidence not in VALID_CONFIDENCE:
        raise ValueError(f"Invalid prediction confidence: {confidence}")
    if not prediction_text or not prediction_text.strip():
        raise ValueError("Prediction text is required.")
    if not supabase:
        return None

    now = _now_iso()
    row = {
        "matchnumber": int(matchnumber),
        "language": language,
        "predicted_home_score": int(predicted_home_score),
        "predicted_away_score": int(predicted_away_score),
        "prediction_text": prediction_text.strip(),
        "confidence": confidence,
        "source_context": source_context or {},
        "review_status": "draft",
        "updated_at": now,
    }
    res = (
        supabase.table("match_predictions")
        .upsert(row, on_conflict="matchnumber,language")
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else get_match_prediction(matchnumber, language=language)


def mark_match_prediction(matchnumber, status, language="am", published_message_id=None):
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"Invalid prediction status: {status}")
    if not supabase:
        return None

    payload = {"review_status": status, "updated_at": _now_iso()}
    if published_message_id is not None:
        payload["published_message_id"] = int(published_message_id)
    res = (
        supabase.table("match_predictions")
        .update(payload)
        .eq("matchnumber", int(matchnumber))
        .eq("language", language)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def publish_match_prediction(matchnumber, language="am"):
    item = get_match_prediction(matchnumber, language=language)
    if not item:
        raise ValueError(f"Prediction {matchnumber} not found.")
    if item.get("review_status") == "published":
        return {"sent": False, "skipped": True, "item": item, "reason": "already_published"}

    sent_message = send_telegram_message(item["prediction_text"], return_message=True)
    if not sent_message:
        raise RuntimeError("Telegram delivery failed. Check bot configuration.")

    updated = mark_match_prediction(
        matchnumber,
        "published",
        language=language,
        published_message_id=_message_id(sent_message),
    )
    return {"sent": True, "skipped": False, "item": updated or item}
