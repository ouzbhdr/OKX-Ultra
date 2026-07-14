# OKX Ultra

OKX Ultra, OKX borsası üzerinde hem spot hem de vadeli işlemler için tasarlanmış, çoklu daemon mimarisine sahip gelişmiş bir algoritmik ticaret botu ve backtest platformudur.

## 🚀 Özellikler

* **Çoklu Daemon Yapısı (`run_bot.py`):**
  * **Trader (`solo.py`):** Açık pozisyonları ve bekleyen emirleri dinamik olarak takip eder (ccxt OKX entegrasyonu ile Demo ve Gerçek mod desteği).
  * **Hunter (`mando.py`):** 15 dakikalık grafik mum kapanışlarına göre hizalanmış sinyal tarayıcı.
  * **Jawa (`jawa.py`):** Günlük rutin işler ve kontroller.
  * **Scanner (`c3po.py`):** Belirli aralıklarla çalışan hiperparametre optimizasyon modülü.
* **Veritabanı Entegrasyonu (`holocron.py`):** Supabase üzerinde aktif pozisyonlar, strateji kılavuz parametreleri, işlem geçmişi ve kara liste yönetimi.
* **Telegram Arayüzü (`hologram.py`):** Bot durumunu sorgulama, parametre değiştirme ve anlık işlem bildirimleri (telemetri). Telegram komutları ile bot yönetimi.
* **Rönesans Modülü (`Ronesans/`):** Cointegration (eşbütünleşme) tabanlı parite ticareti (DASH-ZEC, OL-DOGE vb.) motoru.
* **Deneyler ve Backtest (`Deneyler/`):** Çeşitli grid, zigzag ve funding tabanlı simülasyon araçları ile sapma analizörleri.
* **MetaTrader 5 Desteği:** `Sadece bir deneme

---

## 🛠️ Kurulum ve Çalıştırma

### 1. Gereksinimler
Bağımlılıkları yükleyin:
```bash
pip install -r requirements.txt
```

### 2. Yapılandırma
Projenin kök dizininde bir `.env` dosyası oluşturun ve aşağıdaki değişkenleri tanımlayın:
```env
# Supabase
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

# OKX API Keys
DEMO_OKX_API_KEY=your_demo_api_key
DEMO_OKX_SECRET_KEY=your_demo_secret_key
DEMO_OKX_PASSPHRASE=your_demo_passphrase

REAL_OKX_API_KEY=your_real_api_key
REAL_OKX_SECRET_KEY=your_real_secret_key
REAL_OKX_PASSPHRASE=your_real_passphrase

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
ENABLE_TELEGRAM=True
```

### 3. Çalıştırma
Ana bot konsolunu başlatmak için:
```bash
python kodlar/run_bot.py
```

Rönesans eşbütünleşme botunu başlatmak için:
```bash
python Ronesans/ronesans_run.py
```
