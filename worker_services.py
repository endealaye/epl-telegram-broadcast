from broadcasts import broadcast_daily, broadcast_reminders, broadcast_results, maybe_send_auto_standings, reconcile_post_match_delivery
from commands import broadcast_heartbeat, process_commands
from live import process_live_updates
from match_predictions import publish_match_prediction, save_match_prediction
from news_pipeline import fetch_news_items, get_review_queue, mark_review_item
from posting_policy import build_policy_summary, classify_match_day, should_run_live, should_send_daily, should_send_reminders
from service_models import ServiceResult
from standings import broadcast_standings
from store import fetch_fixtures_for_dates, has_live_window_matches, has_matches_today, has_pending_results, has_upcoming_matches
from bot_config import get_eat_today
from sync import update_fixtures_from_json
from world_cup_analysis import (
    generate_group_stage_previews,
    list_analysis_queue,
    mark_analysis_preview,
    publish_due_analysis,
    send_analysis_review_reminder,
)
from world_cup_facts import publish_daily_world_cup_fact, seed_world_cup_facts
from world_cup_form import refresh_world_cup_qualifier_form
from world_cup_coaches import update_world_cup_coaches
try:
    from world_cup_players import refresh_world_cup_players, refresh_world_cup_players_with_bbc
except ImportError as e:
    print(f"DEBUG: Failed to import players functions from world_cup_players: {e}")
    # Define dummy functions to allow the rest of the script to run for diagnostics
    def refresh_world_cup_players(*args, **kwargs):
        print("DEBUG: Dummy refresh_world_cup_players called.")
        return {"error": f"ImportError: {e}"}
    def refresh_world_cup_players_with_bbc(*args, **kwargs):
        print("DEBUG: Dummy refresh_world_cup_players_with_bbc called.")
        return {"error": f"ImportError: {e}"}
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


def seed_world_cup_facts_service():
    try:
        result = seed_world_cup_facts()
        return ServiceResult(
            action="world_cup_facts_seed",
            success=True,
            message=f"World Cup fact queue seeded with {result.get('total', 0)} facts.",
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_facts_seed",
            success=False,
            message=f"World Cup fact seeding failed: {e}",
        )


def publish_world_cup_fact_service():
    try:
        result = publish_daily_world_cup_fact()
        return ServiceResult(
            action="world_cup_fact",
            success=True,
            skipped=result.get("skipped", False),
            message=(
                f"World Cup fact sent: {result.get('fact_id')}."
                if result.get("sent")
                else f"World Cup fact skipped: {result.get('reason', 'no_fact_sent')}."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_fact",
            success=False,
            message=f"World Cup fact publish failed: {e}",
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


def remind_world_cup_analysis_review_service():
    try:
        result = send_analysis_review_reminder()
        return ServiceResult(
            action="world_cup_analysis_review_reminder",
            success=True,
            skipped=result.get("skipped", False) or not result.get("sent", False),
            message=(
                f"World Cup analysis review reminder sent for {result.get('count', 0)} previews."
                if result.get("sent")
                else f"No new World Cup analysis review reminder sent; {result.get('count', 0)} previews pending."
            ),
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_analysis_review_reminder",
            success=False,
            message=f"World Cup analysis review reminder failed: {e}",
        )


def publish_world_cup_analysis_service():
    try:
        result = publish_due_analysis()
        return ServiceResult(
            action="world_cup_analysis_publish",
            success=True,
            skipped=result.get("published", 0) == 0,
            message=f"World Cup analysis published {result.get('published', 0)} approved previews.",
            data=result,
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_analysis_publish",
            success=False,
            message=f"World Cup analysis publish failed: {e}",
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


def save_world_cup_prediction_service(
    matchnumber,
    predicted_home_score,
    predicted_away_score,
    prediction_text,
    confidence="medium",
    source_context=None,
    language="am",
):
    try:
        item = save_match_prediction(
            matchnumber=matchnumber,
            predicted_home_score=predicted_home_score,
            predicted_away_score=predicted_away_score,
            prediction_text=prediction_text,
            confidence=confidence,
            source_context=source_context,
            language=language,
        )
        return ServiceResult(
            action="world_cup_prediction_save",
            success=item is not None,
            message=(
                f"Prediction {matchnumber} saved."
                if item
                else f"Prediction {matchnumber} was not saved."
            ),
            data={"item": item} if item else {},
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_prediction_save",
            success=False,
            message=f"World Cup prediction save failed: {e}",
        )


def publish_world_cup_prediction_service(matchnumber, language="am"):
    try:
        result = publish_match_prediction(matchnumber=matchnumber, language=language)
        item = result.get("item") or {}
        return ServiceResult(
            action="world_cup_prediction_publish",
            success=True,
            skipped=result.get("skipped", False),
            message=(
                f"Prediction {matchnumber} already published."
                if result.get("skipped")
                else f"Prediction {matchnumber} published."
            ),
            data={"item": item, "sent": result.get("sent", False)},
        )
    except Exception as e:
        return ServiceResult(
            action="world_cup_prediction_publish",
            success=False,
            message=f"World Cup prediction publish failed: {e}",
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
