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
from world_cup_analysis import generate_group_stage_previews, list_analysis_queue, mark_analysis_preview
from world_cup_form import refresh_world_cup_qualifier_form
from world_cup_players import refresh_world_cup_players
from world_cup_squad_audit import audit_world_cup_squads
from world_cup_standings import refresh_world_cup_group_standings


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


def generate_world_cup_analysis_service():
    try:
        result = generate_group_stage_previews()
        return ServiceResult(
            action="world_cup_analysis",
            success=True,
            message=(
                f"World Cup analysis generated {result.get('generated', 0)} draft previews "
                f"from {result.get('fixtures', 0)} group fixtures."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_analysis",
            success=False,
            message=f"World Cup analysis generation failed: {e}",
        )


def list_world_cup_analysis_queue_service(limit=20, status="draft"):
    try:
        items = list_analysis_queue(limit=limit, status=status)
        return ServiceResult(
            action="world_cup_analysis_queue",
            success=True,
            message=f"Loaded {len(items)} {status} World Cup previews.",
            data={"items": items, "count": len(items), "status": status},
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_analysis_queue",
            success=False,
            message=f"World Cup analysis queue failed: {e}",
        )


def mark_world_cup_analysis_service(matchnumber, status):
    try:
        updated = mark_analysis_preview(matchnumber, status)
        return ServiceResult(
            action="world_cup_analysis_mark",
            success=updated is not None,
            message=(
                f"Preview {matchnumber} marked {status}."
                if updated
                else f"Preview {matchnumber} not found."
            ),
            data={"item": updated} if updated else {},
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_analysis_mark",
            success=False,
            message=f"World Cup analysis mark failed: {e}",
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
