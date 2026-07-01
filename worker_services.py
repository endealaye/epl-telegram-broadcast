from broadcasts import broadcast_daily, broadcast_reminders, broadcast_results
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


def refresh_world_cup_standings_service():
    try:
        result = refresh_world_cup_group_standings()
        return ServiceResult(
            action="world_cup_standings",
            success=True,
            message=(
                f"World Cup standings refreshed for {result.get('groups', 0)} groups "
                f"and {result.get('teams', 0)} teams."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_standings",
            success=False,
            message=f"World Cup standings refresh failed: {e}",
        )


def refresh_world_cup_players_service():
    try:
        result = refresh_world_cup_players()
        verification = result.get("verification") or {}
        return ServiceResult(
            action="world_cup_players",
            success=True,
            message=(
                f"World Cup players refreshed: {result.get('persisted', 0)} persisted "
                f"from {result.get('teams_found', 0)} teams; "
                f"{verification.get('confirmed', 0)} confirmed by Sky."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_players",
            success=False,
            message=f"World Cup players refresh failed: {e}",
        )


def refresh_world_cup_bbc_squads_service():
    try:
        result = refresh_world_cup_players_with_bbc()
        return ServiceResult(
            action="world_cup_bbc_squads",
            success=True,
            message=(
                f"BBC squads refreshed: {result.get('confirmed_players', 0)} players confirmed, "
                f"{result.get('inserted_players', 0)} inserted, "
                f"{result.get('teams_confirmed', 0)} teams confirmed, "
                f"{result.get('availability_rows', 0)} availability rows added."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_bbc_squads",
            success=False,
            message=f"BBC squad refresh failed: {e}",
        )


def refresh_world_cup_coaches_service():
    try:
        result = update_world_cup_coaches()
        return ServiceResult(
            action="world_cup_coaches",
            success=True,
            message=(
                f"World Cup coaches refreshed: {result.get('updated', 0)} teams updated "
                f"({'columns' if result.get('columns_updated') else 'raw payload'})."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_coaches",
            success=False,
            message=f"World Cup coaches refresh failed: {e}",
        )


def refresh_world_cup_form_service():
    try:
        result = refresh_world_cup_qualifier_form()
        return ServiceResult(
            action="world_cup_form",
            success=True,
            message=(
                f"World Cup qualifier form refreshed: {result.get('persisted', 0)} rows "
                f"for {result.get('teams_with_rows', 0)} teams."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_form",
            success=False,
            message=f"World Cup qualifier form refresh failed: {e}",
        )


def audit_world_cup_squads_service():
    try:
        result = audit_world_cup_squads(update_metadata=True)
        return ServiceResult(
            action="world_cup_squad_audit",
            success=True,
            message=(
                f"World Cup squad audit: {result.get('local_total_players', 0)}/"
                f"{result.get('expected_total_players', 0)} players; "
                f"{len(result.get('incomplete_teams', {}))} incomplete teams."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_squad_audit",
            success=False,
            message=f"World Cup squad audit failed: {e}",
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
