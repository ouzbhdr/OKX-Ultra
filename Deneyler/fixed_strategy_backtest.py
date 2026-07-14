import os
import sys
import pandas as pd
import numpy as np

MOST_PERIODS  = [8, 13, 21, 34]
MOST_PCTS     = [0.003, 0.005, 0.008, 0.010, 0.012, 0.015]
STOCH_PERIODS = [7, 14, 21, 28]
WMA_PERIODS   = [5, 9]

FEE_RATE = 0.0002
MIN_SL_PCT = 0.005

def wma(series, period):
    w = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)

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
    return line1, line2, k1, k2, trend, ift

def run_corrected_backtest(df, p, pct, slen, wlen, risk_pct=0.02):
    l1, l2, k1, k2, trend, ift = calc_indicators(df, p, pct, slen, wlen)
    close_arr = df['close'].values
    low_arr = df['low'].values
    high_arr = df['high'].values
    
    capital = 100.0
    in_pos = False
    pos_type = None
    entry_pr = 0.0
    sl_price_val = 0.0
    pos_sz = 0.0
    risk_amount = 0.0
    
    total_trades = 0
    wins = 0
    losses = 0
    max_capital = 100.0
    max_dd = 0.0
    
    k1_indices = []
    k2_indices = []
    
    for i in range(50, len(df)):
        if k1[i]: k1_indices.append(i)
        if k2[i]: k2_indices.append(i)
        
        if not in_pos:
            is_most_buy = trend[i]
            
            # LONG
            has_recent_buy = is_most_buy and len(k1_indices) > 0 and (i - k1_indices[-1] <= 20)
            if has_recent_buy:
                k1_idx = k1_indices[-1]
                start_w = max(0, k1_idx - 3)
                window_ift = ift[start_w : i + 1]
                below = sum(1 for val in window_ift if val <= -0.5)
                above = sum(1 for val in window_ift if val > -0.5)
                if below >= 2 and above >= 1:
                    entry_pr = close_arr[i]
                    sl_p = max(MIN_SL_PCT, (entry_pr - l1[i]) / entry_pr)
                    
                    # Stop loss correction (must be strictly below entry)
                    sl_price_val = entry_pr * (1.0 - sl_p)
                    
                    risk_amount = capital * risk_pct
                    pos_sz = risk_amount / sl_p
                    capital -= pos_sz * FEE_RATE
                    in_pos = True
                    pos_type = 'LONG'
                    continue
            
            # SHORT
            has_recent_sell = not is_most_buy and len(k2_indices) > 0 and (i - k2_indices[-1] <= 20)
            if has_recent_sell:
                k2_idx = k2_indices[-1]
                start_w = max(0, k2_idx - 3)
                window_ift = ift[start_w : i + 1]
                above = sum(1 for val in window_ift if val >= 0.5)
                below = sum(1 for val in window_ift if val < 0.5)
                if above >= 2 and below >= 1:
                    entry_pr = close_arr[i]
                    sl_p = max(MIN_SL_PCT, (l2[i] - entry_pr) / entry_pr)
                    
                    # Stop loss correction (must be strictly above entry)
                    sl_price_val = entry_pr * (1.0 + sl_p)
                    
                    risk_amount = capital * risk_pct
                    pos_sz = risk_amount / sl_p
                    capital -= pos_sz * FEE_RATE
                    in_pos = True
                    pos_type = 'SHORT'
                    
        else:
            # Manage exits
            if pos_type == 'LONG':
                trail_sl = l1[i]
                if trail_sl >= close_arr[i]:
                    trail_sl = sl_price_val
                sl_price_val = max(sl_price_val, trail_sl)
                
                is_sl = low_arr[i] <= sl_price_val
                is_sell = not trend[i] or k2[i]
                
                if is_sl:
                    pnl_pct = (sl_price_val - entry_pr) / entry_pr
                    capital += (pos_sz * pnl_pct) - (pos_sz * (1.0 + pnl_pct) * FEE_RATE)
                    losses += 1; in_pos = False; total_trades += 1
                elif is_sell:
                    pnl_pct = (close_arr[i] - entry_pr) / entry_pr
                    capital += (pos_sz * pnl_pct) - (pos_sz * (1.0 + pnl_pct) * FEE_RATE)
                    wins += 1; in_pos = False; total_trades += 1
                    
            else: # SHORT
                trail_sl = l2[i]
                if trail_sl <= close_arr[i]:
                    trail_sl = sl_price_val
                sl_price_val = min(sl_price_val, trail_sl)
                
                is_sl = high_arr[i] >= sl_price_val
                is_buy = trend[i] or k1[i]
                
                if is_sl:
                    pnl_pct = (entry_pr - sl_price_val) / entry_pr
                    capital += (pos_sz * pnl_pct) - (pos_sz * (1.0 + pnl_pct) * FEE_RATE)
                    losses += 1; in_pos = False; total_trades += 1
                elif is_buy:
                    pnl_pct = (entry_pr - close_arr[i]) / entry_pr
                    capital += (pos_sz * pnl_pct) - (pos_sz * (1.0 + pnl_pct) * FEE_RATE)
                    wins += 1; in_pos = False; total_trades += 1
                    
        if capital > max_capital:
            max_capital = capital
        dd = (max_capital - capital) / max_capital * 100
        if dd > max_dd:
            max_dd = dd
            
    pnl = (capital - 100.0)
    wr = wins / total_trades * 100 if total_trades > 0 else 0
    return capital, pnl, total_trades, wins, losses, wr, max_dd

def main():
    # We will test BTC, ETH, and SOL on the last 1 year of data
    data_dir = r"D:\OKX Ultra\veriler"
    coins = ['BTC', 'ETH', 'SOL']
    
    # 1. Optimal Parameters found by the bug-free optimizer
    # (We can use these parameters directly for the 1-year backtest)
    params_dict = {
        'BTC': (8, 0.003, 21, 9),
        'ETH': (8, 0.003, 21, 9), # Use similar tight parameters for ETH
        'SOL': (8, 0.003, 21, 9)
    }
    
    print("BTC-ETH-SOL verileri yükleniyor...")
    for base in coins:
        coin_folder = os.path.join(data_dir, base)
        if not os.path.exists(coin_folder):
            continue
            
        csv_files = [f for f in os.listdir(coin_folder) if f.startswith(f"historical_{base}_USDT_SWAP_") and f.endswith(".csv")]
        csv_files.sort()
        
        dfs = []
        for csv_file in csv_files:
            path = os.path.join(coin_folder, csv_file)
            dfs.append(pd.read_csv(path))
            
        df = pd.concat(dfs, ignore_index=True)
        df = df.drop_duplicates(subset=['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # Resample to 15m
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('datetime')
        df = df.resample('15Min').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna().reset_index()
        
        # 1 year data slice
        one_year_bars = 365 * 96
        if len(df) > one_year_bars:
            df = df.iloc[-one_year_bars:].reset_index(drop=True)
            
        p, pct, slen, wlen = params_dict[base]
        
        print(f"\nSimülasyon çalışıyor: {base} | MOST({p}, {pct*100:.1f}%) | IFT({slen}, {wlen})...")
        cap, pnl, trades, wins, losses, wr, max_dd = run_corrected_backtest(df, p, pct, slen, wlen, risk_pct=0.02) # Safe 2% risk
        
        print("=" * 65)
        print(f"Hatasız 1 Yıllık Backtest Sonucu: {base}")
        print("=" * 65)
        print(f"Başlangıç Kasası     : $100.00")
        print(f"Bitiş Kasası         : ${cap:.2f}")
        print(f"Net Kar/Zarar        : {pnl:+.2f}%")
        print(f"Maksimum Drawdown    : {max_dd:.2f}%")
        print(f"Toplam İşlem Adedi   : {trades}")
        print(f"Kazanan              : {wins}  |  Kaybeden: {losses}")
        print(f"Kazanma Oranı (WR)   : {wr:.1f}%")
        print("=" * 65)

if __name__ == "__main__":
    main()
