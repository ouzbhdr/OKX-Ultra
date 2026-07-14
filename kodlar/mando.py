import os
import time
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

# Calculate indicators on live data slice
def calculate_indicators(df, p, pct, slen, wlen):
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

    return {
        'ema': ema,
        'line1': line1,
        'line2': line2,
        'k1': most_k1,
        'k2': most_k2,
        'trend': trend_state,
        'ift': ift
    }

def check_live_signals(symbol, exchange):
    # Check if we already have an active/pending position in database
    active_positions = db.get_active_positions()
    for pos in active_positions:
        if pos['coin'] == symbol:
            # Already in trade or pending for this symbol
            return
            
    # Get active parameters from guide_table
    params = db.get_guide_params(symbol)
    if not params:
        print(f"[Hunter Info] guide_table'da {symbol} için parametre bulunamadı. Anlık optimizasyon tetikleniyor...")
        try:
            from c3po import run_scanner
            run_scanner(single_coin=symbol)
            # Re-fetch after optimization completes
            params = db.get_guide_params(symbol)
        except Exception as e:
            print(f"[Hunter Error] {symbol} anlık optimizasyonu başarısız oldu: {e}")
            
        if not params:
            print(f"[Hunter Warning] {symbol} parametreleri hâlâ eksik. Es geçiliyor.")
            return
        
    p = int(params['most_period'])
    pct = float(params['most_pct'])
    slen = int(params['stoch_len'])
    wlen = int(params['wma_len'])
    
    # Fetch last 100 15M candles from OKX (enough for indicator stabilization)
    ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=100)
    if len(ohlcv) < 30:
        return
        
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Calculate indicators
    ind = calculate_indicators(df, p, pct, slen, wlen)
    
    # Signal is checked on the LAST CLOSED CANDLE (index -2)
    # Index -1 is the current active candle (uncompleted)
    idx = len(df) - 2 
    
    is_most_long = ind['trend'][idx]
    k1 = ind['k1']
    k2 = ind['k2']
    ift = ind['ift']
    
    # Trace K1 and K2 indices on the slice
    k1_indices = [i for i, val in enumerate(k1[:idx+1]) if val]
    k2_indices = [i for i, val in enumerate(k2[:idx+1]) if val]
    
    # --- Check LONG Trigger ---
    # V1 Mantigi: 20 bar siniri var, crossover yok, esik -0.5
    has_recent_buy = is_most_long and len(k1_indices) > 0 and (idx - k1_indices[-1] <= 20)
    if has_recent_buy:
        k1_idx = k1_indices[-1]
        start_w = max(0, k1_idx - 3)
        window_ift = ift[start_w : idx + 1]
        below = sum(1 for val in window_ift if val <= -0.5)
        above = sum(1 for val in window_ift if val > -0.5)
        if below >= 2 and above >= 1:
            trigger_entry(symbol, 'BUY', df.iloc[idx]['close'], ind['line1'][idx], exchange)
            return

    # --- Check SHORT Trigger ---
    # V1 Mantigi: 20 bar siniri var, crossover yok, esik +0.5
    has_recent_sell = not is_most_long and len(k2_indices) > 0 and (idx - k2_indices[-1] <= 20)
    if has_recent_sell:
        k2_idx = k2_indices[-1]
        start_w = max(0, k2_idx - 3)
        window_ift = ift[start_w : idx + 1]
        above = sum(1 for val in window_ift if val >= 0.5)
        below = sum(1 for val in window_ift if val < 0.5)
        if above >= 2 and below >= 1:
            trigger_entry(symbol, 'SELL', df.iloc[idx]['close'], ind['line2'][idx], exchange)
            return

def trigger_entry(symbol, side, entry_price, sl_price, exchange):
    print(f"[Hunter Info] Triggering {side} entry for {symbol} at {entry_price}...")
    
    # 1. Fetch balance in USDT
    try:
        balance = exchange.fetch_balance()
        capital = balance['free'].get('USDT', 0.0)
        if capital < 5.0:
            print(f"[Hunter Error] Insufficient capital: ${capital:.2f}")
            return
    except Exception as e:
        print(f"[Hunter Error] Failed to fetch balance: {e}")
        return
        
    # 2. Calculate dynamic Stop Loss %
    if side == 'BUY': # LONG
        sl_pct = (entry_price - sl_price) / entry_price
    else: # SHORT
        sl_pct = (sl_price - entry_price) / entry_price
        
    sl_pct = max(config.MIN_SL_PCT, sl_pct)
    
    # Correct sl_price to be on the proper side of entry_price based on sl_pct
    if side == 'BUY': # LONG
        sl_price = entry_price * (1 - sl_pct)
    else: # SHORT
        sl_price = entry_price * (1 + sl_pct)
    
    # 3. Calculate Position Size
    risk_amount = capital * config.RISK_PCT
    desired_pos_size = risk_amount / sl_pct
    
    # Leverage cap
    leverage = int(min(config.MAX_LEVERAGE, desired_pos_size / capital))
    leverage = max(1, leverage)
    
    pos_size_usd = min(desired_pos_size, capital * leverage)
    
    # Load market limits
    market = exchange.market(symbol)
    contract_size = market['contractSize'] # e.g. 1.0 for SOL, 0.01 for BTC
    
    # Calculate amount in contracts
    # Amount = position_size_usd / (entry_price * contract_size)
    amount_contracts = pos_size_usd / (entry_price * contract_size)
    
    # Round amount to OKX lot size precision
    amount_contracts = exchange.amount_to_precision(symbol, amount_contracts)
    amount_contracts = float(amount_contracts)
    
    if amount_contracts < market['limits']['amount']['min']:
        print(f"[Hunter Warning] Position size too small for {symbol}. Required min contracts: {market['limits']['amount']['min']}")
        return
        
    # Calculate actual position size in USD
    actual_pos_size = amount_contracts * entry_price * contract_size
    
    # 4. Submit Post-Only Limit Order
    try:
        # Get order book to place at best Bid (for buy) or best Ask (for sell)
        orderbook = exchange.fetch_order_book(symbol)
        limit_price = orderbook['bids'][0][0] if side == 'BUY' else orderbook['asks'][0][0]
        
        # Set leverage on exchange before order placement - Commented out to keep manual max leverage settings
        # try:
        #     exchange.set_leverage(leverage, symbol, {'mgnMode': 'cross'})
        # except Exception as le:
        #     print(f"[Hunter Warning] Failed to set leverage: {le}")
            
        print(f"[Hunter Info] Placing Post-Only {side} Limit Order: {amount_contracts} contracts at {limit_price}...")
        
        # OKX CCXT standard parameters for Post-Only limit orders
        params = {
            'execInst': 'post_only', 
            'tdMode': 'cross'
        }
        
        order = exchange.create_order(symbol, 'limit', 'buy' if side == 'BUY' else 'sell', amount_contracts, limit_price, params)
        order_id = order['id']
        
        # Save to database as PENDING
        db.add_pending_position(symbol, 'LONG' if side == 'BUY' else 'SHORT', limit_price, actual_pos_size, leverage, sl_price, order_id)
        
        # Notify Telegram
        msg = f"🏹 *OKX Ultra Avcı Sinyali*\n" \
              f"Parite: `{symbol}`\n" \
              f"Yön: `{ 'LONG (AL)' if side == 'BUY' else 'SHORT (SAT)' }`\n" \
              f"Limit Giriş Fiyatı: `${limit_price:.4f}`\n" \
              f"Dinamik Stop: `${sl_price:.4f}` (`%{sl_pct*100:.2f}`)\n" \
              f"Hesaplanan Kaldıraç: `{leverage}x`\n" \
              f"Durum: `Tahtada Bekliyor (Chasing Aktif)`"
        send_telegram_alert(msg)
        
    except Exception as e:
        print(f"[Hunter Error] Order execution failed: {e}")


def run_hunter():
    print(f"[{datetime.now()}] Hunter active.")
    
    # Check if Single Position Limit flag is active
    if os.path.exists("single_position.flag"):
        try:
            active_positions = db.get_active_positions()
            if len(active_positions) > 0:
                print(f"[Hunter Info] Globally active trade in flight ({active_positions[0]['coin']}) and Single Position Limit is ON. Skipping new entries.")
                print(f"[{datetime.now()}] Hunter sleep.")
                return
        except Exception as e:
            print(f"[Hunter Warning] Failed to check global active positions: {e}")
        
    # Initialize exchange
    exchange = ccxt.okx({
        'apiKey': config.OKX_API_KEY,
        'secret': config.OKX_SECRET_KEY,
        'password': config.OKX_PASSPHRASE,
        'enableRateLimit': True
    })
    if config.DEMO_MODE:
        exchange.set_sandbox_mode(True)
        
    # Get active blacklist
    blacklist = db.get_blacklist()
    
    for symbol in config.TARGET_COINS:
        if symbol in blacklist:
            continue
        try:
            check_live_signals(symbol, exchange)
        except Exception as e:
            print(f"[Hunter Error] Failed check for {symbol}: {e}")
            
    print(f"[{datetime.now()}] Hunter sleep.")

if __name__ == "__main__":
    # If run directly, run once. In Termux, this can be called via cron every 5 minutes.
    run_hunter()
