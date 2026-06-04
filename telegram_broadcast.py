import json
import sys

from orchestrator import parse_event_json, route_event_dict


def print_usage():
    print(
        "Usage: python3 telegram_broadcast.py "
        "[refresh|commands|live|daily|reminders|results|standings [short|full]|world-cup-analysis|world-cup-analysis-queue|world-cup-analysis-mark|world-cup-squad-audit|world-cup-form|world-cup-players|world-cup-standings|heartbeat|news-fetch|news-queue|news-mark|event]"
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
        elif mode == 'standings':
            payload = {}
            if len(sys.argv) > 2:
                payload["format"] = sys.argv[2]
            result = route_event_dict({"intent": "standings", "payload": payload})
        elif mode == 'world-cup-analysis':
            result = route_event_dict({"intent": "world_cup_analysis"})
        elif mode == 'world-cup-analysis-queue':
            payload = {}
            if len(sys.argv) > 2:
                payload["limit"] = int(sys.argv[2])
            if len(sys.argv) > 3:
                payload["status"] = sys.argv[3]
            result = route_event_dict({"intent": "world_cup_analysis_queue", "payload": payload})
        elif mode == 'world-cup-analysis-mark':
            if len(sys.argv) < 4:
                print(json.dumps({
                    "action": "world_cup_analysis_mark",
                    "success": False,
                    "message": "Usage: python3 telegram_broadcast.py world-cup-analysis-mark <matchnumber> <draft|approved|published|rejected>",
                }, ensure_ascii=False))
                raise SystemExit(1)
            result = route_event_dict({
                "intent": "world_cup_analysis_mark",
                "payload": {"matchnumber": int(sys.argv[2]), "status": sys.argv[3]},
            })
        elif mode == 'world-cup-players':
            result = route_event_dict({"intent": "world_cup_players"})
        elif mode == 'world-cup-form':
            result = route_event_dict({"intent": "world_cup_form"})
        elif mode == 'world-cup-squad-audit':
            result = route_event_dict({"intent": "world_cup_squad_audit"})
        elif mode == 'world-cup-standings':
            result = route_event_dict({"intent": "world_cup_standings"})
        else:
            result = route_event_dict({"intent": mode})
        print(json.dumps(result.to_dict(), ensure_ascii=False))
