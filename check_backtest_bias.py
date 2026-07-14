import os
import sys
import pandas as pd
import numpy as np

MOST_PERIODS  = [8, 13, 21, 34]
MOST_PCTS     = [0.003, 0.005, 0.008, 0.010, 0.012, 0.015]
STOCH_PERIODS = [7, 14, 21, 28]
WMA_PERIODS   = [5, 9]

RISK_PCT      = 0.10
MIN_SL_PCT    = 0.005
FEE_MAKER     = 0.0002
START_CAPITAL = 20.0
FIXED_RISK    = 2.0

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
    
    # 1H EMA 200
    ema_trend = df['close'].ewm(span=200, adjust=False).mean().values
    
    # ADX(14)
    adx = calc_adx(df, 14)
    
    return line1, line2, k1, k2, trend, ift, ema_trend, adx

def run_backtest(df_dict, use_correction=True):
    # Fixed parameters to run fast and compare directly
    p, pct, slen, wlen = 21, 0.005, 28, 5
    
    coin_data = {}
    for base, df in df_dict.items():
        l1, l2, k1, k2, tr, ift, ema_trend, adx = calc_indicators(df, p, pct, slen, wlen)
        coin_data[base] = {
            'l1': l1, 'l2': l2, 'k1': k1, 'k2': k2, 'trend': tr, 'ift': ift,
            'ema_trend': ema_trend, 'adx': adx,
            'close': df['close'].values, 'low': df['low'].values, 'high': df['high'].values,
            'ts': df['timestamp'].values,
            'ts_idx': {ts: i for i, ts in enumerate(df['timestamp'].values)}
        }
        
    common_ts = None
    for data in coin_data.values():
        s = set(data['ts'])
        common_ts = s if common_ts is None else common_ts & s
    common_ts = sorted(common_ts)
    
    capital = START_CAPITAL
    open_pos = {}
    trades = 0; wins = 0; losses = 0; fees = 0.0
    
    for t_pos, ts in enumerate(common_ts):
        bar = {b: data['ts_idx'][ts] for b, data in coin_data.items() if ts in data['ts_idx']}
        
        # Manage open positions
        to_close = []
        for base, pos in open_pos.items():
            if base not in bar: continue
            i = bar[base]
            d = coin_data[base]
            pt = pos['pt']; sl = pos['sl']; ep = pos['ep']; ps = pos['pos_size']
            
            if pt == 'L':
                tp = pos.get('tp', ep * 1.5)
                # Check TP first
                if d['high'][i] >= tp:
                    pnl_pct = (tp - ep) / ep
                    fee_out = ps * (1 + pnl_pct) * FEE_MAKER
                    net = ps * pnl_pct - fee_out
                    to_close.append((base, net, fee_out))
                elif d['low'][i] <= sl:
                    pnl_pct = (sl - ep) / ep
                    fee_out = ps * (1 + pnl_pct) * FEE_MAKER
                    net = ps * pnl_pct - fee_out
                    to_close.append((base, net, fee_out))
                else:
                    # Update trailing stop
                    trail_sl = d['l1'][i]
                    if use_correction:
                        if trail_sl >= d['close'][i]:
                            trail_sl = sl
                    
                    if trail_sl > sl: 
                        pos['sl'] = trail_sl
                        sl = trail_sl
            else:
                tp = pos.get('tp', ep * 0.5)
                # Check TP first
                if d['low'][i] <= tp:
                    pnl_pct = (ep - tp) / ep
                    fee_out = ps * (1 + pnl_pct) * FEE_MAKER
                    net = ps * pnl_pct - fee_out
                    to_close.append((base, net, fee_out))
                elif d['high'][i] >= sl:
                    pnl_pct = (ep - sl) / ep
                    fee_out = ps * (1 + pnl_pct) * FEE_MAKER
                    net = ps * pnl_pct - fee_out
                    to_close.append((base, net, fee_out))
                else:
                    trail_sl = d['l2'][i]
                    if use_correction:
                        if trail_sl <= d['close'][i]:
                            trail_sl = sl
                            
                    if trail_sl < sl:
                        pos['sl'] = trail_sl
                        sl = trail_sl
                    
        for base, net, fee_out in to_close:
            capital += net
            fees += fee_out; trades += 1
            if net > 0: wins += 1
            else: losses += 1
            del open_pos[base]
            
        # New signals
        for base, i in bar.items():
            if base in open_pos: continue
            d = coin_data[base]
            k1a = np.where(d['k1'][:i+1])[0]
            k2a = np.where(d['k2'][:i+1])[0]
            
            # Filters
            if use_correction:
                is_trend_ok = d['close'][i] > d['ema_trend'][i]
                is_adx_ok = d['adx'][i] >= 25
                recent_limit = 5
            else:
                is_trend_ok = True
                is_adx_ok = True
                recent_limit = 20
            
            # LONG
            if d['trend'][i] and len(k1a) > 0 and (i - k1a[-1] <= recent_limit) and is_trend_ok and is_adx_ok:
                w = d['ift'][max(0, int(k1a[-1])-3):i+1]
                if (w <= -0.5).sum() >= 2 and (w > -0.5).sum() >= 1:
                    ep = d['close'][i]
                    raw_sl = d['l1'][i]
                    
                    sl_pct = (ep - raw_sl) / ep
                    sl_pct = max(MIN_SL_PCT, sl_pct)
                    
                    if use_correction:
                        sl = ep * (1.0 - sl_pct)
                        tp = ep * (1.0 + 2.0 * sl_pct) # 2R TP
                    else:
                        sl = raw_sl
                        tp = ep * 1.5
                        
                    ps = FIXED_RISK / sl_pct
                    fee_in = ps * FEE_MAKER
                    capital -= fee_in; fees += fee_in
                    open_pos[base] = {'pt':'L','ep':ep,'sl':sl,'tp':tp,'pos_size':ps}
                    continue
                    
            # Filters for SHORT
            if use_correction:
                is_trend_ok = d['close'][i] < d['ema_trend'][i]
            else:
                is_trend_ok = True
                
            # SHORT
            if not d['trend'][i] and len(k2a) > 0 and (i - k2a[-1] <= recent_limit) and is_trend_ok and is_adx_ok:
                w = d['ift'][max(0, int(k2a[-1])-3):i+1]
                if (w >= 0.5).sum() >= 2 and (w < 0.5).sum() >= 1:
                    ep = d['close'][i]
                    raw_sl = d['l2'][i]
                    
                    sl_pct = (raw_sl - ep) / ep
                    sl_pct = max(MIN_SL_PCT, sl_pct)
                    
                    if use_correction:
                        sl = ep * (1.0 + sl_pct)
                        tp = ep * (1.0 - 2.0 * sl_pct) # 2R TP
                    else:
                        sl = raw_sl
                        tp = ep * 0.5
                        
                    ps = FIXED_RISK / sl_pct
                    fee_in = ps * FEE_MAKER
                    capital -= fee_in; fees += fee_in
                    open_pos[base] = {'pt':'S','ep':ep,'sl':sl,'tp':tp,'pos_size':ps}
                    
    pnl = (capital - START_CAPITAL) / START_CAPITAL * 100
    wr = wins / trades * 100 if trades > 0 else 0
    return capital, pnl, trades, wins, losses, wr

def main():
    data_dir = r"D:\OKX Ultra\veriler"
    coins = ['BTC', 'ETH', 'SOL']
    
    # Load and resample data
    df_dict = {}
    print("Veriler yükleniyor...")
    for base in coins:
        coin_folder = os.path.join(data_dir, base)
        csv_files = [f for f in os.listdir(coin_folder) if f.startswith(f"historical_{base}_USDT_SWAP_") and f.endswith(".csv")]
        csv_files.sort()
        
        dfs = []
        for csv_file in csv_files:
            path = os.path.join(coin_folder, csv_file)
            dfs.append(pd.read_csv(path))
            
        df = pd.concat(dfs, ignore_index=True)
        df = df.drop_duplicates(subset=['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('datetime')
        df = df.resample('1h').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna().reset_index()
        df['timestamp'] = df['datetime'].astype(np.int64) // 10**6
        df_dict[base] = df
        
    print("\n--- Simülasyon Çalıştırılıyor (Düzeltmesiz Eski Mantık) ---")
    cap_old, pnl_old, t_old, w_old, l_old, wr_old = run_backtest(df_dict, use_correction=False)
    
    print("\n--- Simülasyon Çalıştırılıyor (DÜZELTİLMİŞ YENİ MANTIK) ---")
    cap_new, pnl_new, t_new, w_new, l_new, wr_new = run_backtest(df_dict, use_correction=True)
    
    print("\n" + "=" * 60)
    print("BACKTEST SAPMA KARŞILAŞTIRMA SONUÇLARI (3 YILLIK BTC-ETH-SOL)")
    print("=" * 60)
    print(f"ESKİ MANTIK (Hatalı Stoplu):")
    print(f"  Bitiş Kasası : ${cap_old:.2f} ({pnl_old:+.2f}%)")
    print(f"  Toplam İşlem : {t_old} | WR: {wr_old:.1f}% (Win: {w_old}, Loss: {l_old})")
    print("-" * 60)
    print(f"YENİ MANTIK (Düzeltilmiş Güvenli Stoplu):")
    print(f"  Bitiş Kasası : ${cap_new:.2f} ({pnl_new:+.2f}%)")
    print(f"  Toplam İşlem : {t_new} | WR: {wr_new:.1f}% (Win: {w_new}, Loss: {l_new})")
    print("=" * 60)

if __name__ == "__main__":
    main()
