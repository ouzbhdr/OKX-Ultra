import os
import time
import urllib.request
import json
import threading
from datetime import datetime
import config
from holocron import DBHelper, send_telegram_alert
from run_bot import start_bot_engine, stop_bot_engine, is_bot_running
from config import get_target_coins, save_target_coins

db = DBHelper()
_listener_started = False
_lock = threading.Lock()

def get_bot_status_msg():
    running = is_bot_running()
    single_limit = os.path.exists("single_position.flag")
    coins = get_target_coins()
    blacklist = db.get_blacklist()
    
    # Try to fetch current balance
    balance_str = "Bilinmiyor"
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
        bal_usdt = balance['free'].get('USDT', 0.0)
        balance_str = f"${bal_usdt:.2f} USDT"
    except Exception as e:
        balance_str = f"Hata ({e})"
        
    active_pos = db.get_active_positions()
    pos_str = ""
    if active_pos:
        for p in active_pos:
            pos_str += f"• `{p['coin']}` | {p['side']} | Giriş: `${p['entry_price']}` | Durum: {p['status']}\n"
    else:
        pos_str = "Açık pozisyon yok."

    msg = f"📊 *OKX Ultra Sistem Durumu*\n\n" \
          f"🤖 *Bot Durumu:* {'🟢 ÇALIŞIYOR (ONLINE)' if running else '🔴 DURDURULDU (OFFLINE)'}\n" \
          f"🛡️ *Portföy Modu:* {'🔒 TEK İŞLEM LİMİTİ' if single_limit else '🔓 ÇOKLU İŞLEM LİMİTİ'}\n" \
          f"💰 *Bakiye ({'Demo' if config.DEMO_MODE else 'Gerçek'}):* `{balance_str}`\n\n" \
          f"📡 *Aktif Radar:* {', '.join(coins)}\n" \
          f"🚫 *Kara Liste:* {', '.join(blacklist) if blacklist else 'Temiz'}\n\n" \
          f"🏹 *Açık İşlemler:*\n{pos_str}"
    return msg

def get_active_positions_msg():
    positions = db.get_active_positions()
    if not positions:
        return "ℹ️ *Şu an açıkta aktif bir pozisyon bulunmuyor.*"
        
    msg = "📊 *OKX Ultra Aktif Pozisyonlar Raporu*\n\n"
    for pos in positions:
        coin = pos.get('coin')
        side = pos.get('side')
        entry_price = float(pos.get('entry_price', 0))
        sl_price = float(pos.get('sl_price', 0))
        size = float(pos.get('position_size', 0))
        leverage = int(pos.get('leverage', 0))
        status = pos.get('status')
        
        # Calculate current price and PnL if possible
        current_price_str = ""
        dist_str = ""
        pnl_str = ""
        try:
            import ccxt
            exchange = ccxt.okx()
            if config.DEMO_MODE:
                exchange.set_sandbox_mode(True)
            ticker = exchange.fetch_ticker(coin)
            last = float(ticker['last'])
            current_price_str = f"\nAnlık Fiyat: `${last:.4f}`"
            
            # Calculate distance to stop loss
            dist_pct = abs(last - sl_price) / last * 100
            dist_str = f" (Mesafe: `%{dist_pct:.2f}`)"
            
            # Calculate estimated PnL
            if side == 'LONG':
                pnl_pct = (last - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - last) / entry_price * 100
                
            pnl_usd = size * (pnl_pct / 100)
            sign = "+" if pnl_usd >= 0 else ""
            pnl_str = f"\nAnlık Kâr/Zarar: `{sign}${pnl_usd:.2f} ({sign}{pnl_pct:.2f}%)`"
        except Exception:
            pass
            
        msg += f"🔸 *{coin}* ({side})\n" \
               f"Giriş Fiyatı: `${entry_price:.4f}`{current_price_str}\n" \
               f"İz Süren Stop: `${sl_price:.4f}`{dist_str}{pnl_str}\n" \
               f"Pozisyon Büyüklüğü: `${size:.2f} USD` (`{leverage}x`)\n" \
               f"Durum: `{status}`\n" \
               f"-----------------------------------------\n"
    return msg

def send_reply(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
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
        print(f"[Telegram Bot] Send message failed: {e}")

def telegram_polling_loop():
    print("[Telegram Bot] Command listener daemon active. Polling started...")
    offset = 0
    
    # Send system startup alert
    try:
        send_reply(config.TELEGRAM_CHAT_ID, "📲 *OKX Ultra Telegram Komut Modülü Aktif*\nYardım için `/yardim` yazabilirsiniz.")
    except Exception:
        pass

    while True:
        if not config.ENABLE_TELEGRAM or config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
            time.sleep(10)
            continue
            
        try:
            url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
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
                    
                # Security Check: Only allow commands from authorized chat ID
                if str(chat_id) != str(config.TELEGRAM_CHAT_ID):
                    print(f"[Telegram Bot Security] Rejected command '{text}' from unauthorized chat: {chat_id}")
                    send_reply(chat_id, "❌ *YETKİSİZ ERİŞİM ENGELENDİ.*\nBu bot sadece sahibine yanıt verir.")
                    continue
                
                # Process Commands
                command = text.split()[0].lower()
                args = text.split()[1:]
                
                if command == '/baslat':
                    if is_bot_running():
                        send_reply(chat_id, "🤖 *Bot zaten çalışıyor durumda.*")
                    else:
                        send_reply(chat_id, "🚀 *Bot motoru arka planda başlatılıyor...*")
                        # Start in background thread
                        threading.Thread(target=start_bot_engine, daemon=True).start()
                        
                elif command in ['/durdur', '/dur']:
                    if not is_bot_running():
                        send_reply(chat_id, "🛑 *Bot zaten durdurulmuş durumda.*")
                    else:
                        stop_bot_engine()
                        send_reply(chat_id, "🛑 *Bot motoru durduruldu.*")
                        
                elif command == '/tekislem':
                    with open("single_position.flag", "w") as f:
                        f.write(str(datetime.now()))
                    send_reply(chat_id, "🔒 *Tek İşlem Limiti Aktif Edildi.* (Aynı anda sadece 1 işlem açılır)")
                    
                elif command == '/cokluislem':
                    if os.path.exists("single_position.flag"):
                        os.remove("single_position.flag")
                    num_coins = len(get_target_coins())
                    send_reply(chat_id, f"🔓 *Çoklu İşlem Moduna Geçildi.* (Paralel {num_coins} farklı coinde işleme izin verilir)")
                    
                elif command == '/durum':
                    status_msg = get_bot_status_msg()
                    send_reply(chat_id, status_msg)
                    
                elif command in ['/acik', '/acikislemler']:
                    msg = get_active_positions_msg()
                    send_reply(chat_id, msg)
                    
                elif command == '/ekle':
                    if not args:
                        send_reply(chat_id, "⚠️ *Kullanım:* `/ekle SOL-USDT-SWAP`")
                        continue
                    coin = args[0].upper()
                    current = get_target_coins()
                    if coin in current:
                        send_reply(chat_id, f"ℹ️ `{coin}` zaten radar listesinde mevcut.")
                    else:
                        current.append(coin)
                        save_target_coins(current)
                        send_reply(chat_id, f"✅ `{coin}` radar listesine eklendi. Anlık optimizasyon başlatıldı...")
                        # Run scanner for the newly added coin instantly in a background thread
                        from c3po import run_scanner
                        threading.Thread(target=run_scanner, args=(coin,), daemon=True).start()
                        
                elif command == '/sil':
                    if not args:
                        send_reply(chat_id, "⚠️ *Kullanım:* `/sil SOL-USDT-SWAP`")
                        continue
                    coin = args[0].upper()
                    current = get_target_coins()
                    if coin not in current:
                        send_reply(chat_id, f"⚠️ `{coin}` radar listesinde bulunamadı.")
                    else:
                        current.remove(coin)
                        save_target_coins(current)
                        send_reply(chat_id, f"❌ `{coin}` radar listesinden kaldırıldı.")
                        
                elif command == '/rehbertablo':
                    try:
                        res = db.client.table("guide_table").select("*").execute()
                        current_coins = get_target_coins()
                        if res.data:
                            msg = "🔍 *OKX Ultra Güncel Rehber Tablo*\n\n"
                            rows_added = 0
                            for row in res.data:
                                if row['coin'] in current_coins:
                                    msg += f"• `{row['coin']}` | Periyot: `{row['most_period']}` | Yüzde: `%{float(row['most_pct'])*100:.2f}` | Stoch: `{row['stoch_len']}/{row['wma_len']}`\n"
                                    rows_added += 1
                            if rows_added == 0:
                                msg = "ℹ️ Rehber tabloda aktif paritelerinize ait parametre bulunamadı."
                            send_reply(chat_id, msg)
                        else:
                            send_reply(chat_id, "ℹ️ Rehber tablo veritabanında bulunamadı.")
                    except Exception as e:
                        send_reply(chat_id, f"❌ Rehber tablo okunamadı: {e}")
                        
                elif command == '/karaliste':
                    try:
                        res = db.client.table("blacklist").select("*").execute()
                        if res.data:
                            msg = "🚫 *OKX Ultra Güncel Kara Liste*\n\n"
                            for row in res.data:
                                msg += f"• `{row['coin']}` | Sebep: `{row.get('reason', 'Yetersiz Bakiye')}`\n"
                            send_reply(chat_id, msg)
                        else:
                            send_reply(chat_id, "ℹ️ *Kara listede şu an aktif hiçbir coin bulunmuyor.*")
                    except Exception as e:
                        send_reply(chat_id, f"❌ Kara liste okunamadı: {e}")
                        
                elif command == '/tara':
                    try:
                        from c3po import run_scanner
                        threading.Thread(target=run_scanner, daemon=True).start()
                        send_reply(chat_id, "🔄 *Anlık optimizasyon taraması arka planda başlatıldı!* Güncel parametreler rehber tabloya yazılacaktır.")
                    except Exception as e:
                        send_reply(chat_id, f"❌ Optimizasyon başlatılamadı: {e}")
                        
                elif command == '/sanalmod':
                    from config import save_demo_mode
                    save_demo_mode(True)
                    if is_bot_running():
                        send_reply(chat_id, "🔄 *OKX Ultra Sanal Ticaret (Demo) Moduna Geçiliyor...*\nBağlantıların güncellenmesi için bot motoru yeniden başlatılıyor...")
                        stop_bot_engine()
                        time.sleep(3)
                        threading.Thread(target=start_bot_engine, daemon=True).start()
                        send_reply(chat_id, "✅ *OKX Ultra Sanal Ticaret Modunda Yeniden Başlatıldı!*")
                    else:
                        send_reply(chat_id, "✅ *Çalışma Modu: Sanal Ticaret (Demo) olarak ayarlandı.*")
                        
                elif command == '/gercekmod':
                    from config import save_demo_mode
                    save_demo_mode(False)
                    if is_bot_running():
                        send_reply(chat_id, "🔄 *OKX Ultra Gerçek Ticaret Moduna Geçiliyor...*\nBağlantıların güncellenmesi için bot motoru yeniden başlatılıyor...")
                        stop_bot_engine()
                        time.sleep(3)
                        threading.Thread(target=start_bot_engine, daemon=True).start()
                        send_reply(chat_id, "✅ *OKX Ultra Gerçek Ticaret Modunda Yeniden Başlatıldı!*")
                    else:
                        send_reply(chat_id, "✅ *Çalışma Modu: Gerçek Ticaret olarak ayarlandı.*")

                elif command == '/yardim':
                    help_txt = "📚 *OKX Ultra Komut Listesi:*\n\n" \
                               "🚀 `/baslat` - Bot motorunu çalıştırır.\n" \
                               "🛑 `/durdur` - Bot motorunu durdurur.\n" \
                               "🔒 `/tekislem` - Tek pozisyon limitini açar.\n" \
                               "🔓 `/cokluislem` - Çoklu paralel pozisyon moduna geçer.\n" \
                               "📊 `/durum` - Bakiye, açık işlemler ve parite bilgilerini döner.\n" \
                               "📈 `/acik` - Sadece açık pozisyonların detaylı durumunu gösterir.\n" \
                               "🔍 `/rehbertablo` - Aktif parite optimizasyon parametrelerini listeler.\n" \
                               "🧪 `/sanalmod` - OKX Sanal Ticaret (Demo) moduna geçer.\n" \
                               "💰 `/gercekmod` - OKX Gerçek Ticaret moduna geçer.\n" \
                               "➕ `/ekle <parite>` - Listeye yeni coin ekler ve anında optimize eder.\n" \
                               "➖ `/sil <parite>` - Listeden coin siler."
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
        
        # Check if Telegram is configured
        if config.TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN" or not config.TELEGRAM_CHAT_ID:
            print("[Telegram Bot Warning] Telegram credentials not configured in config.py. Command listener disabled.")
            return
            
        # Start command listener in a daemon thread
        bot_thread = threading.Thread(target=telegram_polling_loop, daemon=True)
        bot_thread.start()
