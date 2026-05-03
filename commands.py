from pathlib import Path
import json

import requests

from bot_config import TELEGRAM_ADMIN_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_eat_now
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


def set_telegram_message_reaction(message_id, reaction_emoji, chat_id=None, is_big=True):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat or not message_id or not reaction_emoji:
        return False
    payload = {
        "chat_id": target_chat,
        "message_id": message_id,
        "reaction": json.dumps([{"type": "emoji", "emoji": reaction_emoji}]),
        "is_big": is_big,
    }
    _telegram_post("setMessageReaction", data=payload)
    return True


def send_admin_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_ID:
        print(f"Admin Alert: {message}")
        return False
    payload = {"chat_id": TELEGRAM_ADMIN_ID, "text": f"⚠️ *System Alert*\n\n{message}", "parse_mode": "Markdown"}
    _telegram_post("sendMessage", json_payload=payload)
    return True


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

            if str(chat_id) != str(TELEGRAM_ADMIN_ID):
                continue

            if text == '/heartbeat':
                broadcast_heartbeat(chat_id=chat_id)
            elif text == '/status':
                send_telegram_message("✅ *Bot Status*: Online\n🕒 *Next run*: Every 30m", chat_id=chat_id)

            last_update_id = update['update_id']

        if updates:
            set_bot_state_value('last_update_id', str(last_update_id))
    except Exception as e:
        print(f"Command processing error: {e}")
