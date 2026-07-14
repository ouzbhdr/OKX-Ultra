import os
import sys
import pandas as pd
import numpy as np

def calculate_zigzag(high, low, deviation=0.01):
    n = len(high)
    zigzag_peaks = np.zeros(n)
    zigzag_troughs = np.zeros(n)
    
    last_low = low[0]
    last_high = high[0]
    last_low_idx = 0
    last_high_idx = 0
    is_up = True
    
    for i in range(1, n):
        if is_up:
            if high[i] > last_high:
                last_high = high[i]
                last_high_idx = i
            elif low[i] < last_high * (1.0 - deviation):
                # Peak confirmed at last_high_idx
                zigzag_peaks[last_high_idx] = last_high
                is_up = False
                last_low = low[i]
                last_low_idx = i
        else:
            if low[i] < last_low:
                last_low = low[i]
                last_low_idx = i
            elif high[i] > last_low * (1.0 + deviation):
                # Trough confirmed at last_low_idx
                zigzag_troughs[last_low_idx] = last_low
                is_up = True
                last_high = high[i]
                last_high_idx = i
                
    # Fill forward the last confirmed peaks and troughs to be usable at bar i
    last_peaks_ff = np.empty(n)
    last_troughs_ff = np.empty(n)
    curr_peak = np.nan
    curr_trough = np.nan
    
    for i in range(n):
        if zigzag_peaks[i] > 0:
            curr_peak = zigzag_peaks[i]
        if zigzag_troughs[i] > 0:
            curr_trough = zigzag_troughs[i]
        last_peaks_ff[i] = curr_peak
        last_troughs_ff[i] = curr_trough
        
    return last_peaks_ff, last_troughs_ff

def main():
    data_dir = r"D:\OKX Ultra\veriler\BTC"
    
    # 1. Load and concatenate historical data
    print("BTC verileri yükleniyor...")
    if not os.path.exists(data_dir):
        return
        
    csv_files = [f for f in os.listdir(data_dir) if f.startswith("historical_BTC_USDT_SWAP_") and f.endswith(".csv")]
    csv_files.sort()
    
    dfs = []
    for csv_file in csv_files:
        path = os.path.join(data_dir, csv_file)
        dfs.append(pd.read_csv(path))
        
    df = pd.concat(dfs, ignore_index=True)
    df = df.drop_duplicates(subset=['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # 2. Resample to 15m
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.set_index('datetime')
    df = df.resample('15Min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna().reset_index()
    
    one_year_bars = 365 * 96
    if len(df) > one_year_bars:
        df = df.iloc[-one_year_bars:].reset_index(drop=True)
        
    # 3. Calculate Yesterday's Daily OHLC
    df['date'] = df['datetime'].dt.date
    daily = df.groupby('date').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).rename(columns={
        'open': 'd_open',
        'high': 'd_high',
        'low': 'd_low',
        'close': 'd_close'
    })
    
    daily_yesterday = daily.shift(1)
    df = df.merge(daily_yesterday, on='date', how='left')
    df = df.dropna(subset=['d_open', 'd_high', 'd_low', 'd_close']).reset_index(drop=True)
    
    df['d_range'] = df['d_high'] - df['d_low']
    df['d_green'] = df['d_close'] >= df['d_open']
    
    # 4. Calculate ZigZag Peaks and Troughs (1% deviation)
    print("ZigZag tepeleri ve dipleri hesaplanıyor (1% sapma)...")
    last_peaks, last_troughs = calculate_zigzag(df['high'].values, df['low'].values, deviation=0.01)
    df['last_peak'] = last_peaks
    df['last_trough'] = last_troughs
    
    df = df.dropna(subset=['last_peak', 'last_trough']).reset_index(drop=True)
    
    # 5. Run simulation
    START_CAPITAL = 100.0
    RISK_REWARD = 3.0  # 1:3 R/R target as requested
    FEE_RATE = 0.0002
    MIN_SL_PCT = 0.005
    INITIAL_RISK_PCT = 0.05 # 5% risk
    
    capital = START_CAPITAL
    in_pos = False
    pos_type = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pos_size = 0.0
    risk_amount = 0.0
    
    total_trades = 0
    wins = 0
    losses = 0
    max_capital = START_CAPITAL
    max_drawdown = 0.0
    
    prev_close = df.loc[0, 'close']
    
    for i in range(1, len(df)):
        close = df.loc[i, 'close']
        high = df.loc[i, 'high']
        low = df.loc[i, 'low']
        
        d_green = df.loc[i, 'd_green']
        d_low = df.loc[i, 'd_low']
        d_high = df.loc[i, 'd_high']
        d_range = df.loc[i, 'd_range']
        
        last_peak = df.loc[i, 'last_peak']
        last_trough = df.loc[i, 'last_trough']
        
        if not in_pos:
            # LONG: Yesterday Green, Close in [d_low - d_range, d_low], Close crosses above last_peak (MSB Bullish)
            if d_green and (close >= d_low - d_range) and (close <= d_low):
                if prev_close <= last_peak and close > last_peak:
                    entry_price = close
                    # Stop loss is the confirmed ZigZag trough
                    sl_dist = entry_price - last_trough
                    sl_pct = sl_dist / entry_price
                    if sl_pct < MIN_SL_PCT:
                        sl_pct = MIN_SL_PCT
                        sl_dist = entry_price * MIN_SL_PCT
                        
                    sl_price = entry_price - sl_dist
                    tp_price = entry_price + RISK_REWARD * sl_dist
                    
                    risk_amount = capital * INITIAL_RISK_PCT
                    pos_size = risk_amount / sl_pct
                    capital -= pos_size * FEE_RATE
                    in_pos = True
                    pos_type = 'L'
                    prev_close = close
                    continue
                    
            # SHORT: Yesterday Red, Close in [d_high, d_high + d_range], Close crosses below last_trough (MSB Bearish)
            if not d_green and (close >= d_high) and (close <= d_high + d_range):
                if prev_close >= last_trough and close < last_trough:
                    entry_price = close
                    # Stop loss is the confirmed ZigZag peak
                    sl_dist = last_peak - entry_price
                    sl_pct = sl_dist / entry_price
                    if sl_pct < MIN_SL_PCT:
                        sl_pct = MIN_SL_PCT
                        sl_dist = entry_price * MIN_SL_PCT
                        
                    sl_price = entry_price + sl_dist
                    tp_price = entry_price - RISK_REWARD * sl_dist
                    
                    risk_amount = capital * INITIAL_RISK_PCT
                    pos_size = risk_amount / sl_pct
                    capital -= pos_size * FEE_RATE
                    in_pos = True
                    pos_type = 'S'
                    prev_close = close
                    continue
        else:
            if pos_type == 'L':
                if low <= sl_price:
                    capital -= (risk_amount + pos_size * (1.0 - (entry_price - sl_price)/entry_price) * FEE_RATE)
                    losses += 1; in_pos = False; total_trades += 1
                elif high >= tp_price:
                    capital += (risk_amount * RISK_REWARD - pos_size * (1.0 + (tp_price - entry_price)/entry_price) * FEE_RATE)
                    wins += 1; in_pos = False; total_trades += 1
            else:
                if high >= sl_price:
                    capital -= (risk_amount + pos_size * (1.0 - (sl_price - entry_price)/entry_price) * FEE_RATE)
                    losses += 1; in_pos = False; total_trades += 1
                elif low <= tp_price:
                    capital += (risk_amount * RISK_REWARD - pos_size * (1.0 + (entry_price - tp_price)/entry_price) * FEE_RATE)
                    wins += 1; in_pos = False; total_trades += 1
                    
        if capital > max_capital:
            max_capital = capital
        dd = (max_capital - capital) / max_capital * 100
        if dd > max_drawdown:
            max_drawdown = dd
            
        prev_close = close
        
    print("\n" + "=" * 60)
    print("ZIGZAG MSB + GRID PROJEKSİYON STRATEJİSİ | BTC 15M (1 YIL)")
    print("=" * 60)
    print(f"Başlangıç Kasası     : ${START_CAPITAL:.2f}")
    print(f"Bitiş Kasası         : ${capital:.2f}")
    print(f"Net Kar/Zarar        : {((capital - START_CAPITAL)/START_CAPITAL*100):+.2f}%")
    print(f"Maksimum Drawdown    : {max_drawdown:.2f}%")
    print(f"Toplam İşlem Adedi   : {total_trades}")
    print(f"Kazanan              : {wins}  |  Kaybeden: {losses}")
    wr = wins / total_trades * 100 if total_trades > 0 else 0
    print(f"Kazanma Oranı (WR)   : {wr:.1f}%")
    print("=" * 60)

if __name__ == "__main__":
    main()
