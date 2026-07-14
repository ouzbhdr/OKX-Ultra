import os
import sys
import time
import threading
from datetime import datetime, timedelta

# Reconfigure stdout/stderr to UTF-8 on Windows to prevent UnicodeEncodeError in console
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
import config
from holocron import DBHelper, send_telegram_alert

class FileLock:
    def __init__(self, filename):
        self.filename = filename
        self.fd = None

    def acquire(self):
        try:
            self.fd = os.open(self.filename, os.O_CREAT | os.O_WRONLY)
            if sys.platform.startswith('win'):
                import msvcrt
                try:
                    msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                    return True
                except IOError:
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except IOError:
                    return False
        except Exception:
            return False

    def release(self):
        if self.fd is not None:
            try:
                if sys.platform.startswith('win'):
                    import msvcrt
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None
from c3po import run_scanner
from mando import run_hunter
from solo import run_trader_loop, monitor_filled_positions, manage_pending_orders
from jawa import run_jawa

db = DBHelper()
FLAG_FILE = "bot_running.flag"

# Helper check for running state
def is_bot_running():
    return os.path.exists(FLAG_FILE)

# Modified Trader Loop that respects the flag
def run_trader_loop_controlled():
    import ccxt
    print("[Master] Trader daemon active. Monitoring loop started...")
    
    exchange = ccxt.okx({
        'apiKey': config.OKX_API_KEY,
        'secret': config.OKX_SECRET_KEY,
        'password': config.OKX_PASSPHRASE,
        'enableRateLimit': True
    })
    if config.DEMO_MODE:
        exchange.set_sandbox_mode(True)
        
    while is_bot_running():
        try:
            positions = db.get_active_positions()
            for pos in positions:
                if pos['status'] == 'PENDING':
                    manage_pending_orders(pos, exchange)
                elif pos['status'] == 'FILLED':
                    monitor_filled_positions(pos, exchange)
        except Exception as e:
            print(f"[Trader Error] Loop exception: {e}")
            
        # Check flag frequently (every 1 second) during sleep
        for _ in range(10):
            if not is_bot_running():
                break
            time.sleep(1)
            
    print("[Master] Trader loop stopped gracefully.")

# Modified Hunter Loop that respects the flag
def run_hunter_loop_controlled():
    print("[Master] Hunter loop active...")
    while is_bot_running():
        try:
            run_hunter()
        except Exception as e:
            print(f"[Master Error] Hunter execution failed: {e}")
            
        if not is_bot_running():
            break
            
        # Calculate seconds to sleep to align to the next 15-minute block + 5s buffer
        now = datetime.now()
        seconds_past_block = (now.minute % 15) * 60 + now.second + now.microsecond / 1_000_000.0
        sleep_needed = 900.0 - seconds_past_block + 5.0
        if sleep_needed <= 0:
            sleep_needed += 900.0
            
        print(f"[Master] Hunter sleeping for {sleep_needed:.1f} seconds to align with 15-minute block...")
        
        # Sleep in 1-second chunks to check the stop flag frequently
        for _ in range(int(sleep_needed)):
            if not is_bot_running():
                break
            time.sleep(1)
            
    print("[Master] Hunter loop stopped gracefully.")

# Modified Jawa Loop that respects the flag
def run_jawa_loop_controlled():
    print("[Master] Jawa loop active...")
    while is_bot_running():
        try:
            run_jawa()
        except Exception as e:
            print(f"[Master Error] Jawa execution failed: {e}")
            
        # Sleep for 24 hours (86400 seconds), check flag frequently
        for _ in range(86400):
            if not is_bot_running():
                break
            time.sleep(1)
            
    print("[Master] Jawa loop stopped gracefully.")

# Modified Scanner Loop that runs on fixed 42-hour slots:
# Monday 03:00, Wednesday 21:00, Friday 15:00, Sunday 09:00
def run_scanner_loop_controlled():
    print("[Master] Scanner loop active. Fixed 42-hour slots check started...")
    TIMESTAMP_FILE = "last_scan.txt"
    
    while is_bot_running():
        try:
            now = datetime.now()
            
            # Find Monday 03:00 of the current week
            days_to_subtract = now.weekday()
            monday_three = datetime(now.year, now.month, now.day, 3, 0, 0) - timedelta(days=days_to_subtract)
            
            # Target offsets from Monday 03:00:
            # Slot 0: Monday 03:00
            # Slot 1: Wednesday 21:00 (42h)
            # Slot 2: Friday 15:00 (84h)
            # Slot 3: Sunday 09:00 (126h)
            diff_hours = (now - monday_three).total_seconds() / 3600.0
            
            if diff_hours < 0:
                # We are before Monday 03:00 of this week. Last slot was Sunday 09:00 of previous week
                target_slot = monday_three - timedelta(days=7) + timedelta(hours=126)
            elif diff_hours >= 126:
                target_slot = monday_three + timedelta(hours=126)
            elif diff_hours >= 84:
                target_slot = monday_three + timedelta(hours=84)
            elif diff_hours >= 42:
                target_slot = monday_three + timedelta(hours=42)
            else:
                target_slot = monday_three
                
            last_run = None
            if os.path.exists(TIMESTAMP_FILE):
                try:
                    with open(TIMESTAMP_FILE, "r") as f:
                        last_run = datetime.fromisoformat(f.read().strip())
                except Exception:
                    pass
            
            # Run scan if never run, or if the last run was BEFORE the current target_slot
            if not last_run or last_run < target_slot:
                print(f"[Master] Target slot {target_slot} reached/missed. Running parameter optimizer...")
                run_scanner()
                with open(TIMESTAMP_FILE, "w") as f:
                    f.write(now.isoformat())
        except Exception as e:
            print(f"[Master Error] Scanner execution failed: {e}")
            
        # Sleep for 10 minutes (600 seconds), check flag frequently
        for _ in range(600):
            if not is_bot_running():
                break
            time.sleep(1)
            
    print("[Master] Scanner loop stopped gracefully.")

engine_started = False
engine_lock = threading.Lock()

def start_bot_engine():
    global engine_started
    with engine_lock:
        if engine_started:
            print("[Master] Bot engine is already running inside this process.")
            return
            
        if not is_bot_running():
            # Create flag file
            with open(FLAG_FILE, "w") as f:
                f.write(str(datetime.now()))
        
        engine_started = True
            
    print("=========================================================")
    print("🚀 OKX-ULTRA MASTER BOT ENGINE INITIALIZING")
    print("=========================================================")
    
    if not db.enabled:
        print("[Master Error] Database credentials not set. Exiting.")
        with engine_lock:
            if os.path.exists(FLAG_FILE):
                os.remove(FLAG_FILE)
            engine_started = False
        return
        
    send_telegram_alert("🚀 *OKX Ultra Konsol Başlatıldı*\nDemo Modu: " + str(config.DEMO_MODE) + "\nSistem aktif, telemetri akışı bekleniyor.")
    
    # 1. Run Jawa once on startup
    try:
        run_jawa()
    except Exception as e:
        print(f"[Master Warning] Initial Jawa failed: {e}")
        
    # 2. Check if guide_table has parameters
    try:
        res = db.client.table("guide_table").select("coin").execute()
        if not res.data:
            print("[Master] Guide table is empty. Running initial Scanner...")
            run_scanner()
    except Exception as e:
        print(f"[Master Warning] Failed check guide table: {e}. Running scanner.")
        run_scanner()

    # 3. Start Trader daemon thread
    trader_thread = threading.Thread(target=run_trader_loop_controlled, daemon=True)
    trader_thread.start()
    
    # 4. Start Jawa daemon thread
    jawa_thread = threading.Thread(target=run_jawa_loop_controlled, daemon=True)
    jawa_thread.start()
    
    # 5. Start Hunter loop in background thread
    hunter_thread = threading.Thread(target=run_hunter_loop_controlled, daemon=True)
    hunter_thread.start()
    
    # 6. Start Scanner weekly daemon thread
    scanner_thread = threading.Thread(target=run_scanner_loop_controlled, daemon=True)
    scanner_thread.start()

def stop_bot_engine():
    global engine_started
    with engine_lock:
        if os.path.exists(FLAG_FILE):
            os.remove(FLAG_FILE)
        engine_started = False
    print("[Master] Stop flag written. Backend will exit gracefully on next loop tick.")
    send_telegram_alert("🛑 *OKX Ultra Konsol Durduruldu*\nSistem pasif, işlemler askıya alındı.")

if __name__ == "__main__":
    lock = FileLock("bot.lock")
    if not lock.acquire():
        print("[Master Error] Another process is already running OKX-Ultra (bot.lock is locked). Exiting.")
        sys.exit(1)
        
    try:
        # Start Telegram Bot command listener in the background
        from hologram import start_telegram_listener
        start_telegram_listener()
        
        # Auto-start trading engine immediately on launch
        start_bot_engine()
        
        print("[Master] Headless (Ekransız) konsol modu aktif. Telegram dinleniyor. Çıkış için: Ctrl+C")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_bot_engine()
    finally:
        lock.release()
