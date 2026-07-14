"""
OKX Ultra - Coklu Coin Shared Capital Backtest
Tek havuz, tum coinler ortak kapital kullanir.
Yeni pozisyon acilirken sadece FREE kapitalin %10'u riske edilir.
"""

import os
import pandas as pd
import numpy as np

MOST_PERIODS  = [8, 13, 21, 34]
MOST_PCTS     = [0.003, 0.005, 0.008, 0.010, 0.012, 0.015]
STOCH_PERIODS = [7, 14, 21, 28]
WMA_PERIODS   = [5, 9]

RISK_PCT      = 0.10
MIN_SL_PCT    = 0.005
FEE_MAKER     = 0.0002
LOOKBACK      = 720
WFO_STEP      = 168
START_CAPITAL = 20.0

combinations = [
    (p, pct, slen, wlen)
    for p in MOST_PERIODS for pct in MOST_PCTS
    for slen in STOCH_PERIODS for wlen in WMA_PERIODS
]

def wma(series, period):
    w = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

def calc_adx(df, period=14):
    df = df.copy()
    df['up'] = df['high'].diff()
    df['down'] = -df['low'].diff()
    
    df['+dm'] = np.where((df['up'] > df['down']) & (df['up'] > 0), df['up'], 0)
    df['-dm'] = np.where((df['down'] > df['up']) & (df['down'] > 0), df['down'], 0)
    
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = (df['high'] - df['close'].shift(1)).abs()
    df['tr3'] = (df['low'] - df['close'].shift(1)).abs()
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    
    tr_smooth = df['tr'].ewm(alpha=1/period, adjust=False).mean()
    dm_plus_smooth = df['+dm'].ewm(alpha=1/period, adjust=False).mean()
    dm_minus_smooth = df['-dm'].ewm(alpha=1/period, adjust=False).mean()
    
    df['+di'] = 100 * (dm_plus_smooth / tr_smooth)
    df['-di'] = 100 * (dm_minus_smooth / tr_smooth)
    
    df['dx'] = 100 * ((df['+di'] - df['-di']).abs() / (df['+di'] + df['-di']).abs())
    adx = df['dx'].ewm(alpha=1/period, adjust=False).mean()
    return adx.fillna(0).values

def calc_indicators(df, p, pct, slen, wlen):
    n = len(df)
    ema = df['close'].ewm(span=p, adjust=False).mean().values
    ortp = ema * (1 - pct); ortm = ema * (1 + pct)
    line1 = np.empty(n); line2 = np.empty(n)
    line1[0] = ortp[0]; line2[0] = ortm[0]
    for i in range(1, n):
        line1[i] = ortp[i] if ema[i] < line1[i-1] else max(line1[i-1], ortp[i])
        line2[i] = ortm[i] if ema[i] > line2[i-1] else min(line2[i-1], ortm[i])
    trend = np.zeros(n, dtype=bool)
    k1 = np.zeros(n, dtype=bool)
    k2 = np.zeros(n, dtype=bool)
    for i in range(1, n):
        k1[i] = ema[i-1] <= line2[i-1] and ema[i] > line2[i-1]
        k2[i] = ema[i-1] >= line1[i-1] and ema[i] < line1[i-1]
        trend[i] = True if k1[i] else (False if k2[i] else trend[i-1])
    ll = df['low'].rolling(slen).min()
    hh = df['high'].rolling(slen).max()
    stoch = 100.0 * (df['close'] - ll) / (hh - ll)
    v2 = wma(0.1 * (stoch - 50.0), wlen)
    e2v = np.exp(2 * v2)
    ift = ((e2v - 1) / (e2v + 1)).values
    
    ema_trend = df['close'].ewm(span=800, adjust=False).mean().values
    adx = calc_adx(df, 14)
    
    return line1, line2, k1, k2, trend, ift, ema_trend, adx

def eval_slice(arrays, start, end):
    """WFO parametre secimi icin hizli single-coin sim (kendi kasasiyla)"""
    line1, line2, k1, k2, trend, ift, ema_trend, adx, close_a, low_a, high_a = arrays
    cap = 100.0; inp = False; pt = None; ep = 0.0; ps = 0.0; sl = 0.0; tp = 0.0
    
    last_k1_idx = -1
    last_k2_idx = -1
    
    for idx in range(max(0, start - 20), start):
        if k1[idx]: last_k1_idx = idx
        if k2[idx]: last_k2_idx = idx

    for i in range(start, end):
        if k1[i]: last_k1_idx = i
        if k2[i]: last_k2_idx = i
        
        if not inp:
            is_trend_ok_long = close_a[i] > ema_trend[i]
            is_adx_ok = adx[i] >= 25
            
            if trend[i] and last_k1_idx != -1 and (i - last_k1_idx <= 5) and is_trend_ok_long and is_adx_ok:
                w_start = max(0, last_k1_idx - 3)
                under_neg_half = 0
                above_neg_half = 0
                for val in ift[w_start:i+1]:
                    if val <= -0.5:
                        under_neg_half += 1
                    else:
                        above_neg_half += 1
                
                if under_neg_half >= 2 and above_neg_half >= 1:
                    ep = close_a[i]
                    sl_pct = max(MIN_SL_PCT, (ep - line1[i]) / ep)
                    sl = ep * (1.0 - sl_pct)
                    tp = ep * (1.0 + 2.0 * sl_pct)
                    ps = cap * RISK_PCT / sl_pct
                    cap -= ps * FEE_MAKER
                    inp = True; pt = 'L'; continue
                    
            is_trend_ok_short = close_a[i] < ema_trend[i]
            if not trend[i] and last_k2_idx != -1 and (i - last_k2_idx <= 5) and is_trend_ok_short and is_adx_ok:
                w_start = max(0, last_k2_idx - 3)
                above_pos_half = 0
                under_pos_half = 0
                for val in ift[w_start:i+1]:
                    if val >= 0.5:
                        above_pos_half += 1
                    else:
                        under_pos_half += 1
                
                if above_pos_half >= 2 and under_pos_half >= 1:
                    ep = close_a[i]
                    sl_pct = max(MIN_SL_PCT, (line2[i] - ep) / ep)
                    sl = ep * (1.0 + sl_pct)
                    tp = ep * (1.0 - 2.0 * sl_pct)
                    ps = cap * RISK_PCT / sl_pct
                    cap -= ps * FEE_MAKER
                    inp = True; pt = 'S'; continue
        else:
            if pt == 'L':
                if high_a[i] >= tp:
                    pnl = ps * (tp - ep) / ep
                    cap += pnl - ps * (1 + (tp - ep) / ep) * FEE_MAKER; inp = False
                elif low_a[i] <= sl:
                    pnl = ps * (sl - ep) / ep
                    cap += pnl - ps * (1 + (sl - ep) / ep) * FEE_MAKER; inp = False
                else:
                    trail_sl = line1[i]
                    if trail_sl >= close_a[i]:
                        trail_sl = sl
                    if trail_sl > sl: 
                        sl = trail_sl
            else:
                if low_a[i] <= tp:
                    pnl = ps * (ep - tp) / ep
                    cap += pnl - ps * (1 + (ep - tp) / ep) * FEE_MAKER; inp = False
                elif high_a[i] >= sl:
                    pnl = ps * (ep - sl) / ep
                    cap += pnl - ps * (1 + (ep - sl) / ep) * FEE_MAKER; inp = False
                else:
                    trail_sl = line2[i]
                    if trail_sl <= close_a[i]:
                        trail_sl = sl
                    if trail_sl < sl:
                        sl = trail_sl
    return cap

def main():
    data_dir = r"D:\OKX Ultra\veriler"
    coins = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE']

    # --- Veri yukle ve indiktorleri hesapla ---
    coin_data = {}
    print("Veriler yukleniyor...")
    for base in coins:
        csv = os.path.join(data_dir, base, "historical_15m_last_30d.csv")
        if not os.path.exists(csv): continue
        df = pd.read_csv(csv)
        if len(df) < LOOKBACK + 50: continue
        precomp = {}
        for combo in combinations:
            p, pct, slen, wlen = combo
            l1, l2, k1, k2, tr, ift, ema_trend, adx = calc_indicators(df, p, pct, slen, wlen)
            precomp[combo] = (l1, l2, k1, k2, tr, ift, ema_trend, adx,
                              df['close'].values, df['low'].values, df['high'].values)
        coin_data[base] = {
            'precomp': precomp,
            'ts': df['timestamp'].values,
            'ts_idx': {ts: i for i, ts in enumerate(df['timestamp'].values)}
        }
        print(f"  {base}: {len(df)} bar, {len(combinations)} combo hazir.")

    # Ortak timestamp'leri bul (inner join)
    common_ts = None
    for data in coin_data.values():
        s = set(data['ts'])
        common_ts = s if common_ts is None else common_ts & s
    common_ts = sorted(common_ts)
    print(f"\nOrtak bar sayisi: {len(common_ts)}")

    # --- Shared capital simulasyonu ---
    free_cap   = START_CAPITAL   # kullanilabilir serbest kapital
    open_pos   = {}              # {base: {pt, ep, sl, sl_pct_entry, margin, pos_size}}
    active_c   = {b: None for b in coin_data}

    trades = 0; wins = 0; losses = 0; fees = 0.0; r_list = []

    def total_cap():
        return free_cap + sum(p['margin'] for p in open_pos.values())

    print("\nSimulasyon basliyor...")

    for t_pos, ts in enumerate(common_ts):
        bar = {b: data['ts_idx'][ts] for b, data in coin_data.items() if ts in data['ts_idx']}

        # WFO: her step'te her coin icin en iyi parametreyi sec
        if t_pos >= LOOKBACK and (t_pos - LOOKBACK) % WFO_STEP == 0:
            for base, i in bar.items():
                best_pnl = -1e9; best_c = None
                for combo, arrays in coin_data[base]['precomp'].items():
                    pnl = eval_slice(arrays, max(0, i-LOOKBACK), i)
                    if pnl > best_pnl: best_pnl = pnl; best_c = combo
                active_c[base] = best_c

        if t_pos < LOOKBACK:
            continue

        # --- 1. Acik pozisyonlari yonet ---
        to_close = []
        for base, pos in open_pos.items():
            if base not in bar or active_c[base] is None: continue
            i = bar[base]
            l1, l2, k1, k2, tr, ift, ema_trend, adx, close_a, low_a, high_a = coin_data[base]['precomp'][active_c[base]]
            pt = pos['pt']; sl = pos['sl']; ep = pos['ep']; ps = pos['pos_size']; tp = pos['tp']

            if pt == 'L':
                if high_a[i] >= tp:
                    pnl_pct = (tp - ep) / ep
                    fee_out = ps * (1 + pnl_pct) * FEE_MAKER
                    net = ps * pnl_pct - fee_out
                    to_close.append((base, pos['margin'], net, fee_out, pos['sl_pct_entry'], pnl_pct))
                elif low_a[i] <= sl:
                    pnl_pct = (sl - ep) / ep
                    fee_out = ps * (1 + pnl_pct) * FEE_MAKER
                    net = ps * pnl_pct - fee_out
                    to_close.append((base, pos['margin'], net, fee_out, pos['sl_pct_entry'], pnl_pct))
                else:
                    trail_sl = l1[i]
                    if trail_sl >= close_a[i]:
                        trail_sl = sl
                    if trail_sl > sl: 
                        pos['sl'] = trail_sl
                        sl = trail_sl
            else:
                if low_a[i] <= tp:
                    pnl_pct = (ep - tp) / ep
                    fee_out = ps * (1 + pnl_pct) * FEE_MAKER
                    net = ps * pnl_pct - fee_out
                    to_close.append((base, pos['margin'], net, fee_out, pos['sl_pct_entry'], pnl_pct))
                elif high_a[i] >= sl:
                    pnl_pct = (ep - sl) / ep
                    fee_out = ps * (1 + pnl_pct) * FEE_MAKER
                    net = ps * pnl_pct - fee_out
                    to_close.append((base, pos['margin'], net, fee_out, pos['sl_pct_entry'], pnl_pct))
                else:
                    trail_sl = l2[i]
                    if trail_sl <= close_a[i]:
                        trail_sl = sl
                    if trail_sl < sl: 
                        pos['sl'] = trail_sl
                        sl = trail_sl

        for base, margin, net, fee_out, sl_pct_e, pnl_pct in to_close:
            free_cap += margin + net   # margin geri + kar/zarar
            fees += fee_out; trades += 1
            r = (pnl_pct - FEE_MAKER - (1+pnl_pct)*FEE_MAKER) / sl_pct_e
            r_list.append(r)
            if net > 0: wins += 1
            else: losses += 1
            del open_pos[base]

        # --- 2. Yeni giris sinyalleri ---
        for base, i in bar.items():
            if base in open_pos: continue          # zaten pozisyon var
            if active_c[base] is None: continue
            if free_cap < 0.5: continue            # kapital bitti

            l1, l2, k1, k2, tr, ift, ema_trend, adx, close_a, low_a, high_a = coin_data[base]['precomp'][active_c[base]]
            k1a = np.where(k1[:i+1])[0]
            k2a = np.where(k2[:i+1])[0]

            # Filters
            is_trend_ok_long = close_a[i] > ema_trend[i]
            is_adx_ok = adx[i] >= 25

            # LONG
            if tr[i] and len(k1a) > 0 and (i - k1a[-1] <= 5) and is_trend_ok_long and is_adx_ok:
                w = ift[max(0, int(k1a[-1])-3):i+1]
                if (w <= -0.5).sum() >= 2 and (w > -0.5).sum() >= 1:
                    ep = close_a[i]
                    sl_pct = max(MIN_SL_PCT, (ep - l1[i]) / ep)
                    sl = ep * (1.0 - sl_pct)
                    tp = ep * (1.0 + 2.0 * sl_pct)
                    margin = free_cap * RISK_PCT       # free kasanin %10'u
                    ps = margin / sl_pct               # notional buyukluk
                    fee_in = ps * FEE_MAKER
                    free_cap -= (margin + fee_in); fees += fee_in
                    open_pos[base] = {'pt':'L','ep':ep,'sl':sl,'tp':tp,'pos_size':ps,'margin':margin,'sl_pct_entry':sl_pct}
                    continue

            # SHORT
            is_trend_ok_short = close_a[i] < ema_trend[i]
            if not tr[i] and len(k2a) > 0 and (i - k2a[-1] <= 5) and is_trend_ok_short and is_adx_ok:
                w = ift[max(0, int(k2a[-1])-3):i+1]
                if (w >= 0.5).sum() >= 2 and (w < 0.5).sum() >= 1:
                    ep = close_a[i]
                    sl_pct = max(MIN_SL_PCT, (l2[i] - ep) / ep)
                    sl = ep * (1.0 + sl_pct)
                    tp = ep * (1.0 - 2.0 * sl_pct)
                    margin = free_cap * RISK_PCT
                    ps = margin / sl_pct
                    fee_in = ps * FEE_MAKER
                    free_cap -= (margin + fee_in); fees += fee_in
                    open_pos[base] = {'pt':'S','ep':ep,'sl':sl,'tp':tp,'pos_size':ps,'margin':margin,'sl_pct_entry':sl_pct}

    final = total_cap()
    pnl   = (final - START_CAPITAL) / START_CAPITAL * 100
    wr    = wins / trades * 100 if trades > 0 else 0
    avgr  = float(np.mean(r_list)) if r_list else 0.0

    print("\n" + "=" * 50)
    print("SONUC - COKLU COIN | SHARED CAPITAL")
    print("=" * 50)
    print(f"Baslangic Kasa : ${START_CAPITAL:.2f}")
    print(f"Bitis Kasa     : ${final:,.2f}")
    print(f"Net PnL        : {pnl:+,.2f}%")
    print(f"Toplam Islem   : {trades}")
    print(f"Kazanan        : {wins}  |  Kaybeden: {losses}")
    print(f"Win Rate       : {wr:.1f}%")
    print(f"Ortalama R     : {avgr:+.4f}")
    print(f"Odenen Fee     : ${fees:.2f}")
    print(f"Ayni anda max  : {len(coin_data)} acik pozisyon")
    print("=" * 50)

if __name__ == "__main__":
    main()
