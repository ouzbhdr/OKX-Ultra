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
    
    if not csv_files:
        print("Hata: Geçmiş veri dosyaları bulunamadı!")
        return
        
    dfs = []
    for csv_file in csv_files:
        path = os.path.join(data_dir, csv_file)
        dfs.append(pd.read_csv(path))
        
    df = pd.concat(dfs, ignore_index=True)
    df = df.drop_duplicates(subset=['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # 2. Resample to 15m
    print(f"{len(df)} adet 1M bar 15M'e resample ediliyor...")
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
    else:
        print(f"Veri seti 1 yıldan kısa ({len(df)} bar), tüm veri kullanılıyor.")
        
    # 3. Calculate Donchian Channel & Volume indicators
    print("Göstergeler hesaplanıyor (Donchian 20, Hacim Ortalaması 20)...")
    df['high_channel'] = df['high'].rolling(20).max().shift(1)
    df['low_channel'] = df['low'].rolling(20).min().shift(1)
    df['vol_mean'] = df['volume'].rolling(20).mean()
    
    # Drop rows with NaN channels
    df = df.dropna().reset_index(drop=True)
    
    # 4. Simulation Parameters
    START_CAPITAL = 100.0
    INITIAL_RISK_PCT = 0.10
    FEE_RATE = 0.0002 # 0.02% Maker fee
    MIN_SL_PCT = 0.005 # 0.5%
    
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
    
    capital_history = []
    
    print("\nSimülasyon başlatılıyor...")
    
    for i in range(len(df)):
        close = df.loc[i, 'close']
        high = df.loc[i, 'high']
        low = df.loc[i, 'low']
        volume = df.loc[i, 'volume']
        hc = df.loc[i, 'high_channel']
        lc = df.loc[i, 'low_channel']
        vol_mean = df.loc[i, 'vol_mean']
        
        if not in_pos:
            # Check for LONG signal
            if close > hc and volume > 1.5 * vol_mean:
                entry_price = close
                # Stop loss is the low of the 20-bar channel
                sl_dist = entry_price - lc
                sl_pct = sl_dist / entry_price
                if sl_pct < MIN_SL_PCT:
                    sl_pct = MIN_SL_PCT
                    sl_dist = entry_price * MIN_SL_PCT
                    
                sl_price = entry_price - sl_dist
                tp_price = entry_price + 3.0 * sl_dist
                
                # Risk calculation
                if parlay_step == 1:
                    current_risk_amount = capital * INITIAL_RISK_PCT
                else:
                    # Risk the gross profit of the previous step
                    current_risk_amount = previous_risk_amount * 3.0
                    
                # Position size
                pos_size = current_risk_amount / sl_pct
                # Pay entry fee
                capital -= pos_size * FEE_RATE
                
                in_pos = True
                pos_type = 'L'
                continue
                
            # Check for SHORT signal
            if close < lc and volume > 1.5 * vol_mean:
                entry_price = close
                # Stop loss is the high of the 20-bar channel
                sl_dist = hc - entry_price
                sl_pct = sl_dist / entry_price
                if sl_pct < MIN_SL_PCT:
                    sl_pct = MIN_SL_PCT
                    sl_dist = entry_price * MIN_SL_PCT
                    
                sl_price = entry_price + sl_dist
                tp_price = entry_price - 3.0 * sl_dist
                
                # Risk calculation
                if parlay_step == 1:
                    current_risk_amount = capital * INITIAL_RISK_PCT
                else:
                    current_risk_amount = previous_risk_amount * 3.0
                    
                pos_size = current_risk_amount / sl_pct
                # Pay entry fee
                capital -= pos_size * FEE_RATE
                
                in_pos = True
                pos_type = 'S'
                
        else:
            # Manage active position
            if pos_type == 'L':
                # Check for Loss (SL)
                if low <= sl_price:
                    # Close in loss
                    loss = current_risk_amount
                    fee_out = pos_size * (1 - (entry_price - sl_price)/entry_price) * FEE_RATE
                    capital -= (loss + fee_out)
                    
                    if parlay_step == 1:
                        step1_losses += 1
                    else:
                        step2_losses += 1
                        
                    parlay_step = 1 # Reset to step 1
                    in_pos = False
                    total_trades += 1
                    
                # Check for Profit (TP)
                elif high >= tp_price:
                    # Close in profit
                    profit = current_risk_amount * 3.0
                    fee_out = pos_size * (1 + (tp_price - entry_price)/entry_price) * FEE_RATE
                    capital += (profit - fee_out)
                    
                    if parlay_step == 1:
                        step1_wins += 1
                        previous_risk_amount = current_risk_amount
                        parlay_step = 2 # Advance to step 2
                    else:
                        step2_wins += 1
                        parlay_step = 1 # Completed Parlay cycle!
                        
                    in_pos = False
                    total_trades += 1
                    
            elif pos_type == 'S':
                # Check for Loss (SL)
                if high >= sl_price:
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
                    
                # Check for Profit (TP)
                elif low <= tp_price:
                    profit = current_risk_amount * 3.0
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
            
        capital_history.append(capital)
        
    print("\n" + "=" * 60)
    print("PARLAY DENEYSEL BACKTEST SONUÇLARI | BTC 15M (1 YIL)")
    print("=" * 60)
    print(f"Başlangıç Kasası     : ${START_CAPITAL:.2f}")
    print(f"Bitiş Kasası         : ${capital:.2f}")
    print(f"Net PnL              : {((capital - START_CAPITAL)/START_CAPITAL*100):+.2f}%")
    print(f"Maksimum Drawdown    : {max_drawdown:.2f}%")
    print(f"Toplam İşlem Adedi   : {total_trades}")
    print("-" * 60)
    print("--- ADIM 1 (1R Riskli İşlemler) ---")
    total_step1 = step1_wins + step1_losses
    wr1 = step1_wins / total_step1 * 100 if total_step1 > 0 else 0
    print(f"Toplam Adım 1 İşlemi : {total_step1}")
    print(f"Adım 1 Kazanılan     : {step1_wins}  |  Kaybedilen: {step1_losses}")
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
