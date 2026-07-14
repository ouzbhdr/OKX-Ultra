import os
import sys
import time
from datetime import datetime

# Path ayarlari
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import Ronesans.ronesans_config as r_config
from Ronesans.ronesans_telegram import send_telegram_alert
from Ronesans.ronesans_engine import run_ronesans_tick

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

def is_bot_running():
    return os.path.exists(r_config.FLAG_FILE)

def main():
    lock = FileLock(r_config.LOCK_FILE)
    if not lock.acquire():
        print("[Ronesans Error] Ronesans botunun baska bir kopyasi zaten calisiyor (bot.lock kilitli).")
        sys.exit(1)
        
    try:
        # Flag dosyasini olustur
        with open(r_config.FLAG_FILE, "w") as f:
            f.write(str(datetime.now()))
            
        # Telegram dinleyici arka plan threadini baslat
        from Ronesans.ronesans_hologram import start_telegram_listener
        start_telegram_listener()
            
        print("=========================================================")
        print("🚀 RONESANS COINTEGRATION BOT ENGINE INITIALIZED")
        print("=========================================================")
        print(f"Demo Modu: {r_config.DEMO_MODE}")
        print("Çıkış için: Ctrl+C")
        
        send_telegram_alert(f"🚀 *Rönesans Bot Başlatıldı*\nDemo Modu: {r_config.DEMO_MODE}\nStrateji: Cointegration Pairs Trading")
        
        # Ana döngü
        while is_bot_running():
            try:
                run_ronesans_tick()
            except Exception as e:
                print(f"[Ronesans Loop Error] {e}")
                
            # 60 saniye bekle (durdurma bayragini her saniye kontrol et)
            for _ in range(60):
                if not is_bot_running():
                    break
                time.sleep(1)
                
        print("[Ronesans] Döngü güvenli bir şekilde sonlandırıldı.")
        send_telegram_alert("🛑 *Rönesans Bot Durduruldu*\nSistem pasif, emir gönderimi askıya alındı.")
        
    except KeyboardInterrupt:
        print("\n[Ronesans] Kullanici tarafindan durduruldu. Cikiliyor...")
        if os.path.exists(r_config.FLAG_FILE):
            os.remove(r_config.FLAG_FILE)
        send_telegram_alert("🛑 *Rönesans Bot Durduruldu (Ctrl+C)*\nSistem pasif.")
    finally:
        if os.path.exists(r_config.FLAG_FILE):
            try:
                os.remove(r_config.FLAG_FILE)
            except Exception:
                pass
        lock.release()

if __name__ == "__main__":
    main()
