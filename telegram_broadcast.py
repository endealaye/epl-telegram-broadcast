import json
import sys
from datetime import datetime

from orchestrator import parse_event_json, route_event_dict
from store import supabase_health_check


SUPABASE_REQUIRED_MODES = {
    "refresh",
    "commands",
    "live",
    "daily",
    "reminders",
    "results",
    "standings",
    "world-cup-analysis",
    "world-cup-analysis-review-reminder",
    "world-cup-analysis-publish",
    "world-cup-recap",
    "world-cup-analysis-queue",
    "world-cup-analysis-mark",
    "world-cup-prediction-save",
    "world-cup-prediction-publish",
    "world-cup-facts-seed",
    "world-cup-fact",
    "world-cup-squad-audit",
    "world-cup-coaches",
    "world-cup-form",
    "world-cup-players",
    "world-cup-bbc-squads",
    "world-cup-standings",
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
        "[refresh|commands|live|daily|reminders|results|standings [short|full]|world-cup-analysis|world-cup-analysis-review-reminder|world-cup-analysis-publish|world-cup-recap|world-cup-analysis-queue|world-cup-analysis-mark|world-cup-prediction-save|world-cup-prediction-publish|world-cup-facts-seed|world-cup-fact|world-cup-squad-audit|world-cup-coaches|world-cup-form|world-cup-players|world-cup-bbc-squads|world-cup-standings|heartbeat|news-fetch|news-queue|news-mark|event]"
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
        elif mode == 'world-cup-analysis':
            result = route_event_dict({"intent": "world_cup_analysis"})
        elif mode == 'world-cup-analysis-review-reminder':
            result = route_event_dict({"intent": "world_cup_analysis_review_reminder"})
        elif mode == 'world-cup-analysis-publish':
            result = route_event_dict({"intent": "world_cup_analysis_publish"})
        elif mode == 'world-cup-recap':
            payload = {}
            if len(sys.argv) > 2:
                payload["date_strings"] = [part.strip() for part in sys.argv[2].split(",") if part.strip()]
            result = route_event_dict({"intent": "world_cup_recap", "payload": payload})
        elif mode == 'world-cup-facts-seed':
            result = route_event_dict({"intent": "world_cup_facts_seed"})
        elif mode == 'world-cup-fact':
            result = route_event_dict({"intent": "world_cup_fact"})
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
                }, ensure_ascii=False, default=json_serial))
                raise SystemExit(1)
            result = route_event_dict({
                "intent": "world_cup_analysis_mark",
                "payload": {"matchnumber": int(sys.argv[2]), "status": sys.argv[3]},
            })
        elif mode == 'world-cup-prediction-save':
            if len(sys.argv) < 6:
                print(json.dumps({
                    "action": "world_cup_prediction_save",
                    "success": False,
                    "message": "Usage: python3 telegram_broadcast.py world-cup-prediction-save <matchnumber> <home_score> <away_score> <prediction_text> [low|medium|high]",
                }, ensure_ascii=False, default=json_serial))
                raise SystemExit(1)
            confidence = sys.argv[6] if len(sys.argv) > 6 else "medium"
            result = route_event_dict({
                "intent": "world_cup_prediction_save",
                "payload": {
                    "matchnumber": int(sys.argv[2]),
                    "predicted_home_score": int(sys.argv[3]),
                    "predicted_away_score": int(sys.argv[4]),
                    "prediction_text": sys.argv[5],
                    "confidence": confidence,
                },
            })
        elif mode == 'world-cup-prediction-publish':
            if len(sys.argv) < 3:
                print(json.dumps({
                    "action": "world_cup_prediction_publish",
                    "success": False,
                    "message": "Usage: python3 telegram_broadcast.py world-cup-prediction-publish <matchnumber>",
                }, ensure_ascii=False, default=json_serial))
                raise SystemExit(1)
            result = route_event_dict({
                "intent": "world_cup_prediction_publish",
                "payload": {"matchnumber": int(sys.argv[2])},
            })
        elif mode == 'world-cup-players':
            result = route_event_dict({"intent": "world_cup_players"})
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
