from broadcasts import broadcast_daily, broadcast_reminders, broadcast_results, maybe_send_auto_standings, reconcile_post_match_delivery
from commands import broadcast_heartbeat, process_commands
from live import process_live_updates
from news_pipeline import fetch_news_items, get_review_queue, mark_review_item
from posting_policy import build_policy_summary, classify_match_day, should_run_live, should_send_daily, should_send_reminders
from service_models import ServiceResult
from standings import broadcast_standings
from store import fetch_fixtures_for_dates, has_live_window_matches, has_matches_today, has_pending_results, has_upcoming_matches
from bot_config import get_eat_today
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
    try:
        policy = classify_match_day()
        if not should_run_live(policy):
            return ServiceResult(
                action="live",
                success=True,
                skipped=True,
                message=f"Skip live: {build_policy_summary(policy)}",
                data={"policy": policy},
            )
        process_live_updates()
        return ServiceResult(
            action="live",
            success=True,
            message="Live update processing completed.",
            data={"policy": policy},
        )
    except Exception as e:
        return ServiceResult(
            action="live",
            success=False,
            message=f"Live update processing failed: {e}",
        )


def send_daily_broadcast_service():
    try:
        policy = classify_match_day()
        if not should_send_daily(policy):
            return ServiceResult(
                action="daily",
                success=True,
                skipped=True,
                message=f"Skip daily: {build_policy_summary(policy)}",
                data={"policy": policy},
            )
        broadcast_daily()
        return ServiceResult(
            action="daily",
            success=True,
            message="Daily broadcast processing completed.",
            data={"policy": policy},
        )
    except Exception as e:
        return ServiceResult(
            action="daily",
            success=False,
            message=f"Daily broadcast processing failed: {e}",
        )


def send_reminders_service():
    try:
        policy = classify_match_day()
        if not should_send_reminders(policy):
            return ServiceResult(
                action="reminders",
                success=True,
                skipped=True,
                message=f"Skip reminders: {build_policy_summary(policy)}",
                data={"policy": policy},
            )
        broadcast_reminders()
        return ServiceResult(
            action="reminders",
            success=True,
            message="Reminder broadcast processing completed.",
            data={"policy": policy},
        )
    except Exception as e:
        return ServiceResult(
            action="reminders",
            success=False,
            message=f"Reminder broadcast processing failed: {e}",
        )


def send_results_service():
    try:
        reconciliation = reconcile_post_match_delivery()
        if reconciliation.get("results_sent_dates") or reconciliation.get("standings_sent_dates"):
            return ServiceResult(
                action="results",
                success=True,
                message="Post-match reconciliation completed.",
                data=reconciliation,
            )

        if not has_pending_results():
            today = get_eat_today()
            retry_result = maybe_send_auto_standings(fetch_fixtures_for_dates([today]), today=today)
            if retry_result.get("sent"):
                return ServiceResult(
                    action="results",
                    success=True,
                    message="No new results, but standings retry was sent.",
                    data={"standings_retry": retry_result},
                )
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
    except Exception as e:
        return ServiceResult(
            action="results",
            success=False,
            message=f"Results broadcast processing failed: {e}",
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
