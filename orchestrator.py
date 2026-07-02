import json
from datetime import datetime

from service_models import AgentEvent, ServiceResult
from worker_services import (
    fetch_news_service,
    list_news_queue_service,
    mark_news_item_service,
)

from worker_services import (
    process_admin_commands_service,
    process_live_window_service,
    send_daily_broadcast_service,
    send_heartbeat_service,
    send_reminders_service,
    send_results_service,
    send_standings_service,
    sync_fixtures_service,
    automated_news_pipeline_service,
)


def convert_datetimes_to_iso(data):
    if isinstance(data, datetime):
        return data.isoformat()
    if isinstance(data, dict):
        return {k: convert_datetimes_to_iso(v) for k, v in data.items()}
    if isinstance(data, list):
        return [convert_datetimes_to_iso(elem) for elem in data]
    return data


INTENT_HANDLERS = {
    "refresh": lambda payload: sync_fixtures_service(),
    "commands": lambda payload: process_admin_commands_service(),
    "live": lambda payload: process_live_window_service(),
    "daily": lambda payload: send_daily_broadcast_service(),
    "reminders": lambda payload: send_reminders_service(),
    "results": lambda payload: send_results_service(),
    "standings": lambda payload: send_standings_service(format_name=payload.get("format")),
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
    "automated_news": lambda payload: automated_news_pipeline_service(),
}


def route_event(event: AgentEvent):
    handler = INTENT_HANDLERS.get(event.intent)
    if not handler:
        return ServiceResult(
            action=event.intent,
            success=False,
            message=f"Unsupported intent: {event.intent}",
        )
    result = handler(event.payload)
    if result and result.data:
        result.data = convert_datetimes_to_iso(result.data)
    return result


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
