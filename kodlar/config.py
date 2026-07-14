import os

# Helper to load .env manually if it exists to avoid external dependencies
def _load_env_file():
    paths = [
        ".env",
        "../.env",
        "../../.env",
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]
    for p in paths:
        if os.path.exists(p) and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            os.environ[k] = v
                break
            except Exception:
                pass

_load_env_file()

# --- Supabase Credentials ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_KEY")

# --- OKX API Credentials ---
# Demo Trading Keys
DEMO_OKX_API_KEY = os.getenv("DEMO_OKX_API_KEY", "YOUR_DEMO_OKX_API_KEY")
DEMO_OKX_SECRET_KEY = os.getenv("DEMO_OKX_SECRET_KEY", "YOUR_DEMO_OKX_SECRET_KEY")
DEMO_OKX_PASSPHRASE = os.getenv("DEMO_OKX_PASSPHRASE", "YOUR_DEMO_OKX_PASSPHRASE")

# Real Trading Keys
REAL_OKX_API_KEY = os.getenv("REAL_OKX_API_KEY", "YOUR_REAL_OKX_API_KEY")
REAL_OKX_SECRET_KEY = os.getenv("REAL_OKX_SECRET_KEY", "YOUR_REAL_OKX_SECRET_KEY")
REAL_OKX_PASSPHRASE = os.getenv("REAL_OKX_PASSPHRASE", "YOUR_REAL_OKX_PASSPHRASE")

# --- Telegram Bot Settings ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "True").lower() == "true"

# --- Trading Strategy Parameters ---
RISK_PCT = 0.10         # Risk 10% of total capital per trade
MIN_SL_PCT = 0.0050     # 0.50% minimum Stop Loss distance to filter noise
MAX_LEVERAGE = 50       # Maximum OKX leverage cap

# --- Target Pairs Helper (Dynamic File Loading) ---
def get_target_coins():
    file_path = "target_coins.txt"
    default_coins = [
        'BTC-USDT-SWAP',
        'ETH-USDT-SWAP',
        'SOL-USDT-SWAP',
        'BNB-USDT-SWAP',
        'XRP-USDT-SWAP',
        'DOGE-USDT-SWAP'
    ]
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            f.write("\n".join(default_coins))
        return default_coins
    
    with open(file_path, "r") as f:
        return [line.strip() for line in f.read().splitlines() if line.strip()]

def save_target_coins(coins):
    file_path = "target_coins.txt"
    with open(file_path, "w") as f:
        f.write("\n".join(coins))

def get_demo_mode():
    file_path = "demo_mode.txt"
    if not os.path.exists(file_path):
        try:
            with open(file_path, "w") as f:
                f.write("True")
        except Exception:
            pass
        return True
    try:
        with open(file_path, "r") as f:
            val = f.read().strip()
            if not val:
                return True
            return val == "True"
    except Exception:
        return True

def save_demo_mode(is_demo):
    file_path = "demo_mode.txt"
    with open(file_path, "w") as f:
        f.write("True" if is_demo else "False")

# Python 3.7+ module level attribute getter
def __getattr__(name):
    if name == "TARGET_COINS":
        return get_target_coins()
    if name == "DEMO_MODE":
        return get_demo_mode()
    if name == "OKX_API_KEY":
        return DEMO_OKX_API_KEY if get_demo_mode() else REAL_OKX_API_KEY
    if name == "OKX_SECRET_KEY":
        return DEMO_OKX_SECRET_KEY if get_demo_mode() else REAL_OKX_SECRET_KEY
    if name == "OKX_PASSPHRASE":
        return DEMO_OKX_PASSPHRASE if get_demo_mode() else REAL_OKX_PASSPHRASE
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
