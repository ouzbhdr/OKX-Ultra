import os
import sys
import pandas as pd
import numpy as np

def main():
    ohlcv_path = r"D:\OKX Ultra\veriler\BTC\historical_15m_last_30d.csv"
    funding_path = r"btc_funding_history.csv"
    
    if not os.path.exists(ohlcv_path) or not os.path.exists(funding_path):
        print("Hata: Gerekli veri dosyaları bulunamadı!")
        return
        
    df = pd.read_csv(ohlcv_path)
    df_funding = pd.read_csv(funding_path)
    
    df = df.sort_values('timestamp').reset_index(drop=True)
    df_funding = df_funding.sort_values('timestamp').reset_index(drop=True)
    
    # Match funding rates
    funding_ts = df_funding['timestamp'].values
    funding_rates = df_funding['funding_rate'].values
    matched_rates = []
    for t in df['timestamp'].values:
        idx = np.searchsorted(funding_ts, t)
        if idx < len(funding_ts):
            matched_rates.append(funding_rates[idx])
        else:
            matched_rates.append(funding_rates[-1])
    df['funding_rate'] = matched_rates
    
    # Donchian Channel
    df['high_channel'] = df['high'].rolling(20).max().shift(1)
    df['low_channel'] = df['low'].rolling(20).min().shift(1)
    df['mid_channel'] = (df['high_channel'] + df['low_channel']) / 2.0
    df = df.dropna().reset_index(drop=True)
    
    # Sim Parameters
    START_CAPITAL = 100.0
    INITIAL_RISK_PCT = 0.10
    FEE_RATE = 0.0002
    MIN_SL_PCT = 0.005
    RISK_REWARD = 2.0  # 1:2 R/R target for both steps
    FUNDING_THRESHOLD = 0.0 # Any negative funding rate indicating more shorts
    
    capital = START_CAPITAL
    parlay_step = 1 # 1 (Breakout) or 2 (Pullback/Mean Reversion)
    previous_risk_amount = 0.0
    previous_direction = None # 'L' or 'S'
    
    in_pos = False
    pos_type = None # 'L' or 'S'
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pos_size = 0.0
    current_risk_amount = 0.0
    
    # Stats
    total_trades = 0
    step1_wins = 0
    step1_losses = 0
    step2_wins = 0
    step2_losses = 0
    max_capital = START_CAPITAL
    max_drawdown = 0.0
    
    for i in range(1, len(df)):
        close = df.loc[i, 'close']
        high = df.loc[i, 'high']
        low = df.loc[i, 'low']
        funding = df.loc[i, 'funding_rate']
        hc = df.loc[i, 'high_channel']
        lc = df.loc[i, 'low_channel']
        mc = df.loc[i, 'mid_channel']
        
        if not in_pos:
            if parlay_step == 1:
                # --- STEP 1: BREAKOUT ENTRY ---
                # LONG Breakout on Negative Funding
                if funding <= FUNDING_THRESHOLD and close > hc:
                    entry_price = close
                    sl_dist = entry_price - lc
                    sl_pct = sl_dist / entry_price
                    if sl_pct < MIN_SL_PCT:
                        sl_pct = MIN_SL_PCT
                        sl_dist = entry_price * MIN_SL_PCT
                        
                    sl_price = entry_price - sl_dist
                    tp_price = entry_price + RISK_REWARD * sl_dist
                    
                    current_risk_amount = capital * INITIAL_RISK_PCT
                    pos_size = current_risk_amount / sl_pct
                    capital -= pos_size * FEE_RATE
                    
                    in_pos = True
                    pos_type = 'L'
                    previous_direction = 'L'
                    
                # SHORT Breakout on Positive Funding (arbitrage momentum) or negative (we stick to same threshold)
                # Since we want short squeeze, let's focus on Long breakouts. But we can also look for Short breakdowns.
                # For short breakdown, let's check if funding is positive (more longs to squeeze).
                elif funding > FUNDING_THRESHOLD and close < lc:
                    entry_price = close
                    sl_dist = hc - entry_price
                    sl_pct = sl_dist / entry_price
                    if sl_pct < MIN_SL_PCT:
                        sl_pct = MIN_SL_PCT
                        sl_dist = entry_price * MIN_SL_PCT
                        
                    sl_price = entry_price + sl_dist
                    tp_price = entry_price - RISK_REWARD * sl_dist
                    
                    current_risk_amount = capital * INITIAL_RISK_PCT
                    pos_size = current_risk_amount / sl_pct
                    capital -= pos_size * FEE_RATE
                    
                    in_pos = True
                    pos_type = 'S'
                    previous_direction = 'S'
            
            elif parlay_step == 2:
                # --- STEP 2: PULLBACK ENTRY (VALUE BUY/SELL) ---
                # If previous direction was LONG: we wait for price to touch/fall below mid_channel (pullback)
                if previous_direction == 'L' and close <= mc:
                    entry_price = close
                    # SL is set to the low channel (bottom of value zone)
                    sl_dist = entry_price - lc
                    sl_pct = sl_dist / entry_price
                    if sl_pct < MIN_SL_PCT:
                        sl_pct = MIN_SL_PCT
                        sl_dist = entry_price * MIN_SL_PCT
                        
                    sl_price = entry_price - sl_dist
                    tp_price = entry_price + RISK_REWARD * sl_dist
                    
                    current_risk_amount = previous_risk_amount * RISK_REWARD
                    pos_size = current_risk_amount / sl_pct
                    capital -= pos_size * FEE_RATE
                    
                    in_pos = True
                    pos_type = 'L'
                    
                # If previous direction was SHORT: we wait for price to touch/rise above mid_channel
                elif previous_direction == 'S' and close >= mc:
                    entry_price = close
                    # SL is set to the high channel (top of value zone)
                    sl_dist = hc - entry_price
                    sl_pct = sl_dist / entry_price
                    if sl_pct < MIN_SL_PCT:
                        sl_pct = MIN_SL_PCT
                        sl_dist = entry_price * MIN_SL_PCT
                        
                    sl_price = entry_price + sl_dist
                    tp_price = entry_price - RISK_REWARD * sl_dist
                    
                    current_risk_amount = previous_risk_amount * RISK_REWARD
                    pos_size = current_risk_amount / sl_pct
                    capital -= pos_size * FEE_RATE
                    
                    in_pos = True
                    pos_type = 'S'
                    
        else:
            # Manage Position
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
                        parlay_step = 2 # Go to Step 2
                    else:
                        step2_wins += 1
                        parlay_step = 1 # Completed cycle!
                        
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
                    
        # Track DD
        if capital > max_capital:
            max_capital = capital
        dd = (max_capital - capital) / max_capital * 100
        if dd > max_drawdown:
            max_drawdown = dd
            
    print("\n" + "=" * 60)
    print("HYBRID PARLAY (BREAKOUT + PULLBACK) | BTC 15M (SON 30 GÜN)")
    print("=" * 60)
    print(f"Başlangıç Kasası     : ${START_CAPITAL:.2f}")
    print(f"Bitiş Kasası         : ${capital:.2f}")
    print(f"Net Kar/Zarar        : {((capital - START_CAPITAL)/START_CAPITAL*100):+.2f}%")
    print(f"Maksimum Drawdown    : {max_drawdown:.2f}%")
    print(f"Toplam İşlem Adedi   : {total_trades}")
    print("-" * 60)
    print("--- ADIM 1 (Kırılım/Expansion) ---")
    total_step1 = step1_wins + step1_losses
    wr1 = step1_wins / total_step1 * 100 if total_step1 > 0 else 0
    print(f"Toplam Adım 1 İşlemi : {total_step1}")
    print(f"Adım 1 Kazanılan     : {step1_wins}  |  Kaybeden: {step1_losses}")
    print(f"Adım 1 Win Rate      : {wr1:.1f}%")
    print("-" * 60)
    print("--- ADIM 2 (Düzeltme/Contraction) ---")
    total_step2 = step2_wins + step2_losses
    wr2 = step2_wins / total_step2 * 100 if total_step2 > 0 else 0
    print(f"Toplam Adım 2 İşlemi : {total_step2}")
    print(f"Adım 2 Kazanılan     : {step2_wins} (Döngüyü tamamlayan)")
    print(f"Adım 2 Kaybeden      : {step2_losses} (Döngüyü sıfırlayan)")
    print(f"Adım 2 Win Rate      : {wr2:.1f}%")
    print("=" * 60)

if __name__ == "__main__":
    main()
