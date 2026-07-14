import os
import sys
import pandas as pd
import numpy as np

def main():
    data_dir = r"D:\OKX Ultra\veriler\BTC"
    
    # 1. Load and concatenate historical data
    print("BTC verileri yükleniyor...")
    if not os.path.exists(data_dir):
        print(f"Hata: {data_dir} klasörü bulunamadı!")
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
        print(f"Son 1 yıllık veri kesiliyor (son {one_year_bars} bar)...")
        df = df.iloc[-one_year_bars:].reset_index(drop=True)
        
    # 3. Calculate 24h High and Low (96 bars of 15m)
    print("24 saatlik en yüksek/en düşük seviyeler (96 bar) hesaplanıyor...")
    df['high_24h'] = df['high'].rolling(96).max().shift(1)
    df['low_24h'] = df['low'].rolling(96).min().shift(1)
    df = df.dropna().reset_index(drop=True)
    
    # 4. Simulation Parameters
    START_CAPITAL = 100.0
    INITIAL_RISK_PCT = 0.05  # Safe 5% risk
    RISK_REWARD = 3.0  # 1:3 R/R target
    FEE_RATE = 0.0002
    MIN_SL_PCT = 0.003 # 0.3% min stop loss
    
    capital = START_CAPITAL
    parlay_step = 1 # 1 or 2
    previous_risk_amount = 0.0
    in_pos = False
    pos_type = None # 'L' or 'S'
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
    
    print("\nSimülasyon başlatılıyor...")
    
    for i in range(len(df)):
        close = df.loc[i, 'close']
        high = df.loc[i, 'high']
        low = df.loc[i, 'low']
        h24 = df.loc[i, 'high_24h']
        l24 = df.loc[i, 'low_24h']
        
        if not in_pos:
            # Check for BULLISH SWEEP (LONG)
            # Low goes below 24h low, but Close is above 24h low
            if low < l24 and close > l24:
                entry_price = close
                # Stop loss is the absolute bottom of the sweep with 0.05% buffer
                sl_dist = entry_price - (low * 0.9995)
                sl_pct = sl_dist / entry_price
                if sl_pct < MIN_SL_PCT:
                    sl_pct = MIN_SL_PCT
                    sl_dist = entry_price * MIN_SL_PCT
                    
                sl_price = entry_price - sl_dist
                tp_price = entry_price + RISK_REWARD * sl_dist
                
                # Parlay Risk
                if parlay_step == 1:
                    current_risk_amount = capital * INITIAL_RISK_PCT
                else:
                    current_risk_amount = previous_risk_amount * 3.0
                    
                pos_size = current_risk_amount / sl_pct
                capital -= pos_size * FEE_RATE
                in_pos = True
                pos_type = 'L'
                continue
                
            # Check for BEARISH SWEEP (SHORT)
            # High goes above 24h high, but Close is below 24h high
            if high > h24 and close < h24:
                entry_price = close
                sl_dist = (high * 1.0005) - entry_price
                sl_pct = sl_dist / entry_price
                if sl_pct < MIN_SL_PCT:
                    sl_pct = MIN_SL_PCT
                    sl_dist = entry_price * MIN_SL_PCT
                    
                sl_price = entry_price + sl_dist
                tp_price = entry_price - RISK_REWARD * sl_dist
                
                # Parlay Risk
                if parlay_step == 1:
                    current_risk_amount = capital * INITIAL_RISK_PCT
                else:
                    current_risk_amount = previous_risk_amount * 3.0
                    
                pos_size = current_risk_amount / sl_pct
                capital -= pos_size * FEE_RATE
                in_pos = True
                pos_type = 'S'
                
        else:
            # Manage active position
            if pos_type == 'L':
                if low <= sl_price:
                    # Loss
                    loss = current_risk_amount
                    fee_out = pos_size * (1 - (entry_price - sl_price)/entry_price) * FEE_RATE
                    capital -= (loss + fee_out)
                    
                    if parlay_step == 1:
                        step1_losses += 1
                    else:
                        step2_losses += 1
                        
                    parlay_step = 1 # Reset
                    in_pos = False
                    total_trades += 1
                elif high >= tp_price:
                    # Win
                    profit = current_risk_amount * RISK_REWARD
                    fee_out = pos_size * (1 + (tp_price - entry_price)/entry_price) * FEE_RATE
                    capital += (profit - fee_out)
                    
                    if parlay_step == 1:
                        step1_wins += 1
                        previous_risk_amount = current_risk_amount
                        parlay_step = 2 # Advance
                    else:
                        step2_wins += 1
                        parlay_step = 1 # Completed Parlay cycle!
                        
                    in_pos = False
                    total_trades += 1
            else:
                if high >= sl_price:
                    # Loss
                    loss = current_risk_amount
                    fee_out = pos_size * (1 - (sl_price - entry_price)/entry_price) * FEE_RATE
                    capital -= (loss + fee_out)
                    
                    if parlay_step == 1:
                        step1_losses += 1
                    else:
                        step2_losses += 1
                        
                    parlay_step = 1
                    in_pos = False
                    total_trades += 1
                elif low <= tp_price:
                    # Win
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
                    
        # Track drawdown
        if capital > max_capital:
            max_capital = capital
        dd = (max_capital - capital) / max_capital * 100
        if dd > max_drawdown:
            max_drawdown = dd
            
    print("\n" + "=" * 60)
    print("LIQUIDITY SWEEP PARLAY BACKTEST | BTC 15M (1 YIL)")
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
    print("--- ADIM 2 (3R Riskli İşlemler) ---")
    total_step2 = step2_wins + step2_losses
    wr2 = step2_wins / total_step2 * 100 if total_step2 > 0 else 0
    print(f"Toplam Adım 2 İşlemi : {total_step2} (Döngüye giren)")
    print(f"Adım 2 Kazanılan     : {step2_wins} (Döngüyü tamamlayan)")
    print(f"Adım 2 Kaybeden      : {step2_losses} (Döngüyü sıfırlayan)")
    print(f"Adım 2 Win Rate      : {wr2:.1f}%")
    print("=" * 60)

if __name__ == "__main__":
    main()
