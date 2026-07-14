import os
import urllib.request
import json
from datetime import datetime
import config
from holocron import DBHelper

db = DBHelper()

def run_jawa():
    print(f"[{datetime.now()}] Jawa aktif. OKX minimum limitler kontrol ediliyor...")
    
    # 1. Fetch balance to estimate capital
    # We can connect to OKX or query Supabase active capital.
    # Let's write a fallback: if OKX credentials are not set, assume $20.0
    capital = 20.0
    try:
        import ccxt
        exchange = ccxt.okx({
            'apiKey': config.OKX_API_KEY,
            'secret': config.OKX_SECRET_KEY,
            'password': config.OKX_PASSPHRASE,
        })
        if config.DEMO_MODE:
            exchange.set_sandbox_mode(True)
        balance = exchange.fetch_balance()
        capital = balance['free'].get('USDT', 20.0)
        print(f"[Jawa Bilgi] Mevcut OKX bakiyesi: ${capital:.2f}")
    except Exception as e:
        print(f"[Jawa Uyarı] Canlı bakiye sorgulanamadı: {e}. Varsayılan bakiye kabul ediliyor: ${capital:.2f}")
        
    # 2. Fetch OKX public instruments and tickers to get last prices
    try:
        url_insts = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
        url_tickers = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        
        req_inst = urllib.request.Request(url_insts, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_inst) as res:
            insts_data = json.loads(res.read().decode())['data']
            
        req_tick = urllib.request.Request(url_tickers, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_tick) as res:
            tickers_data = json.loads(res.read().decode())['data']
            
        tickers = {t['instId']: float(t['last']) for t in tickers_data}
        
    except Exception as e:
        print(f"[Jawa Hata] OKX API'den veri alınamadı: {e}")
        return
        
    # 3. Analyze each target coin and update blacklist
    # Our maximum trade size at 10% risk is: capital * 0.10 / MIN_SL_PCT
    # Which is capital * 0.10 / 0.0050 = capital * 20
    max_trade_usd = capital * 20.0
    
    # We also cap it by maximum borsa leverage (capital * MAX_LEVERAGE)
    max_trade_usd = min(max_trade_usd, capital * config.MAX_LEVERAGE)
    
    print(f"[Jawa Bilgi] Bu bakiye için maksimum olası işlem büyüklüğü: ${max_trade_usd:.2f}")
    
    active_blacklist = db.get_blacklist()
    
    for inst in insts_data:
        symbol = inst['instId']
        if symbol in config.TARGET_COINS:
            ct_val = float(inst['ctVal']) # Multiplier
            min_sz = float(inst['minSz']) # Min contracts
            last_price = tickers.get(symbol, 0.0)
            
            # Minimum order size in USD
            min_order_usd = ct_val * min_sz * last_price
            
            # If the minimum order size in USD exceeds our maximum possible position size, blacklist it!
            # (Plus a 10% buffer to prevent margin errors)
            if min_order_usd > max_trade_usd * 0.90:
                reason = f"Min order size (${min_order_usd:.2f}) exceeds max trade capability (${max_trade_usd:.2f})"
                db.add_to_blacklist(symbol, reason)
            else:
                # If it was blacklisted but now we have enough capital, remove it!
                if symbol in active_blacklist:
                    db.remove_from_blacklist(symbol)
                    print(f"[Jawa Bilgi] {symbol} tekrar aktif edildi (Mevcut bakiye ${min_order_usd:.2f} minimum tutarı karşılıyor).")
                    
    print(f"[{datetime.now()}] Jawa kontrolü tamamlandı.")

if __name__ == "__main__":
    run_jawa()
