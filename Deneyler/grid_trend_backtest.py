import os
import sys
import pandas as pd
import numpy as np

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
    
    # 4. Calculate real-time 5-bar Fractal Swings
    df['is_swing_high'] = (df['high'].shift(2) > df['high'].shift(3)) & (df['high'].shift(2) > df['high'].shift(4)) & \
                          (df['high'].shift(2) > df['high'].shift(1)) & (df['high'].shift(2) > df['high'].shift(0))
                          
    df['is_swing_low'] = (df['low'].shift(2) < df['low'].shift(3)) & (df['low'].shift(2) < df['low'].shift(4)) & \
                         (df['low'].shift(2) < df['low'].shift(1)) & (df['low'].shift(2) < df['low'].shift(0))
                         
    last_sh_arr = np.empty(len(df))
    last_sl_arr = np.empty(len(df))
    last_sh = np.nan
    last_sl = np.nan
    
    for i in range(len(df)):
        if df.loc[i, 'is_swing_high']:
            last_sh = df.loc[i-2, 'high']
        if df.loc[i, 'is_swing_low']:
            last_sl = df.loc[i-2, 'low']
        last_sh_arr[i] = last_sh
        last_sl_arr[i] = last_sl
        
    df['last_sh'] = last_sh_arr
    df['last_sl'] = last_sl_arr
    df = df.dropna(subset=['last_sh', 'last_sl']).reset_index(drop=True)
    
    # 5. Run simulation (TREND-FOLLOWING DAILY BIAS)
    START_CAPITAL = 100.0
    RISK_REWARD = 2.0  # 1:2 R/R
    FEE_RATE = 0.0002
    MIN_SL_PCT = 0.005
    INITIAL_RISK_PCT = 0.05
    
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
        
        last_sh = df.loc[i, 'last_sh']
        last_sl = df.loc[i, 'last_sl']
        
        if not in_pos:
            # TREND-FOLLOWING LONG: Yesterday Green, Close inside [d_high, d_high + d_range], Close crosses above last_sh
            if d_green and (close >= d_high) and (close <= d_high + d_range):
                if prev_close <= last_sh and close > last_sh:
                    entry_price = close
                    sl_dist = entry_price - last_sl
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
                    
            # TREND-FOLLOWING SHORT: Yesterday Red, Close inside [d_low - d_range, d_low], Close crosses below last_sl
            if not d_green and (close >= d_low - d_range) and (close <= d_low):
                if prev_close >= last_sl and close < last_sl:
                    entry_price = close
                    sl_dist = last_sh - entry_price
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
    print("TREND TAKİPÇİ PROJEKSİYON STRATEJİSİ | BTC 15M (1 YIL)")
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
