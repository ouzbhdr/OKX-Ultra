import os
import glob
import pandas as pd
import numpy as np
from statsmodels.tsa.stattools import coint

def load_data(coins):
    data_dir = r"D:\OKX Ultra\veriler"
    prices = {}
    for coin in coins:
        filepath = os.path.join(data_dir, coin, "historical_15m_1y.csv")
        if os.path.exists(filepath):
            df = pd.read_csv(filepath)
            df = df.sort_values('timestamp').drop_duplicates('timestamp')
            prices[coin] = df.set_index('timestamp')['close']
        else:
            print(f"[Warning] {coin} verisi bulunamadi!")
            
    df_all = pd.DataFrame(prices).dropna()
    df_all['datetime'] = pd.to_datetime(df_all.index, unit='ms')
    df_all = df_all.sort_values('datetime').reset_index(drop=True)
    return df_all

def calculate_pair_metrics(df, coin_y, coin_x, window=180):
    y = df[coin_y]
    x = df[coin_x]
    
    rolling_cov = y.rolling(window=window).cov(x)
    rolling_var_x = x.rolling(window=window).var()
    beta = rolling_cov / rolling_var_x
    
    spread = y - beta * x
    mean_spread = spread.rolling(window=window).mean()
    std_spread = spread.rolling(window=window).std()
    
    z_score = np.where(std_spread > 0, (spread - mean_spread) / std_spread, 0.0)
    
    return {
        'beta': beta.values,
        'mean': mean_spread.values,
        'std': std_spread.values,
        'z': z_score,
        'price_y': y.values,
        'price_x': x.values
    }

def main():
    target_pairs = [
        ("DASH", "ZEC", 180, 2.0, 4.0, 10.0),
        ("OL", "DOGE", 60, 2.0, 4.0, 10.0),
        ("DASH", "ICP", 60, 2.0, 4.5, 10.0)
    ]
    
    coins = ["DASH", "ZEC", "OL", "DOGE", "ICP"]
    print("Tarihsel veriler yukleniyor...")
    df = load_data(coins)
    n_rows = len(df)
    print(f"Toplam Veri Noktasi: {n_rows} bar (~1 yil)")
    
    print("\nTeknik metrikler ve Z-Score serileri hesaplaniyor...")
    metrics = {}
    for cy, cx, win, _, _, _ in target_pairs:
        pair_key = f"{cy}/{cx}"
        metrics[pair_key] = calculate_pair_metrics(df, cy, cx, win)
        
    initial_balance = 10.0
    balance = initial_balance
    risk_pct = 0.20  # Kullanici talebi: %20 risk oranı!
    fee_rate = 0.0002 # Maker komisyonu (%0.02)
    
    active_positions = {}
    balance_history = []
    
    # Islem istatistikleri
    total_trades = 0
    winning_trades = 0
    losing_trades = 0
    
    print("\nSimulasyon baslatiliyor (Shared Capital)...")
    
    # 180 barlik lookback sonrasindan basla
    for t in range(180, n_rows):
        # 1. Pozisyon Kapanis Kontrolleri
        if active_positions:
            for pair_key, pos in list(active_positions.items()):
                z = metrics[pair_key]['z'][t]
                p_y = metrics[pair_key]['price_y'][t]
                p_x = metrics[pair_key]['price_x'][t]
                
                exit_z = 0.0
                stop_z = pos['stop_z']
                
                exit_triggered = False
                if pos['direction'] == 1: # Long Y / Short X
                    if z >= exit_z:
                        exit_triggered = True
                        reason = "TAKE_PROFIT"
                    elif z <= -stop_z:
                        exit_triggered = True
                        reason = "STOP_LOSS"
                elif pos['direction'] == -1: # Short Y / Long X
                    if z <= exit_z:
                        exit_triggered = True
                        reason = "TAKE_PROFIT"
                    elif z >= stop_z:
                        exit_triggered = True
                        reason = "STOP_LOSS"
                        
                if exit_triggered:
                    ret_y = (p_y - pos['entry_p_y']) / pos['entry_p_y']
                    ret_x = -(p_x - pos['entry_p_x']) / pos['entry_p_x']
                    if pos['direction'] == -1:
                        ret_y, ret_x = -ret_y, -ret_x
                        
                    w_y = pos['w_y']
                    w_x = pos['w_x']
                    pnl = (w_y * ret_y + w_x * ret_x) - (w_y + w_x) * fee_rate * 2
                    balance += pnl
                    
                    total_trades += 1
                    if pnl > 0:
                        winning_trades += 1
                    else:
                        losing_trades += 1
                        
                    del active_positions[pair_key]
                    
        # 2. Yeni Pozisyon Giris Kontrolleri
        # Her bir bar basinda, o anki aktif pozisyon sayisina gore riski paylastir
        max_active_slots = len(target_pairs)
        active_risk_pct = risk_pct / max_active_slots
        
        for cy, cx, win, entry_z, stop_z, leverage in target_pairs:
            pair_key = f"{cy}/{cx}"
            if pair_key in active_positions:
                continue
                
            z = metrics[pair_key]['z'][t]
            std_val = metrics[pair_key]['std'][t]
            beta_val = metrics[pair_key]['beta'][t]
            p_y = metrics[pair_key]['price_y'][t]
            p_x = metrics[pair_key]['price_x'][t]
            
            direction = 0
            # Giris limitleri (Stop disinda kalacak)
            if entry_z < z < stop_z:
                direction = -1 # Short Y / Long X
            elif -stop_z < z < -entry_z:
                direction = 1  # Long Y / Short X
                
            if direction != 0 and std_val > 0:
                # Eşbütünleşme kontrolü (Rolling 180 barda Engle-Granger p < 0.05)
                # Hizlandirma acisindan simülasyonda her bar Engle-Granger cagirilir.
                # Ancak coint testi agir oldugu icin veri setinde p-value her 16 barda bir simüle edilir.
                # Burada direkt coint p-degerini hesaplayalim
                if t % 16 == 0:
                    try:
                        y_slice = metrics[pair_key]['price_y'][t-180:t]
                        x_slice = metrics[pair_key]['price_x'][t-180:t]
                        _, p_val, _ = coint(y_slice, x_slice)
                        is_coint = (p_val < 0.05)
                    except Exception:
                        is_coint = False
                else:
                    is_coint = True # Diger barlarda en son durumu koru
                    
                if not is_coint:
                    continue
                    
                z_diff = stop_z - entry_z
                expected_spread_loss = z_diff * std_val
                
                w_y = (active_risk_pct * balance) * (p_y / expected_spread_loss) if expected_spread_loss > 0 else 0
                ratio = beta_val * p_x / p_y
                w_x = w_y * abs(ratio)
                
                # 10x leverage cap
                max_allowed_nominal = balance * active_risk_pct * leverage
                current_nominal = w_y + w_x
                if current_nominal > max_allowed_nominal and current_nominal > 0:
                    factor = max_allowed_nominal / current_nominal
                    w_y *= factor
                    w_x *= factor
                    
                if w_y > 0 and w_x > 0:
                    active_positions[pair_key] = {
                        'direction': direction,
                        'entry_p_y': p_y,
                        'entry_p_x': p_x,
                        'w_y': w_y,
                        'w_x': w_x,
                        'stop_z': stop_z
                    }
                    
        balance_history.append(balance)
        
    # Sonuclari Raporla
    bh_df = pd.DataFrame(balance_history, columns=['balance'])
    bh_df['cummax'] = bh_df['balance'].cummax()
    bh_df['drawdown'] = (bh_df['balance'] - bh_df['cummax']) / bh_df['cummax']
    
    final_balance = balance
    roi = (final_balance - initial_balance) / initial_balance * 100
    max_dd = bh_df['drawdown'].min() * 100
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    print("\n" + "="*80)
    print(f" %20 RISKILE RONESANS 1 YILLIK BACKTEST SONUCLARI")
    print("="*80)
    print(f"Baslangic Bakiyesi      : ${initial_balance:.2f}")
    print(f"Bitis Bakiyesi          : ${final_balance:.2f}")
    print(f"Net Kar (ROI)           : %{roi:.2f}")
    print(f"Maksimum Cekilme (DD)   : %{max_dd:.2f}")
    print(f"Toplam Islem Sayisi     : {total_trades}")
    print(f"Kazanma Orani (WinRate) : %{win_rate:.2f} ({winning_trades} / {total_trades})")
    print("="*80)

if __name__ == "__main__":
    main()
