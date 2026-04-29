import requests

from bot_config import TELEGRAM_ADMIN_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_eat_now
from store import supabase


def send_telegram_message(message, chat_id=None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print(message)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target_chat, "text": message, "parse_mode": "Markdown"}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return True


def send_admin_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_ID:
        print(f"Admin Alert: {message}")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_ADMIN_ID, "text": f"⚠️ *System Alert*\n\n{message}", "parse_mode": "Markdown"}
    response = requests.post(url, json=payload)
    response.raise_for_status()
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
        res = supabase.table('bot_state').select('value').eq('key', 'last_update_id').single().execute()
        last_update_id = int(res.data['value']) if res.data else 0

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
            supabase.table('bot_state').upsert({"key": 'last_update_id', "value": str(last_update_id)}).execute()
    except Exception as e:
        print(f"Command processing error: {e}")
