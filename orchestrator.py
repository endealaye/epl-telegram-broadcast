import json

from service_models import AgentEvent, ServiceResult
from worker_services import (
    fetch_news_service,
    generate_world_cup_analysis_service,
    list_news_queue_service,
    list_world_cup_analysis_queue_service,
    mark_news_item_service,
    mark_world_cup_analysis_service,
    process_admin_commands_service,
    process_live_window_service,
    send_daily_broadcast_service,
    send_heartbeat_service,
    send_reminders_service,
    send_results_service,
    send_standings_service,
    audit_world_cup_squads_service,
    refresh_world_cup_form_service,
    refresh_world_cup_players_service,
    refresh_world_cup_standings_service,
    sync_fixtures_service,
)


INTENT_HANDLERS = {
    "refresh": lambda payload: sync_fixtures_service(),
    "commands": lambda payload: process_admin_commands_service(),
    "live": lambda payload: process_live_window_service(),
    "daily": lambda payload: send_daily_broadcast_service(),
    "reminders": lambda payload: send_reminders_service(),
    "results": lambda payload: send_results_service(),
    "standings": lambda payload: send_standings_service(format_name=payload.get("format")),
    "world_cup_analysis": lambda payload: generate_world_cup_analysis_service(),
    "world_cup_analysis_queue": lambda payload: list_world_cup_analysis_queue_service(
        limit=payload.get("limit", 20),
        status=payload.get("status", "draft"),
    ),
    "world_cup_analysis_mark": lambda payload: mark_world_cup_analysis_service(
        matchnumber=payload.get("matchnumber"),
        status=payload.get("status", ""),
    ),
    "world_cup_squad_audit": lambda payload: audit_world_cup_squads_service(),
    "world_cup_form": lambda payload: refresh_world_cup_form_service(),
    "world_cup_players": lambda payload: refresh_world_cup_players_service(),
    "world_cup_standings": lambda payload: refresh_world_cup_standings_service(),
    "heartbeat": lambda payload: send_heartbeat_service(chat_id=payload.get("chat_id")),
    "news_fetch": lambda payload: fetch_news_service(),
    "news_queue": lambda payload: list_news_queue_service(limit=payload.get("limit", 20)),
    "news_mark": lambda payload: mark_news_item_service(
        item_id=payload.get("item_id"),
        status=payload.get("status", ""),
        translated_title_am=payload.get("translated_title_am"),
        translated_story_am=payload.get("translated_story_am"),
        notes=payload.get("notes"),
    ),
}


def route_event(event: AgentEvent):
    handler = INTENT_HANDLERS.get(event.intent)
    if not handler:
        return ServiceResult(
            action=event.intent,
            success=False,
            message=f"Unsupported intent: {event.intent}",
        )
    return handler(event.payload)


def route_event_dict(event_dict):
    event = AgentEvent(
        intent=event_dict.get("intent", ""),
        source=event_dict.get("source", "cli"),
        locale=event_dict.get("locale", "am"),
        payload=event_dict.get("payload", {}),
    )
    return route_event(event)


def parse_event_json(raw_event):
    event_dict = json.loads(raw_event)
    if not isinstance(event_dict, dict):
        raise ValueError("Event payload must be a JSON object.")
    return event_dict
