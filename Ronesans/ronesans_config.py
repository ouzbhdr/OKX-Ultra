import os
import sys

# --- Varsayılan Fallback Anahtarlar (Yedekler) ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_KEY")

DEMO_OKX_API_KEY = os.getenv("DEMO_OKX_API_KEY", "YOUR_DEMO_OKX_API_KEY")
DEMO_OKX_SECRET_KEY = os.getenv("DEMO_OKX_SECRET_KEY", "YOUR_DEMO_OKX_SECRET_KEY")
DEMO_OKX_PASSPHRASE = os.getenv("DEMO_OKX_PASSPHRASE", "YOUR_DEMO_OKX_PASSPHRASE")

REAL_OKX_API_KEY = os.getenv("REAL_OKX_API_KEY", "YOUR_REAL_OKX_API_KEY")
REAL_OKX_SECRET_KEY = os.getenv("REAL_OKX_SECRET_KEY", "YOUR_REAL_OKX_SECRET_KEY")
REAL_OKX_PASSPHRASE = os.getenv("REAL_OKX_PASSPHRASE", "YOUR_REAL_OKX_PASSPHRASE")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "True").lower() == "true"

# --- Dinamik Miras Alma (Eski config'den canlı oku) ---
# kodlar/config.py dosyasına ulaşıp güncel anahtarları çekmeyi dener
parent_config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'kodlar'))
sys.path.append(parent_config_path)
try:
    import config as parent_config
    SUPABASE_URL = getattr(parent_config, 'SUPABASE_URL', SUPABASE_URL)
    SUPABASE_KEY = getattr(parent_config, 'SUPABASE_KEY', SUPABASE_KEY)
    DEMO_OKX_API_KEY = getattr(parent_config, 'DEMO_OKX_API_KEY', DEMO_OKX_API_KEY)
    DEMO_OKX_SECRET_KEY = getattr(parent_config, 'DEMO_OKX_SECRET_KEY', DEMO_OKX_SECRET_KEY)
    DEMO_OKX_PASSPHRASE = getattr(parent_config, 'DEMO_OKX_PASSPHRASE', DEMO_OKX_PASSPHRASE)
    REAL_OKX_API_KEY = getattr(parent_config, 'REAL_OKX_API_KEY', REAL_OKX_API_KEY)
    REAL_OKX_SECRET_KEY = getattr(parent_config, 'REAL_OKX_SECRET_KEY', REAL_OKX_SECRET_KEY)
    REAL_OKX_PASSPHRASE = getattr(parent_config, 'REAL_OKX_PASSPHRASE', REAL_OKX_PASSPHRASE)
    TELEGRAM_BOT_TOKEN = getattr(parent_config, 'TELEGRAM_BOT_TOKEN', TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = getattr(parent_config, 'TELEGRAM_CHAT_ID', TELEGRAM_CHAT_ID)
    ENABLE_TELEGRAM = getattr(parent_config, 'ENABLE_TELEGRAM', ENABLE_TELEGRAM)
    print("[Ronesans Config] Eski botun config.py dosyasındaki güncel anahtarlar başarıyla miras alındı.")
except Exception:
    print("[Ronesans Config Warning] Eski config.py bulunamadı, yerel yedek anahtarlar kullanılıyor.")

# --- Ronesans Strateji Ayarları ---
TARGET_PAIRS = [
    ("DASH", "ZEC", 180, 2.0, 4.0, 10.0),
    ("OL", "DOGE", 60, 2.0, 4.0, 10.0),
    ("DASH", "ICP", 60, 2.0, 4.5, 10.0)
]

RISK_PCT = 0.20             # Her işlemde cüzdanın maksimum %20'sini riske et
COINT_CHECK_INTERVAL = 16   # Her 4 saatte bir (16 bar) eşbütünleşme kontrolü yap
DATA_DIR = r"D:\OKX Ultra\veriler"

ACTIVE_PAIRS_FILE = os.path.join(os.path.dirname(__file__), "ronesans_active_pairs.json")
FLAG_FILE = os.path.join(os.path.dirname(__file__), "ronesans_bot_running.flag")
LOCK_FILE = os.path.join(os.path.dirname(__file__), "ronesans_bot.lock")

# Mod kontrolü (demo_mode.txt üst dizinden veya yerel okunabilir)
def get_demo_mode():
    parent_demo_file = os.path.join(os.path.dirname(__file__), "..", "demo_mode.txt")
    local_demo_file = os.path.join(os.path.dirname(__file__), "ronesans_demo_mode.txt")
    
    file_path = parent_demo_file if os.path.exists(parent_demo_file) else local_demo_file
    if not os.path.exists(file_path):
        try:
            with open(file_path, "w") as f:
                f.write("True")
        except Exception:
            pass
        return True
    try:
        with open(file_path, "r") as f:
            return f.read().strip() == "True"
    except Exception:
        return True

def save_demo_mode(is_demo):
    parent_demo_file = os.path.join(os.path.dirname(__file__), "..", "demo_mode.txt")
    local_demo_file = os.path.join(os.path.dirname(__file__), "ronesans_demo_mode.txt")
    
    file_path = parent_demo_file if os.path.exists(parent_demo_file) else local_demo_file
    try:
        with open(file_path, "w") as f:
            f.write("True" if is_demo else "False")
    except Exception:
        pass

DEMO_MODE = get_demo_mode()

# Python 3.7+ module level attribute getter to support dynamic switching
def __getattr__(name):
    is_demo = get_demo_mode()
    if name == "DEMO_MODE":
        return is_demo
    if name == "OKX_API_KEY":
        return DEMO_OKX_API_KEY if is_demo else REAL_OKX_API_KEY
    if name == "OKX_SECRET_KEY":
        return DEMO_OKX_SECRET_KEY if is_demo else REAL_OKX_SECRET_KEY
    if name == "OKX_PASSPHRASE":
        return DEMO_OKX_PASSPHRASE if is_demo else REAL_OKX_PASSPHRASE
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
