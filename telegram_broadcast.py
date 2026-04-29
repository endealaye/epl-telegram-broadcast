import json
import sys

from orchestrator import parse_event_json, route_event_dict


def print_usage():
    print(
        "Usage: python3 telegram_broadcast.py "
        "[refresh|commands|live|daily|reminders|results|heartbeat|event]"
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
        else:
            result = route_event_dict({"intent": mode})
        print(json.dumps(result.to_dict(), ensure_ascii=False))
