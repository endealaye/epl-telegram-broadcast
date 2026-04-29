import json

from service_models import AgentEvent, ServiceResult
from worker_services import (
    process_admin_commands_service,
    process_live_window_service,
    send_daily_broadcast_service,
    send_heartbeat_service,
    send_reminders_service,
    send_results_service,
    sync_fixtures_service,
)


INTENT_HANDLERS = {
    "refresh": lambda payload: sync_fixtures_service(),
    "commands": lambda payload: process_admin_commands_service(),
    "live": lambda payload: process_live_window_service(),
    "daily": lambda payload: send_daily_broadcast_service(),
    "reminders": lambda payload: send_reminders_service(),
    "results": lambda payload: send_results_service(),
    "heartbeat": lambda payload: send_heartbeat_service(chat_id=payload.get("chat_id")),
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
