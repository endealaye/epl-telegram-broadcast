import json
import sys

from orchestrator import parse_event_json, route_event_dict


def print_usage():
    print(
        "Usage: python3 telegram_broadcast.py "
        "[refresh|commands|live|daily|reminders|results|heartbeat|news-fetch|news-queue|news-mark|event]"
    )


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print_usage()
    else:
        mode = sys.argv[1]
        if mode == 'event':
            raw_event = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read()
            if not raw_event.strip():
                print(json.dumps({
                    "action": "event",
                    "success": False,
                    "message": "Missing event JSON payload.",
                }))
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
                }, ensure_ascii=False))
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
        else:
            result = route_event_dict({"intent": mode})
        print(json.dumps(result.to_dict(), ensure_ascii=False))
