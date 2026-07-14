from supabase import create_client
import Ronesans.ronesans_config as r_config

class DBHelper:
    def __init__(self):
        self.url = r_config.SUPABASE_URL
        self.key = r_config.SUPABASE_KEY
        self.client = None
        self.enabled = False
        
        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
                self.enabled = True
            except Exception as e:
                print(f"[DB Warning] Supabase client baslatilamadi: {e}")
        else:
            print("[DB Warning] Supabase kimlik bilgileri eksik. DB devredisi.")

    def add_trade_history(self, coin, side, entry_price, exit_price, pnl_usd, pnl_pct, fees, entry_time, exit_reason):
        """
        Kapatılan bacakları eski veritabanı şemasına uygun olarak islem_gecmisi tablosuna yazar.
        """
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
            print(f"[DB Info] {coin} islemi islem_gecmisi tablosuna kaydedildi.")
        except Exception as e:
            print(f"[DB Error] add_trade_history basarisiz: {e}")
