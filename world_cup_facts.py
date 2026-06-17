import json
from datetime import datetime, timezone

from bot_config import get_eat_today
from commands import send_telegram_message
from store import get_bot_state_value, set_bot_state_value


FACT_QUEUE_KEY = "world_cup_fact_queue"
FACT_LAST_SENT_DATE_KEY = "world_cup_fact_last_sent_date"

WORLD_CUP_FACTS = [
    {
        "id": "first_world_cup_1930",
        "text": "የመጀመሪያው የዓለም ዋንጫ በ1930 በኡራጓይ ተካሄደ። ኡራጓይም የመጀመሪያው አሸናፊ ሆነች።",
    },
    {
        "id": "brazil_five_titles",
        "text": "ብራዚል የዓለም ዋንጫን 5 ጊዜ በማሸነፍ በታሪክ ብዙ ጊዜ ያሸነፈች ሀገር ናት።",
    },
    {
        "id": "brazil_every_tournament",
        "text": "ብራዚል በዓለም ዋንጫ ታሪክ ሁሉንም ውድድሮች የተሳተፈች ብቸኛ ሀገር ናት።",
    },
    {
        "id": "klose_top_scorer",
        "text": "ሚሮስላቭ ክሎዜ በዓለም ዋንጫ 16 ጎሎች በማስቆጠር የታሪኩ ከፍተኛ ጎል አግቢ ነው።",
    },
    {
        "id": "pele_three_titles",
        "text": "ፔሌ የዓለም ዋንጫን 3 ጊዜ ያሸነፈ ብቸኛ ተጫዋች ነው።",
    },
    {
        "id": "three_host_countries_2026",
        "text": "የ2026 ዓለም ዋንጫ ለመጀመሪያ ጊዜ በ3 ሀገራት ይካሄዳል፦ አሜሪካ፣ ካናዳ እና ሜክሲኮ።",
    },
    {
        "id": "forty_eight_teams_2026",
        "text": "2026 የዓለም ዋንጫ 48 ቡድኖች የሚሳተፉበት የመጀመሪያው ውድድር ነው።",
    },
    {
        "id": "morocco_2022_semifinal",
        "text": "ሞሮኮ በ2022 ሴሚፋይናል በመድረስ በዓለም ዋንጫ ታሪክ የመጀመሪያዋ የአፍሪካ ሀገር ሆነች።",
    },
    {
        "id": "fastest_goal_hakan_sukur",
        "text": "በዓለም ዋንጫ የተቆጠረ ፈጣኑ ጎል በ2002 ቱርክ ተጫዋች ሀካን ሹኩር በ11 ሰከንድ ነበር።",
    },
    {
        "id": "mexico_three_hostings",
        "text": "ሜክሲኮ በ2026 ዓለም ዋንጫ ሲያስተናግድ ውድድሩን 3 ጊዜ ያስተናገደች የመጀመሪያ ሀገር ትሆናለች።",
    },
    {
        "id": "current_trophy_1974",
        "text": "የአሁኑ የዓለም ዋንጫ ዋንጫ ከ1974 ጀምሮ ተጠቅሟል። የቀድሞው ዋንጫ “Jules Rimet Trophy” ተብሎ ይጠራ ነበር።",
    },
    {
        "id": "world_cup_ball",
        "text": "የዓለም ዋንጫ ኳስ በየውድድሩ የተለየ ስምና ዲዛይን አለው።",
    },
]


def _load_queue():
    raw = get_bot_state_value(FACT_QUEUE_KEY)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return payload if isinstance(payload, list) else []


def _save_queue(queue):
    return set_bot_state_value(
        FACT_QUEUE_KEY,
        json.dumps(queue, ensure_ascii=False, sort_keys=True),
    )


def seed_world_cup_facts():
    existing = {item.get("id"): item for item in _load_queue() if item.get("id")}
    queue = []
    created = 0
    updated = 0

    for fact in WORLD_CUP_FACTS:
        current = existing.get(fact["id"], {})
        row = {
            **current,
            "id": fact["id"],
            "text": fact["text"],
        }
        if not current:
            created += 1
        elif current.get("text") != fact["text"]:
            updated += 1
        queue.append(row)

    _save_queue(queue)
    return {"total": len(queue), "created": created, "updated": updated}


def _format_fact_message(fact):
    return (
        "🌍 *የዓለም ዋንጫ እውነታ*\n\n"
        f"{fact['text']}\n\n"
        "#WorldCup"
    )


def publish_daily_world_cup_fact(today=None):
    current_date = today or get_eat_today()
    if get_bot_state_value(FACT_LAST_SENT_DATE_KEY) == current_date:
        return {"sent": False, "skipped": True, "reason": "already_sent_today"}

    seed_world_cup_facts()
    queue = _load_queue()
    if not queue:
        return {"sent": False, "skipped": True, "reason": "empty_queue"}

    next_fact = next((fact for fact in queue if not fact.get("sent_at")), None)
    if not next_fact:
        for fact in queue:
            fact.pop("sent_at", None)
        next_fact = queue[0]

    sent = send_telegram_message(_format_fact_message(next_fact))
    if not sent:
        return {"sent": False, "skipped": False, "reason": "telegram_send_failed"}

    sent_at = datetime.now(timezone.utc).isoformat()
    for fact in queue:
        if fact.get("id") == next_fact.get("id"):
            fact["sent_at"] = sent_at
            break
    _save_queue(queue)
    set_bot_state_value(FACT_LAST_SENT_DATE_KEY, current_date)
    return {
        "sent": True,
        "fact_id": next_fact.get("id"),
        "sent_at": sent_at,
        "remaining": sum(1 for fact in queue if not fact.get("sent_at")),
    }
