import os
import time
import urllib.request
import json
import threading
from datetime import datetime

import Ronesans.ronesans_config as r_config

_listener_started = False
_lock = threading.Lock()

def get_active_positions_msg():
    """
    Sadece borsa üzerinde o an aktif olan pozisyonların detaylı analizini raporlar.
    """
    import ccxt
    from Ronesans.ronesans_engine import get_active_positions_from_exchange, calculate_current_zscore
    
    exchange = ccxt.okx({
        'apiKey': r_config.OKX_API_KEY,
        'secret': r_config.OKX_SECRET_KEY,
        'password': r_config.OKX_PASSPHRASE,
    })
    if r_config.DEMO_MODE:
        exchange.set_sandbox_mode(True)
        
    msg = f"📊 *Rönesans Aktif Pozisyonlar Raporu*\n\n"
    active_count = 0
    
    for coin_y, coin_x, window, entry_z, stop_z, leverage in r_config.TARGET_PAIRS:
        pos_y, pos_x = get_active_positions_from_exchange(exchange, coin_y, coin_x)
        if pos_y and pos_x:
            pair_key = f"{coin_y} / {coin_x}"
            metrics = calculate_current_zscore(exchange, coin_y, coin_x, window)
            z_str = f"`{metrics['z_score']:.2f}`" if metrics else "`Hata`"
            coint_str = "🟢 Eşbütünleşme Aktif" if (metrics and metrics['is_coint_valid']) else "🔴 Eşbütünleşme Yok"
            
            val_y = pos_y['contracts'] * pos_y['entry_price'] * exchange.market(pos_y['symbol'])['contractSize']
            val_x = pos_x['contracts'] * pos_x['entry_price'] * exchange.market(pos_x['symbol'])['contractSize']
            
            p_y_cur = metrics['price_y'] if metrics else pos_y['entry_price']
            p_x_cur = metrics['price_x'] if metrics else pos_x['entry_price']
            
            ret_y = (p_y_cur - pos_y['entry_price']) / pos_y['entry_price']
            if pos_y['side'] == 'SHORT':
                ret_y = -ret_y
                
            ret_x = (p_x_cur - pos_x['entry_price']) / pos_x['entry_price']
            if pos_x['side'] == 'SHORT':
                ret_x = -ret_x
                
            pnl = (val_y * ret_y) + (val_x * ret_x)
            pnl_pct = (pnl / (val_y + val_x)) * 100
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            msg += f"🔸 *{pair_key}* ({pos_y['side']} / {pos_x['side']})\n" \
                   f"• Z-Score: {z_str} ({coint_str})\n" \
                   f"• Girişler: {coin_y}: `${pos_y['entry_price']:.4f}` | {coin_x}: `${pos_x['entry_price']:.4f}`\n" \
                   f"• Anlık: {coin_y}: `${p_y_cur:.4f}` | {coin_x}: `${p_x_cur:.4f}`\n" \
                   f"• Büyüklük: `${val_y + val_x:.2f}` ({leverage}x)\n" \
                   f"• Net PnL: {pnl_emoji} `${pnl:.2f} ({pnl_pct:.2f}%)`\n" \
                   f"-----------------------------------------\n"
            active_count += 1
            
    if active_count == 0:
        return "ℹ️ *Şu an açıkta aktif bir Rönesans pozisyonu bulunmuyor.*"
        
    return msg

def get_bot_status_msg():
    import ccxt
    from Ronesans.ronesans_engine import get_active_positions_from_exchange, calculate_current_zscore
    
    running = os.path.exists(r_config.FLAG_FILE)
    
    exchange = ccxt.okx({
        'apiKey': r_config.OKX_API_KEY,
        'secret': r_config.OKX_SECRET_KEY,
        'password': r_config.OKX_PASSPHRASE,
    })
    if r_config.DEMO_MODE:
        exchange.set_sandbox_mode(True)
        
    balance_str = "Bilinmiyor"
    try:
        balance = exchange.fetch_balance()
        bal_usdt = balance['free'].get('USDT', 0.0)
        balance_str = f"${bal_usdt:.2f} USDT"
    except Exception as e:
        balance_str = f"Hata ({e})"
        
    msg = f"📊 *Rönesans Cointegration Bot Durumu*\n\n" \
          f"🤖 *Bot Durumu:* {'🟢 ÇALIŞIYOR (ONLINE)' if running else '🔴 DURDURULDU (OFFLINE)'}\n" \
          f"💰 *Bakiye ({'Demo' if r_config.DEMO_MODE else 'Gerçek'}):* `{balance_str}`\n" \
          f"-----------------------------------------\n" \
          f"📡 *Çiftlerin Anlık Durumu:*\n\n"
          
    for coin_y, coin_x, window, entry_z, stop_z, leverage in r_config.TARGET_PAIRS:
        pair_key = f"{coin_y} / {coin_x}"
        pos_y, pos_x = get_active_positions_from_exchange(exchange, coin_y, coin_x)
        
        metrics = calculate_current_zscore(exchange, coin_y, coin_x, window)
        z_str = f"`{metrics['z_score']:.2f}`" if metrics else "`Hata`"
        coint_str = "🟢 Eşbütünleşme" if (metrics and metrics['is_coint_valid']) else "🔴 Eşbütünleşme Yok"
        
        if pos_y and pos_x:
            val_y = pos_y['contracts'] * pos_y['entry_price'] * exchange.market(pos_y['symbol'])['contractSize']
            val_x = pos_x['contracts'] * pos_x['entry_price'] * exchange.market(pos_x['symbol'])['contractSize']
            
            p_y_cur = metrics['price_y'] if metrics else pos_y['entry_price']
            p_x_cur = metrics['price_x'] if metrics else pos_x['entry_price']
            
            ret_y = (p_y_cur - pos_y['entry_price']) / pos_y['entry_price']
            if pos_y['side'] == 'SHORT':
                ret_y = -ret_y
                
            ret_x = (p_x_cur - pos_x['entry_price']) / pos_x['entry_price']
            if pos_x['side'] == 'SHORT':
                ret_x = -ret_x
                
            pnl = (val_y * ret_y) + (val_x * ret_x)
            pnl_pct = (pnl / (val_y + val_x)) * 100
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            msg += f"🔸 *{pair_key}* (İşlemde)\n" \
                   f"• Z-Score: {z_str} ({coint_str})\n" \
                   f"• Yön: `{'LONG ' + coin_y + ' / SHORT ' + coin_x if pos_y['side'] == 'LONG' else 'SHORT ' + coin_y + ' / LONG ' + coin_x}`\n" \
                   f"• Büyüklük: `${val_y + val_x:.2f}` ({leverage}x)\n" \
                   f"• Anlık PnL: {pnl_emoji} `${pnl:.2f} ({pnl_pct:.2f}%)`\n"
        else:
            msg += f"🔸 *{pair_key}* (Boşta)\n" \
                   f"• Z-Score: {z_str} ({coint_str})\n"
                   
        msg += f"-----------------------------------------\n"
        
    return msg

def send_reply(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{r_config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"[Telegram Bot] Mesaj gonderme hatasi: {e}")

def telegram_polling_loop():
    print("[Telegram Bot] Ronesans Komut dinleyici aktif. Polling basladi...")
    offset = 0
    
    try:
        send_reply(r_config.TELEGRAM_CHAT_ID, "📲 *Rönesans Telegram Komut Modülü Aktif*\nYardım için `/yardim` yazabilirsiniz.")
    except Exception:
        pass

    while True:
        if not r_config.ENABLE_TELEGRAM or not r_config.TELEGRAM_BOT_TOKEN:
            time.sleep(10)
            continue
            
        try:
            url = f"https://api.telegram.org/bot{r_config.TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            
            with urllib.request.urlopen(req, timeout=15) as res:
                response = json.loads(res.read().decode())
                
            for update in response.get('result', []):
                offset = update['update_id'] + 1
                message = update.get('message', {})
                text = message.get('text', '').strip()
                chat_id = message.get('chat', {}).get('id')
                
                if not text or not chat_id:
                    continue
                    
                # Guvenlik Kontrolu: Sadece yetkili Telegram Chat ID
                if str(chat_id) != str(r_config.TELEGRAM_CHAT_ID):
                    print(f"[Telegram Bot Security] Yetkisiz girisim: {chat_id}")
                    send_reply(chat_id, "❌ *YETKİSİZ ERİŞİM ENGELENDİ.*")
                    continue
                
                command = text.split()[0].lower()
                
                if command == '/baslat':
                    if os.path.exists(r_config.FLAG_FILE):
                        send_reply(chat_id, "🤖 *Rönesans botu zaten calisiyor.*")
                    else:
                        with open(r_config.FLAG_FILE, "w") as f:
                            f.write(str(datetime.now()))
                        send_reply(chat_id, "🚀 *Rönesans bot motoru aktif edildi. Pozisyonlar izleniyor...*")
                        
                elif command in ['/durdur', '/dur']:
                    if not os.path.exists(r_config.FLAG_FILE):
                        send_reply(chat_id, "🛑 *Rönesans botu zaten durdurulmus durumda.*")
                    else:
                        os.remove(r_config.FLAG_FILE)
                        send_reply(chat_id, "🛑 *Rönesans bot motoru durduruldu. Islemler askiya alindi.*")
                        
                elif command == '/durum':
                    send_reply(chat_id, "🔄 *Borsa verileri ve pozisyonlar sorgulanıyor, lütfen bekleyin...*")
                    status_msg = get_bot_status_msg()
                    send_reply(chat_id, status_msg)
                    
                elif command in ['/acik', '/acikislemler']:
                    send_reply(chat_id, "🔄 *Açık pozisyonların anlık verileri borsa üzerinden çekiliyor...*")
                    msg = get_active_positions_msg()
                    send_reply(chat_id, msg)
                    
                elif command == '/sanalmod':
                    r_config.save_demo_mode(True)
                    send_reply(chat_id, "✅ *Rönesans Bot Modu: Sanal Ticaret (Demo) olarak değiştirildi.* Bot kapatılmadan bir sonraki taramada Demo API'ye bağlanacaktır.")
                    
                elif command == '/gercekmod':
                    r_config.save_demo_mode(False)
                    send_reply(chat_id, "⚠️ *Rönesans Bot Modu: GERÇEK TİCARET olarak değiştirildi.* Bot kapatılmadan bir sonraki taramada Real API'ye bağlanacaktır.")
                    
                elif command == '/yardim':
                    help_txt = "📚 *Rönesans Bot Komut Listesi:*\n\n" \
                               "🚀 `/baslat` - Rönesans botunu calistirir.\n" \
                               "🛑 `/durdur` - Rönesans botunu durdurur.\n" \
                               "📊 `/durum` - Tüm çiftlerin anlık Z-Score durumunu raporlar.\n" \
                               "📈 `/acik` - Sadece borsa üzerindeki açık işlemlerin detaylı raporunu döner.\n" \
                               "🧪 `/sanalmod` - OKX Sanal Ticaret (Demo) moduna geçer.\n" \
                               "💰 `/gercekmod` - OKX Gerçek Ticaret moduna geçer.\n" \
                               "ℹ️ `/yardim` - Bu rehberi gosterir."
                    send_reply(chat_id, help_txt)
                    
        except Exception as e:
            print(f"[Telegram Bot Error] Poll exception: {e}")
            
        time.sleep(3)

def start_telegram_listener():
    global _listener_started
    with _lock:
        if _listener_started:
            return
        _listener_started = True
        
        if r_config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or not r_config.TELEGRAM_CHAT_ID:
            print("[Telegram Bot Warning] Kimlik bilgileri config.py'de ayarlanmamis. Komut dinleyici kapali.")
            return
            
        bot_thread = threading.Thread(target=telegram_polling_loop, daemon=True)
        bot_thread.start()
