import sys
import os

# Append the kodlar folder to path so we can import from it
sys.path.append(os.path.join(os.path.dirname(__file__), 'kodlar'))

from holocron import DBHelper

def main():
    db = DBHelper()
    if not db.enabled:
        print('Supabase not enabled!')
        sys.exit(1)

    try:
        res = db.client.table('islem_gecmisi').select('*').execute()
        data = res.data
        if not data:
            print('No trade history found in islem_gecmisi.')
            return
        
        keys = list(data[0].keys())
        print('Columns:', keys)
        
        sort_key = 'created_at' if 'created_at' in keys else ('giris_zamani' if 'giris_zamani' in keys else keys[0])
        try:
            data.sort(key=lambda x: x.get(sort_key, ''), reverse=True)
        except Exception:
            pass
            
        print(f'\n--- Last 20 Trades (Sorted by {sort_key}) ---')
        for i, row in enumerate(data[:20]):
            p = row.get('parite')
            y = row.get('yon')
            gf = row.get('giris_fiyati')
            cf = row.get('cikis_fiyati')
            pnl_usd = row.get('kar_zarar_usd')
            pnl_pct = row.get('kar_zarar_yuzde')
            reason = row.get('kapanis_nedeni')
            t = row.get('giris_zamani')
            print(f"{i+1}. {p} | {y} | Giriş: {gf} | Çıkış: {cf} | PnL: {pnl_usd}$ ({pnl_pct}%) | Neden: {reason} | Zaman: {t}")
    except Exception as e:
        print('Error:', e)

if __name__ == '__main__':
    main()
