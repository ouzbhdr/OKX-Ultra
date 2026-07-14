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
    
    # Slice the last 1 year (approx 35040 bars of 15m)
    one_year_bars = 365 * 96
    if len(df) > one_year_bars:
        df = df.iloc[-one_year_bars:].reset_index(drop=True)
        
    # 3. Calculate 24h High/Low and 200 EMA
    print("Seviyeler ve 200 EMA hesaplanıyor...")
    df['high_24h'] = df['high'].rolling(96).max().shift(1)
    df['low_24h'] = df['low'].rolling(96).min().shift(1)
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
    df = df.dropna().reset_index(drop=True)
    
    # 4. Simulation Parameters
    START_CAPITAL = 100.0
    INITIAL_RISK_PCT = 0.05  # 5% risk
    RISK_REWARD = 2.0  # 1:2 R/R target for better probability
    FEE_RATE = 0.0002
    MIN_SL_PCT = 0.003
    
    capital = START_CAPITAL
    parlay_step = 1
    previous_risk_amount = 0.0
    in_pos = False
    pos_type = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pos_size = 0.0
    current_risk_amount = 0.0
    
    # Statistics
    total_trades = 0
    step1_wins = 0
    step1_losses = 0
    step2_wins = 0
    step2_losses = 0
    max_capital = START_CAPITAL
    max_drawdown = 0.0
    
    for i in range(len(df)):
        close = df.loc[i, 'close']
        high = df.loc[i, 'high']
        low = df.loc[i, 'low']
        h24 = df.loc[i, 'high_24h']
        l24 = df.loc[i, 'low_24h']
        ema = df.loc[i, 'ema_200']
        
        if not in_pos:
            # BULLISH SWEEP (LONG) - ONLY if price is above 200 EMA (Bullish Trend Pullback)
            if close > ema and low < l24 and close > l24:
                entry_price = close
                sl_dist = entry_price - (low * 0.9995)
                sl_pct = sl_dist / entry_price
                if sl_pct < MIN_SL_PCT:
                    sl_pct = MIN_SL_PCT
                    sl_dist = entry_price * MIN_SL_PCT
                    
                sl_price = entry_price - sl_dist
                tp_price = entry_price + RISK_REWARD * sl_dist
                
                if parlay_step == 1:
                    current_risk_amount = capital * INITIAL_RISK_PCT
                else:
                    current_risk_amount = previous_risk_amount * RISK_REWARD
                    
                pos_size = current_risk_amount / sl_pct
                capital -= pos_size * FEE_RATE
                in_pos = True
                pos_type = 'L'
                continue
                
            # BEARISH SWEEP (SHORT) - ONLY if price is below 200 EMA (Bearish Trend Pullback)
            if close < ema and high > h24 and close < h24:
                entry_price = close
                sl_dist = (high * 1.0005) - entry_price
                sl_pct = sl_dist / entry_price
                if sl_pct < MIN_SL_PCT:
                    sl_pct = MIN_SL_PCT
                    sl_dist = entry_price * MIN_SL_PCT
                    
                sl_price = entry_price + sl_dist
                tp_price = entry_price - RISK_REWARD * sl_dist
                
                if parlay_step == 1:
                    current_risk_amount = capital * INITIAL_RISK_PCT
                else:
                    current_risk_amount = previous_risk_amount * RISK_REWARD
                    
                pos_size = current_risk_amount / sl_pct
                capital -= pos_size * FEE_RATE
                in_pos = True
                pos_type = 'S'
                
        else:
            if pos_type == 'L':
                if low <= sl_price:
                    loss = current_risk_amount
                    fee_out = pos_size * (1 - (entry_price - sl_price)/entry_price) * FEE_RATE
                    capital -= (loss + fee_out)
                    if parlay_step == 1: step1_losses += 1
                    else: step2_losses += 1
                    parlay_step = 1
                    in_pos = False
                    total_trades += 1
                elif high >= tp_price:
                    profit = current_risk_amount * RISK_REWARD
                    fee_out = pos_size * (1 + (tp_price - entry_price)/entry_price) * FEE_RATE
                    capital += (profit - fee_out)
                    if parlay_step == 1:
                        step1_wins += 1
                        previous_risk_amount = current_risk_amount
                        parlay_step = 2
                    else:
                        step2_wins += 1
                        parlay_step = 1
                    in_pos = False
                    total_trades += 1
            else:
                if high >= sl_price:
                    loss = current_risk_amount
                    fee_out = pos_size * (1 - (sl_price - entry_price)/entry_price) * FEE_RATE
                    capital -= (loss + fee_out)
                    if parlay_step == 1: step1_losses += 1
                    else: step2_losses += 1
                    parlay_step = 1
                    in_pos = False
                    total_trades += 1
                elif low <= tp_price:
                    profit = current_risk_amount * RISK_REWARD
                    fee_out = pos_size * (1 + (entry_price - tp_price)/entry_price) * FEE_RATE
                    capital += (profit - fee_out)
                    if parlay_step == 1:
                        step1_wins += 1
                        previous_risk_amount = current_risk_amount
                        parlay_step = 2
                    else:
                        step2_wins += 1
                        parlay_step = 1
                    in_pos = False
                    total_trades += 1
                    
        if capital > max_capital:
            max_capital = capital
        dd = (max_capital - capital) / max_capital * 100
        if dd > max_drawdown:
            max_drawdown = dd
            
    print("\n" + "=" * 60)
    print("TREND ALIGN LIQUIDITY SWEEP PARLAY | BTC 15M (1 YIL)")
    print("=" * 60)
    print(f"Başlangıç Kasası     : ${START_CAPITAL:.2f}")
    print(f"Bitiş Kasası         : ${capital:.2f}")
    print(f"Net Kar/Zarar        : {((capital - START_CAPITAL)/START_CAPITAL*100):+.2f}%")
    print(f"Maksimum Drawdown    : {max_drawdown:.2f}%")
    print(f"Toplam İşlem Adedi   : {total_trades}")
    print("-" * 60)
    print("--- ADIM 1 (1R Riskli İşlemler) ---")
    total_step1 = step1_wins + step1_losses
    wr1 = step1_wins / total_step1 * 100 if total_step1 > 0 else 0
    print(f"Toplam Adım 1 İşlemi : {total_step1}")
    print(f"Adım 1 Kazanılan     : {step1_wins}  |  Kaybeden: {step1_losses}")
    print(f"Adım 1 Win Rate      : {wr1:.1f}%")
    print("-" * 60)
    print("--- ADIM 2 (2R Riskli İşlemler) ---")
    total_step2 = step2_wins + step2_losses
    wr2 = step2_wins / total_step2 * 100 if total_step2 > 0 else 0
    print(f"Toplam Adım 2 İşlemi : {total_step2}")
    print(f"Adım 2 Kazanılan     : {step2_wins} (Döngüyü tamamlayan)")
    print(f"Adım 2 Kaybeden      : {step2_losses} (Döngüyü sıfırlayan)")
    print(f"Adım 2 Win Rate      : {wr2:.1f}%")
    print("=" * 60)

if __name__ == "__main__":
    main()
