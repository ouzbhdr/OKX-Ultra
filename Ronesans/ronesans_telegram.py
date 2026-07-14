import requests
import Ronesans.ronesans_config as r_config

def send_telegram_alert(message):
    if not r_config.ENABLE_TELEGRAM or not r_config.TELEGRAM_BOT_TOKEN or not r_config.TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{r_config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": r_config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Telegram Error] Bildirim gonderilemedi: {e}")
