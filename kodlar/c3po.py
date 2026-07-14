import os
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import config
from holocron import DBHelper, send_telegram_alert

db = DBHelper()

# Helper WMA
def wma(series, period):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

# Grid parameters
most_periods = [8, 13, 21, 34]
most_pcts = [0.003, 0.005, 0.008, 0.010, 0.012, 0.015]
stoch_periods = [7, 14, 21, 28]
wma_periods = [5, 9]

# Fast simulation for grid search evaluation
def evaluate_params(df, p, pct, slen, wlen):
    close_arr = df['close'].values
    low_arr = df['low'].values
    high_arr = df['high'].values
    
    # 1. MOST Calculation
    ema = df['close'].ewm(span=p, adjust=False).mean().values
    ortp = ema * (1 - pct)
    ortm = ema * (1 + pct)
    
    line1 = np.zeros(len(df))
    line2 = np.zeros(len(df))
    line1[0] = ortp[0]
    line2[0] = ortm[0]
    
    for i in range(1, len(df)):
        prev_l1 = line1[i-1]
        line1[i] = ortp[i] if ema[i] < prev_l1 else max(prev_l1, ortp[i])
        
        prev_l2 = line2[i-1]
        line2[i] = ortm[i] if ema[i] > prev_l2 else min(prev_l2, ortm[i])
        
    trend_state = np.zeros(len(df), dtype=bool)
    most_k1 = np.zeros(len(df), dtype=bool)
    most_k2 = np.zeros(len(df), dtype=bool)
    
    for i in range(1, len(df)):
        is_k1 = ema[i-1] <= line2[i-1] and ema[i] > line2[i-1]
        is_k2 = ema[i-1] >= line1[i-1] and ema[i] < line1[i-1]
        most_k1[i] = is_k1
        most_k2[i] = is_k2
        trend_state[i] = True if is_k1 else (False if is_k2 else trend_state[i-1])

    # 2. IFTSTOCH Calculation
    lowest_low = df['low'].rolling(window=slen).min()
    highest_high = df['high'].rolling(window=slen).max()
    stoch_k = 100 * (df['close'] - lowest_low) / (highest_high - lowest_low)
    v1 = 0.1 * (stoch_k - 50.0)
    v2 = wma(v1, wlen)
    ift = ((np.exp(2 * v2) - 1) / (np.exp(2 * v2) + 1)).values

    # 3. Simulate Long & Short trades
    sim_capital = 100.0
    in_pos = False
    pos_type = None
    entry_pr = 0.0
    pos_sz = 0.0
    sl_p = 0.0
    k1_indices = []
    k2_indices = []
    
    # We skip first 50 bars to stabilize indicators
    for i in range(50, len(df)):
        if most_k1[i]: k1_indices.append(i)
        if most_k2[i]: k2_indices.append(i)
        
        if not in_pos:
            is_most_buy = trend_state[i]
            
            # Check Long
            has_recent_buy = is_most_buy and len(k1_indices) > 0 and (i - k1_indices[-1] <= 20)
            if has_recent_buy:
                k1_idx = k1_indices[-1]
                start_w = max(0, k1_idx - 3)
                window_ift = ift[start_w : i + 1]
                below = sum(1 for val in window_ift if val <= -0.5)
                above = sum(1 for val in window_ift if val > -0.5)
                if below >= 2 and above >= 1:
                    in_pos = True
                    pos_type = 'LONG'
                    entry_pr = close_arr[i]
                    sl_p = max(0.0050, (entry_pr - line1[i]) / entry_pr)
                    sl_price_val = entry_pr * (1.0 - sl_p)
                    pos_sz = sim_capital * 0.10 / sl_p
                    sim_capital -= pos_sz * 0.0002
                    continue
            
            # Check Short
            has_recent_sell = not is_most_buy and len(k2_indices) > 0 and (i - k2_indices[-1] <= 20)
            if has_recent_sell:
                k2_idx = k2_indices[-1]
                start_w = max(0, k2_idx - 3)
                window_ift = ift[start_w : i + 1]
                above = sum(1 for val in window_ift if val >= 0.5)
                below = sum(1 for val in window_ift if val < 0.5)
                if above >= 2 and below >= 1:
                    in_pos = True
                    pos_type = 'SHORT'
                    entry_pr = close_arr[i]
                    sl_p = max(0.0050, (line2[i] - entry_pr) / entry_pr)
                    sl_price_val = entry_pr * (1.0 + sl_p)
                    pos_sz = sim_capital * 0.10 / sl_p
                    sim_capital -= pos_sz * 0.0002
        else:
            # Manage exits
            if pos_type == 'LONG':
                # Trail stop validation
                trail_sl = line1[i]
                if trail_sl >= close_arr[i]:
                    trail_sl = sl_price_val
                sl_price_val = max(sl_price_val, trail_sl)
                
                is_sl = low_arr[i] <= sl_price_val
                is_sell = not trend_state[i] or most_k2[i]
                if is_sl:
                    exit_pr = sl_price_val
                    pnl_pct = (exit_pr - entry_pr) / entry_pr
                    sim_capital += (pos_sz * pnl_pct) - (pos_sz * (1 + pnl_pct) * 0.0005)
                    in_pos = False
                elif is_sell:
                    exit_pr = close_arr[i]
                    pnl_pct = (exit_pr - entry_pr) / entry_pr
                    sim_capital += (pos_sz * pnl_pct) - (pos_sz * (1 + pnl_pct) * 0.0005)
                    in_pos = False
            else: # SHORT
                trail_sl = line2[i]
                if trail_sl <= close_arr[i]:
                    trail_sl = sl_price_val
                sl_price_val = min(sl_price_val, trail_sl)
                
                is_sl = high_arr[i] >= sl_price_val
                is_buy = trend_state[i] or most_k1[i]
                if is_sl:
                    exit_pr = sl_price_val
                    pnl_pct = (entry_pr - exit_pr) / entry_pr
                    sim_capital += (pos_sz * pnl_pct) - (pos_sz * (1 + pnl_pct) * 0.0005)
                    in_pos = False
                elif is_buy:
                    exit_pr = close_arr[i]
                    pnl_pct = (entry_pr - exit_pr) / entry_pr
                    sim_capital += (pos_sz * pnl_pct) - (pos_sz * (1 + pnl_pct) * 0.0005)
                    in_pos = False
                    
    return sim_capital - 100.0

def run_scanner(single_coin=None):
    print(f"[{datetime.now()}] Scanner active. Fetching markets...")
    
    # Initialize exchange
    exchange = ccxt.okx({
        'apiKey': config.OKX_API_KEY,
        'secret': config.OKX_SECRET_KEY,
        'password': config.OKX_PASSPHRASE,
        'enableRateLimit': True
    })
    if config.DEMO_MODE:
        exchange.set_sandbox_mode(True)
        print("[Scanner Info] Running in Demo Trading Mode.")
        
    # Get blacklist
    blacklist = db.get_blacklist()
    
    target_list = [single_coin] if single_coin else config.TARGET_COINS
    
    for symbol in target_list:
        if symbol in blacklist:
            print(f"[Scanner Info] Symbol {symbol} is blacklisted. Skipping.")
            continue
            
        print(f"\nOptimizing {symbol}...")
        try:
            # Fetch last 30 days of 1H candles (720 bars)
            # OKX fetch_ohlcv returns timestamp, open, high, low, close, volume
            ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=750)
            if len(ohlcv) < 100:
                print(f"[Scanner Warning] Insufficient data for {symbol}.")
                continue
                
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Grid search WFO
            best_pnl = -999999.0
            best_params = None
            
            for p in most_periods:
                for pct in most_pcts:
                    for slen in stoch_periods:
                        for wlen in wma_periods:
                            pnl = evaluate_params(df, p, pct, slen, wlen)
                            if pnl > best_pnl:
                                best_pnl = pnl
                                best_params = (p, pct, slen, wlen)
                                
            p, pct, slen, wlen = best_params
            print(f"Optimal parameters for {symbol}: MOST({p}, {pct*100}%) | IFTSTOCH({slen}, {wlen}) | WFO PnL: {best_pnl:.2f}%")
            
            # Save to Supabase
            db.update_guide_params(symbol, p, pct, slen, wlen, best_pnl)
            
            # Telegram notification
            msg = f"🔍 *OKX Ultra Optimizasyon Raporu*\n" \
                  f"Parite: `{symbol}`\n" \
                  f"MOST Periyot: `{p}`\n" \
                  f"MOST Yüzde: `%{pct*100:.2f}`\n" \
                  f"IFTSTOCH Stoch/WMA: `{slen}/{wlen}`\n" \
                  f"Son 7.5 Gün WFO Getirisi: `%{best_pnl:.2f}`"
            send_telegram_alert(msg)
            
        except Exception as e:
            print(f"[Scanner Error] Failed to optimize {symbol}: {e}")
            
    print(f"\n[{datetime.now()}] Scanner complete.")

if __name__ == "__main__":
    run_scanner()
