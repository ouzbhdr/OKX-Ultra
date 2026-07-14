import os
import requests
import config
from supabase import create_client, Client

class DBHelper:
    def __init__(self):
        self.url = config.SUPABASE_URL
        self.key = config.SUPABASE_KEY
        self.client = None
        self.enabled = False
        
        # Initialize Supabase client if credentials are provided
        if self.url and self.url != "YOUR_SUPABASE_URL" and self.key and self.key != "YOUR_SUPABASE_ANON_KEY":
            try:
                self.client = create_client(self.url, self.key)
                self.enabled = True
            except Exception as e:
                print(f"[DB Warning] Failed to initialize Supabase client: {e}")
        else:
            print("[DB Warning] Supabase credentials not set in ayarlar.py. Database features disabled.")

    def get_guide_params(self, coin):
        if not self.enabled:
            return None
        try:
            res = self.client.table("guide_table").select("*").eq("coin", coin).execute()
            if res.data:
                return res.data[0]
            return None
        except Exception as e:
            print(f"[DB Error] get_guide_params failed for {coin}: {e}")
            return None

    def update_guide_params(self, coin, most_period, most_pct, stoch_len, wma_len, opt_pnl):
        if not self.enabled:
            return
        try:
            payload = {
                "coin": coin,
                "most_period": most_period,
                "most_pct": float(most_pct),
                "stoch_len": stoch_len,
                "wma_len": wma_len,
                "opt_pnl": float(opt_pnl)
            }
            # Upsert using Supabase
            self.client.table("guide_table").upsert(payload).execute()
            print(f"[DB Info] Updated parameters for {coin} in guide_table.")
        except Exception as e:
            print(f"[DB Error] update_guide_params failed: {e}")

    def get_active_positions(self):
        if not self.enabled:
            return []
        try:
            res = self.client.table("active_positions").select("*").execute()
            return res.data
        except Exception as e:
            print(f"[DB Error] get_active_positions failed: {e}")
            return []

    def add_pending_position(self, coin, side, entry_price, size, leverage, sl_price, order_id):
        if not self.enabled:
            return
        try:
            payload = {
                "coin": coin,
                "side": side,
                "entry_price": float(entry_price),
                "position_size": float(size),
                "leverage": int(leverage),
                "sl_price": float(sl_price),
                "status": "PENDING",
                "order_id": order_id
            }
            self.client.table("active_positions").insert(payload).execute()
            print(f"[DB Info] Inserted pending position for {coin} (Order: {order_id}).")
        except Exception as e:
            print(f"[DB Error] add_pending_position failed: {e}")

    def update_position_status(self, order_id, status="FILLED"):
        if not self.enabled:
            return
        try:
            self.client.table("active_positions").update({"status": status}).eq("order_id", order_id).execute()
            print(f"[DB Info] Updated status of order {order_id} to {status}.")
        except Exception as e:
            print(f"[DB Error] update_position_status failed: {e}")

    def update_position_sl(self, coin, sl_price):
        if not self.enabled:
            return
        try:
            self.client.table("active_positions").update({"sl_price": float(sl_price)}).eq("coin", coin).execute()
            print(f"[DB Info] Updated trailing stop price of {coin} to {sl_price}.")
        except Exception as e:
            print(f"[DB Error] update_position_sl failed: {e}")

    def delete_position(self, coin):
        if not self.enabled:
            return
        try:
            self.client.table("active_positions").delete().eq("coin", coin).execute()
            print(f"[DB Info] Deleted active position record for {coin}.")
        except Exception as e:
            print(f"[DB Error] delete_position failed: {e}")

    def add_trade_history(self, coin, side, entry_price, exit_price, pnl_usd, pnl_pct, fees, entry_time, exit_reason):
        if not self.enabled:
            return
        try:
            payload = {
                "parite": coin,
                "yon": side,
                "giris_fiyati": float(entry_price),
                "cikis_fiyati": float(exit_price),
                "kar_zarar_usd": float(pnl_usd),
                "kar_zarar_yuzde": float(pnl_pct),
                "odenen_komisyon": float(fees),
                "giris_zamani": entry_time,
                "kapanis_nedeni": exit_reason
            }
            self.client.table("islem_gecmisi").insert(payload).execute()
            print(f"[DB Info] Saved trade history record for {coin} to islem_gecmisi.")
        except Exception as e:
            print(f"[DB Error] add_trade_history failed: {e}")

    def get_blacklist(self):
        if not self.enabled:
            return []
        try:
            res = self.client.table("blacklist").select("coin").execute()
            return [row["coin"] for row in res.data]
        except Exception as e:
            print(f"[DB Error] get_blacklist failed: {e}")
            return []

    def add_to_blacklist(self, coin, reason):
        if not self.enabled:
            return
        try:
            payload = {"coin": coin, "reason": reason}
            self.client.table("blacklist").upsert(payload).execute()
            print(f"[DB Info] Blacklisted {coin} for reason: {reason}.")
        except Exception as e:
            print(f"[DB Error] add_to_blacklist failed: {e}")

    def remove_from_blacklist(self, coin):
        if not self.enabled:
            return
        try:
            self.client.table("blacklist").delete().eq("coin", coin).execute()
            print(f"[DB Info] Removed {coin} from blacklist.")
        except Exception as e:
            print(f"[DB Error] remove_from_blacklist failed: {e}")


# --- Telegram Notification Helper ---
def send_telegram_alert(message):
    if not config.ENABLE_TELEGRAM:
        print(f"[Telegram Alert (Simulated)] {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"[Telegram Error] Failed to send message: {res.text}")
    except Exception as e:
        print(f"[Telegram Error] Notification exception: {e}")
