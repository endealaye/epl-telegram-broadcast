from broadcasts import broadcast_daily, broadcast_reminders, broadcast_results
from commands import broadcast_heartbeat, process_commands
from live import process_live_updates
from news_pipeline import fetch_news_items, get_review_queue, mark_review_item
from service_models import ServiceResult
from standings import broadcast_standings
from store import has_live_window_matches, has_matches_today, has_pending_results, has_upcoming_matches
from sync import update_fixtures_from_json


def sync_fixtures_service():
    success = update_fixtures_from_json()
    message = "Fixtures refreshed." if success else "Fixture refresh failed."
    return ServiceResult(action="refresh", success=success, message=message)


def process_admin_commands_service():
    process_commands()
    return ServiceResult(
        action="commands",
        success=True,
        message="Admin command polling completed.",
    )


def process_live_window_service():
    if not has_live_window_matches():
        return ServiceResult(
            action="live",
            success=True,
            skipped=True,
            message="Skip live: no fixtures in the active live window.",
        )
    process_live_updates()
    return ServiceResult(
        action="live",
        success=True,
        message="Live update processing completed.",
    )


def send_daily_broadcast_service():
    if not has_matches_today():
        return ServiceResult(
            action="daily",
            success=True,
            skipped=True,
            message="Skip daily: no fixtures scheduled today.",
        )
    broadcast_daily()
    return ServiceResult(
        action="daily",
        success=True,
        message="Daily broadcast processing completed.",
    )


def send_reminders_service():
    if not has_upcoming_matches():
        return ServiceResult(
            action="reminders",
            success=True,
            skipped=True,
            message="Skip reminders: no fixtures in the next 60 minutes.",
        )
    broadcast_reminders()
    return ServiceResult(
        action="reminders",
        success=True,
        message="Reminder broadcast processing completed.",
    )


def send_results_service():
    if not has_pending_results():
        return ServiceResult(
            action="results",
            success=True,
            skipped=True,
            message="Skip results: no completed fixtures awaiting a results post.",
        )
    broadcast_results()
    return ServiceResult(
        action="results",
        success=True,
        message="Results broadcast processing completed.",
    )


def send_standings_service(format_name=None):
    result = broadcast_standings(format_name=format_name)
    return ServiceResult(
        action="standings",
        success=result.get("success", False),
        skipped=result.get("skipped", False),
        message=result.get("message", ""),
        data=result.get("data", {}),
    )


def send_heartbeat_service(chat_id=None):
    success = broadcast_heartbeat(chat_id=chat_id)
    return ServiceResult(
        action="heartbeat",
        success=success,
        message="Heartbeat sent." if success else "Heartbeat failed.",
        data={"chat_id": chat_id} if chat_id else {},
    )


def fetch_news_service():
    try:
        result = fetch_news_items()
        return ServiceResult(
            action="news_fetch",
            success=True,
            message="News fetch completed.",
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="news_fetch",
            success=False,
            message=f"News fetch failed: {e}",
        )


def list_news_queue_service(limit=20):
    try:
        queue = get_review_queue(limit=limit)
        return ServiceResult(
            action="news_queue",
            success=True,
            message=f"Loaded {len(queue)} review items.",
            data={"items": queue, "count": len(queue)},
        )
    except Exception as e:
        return ServiceResult(
            action="news_queue",
            success=False,
            message=f"News queue load failed: {e}",
        )


def mark_news_item_service(
    item_id,
    status,
    translated_title_am=None,
    translated_story_am=None,
    notes=None,
):
    try:
        updated = mark_review_item(
            item_id=item_id,
            status=status,
            translated_title_am=translated_title_am,
            translated_story_am=translated_story_am,
            notes=notes,
        )
        success = updated is not None
        return ServiceResult(
            action="news_mark",
            success=success,
            message="News item published to Telegram." if success and status == "published" else "News item updated." if success else "News item update failed.",
            data={"item": updated} if updated else {},
        )
    except Exception as e:
        return ServiceResult(
            action="news_mark",
            success=False,
            message=f"News item update failed: {e}",
        )
