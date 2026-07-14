import os
import sys
import json
import time
import pandas as pd
import numpy as np
import ccxt
from datetime import datetime
from statsmodels.tsa.stattools import coint

import Ronesans.ronesans_config as r_config
from Ronesans.ronesans_db import DBHelper
from Ronesans.ronesans_telegram import send_telegram_alert

db = DBHelper()

def calculate_current_zscore(exchange, coin_y, coin_x, rolling_window):
    symbol_y = f"{coin_y}-USDT-SWAP"
    symbol_x = f"{coin_x}-USDT-SWAP"
    
    try:
        ohlcv_y = exchange.fetch_ohlcv(symbol_y, '15m', limit=200)
        ohlcv_x = exchange.fetch_ohlcv(symbol_x, '15m', limit=200)
        
        df_y = pd.DataFrame(ohlcv_y, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_x = pd.DataFrame(ohlcv_x, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df = pd.merge(df_y[['timestamp', 'close']], df_x[['timestamp', 'close']], on='timestamp', suffixes=('_y', '_x'))
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        if len(df) < rolling_window:
            return None
            
        y = df['close_y']
        x = df['close_x']
        
        rolling_cov = y.rolling(window=rolling_window).cov(x)
        rolling_var_x = x.rolling(window=rolling_window).var()
        beta_series = rolling_cov / rolling_var_x
        
        spread_series = y - beta_series * x
        mean_spread_series = spread_series.rolling(window=rolling_window).mean()
        std_spread_series = spread_series.rolling(window=rolling_window).std()
        
        beta = beta_series.iloc[-1]
        spread = spread_series.iloc[-1]
        mean_spread = mean_spread_series.iloc[-1]
        std_spread = std_spread_series.iloc[-1]
        
        current_z = (spread - mean_spread) / std_spread if std_spread > 0 else 0.0
        
        is_coint_valid = False
        try:
            y_slice = y.values[-180:]
            x_slice = x.values[-180:]
            _, p_val, _ = coint(y_slice, x_slice)
            is_coint_valid = (p_val < 0.05)
        except Exception:
            pass
            
        return {
            'beta': beta,
            'mean_spread': mean_spread,
            'std_spread': std_spread,
            'z_score': current_z,
            'is_coint_valid': is_coint_valid,
            'price_y': y.iloc[-1],
            'price_x': x.iloc[-1]
        }
    except Exception as e:
        print(f"[Ronesans Error] Veri hesaplama basarisiz ({coin_y}/{coin_x}): {e}")
        return None

def get_total_capital(exchange):
    try:
        balance = exchange.fetch_balance()
        capital = balance['free'].get('USDT', 20.0)
        return max(capital, 10.0)
    except Exception:
        return 10.0

def get_active_positions_from_exchange(exchange, coin_y, coin_x):
    symbol_y = f"{coin_y}-USDT-SWAP"
    symbol_x = f"{coin_x}-USDT-SWAP"
    
    pos_y = None
    pos_x = None
    
    try:
        positions = exchange.fetch_positions([symbol_y, symbol_x])
        for p in positions:
            symbol = p.get('symbol')
            contracts = abs(float(p.get('contracts', 0)))
            if contracts > 0:
                side = 'LONG' if float(p.get('size', 0)) > 0 else 'SHORT'
                p_details = {
                    'symbol': symbol,
                    'contracts': contracts,
                    'side': side,
                    'entry_price': float(p.get('entryPrice', 0)),
                    'initial_margin': float(p.get('initialMargin', 0))
                }
                if symbol == symbol_y:
                    pos_y = p_details
                elif symbol == symbol_x:
                    pos_x = p_details
    except Exception as e:
        print(f"[Ronesans Error] Borsa pozisyon sorgulama hatasi: {e}")
        
    return pos_y, pos_x

def place_order_with_chasing(exchange, symbol, side, qty, max_retries=5):
    print(f"[Chasing] {symbol} icin {side.upper()} {qty} kontrat limit emri yerlestiriliyor...")
    
    orderbook = exchange.fetch_order_book(symbol)
    price = orderbook['bids'][0][0] if side.lower() == 'buy' else orderbook['asks'][0][0]
    
    params = {'execInst': 'post_only', 'tdMode': 'cross'}
    try:
        order = exchange.create_order(symbol, 'limit', side, qty, price, params)
    except Exception as e:
        print(f"[Chasing Warning] Post-only basarisiz, normal limit deneniyor: {e}")
        order = exchange.create_order(symbol, 'limit', side, qty, price, {'tdMode': 'cross'})
        
    order_id = order['id']
    
    for attempt in range(max_retries):
        time.sleep(2)
        
        check = exchange.fetch_order(order_id, symbol)
        if check['status'] == 'closed':
            print(f"[Chasing Success] {symbol} Maker olarak gerceklesti @ {check['average']}")
            return check['average']
            
        orderbook = exchange.fetch_order_book(symbol)
        new_price = orderbook['bids'][0][0] if side.lower() == 'buy' else orderbook['asks'][0][0]
        
        if new_price != price:
            try:
                print(f"[Chasing Update] Fiyat kacti ({price} -> {new_price}). Eski emir iptal ediliyor...")
                exchange.cancel_order(order_id, symbol)
            except Exception:
                pass
                
            price_diff_pct = abs(new_price - price) / price
            if price_diff_pct > 0.0020:
                print(f"[Chasing Warning] Slippage siniri asildi (%{price_diff_pct*100:.3f}). Piyasa emrine donuluyor.")
                break
                
            price = new_price
            try:
                order = exchange.create_order(symbol, 'limit', side, qty, price, params)
                order_id = order['id']
            except Exception:
                order = exchange.create_order(symbol, 'limit', side, qty, price, {'tdMode': 'cross'})
                order_id = order['id']
                
    try:
        print(f"[Chasing Fallback] Siparis doldurulamadi. Market emriyle kapatiliyor...")
        exchange.cancel_order(order_id, symbol)
    except Exception:
        pass
        
    market_order = exchange.create_order(symbol, 'market', side, qty, None, {'tdMode': 'cross'})
    time.sleep(1)
    filled = exchange.fetch_order(market_order['id'], symbol)
    return filled['average'] if filled['average'] else orderbook['bids'][0][0]

def close_both_legs(exchange, coin_y, coin_x, pos_y, pos_x, reason, z_current):
    symbol_y = f"{coin_y}-USDT-SWAP"
    symbol_x = f"{coin_x}-USDT-SWAP"
    
    close_side_y = 'sell' if pos_y['side'] == 'LONG' else 'buy'
    close_side_x = 'sell' if pos_x['side'] == 'LONG' else 'buy'
    
    print(f"[Ronesans Close] Cift pozisyon kapatiliyor! Neden: {reason}")
    
    try:
        exit_p_y = place_order_with_chasing(exchange, symbol_y, close_side_y, pos_y['contracts'])
        exit_p_x = place_order_with_chasing(exchange, symbol_x, close_side_x, pos_x['contracts'])
        
        ret_y = (exit_p_y - pos_y['entry_price']) / pos_y['entry_price']
        if pos_y['side'] == 'SHORT':
            ret_y = -ret_y
            
        ret_x = (exit_p_x - pos_x['entry_price']) / pos_x['entry_price']
        if pos_x['side'] == 'SHORT':
            ret_x = -ret_x
            
        market_y = exchange.market(symbol_y)
        market_x = exchange.market(symbol_x)
        
        val_y_usd = pos_y['contracts'] * pos_y['entry_price'] * market_y['contractSize']
        val_x_usd = pos_x['contracts'] * pos_x['entry_price'] * market_x['contractSize']
        
        fees_y = val_y_usd * 0.0002
        fees_x = val_x_usd * 0.0002
        
        pnl_y = val_y_usd * ret_y - fees_y
        pnl_x = val_x_usd * ret_x - fees_x
        net_pnl = pnl_y + pnl_x
        net_pnl_pct = (net_pnl / (val_y_usd + val_x_usd)) * 100
        
        db.add_trade_history(
            symbol_y, close_side_y.upper(), pos_y['entry_price'], exit_p_y,
            pnl_y, ret_y * 100, fees_y, datetime.now().isoformat(), f"Ronesans_{reason}"
        )
        db.add_trade_history(
            symbol_x, close_side_x.upper(), pos_x['entry_price'], exit_p_x,
            pnl_x, ret_x * 100, fees_x, datetime.now().isoformat(), f"Ronesans_{reason}"
        )
        
        emoji = "🟢" if net_pnl > 0 else "🔴"
        msg = f"{emoji} *Rönesans Çift Pozisyon Kapatıldı (Stateless)*\n" \
              f"Çift: `{coin_y} / {coin_x}`\n" \
              f"Z-Score: `{z_current:.2f}`\n" \
              f"Net Kâr/Zarar: `{emoji} ${net_pnl:.2f}` (`%{net_pnl_pct:.2f}`)\n" \
              f"Neden: `{reason}`"
        send_telegram_alert(msg)
        
    except Exception as e:
        print(f"[Ronesans Error] Pozisyon kapatma hatasi: {e}")
        send_telegram_alert(f"🚨 *Rönesans Kapatma Hatası:* `{e}`")

def run_ronesans_tick():
    exchange = ccxt.okx({
        'apiKey': r_config.OKX_API_KEY,
        'secret': r_config.OKX_SECRET_KEY,
        'password': r_config.OKX_PASSPHRASE,
        'enableRateLimit': True
    })
    if r_config.DEMO_MODE:
        exchange.set_sandbox_mode(True)
        
    capital = get_total_capital(exchange)
    
    for coin_y, coin_x, window, entry_z, stop_z, leverage in r_config.TARGET_PAIRS:
        symbol_y = f"{coin_y}-USDT-SWAP"
        symbol_x = f"{coin_x}-USDT-SWAP"
        
        pos_y, pos_x = get_active_positions_from_exchange(exchange, coin_y, coin_x)
        metrics = calculate_current_zscore(exchange, coin_y, coin_x, window)
        if not metrics:
            continue
            
        z = metrics['z_score']
        is_coint = metrics['is_coint_valid']
        
        if not pos_y or not pos_x:
            if pos_y or pos_x:
                print(f"[Ronesans Warning] {coin_y}/{coin_x} ciftinde tek bacak acik kalmis. Temizleniyor...")
                try:
                    if pos_y:
                        exchange.create_order(symbol_y, 'market', 'sell' if pos_y['side'] == 'LONG' else 'buy', pos_y['contracts'], None, {'tdMode': 'cross'})
                    if pos_x:
                        exchange.create_order(symbol_x, 'market', 'sell' if pos_x['side'] == 'LONG' else 'buy', pos_x['contracts'], None, {'tdMode': 'cross'})
                except Exception as ex:
                    print(f"[Ronesans Error] Tek bacak temizleme hatasi: {ex}")
                continue
                
            if not is_coint:
                continue
                
            direction = 0
            if entry_z < z < stop_z:
                direction = -1
            elif -stop_z < z < -entry_z:
                direction = 1
                
            if direction != 0:
                print(f"[Ronesans Sinyal] {coin_y}/{coin_x} | Z: {z:.2f} | Yon: {direction}")
                
                z_diff = stop_z - entry_z
                expected_spread_loss = z_diff * metrics['std_spread']
                risk_usd = capital * r_config.RISK_PCT
                w_y_usd = risk_usd * (metrics['price_y'] / expected_spread_loss) if expected_spread_loss > 0 else 0
                
                if w_y_usd <= 0:
                    continue
                    
                ratio = metrics['beta'] * metrics['price_x'] / metrics['price_y']
                w_x_usd = w_y_usd * abs(ratio)
                
                max_allowed_nominal = capital * r_config.RISK_PCT * 10.0
                current_nominal = w_y_usd + w_x_usd
                if current_nominal > max_allowed_nominal:
                    factor = max_allowed_nominal / current_nominal
                    w_y_usd *= factor
                    w_x_usd *= factor
                    
                try:
                    market_y = exchange.market(symbol_y)
                    market_x = exchange.market(symbol_x)
                    
                    qty_y = w_y_usd / (metrics['price_y'] * market_y['contractSize'])
                    qty_x = w_x_usd / (metrics['price_x'] * market_x['contractSize'])
                    
                    qty_y = float(exchange.amount_to_precision(symbol_y, qty_y))
                    qty_x = float(exchange.amount_to_precision(symbol_x, qty_x))
                    
                    if qty_y == 0 or qty_x == 0:
                        continue
                        
                    exchange.set_leverage(int(leverage), symbol_y, {'tdMode': 'cross'})
                    exchange.set_leverage(int(leverage), symbol_x, {'tdMode': 'cross'})
                    
                    side_y = 'buy' if direction == 1 else 'sell'
                    side_x = 'sell' if direction == 1 else 'buy'
                    
                    print(f"[Ronesans Entry] Islemler gonderiliyor (Maker Limit Chasing)...")
                    entry_p_y = place_order_with_chasing(exchange, symbol_y, side_y, qty_y)
                    entry_p_x = place_order_with_chasing(exchange, symbol_x, side_x, qty_x)
                    
                    msg = f"🚀 *Rönesans Çift Pozisyon Açıldı (Maker)*\n" \
                          f"Çift: `{coin_y} / {coin_x}`\n" \
                          f"Z-Score: `{z:.2f}`\n" \
                          f"Yön: `{'LONG ' + coin_y + ' / SHORT ' + coin_x if direction == 1 else 'SHORT ' + coin_y + ' / LONG ' + coin_x}`\n" \
                          f"Büyüklük: `${w_y_usd + w_x_usd:.2f}`\n" \
                          f"Kaldıraç: `{leverage}x`"
                    send_telegram_alert(msg)
                    
                except Exception as ex:
                    print(f"[Ronesans Error] Emir girisi basarisiz: {ex}")
                    
        else:
            direction = 1 if pos_y['side'] == 'LONG' else -1
            
            exit_triggered = False
            exit_reason = ""
            
            if direction == 1:
                if z >= 0.0:
                    exit_triggered = True
                    exit_reason = "TAKE_PROFIT"
                elif z <= -stop_z:
                    exit_triggered = True
                    exit_reason = "STOP_LOSS"
            elif direction == -1:
                if z <= 0.0:
                    exit_triggered = True
                    exit_reason = "TAKE_PROFIT"
                elif z >= stop_z:
                    exit_triggered = True
                    exit_reason = "STOP_LOSS"
                    
            if exit_triggered:
                close_both_legs(exchange, coin_y, coin_x, pos_y, pos_x, exit_reason, z)

if __name__ == "__main__":
    print("[Ronesans] Stateless motor kontrol ediliyor...")
    run_ronesans_tick()
