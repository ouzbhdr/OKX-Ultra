-- Supabase PostgreSQL Veritabanı Kurulum Kodları
-- Bu kodları Supabase panelindeki "SQL Editor" kısmına yapıştırıp "Run" diyerek çalıştırın.

-- 1. Rehber Tablo (guide_table)
CREATE TABLE IF NOT EXISTS public.guide_table (
    coin VARCHAR(50) PRIMARY KEY,
    most_period INT NOT NULL,
    most_pct NUMERIC(6, 4) NOT NULL,
    stoch_len INT NOT NULL,
    wma_len INT NOT NULL,
    opt_pnl NUMERIC(12, 2) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Aktif Pozisyonlar (active_positions)
CREATE TABLE IF NOT EXISTS public.active_positions (
    id SERIAL PRIMARY KEY,
    coin VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL, -- 'LONG' or 'SHORT'
    entry_price NUMERIC(16, 8) NOT NULL,
    position_size NUMERIC(16, 4) NOT NULL, -- USD size
    leverage INT NOT NULL,
    sl_price NUMERIC(16, 8) NOT NULL, -- Dynamic trailing stop price
    status VARCHAR(20) DEFAULT 'PENDING' NOT NULL, -- 'PENDING' (chasing) or 'FILLED'
    order_id VARCHAR(100),
    entry_time TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. İşlem Geçmişi (trade_history)
CREATE TABLE IF NOT EXISTS public.trade_history (
    id SERIAL PRIMARY KEY,
    coin VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    entry_price NUMERIC(16, 8) NOT NULL,
    exit_price NUMERIC(16, 8) NOT NULL,
    pnl_usd NUMERIC(16, 4) NOT NULL,
    pnl_pct NUMERIC(8, 4) NOT NULL,
    fees_paid NUMERIC(12, 4) NOT NULL,
    entry_time TIMESTAMP WITH TIME ZONE NOT NULL,
    exit_time TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    exit_reason VARCHAR(50) NOT NULL -- 'TRAILING_SL_HIT' or 'TREND_EXIT'
);

-- 4. Kara Liste (blacklist)
CREATE TABLE IF NOT EXISTS public.blacklist (
    coin VARCHAR(50) PRIMARY KEY,
    reason VARCHAR(255) NOT NULL,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Realtime bildirimleri aktif etmek isterseniz (Opsiyonel)
-- alter publication supabase_realtime add table public.active_positions;
