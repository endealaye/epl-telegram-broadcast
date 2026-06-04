from pathlib import Path
from datetime import timedelta

import requests

from bot_config import TELEGRAM_ADMIN_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_eat_now
from posting_policy import build_policy_summary, classify_match_day
from store import get_bot_state_value, set_bot_state_value, supabase


def _telegram_post(method, *, json_payload=None, data=None, files=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    response = requests.post(url, json=json_payload, data=data, files=files)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API {method} failed: {payload}")
    return payload.get("result")


def send_telegram_message(message, chat_id=None, return_message=False):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print(message)
        return None if return_message else False
    payload = {"chat_id": target_chat, "text": message, "parse_mode": "Markdown"}
    result = _telegram_post("sendMessage", json_payload=payload)
    return result if return_message else True


def send_telegram_photo(photo_url, caption, chat_id=None, return_message=False):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print(caption)
        return None if return_message else False
    payload = {
        "chat_id": target_chat,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "Markdown",
    }
    result = _telegram_post("sendPhoto", json_payload=payload)
    return result if return_message else True


def send_telegram_photo_file(photo_path, caption, chat_id=None, return_message=False):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print(caption)
        return None if return_message else False
    data = {
        "chat_id": target_chat,
        "caption": caption,
        "parse_mode": "Markdown",
    }
    with Path(photo_path).open("rb") as photo_file:
        result = _telegram_post("sendPhoto", data=data, files={"photo": photo_file})
    return result if return_message else True


def send_admin_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_ID:
        print(f"Admin Alert: {message}")
        return False
    payload = {"chat_id": TELEGRAM_ADMIN_ID, "text": f"⚠️ *System Alert*\n\n{message}", "parse_mode": "Markdown"}
    _telegram_post("sendMessage", json_payload=payload)
    return True


def get_next_workflow_run_eat():
    now = get_eat_now()
    next_run = now.replace(second=0, microsecond=0)
    minute_slot = ((next_run.minute // 30) + 1) * 30
    if minute_slot >= 60:
        next_run = next_run.replace(minute=0) + timedelta(hours=1)
    else:
        next_run = next_run.replace(minute=minute_slot)
    return next_run


def build_status_message():
    now = get_eat_now()
    next_run = get_next_workflow_run_eat()
    policy = classify_match_day()
    return (
        "✅ *Bot Status*: Online\n"
        f"🕒 *Now*: {now.strftime('%Y-%m-%d %H:%M:%S')} EAT\n"
        f"⏭️ *Next workflow run*: {next_run.strftime('%Y-%m-%d %H:%M')} EAT\n"
        f"🧠 *Match-day state*: `{policy.get('state')}`\n"
        f"📊 *Policy*: {build_policy_summary(policy)}"
    )


def build_workflow_message():
    next_run = get_next_workflow_run_eat()
    policy = classify_match_day()
    return (
        "🗓️ *Workflow Schedule*\n\n"
        "• `commands`, `reminders`, `results`, `news-fetch`: every 30 minutes\n"
        "• `live`: every 5 minutes\n"
        "• `refresh`: twice daily\n"
        "• `daily`: once daily\n\n"
        f"⏭️ *Next 30-minute cycle*: {next_run.strftime('%Y-%m-%d %H:%M')} EAT\n"
        f"🧠 *Current policy*: {build_policy_summary(policy)}"
    )


def _normalize_command(text):
    command = (text or "").strip().split(None, 1)[0]
    if not command.startswith("/"):
        return ""
    return command.split("@", 1)[0].lower()


def build_command_help_message():
    return (
        "ℹ️ *Available commands*\n\n"
        "• `/status`\n"
        "• `/workflow`\n"
        "• `/heartbeat`"
    )


def broadcast_heartbeat(chat_id=None):
    try:
        now = get_eat_now()
        msg = f"✅ *System Heartbeat*\n\nBot is running normally.\nTime: {now.strftime('%Y-%m-%d %H:%M:%S')} EAT"
        if chat_id:
            return send_telegram_message(msg, chat_id=chat_id)
        return send_admin_alert(msg.replace("⚠️ *System Alert*", "✅ *System Status*"))
    except Exception as e:
        print(f"Heartbeat error: {e}")
        return False


def process_commands():
    if not supabase or not TELEGRAM_BOT_TOKEN:
        return
    try:
        raw_last_update_id = get_bot_state_value('last_update_id')
        last_update_id = int(raw_last_update_id) if raw_last_update_id else 0

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {"offset": last_update_id + 1, "timeout": 10}
        response = requests.get(url, params=params).json()

        if not response.get('ok'):
            return

        updates = response.get('result', [])
        for update in updates:
            msg = update.get('message')
            if not msg:
                continue

            chat_id = msg['chat']['id']
            text = msg.get('text', '')
            sender_id = (msg.get('from') or {}).get('id')
            if str(sender_id) != str(TELEGRAM_ADMIN_ID):
                continue

            command = _normalize_command(text)
            if command == '/heartbeat':
                broadcast_heartbeat(chat_id=chat_id)
            elif command == '/status':
                send_telegram_message(build_status_message(), chat_id=chat_id)
            elif command == '/workflow':
                send_telegram_message(build_workflow_message(), chat_id=chat_id)
            elif command.startswith('/'):
                send_telegram_message(
                    f"❓ *Unknown command*: `{command}`\n\n{build_command_help_message()}",
                    chat_id=chat_id,
                )

            last_update_id = update['update_id']

        if updates:
            set_bot_state_value('last_update_id', str(last_update_id))
    except Exception as e:
        print(f"Command processing error: {e}")
