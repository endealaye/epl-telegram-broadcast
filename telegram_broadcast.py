import json
import sys
from datetime import datetime

from orchestrator import parse_event_json, route_event_dict
from store import supabase_health_check


SUPABASE_REQUIRED_MODES = {
    "refresh",
    "live",
    "daily",
    "reminders",
    "results",
    "standings",
    "news-fetch",
    "news-queue",
    "news-mark",
}


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def print_usage():
    print(
        "Usage: python3 telegram_broadcast.py "
        "[refresh|live|daily|reminders|results|standings [short|full]|world-cup-bbc-squads|world-cup-standings|heartbeat|news-fetch|news-queue|news-mark|event]"
    )


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print_usage()
    else:
        mode = sys.argv[1]
        if mode in SUPABASE_REQUIRED_MODES:
            health = supabase_health_check()
            if not health.get("ok"):
                print(json.dumps({
                    "action": "supabase_health_check",
                    "success": False,
                    "message": f"Supabase startup check failed: {health.get('message', 'unknown error')}",
                    "data": health,
                }, ensure_ascii=False, default=json_serial))
                raise SystemExit(1)
        if mode == 'event':
            raw_event = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read()
            if not raw_event.strip():
                print(json.dumps({
                    "action": "event",
                    "success": False,
                    "message": "Missing event JSON payload.",
                }, default=json_serial))
                raise SystemExit(1)
            result = route_event_dict(parse_event_json(raw_event))
        elif mode == 'news-fetch':
            result = route_event_dict({"intent": "news_fetch"})
        elif mode == 'news-queue':
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            result = route_event_dict({"intent": "news_queue", "payload": {"limit": limit}})
        elif mode == 'news-mark':
            if len(sys.argv) < 4:
                print(json.dumps({
                    "action": "news_mark",
                    "success": False,
                    "message": "Usage: python3 telegram_broadcast.py news-mark <id> <status> [translated_title_am] [translated_story_am]",
                }, ensure_ascii=False, default=json_serial))
                raise SystemExit(1)
            payload = {
                "item_id": int(sys.argv[2]),
                "status": sys.argv[3],
            }
            if len(sys.argv) > 4:
                payload["translated_title_am"] = sys.argv[4]
            if len(sys.argv) > 5:
                payload["translated_story_am"] = sys.argv[5]
            result = route_event_dict({"intent": "news_mark", "payload": payload})
        elif mode == 'standings':
            payload = {}
            if len(sys.argv) > 2:
                payload["format"] = sys.argv[2]
            result = route_event_dict({"intent": "standings", "payload": payload})
        elif mode == 'world-cup-bbc-squads':
            result = route_event_dict({"intent": "world_cup_bbc_squads"})
        elif mode == 'world-cup-form':
            result = route_event_dict({"intent": "world_cup_form"})
        elif mode == 'world-cup-squad-audit':
            result = route_event_dict({"intent": "world_cup_squad_audit"})
        elif mode == 'world-cup-coaches':
            result = route_event_dict({"intent": "world_cup_coaches"})
        elif mode == 'world-cup-standings':
            result = route_event_dict({"intent": "world_cup_standings"})
        else:
            result = route_event_dict({"intent": mode})
        print(json.dumps(result.to_dict(), ensure_ascii=False, default=json_serial))
