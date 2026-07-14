import os
import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import config
from holocron import DBHelper, send_telegram_alert
from mando import calculate_indicators

db = DBHelper()

# Tracker for last updated block of active positions (to avoid recalculating indicators constantly)
last_stop_update_block = {}

# In-memory stop limit order tracker: {symbol: order_id}
stop_orders = {}

def manage_pending_orders(pos, exchange):
    symbol = pos['coin']
    order_id = pos['order_id']
    side = pos['side']
    limit_price = float(pos['entry_price'])
    
    try:
        # Check order status on OKX
        order = exchange.fetch_order(order_id, symbol)
        status = order['status']
        
        if status == 'closed':
            # Order filled! Update status to FILLED in Supabase
            db.update_position_status(order_id, "FILLED")
            msg = f"✅ *OKX Ultra Pozisyon Açıldı*\n" \
                  f"Parite: `{symbol}`\n" \
                  f"Yön: `{side}`\n" \
                  f"Giriş Fiyatı: `${order['price']:.4f}`\n" \
                  f"Büyüklük: `${pos['position_size']:.2f}`\n" \
                  f"Kaldıraç: `{pos['leverage']}x`\n" \
                  f"Durum: `Pozisyon Aktif, Trailing Stop Takip Ediliyor`"
            send_telegram_alert(msg)
            return
            
        elif status in ['canceled', 'rejected']:
            # Order canceled or rejected, remove from database
            db.delete_position(symbol)
            send_telegram_alert(f"⚠️ *OKX Ultra Sinyal İptal*\nParite: `{symbol}` limit emri gerçekleşmedi (Borsa iptal etti).")
            return
            
        elif status == 'open':
            # Order is still open in the book. Check if price moved away
            orderbook = exchange.fetch_order_book(symbol)
            best_bid = orderbook['bids'][0][0]
            best_ask = orderbook['asks'][0][0]
            
            # Slippage/chase thresholds
            # If price moved more than 0.15% from our initial signal close, cancel trade (train left)
            current_price = best_bid if side == 'LONG' else best_ask
            price_change = abs(current_price - limit_price) / limit_price
            if price_change > 0.0015:
                print(f"[Trader Info] Price moved too far ({price_change*100:.2f}%) for {symbol}. Canceling order...")
                exchange.cancel_order(order_id, symbol)
                db.delete_position(symbol)
                send_telegram_alert(f"🚫 *OKX Ultra Kovalama Sonlandı*\nParite: `{symbol}` fiyatı çok fazla kaçtığı için limit emir iptal edildi.")
                return
                
            # If current best price is different from our order price, chase!
            new_target_price = best_bid if side == 'LONG' else best_ask
            if new_target_price != limit_price:
                print(f"[Trader Info] Chasing order for {symbol}. Replacing {limit_price} with {new_target_price}...")
                
                # Cancel current
                exchange.cancel_order(order_id, symbol)
                
                # Place new post-only limit
                params = {'execInst': 'post_only', 'tdMode': 'cross'}
                new_order = exchange.create_order(
                    symbol, 'limit', 
                    'buy' if side == 'LONG' else 'sell', 
                    order['amount'], new_target_price, params
                )
                
                # Update database
                db.client.table("active_positions").update({
                    "order_id": new_order['id'],
                    "entry_price": float(new_target_price)
                }).eq("coin", symbol).execute()
                
                print(f"[Trader Info] Replaced order for {symbol} to {new_target_price}.")
                
    except Exception as e:
        print(f"[Trader Error] manage_pending_orders error for {symbol}: {e}")

def update_stop_limit(pos, sl_price, exchange):
    """Borsaya MOST seviyesinde limit stop emri koyar. Her 15dk trailing ile guncellenir."""
    symbol = pos['coin']
    side = pos['side']

    # 1. Borsadaki bu coine ait tum acik stop (algo) emirlerini bul ve iptal et
    for t in ['conditional', 'trigger']:
        try:
            res = exchange.privateGetTradeOrdersAlgoPending({'instId': symbol, 'ordType': t})
            data = res.get('data', [])
            if data:
                cancel_payload = [{'algoId': a['algoId'], 'instId': symbol} for a in data]
                exchange.privatePostTradeCancelAlgos(cancel_payload)
                print(f"[Trader Info] Cancelled {len(cancel_payload)} old stop algo orders for {symbol}")
        except Exception as e:
            print(f"[Trader Warning] Could not cancel existing algo orders for {symbol}: {e}")

    # Borsadaki gercek sozlesme adedini al
    positions_data = exchange.fetch_positions([symbol])
    pos_amount = 0.0
    for p in positions_data:
        if p['symbol'] == symbol or p['info'].get('instId') == symbol:
            pos_amount = abs(float(p.get('contracts', 0)))
            break

    if pos_amount == 0.0:
        print(f"[Trader Warning] No contracts found for {symbol}, skipping stop limit.")
        return

    close_side = 'sell' if side == 'LONG' else 'buy'
    try:
        order = exchange.create_order(
            symbol, 'limit', close_side, pos_amount, sl_price,
            {
                'stopPrice': sl_price,
                'tdMode': 'cross'
            }
        )
        stop_orders[symbol] = order['id']
        print(f"[Trader Info] Stop limit placed @ {sl_price} for {symbol} | {close_side} {pos_amount} contracts | order: {order['id']}")
    except Exception as e:
        print(f"[Trader Error] Stop limit placement failed for {symbol}: {e}")

def monitor_filled_positions(pos, exchange):
    symbol = pos['coin']
    side = pos['side']
    entry_price = float(pos['entry_price'])
    position_size_usd = float(pos['position_size'])
    sl_price = float(pos['sl_price'])
    
    now = datetime.now()
    current_block = (now.hour, now.minute // 15)
    
    try:
        # 1. Check if position is still open on OKX exchange
        positions = exchange.fetch_positions([symbol])
        on_exchange = False
        for p in positions:
            if p['symbol'] == symbol or p['info'].get('instId') == symbol:
                if abs(float(p.get('contracts', 0))) > 0:
                    on_exchange = True
                    break
                    
        if not on_exchange:
            print(f"[Trader Info] Position for {symbol} is no longer active on exchange. Syncing DB...")
            # Fetch latest ticker for fallback price
            exit_price = entry_price
            try:
                ticker = exchange.fetch_ticker(symbol)
                exit_price = ticker['last']
            except Exception:
                pass
                
            pnl_usd = 0.0
            pnl_pct = 0.0
            fees = 0.0
            
            try:
                trades = exchange.fetch_my_trades(symbol, limit=5)
                if trades:
                    close_side = 'buy' if side == 'SHORT' else 'sell'
                    latest_close = None
                    for t in trades:
                        if t['side'] == close_side:
                            latest_close = t
                            break
                    if not latest_close:
                        latest_close = trades[0]
                        
                    exit_price = latest_close['price']
                    if side == 'LONG':
                        pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price
                    
                    fees = latest_close.get('fee', {}).get('cost', 0.0)
                    pnl_usd = (position_size_usd * pnl_pct) - fees
            except Exception as te:
                print(f"[Trader Warning] Failed to fetch closing trade details for {symbol}: {te}")
                
            db.add_trade_history(
                symbol, side, entry_price, exit_price, 
                pnl_usd, pnl_pct * 100, fees, 
                pos['entry_time'], 'EXTERNAL_CLOSE'
            )
            db.delete_position(symbol)
            
            send_telegram_alert(
                f"ℹ️ *OKX Ultra Pozisyon Kapatıldı (Dışarıdan)*\n"
                f"Parite: `{symbol}`\n"
                f"Yön: `{side}`\n"
                f"Giriş Fiyatı: `${entry_price:.4f}`\n"
                f"Çıkış Fiyatı (Tahmini): `${exit_price:.4f}`\n"
                f"Tahmini Kâr/Zarar: `${pnl_usd:.2f}` (`%{pnl_pct*100:.2f}`)\n"
                f"Durum: `Pozisyon borsa üzerinden manuel veya harici olarak kapatılmış.`"
            )
            return

        # 2. Her 15 dakikada MOST guncelle ve stop limit emrini yenile (trailing)
        if symbol not in last_stop_update_block or last_stop_update_block[symbol] != current_block:
            params = db.get_guide_params(symbol)
            if params:
                p = int(params['most_period'])
                pct = float(params['most_pct'])
                slen = int(params['stoch_len'])
                wlen = int(params['wma_len'])

                ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=100)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                ind = calculate_indicators(df, p, pct, slen, wlen)

                new_sl_price = ind['line1'][-2] if side == 'LONG' else ind['line2'][-2]
                current_price = float(df['close'].iloc[-1])

                sl_updated = False
                if side == 'LONG' and new_sl_price > sl_price:
                    if new_sl_price < current_price * 0.999:
                        db.update_position_sl(symbol, new_sl_price)
                        sl_price = new_sl_price
                        sl_updated = True
                    else:
                        print(f"[Trader Info] Ignored invalid trailing stop update for {symbol} LONG: {new_sl_price} is not below current price {current_price}")
                elif side == 'SHORT' and new_sl_price < sl_price:
                    if new_sl_price > current_price * 1.001:
                        db.update_position_sl(symbol, new_sl_price)
                        sl_price = new_sl_price
                        sl_updated = True
                    else:
                        print(f"[Trader Info] Ignored invalid trailing stop update for {symbol} SHORT: {new_sl_price} is not above current price {current_price}")

                # Stop limit emrini guncelle (degistiyse veya hic yoksa)
                if sl_updated or not stop_orders.get(symbol):
                    update_stop_limit(pos, sl_price, exchange)

                last_stop_update_block[symbol] = current_block

        # 3. Stop limit hic yoksa (bot yeni baslatildi vs) hemen koy
        elif not stop_orders.get(symbol):
            update_stop_limit(pos, sl_price, exchange)

        # 4. Yedek kontrol: stop limit konamadiysa ticker ile market emirle kapat
        if not stop_orders.get(symbol):
            ticker = exchange.fetch_ticker(symbol)
            last_price = ticker['last']
            if (side == 'LONG' and last_price <= sl_price) or (side == 'SHORT' and last_price >= sl_price):
                close_position(pos, last_price, 'TRAILING_SL_HIT_MARKET_FALLBACK', exchange)
            
    except Exception as e:
        print(f"[Trader Error] monitor_filled_positions error for {symbol}: {e}")

def close_position(pos, trigger_price, reason, exchange):
    symbol = pos['coin']
    side = pos['side']
    entry_price = float(pos['entry_price'])
    position_size_usd = float(pos['position_size'])
    
    print(f"[Trader Info] Closing active position for {symbol}. Reason: {reason} at price {trigger_price}...")
    
    try:
        # Load market specs
        market = exchange.market(symbol)
        contract_size = market['contractSize']
        
        # Calculate amount of contracts to close
        # Fetch current position from OKX to close the exact size to avoid orphans
        positions = exchange.fetch_positions([symbol])
        pos_amount = 0.0
        for p in positions:
            if p['symbol'] == symbol or p['info'].get('instId') == symbol:
                pos_amount = abs(float(p['contracts']))
                break
                
        if pos_amount == 0.0:
            # Fallback to database size
            pos_amount = position_size_usd / (entry_price * contract_size)
            pos_amount = float(exchange.amount_to_precision(symbol, pos_amount))
            
        # Place Market Order to Close
        close_side = 'sell' if side == 'LONG' else 'buy'
        print(f"[Trader Info] Submitting Market Close: {close_side} {pos_amount} contracts...")
        
        order = exchange.create_order(symbol, 'market', close_side, pos_amount, None, {'tdMode': 'cross'})
        
        # Fetch execution price
        time.sleep(1) # Wait for execution log
        filled_order = exchange.fetch_order(order['id'], symbol)
        exit_price = filled_order['average'] if filled_order['average'] else trigger_price
        
        # Calculate PnL (including fees: 0.02% Maker entry + 0.05% Taker exit = 0.07% total approx)
        if side == 'LONG':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
            
        actual_pos_usd = pos_amount * entry_price * contract_size
        fees = actual_pos_usd * 0.0002 + (actual_pos_usd * (1 + pnl_pct) * 0.0005)
        pnl_usd = (actual_pos_usd * pnl_pct) - fees
        
        # Save to database
        db.add_trade_history(
            symbol, side, entry_price, exit_price, 
            pnl_usd, pnl_pct * 100, fees, 
            pos['entry_time'], reason
        )
        
        # Delete from active
        db.delete_position(symbol)
        
        # Telegram Notification
        pnl_emoji = "🟢" if pnl_usd > 0 else "🔴"
        msg = f"{pnl_emoji} *OKX Ultra Pozisyon Kapatıldı*\n" \
              f"Parite: `{symbol}`\n" \
              f"Yön: `{side}`\n" \
              f"Giriş Fiyatı: `${entry_price:.4f}`\n" \
              f"Çıkış Fiyatı: `${exit_price:.4f}`\n" \
              f"Net Kâr/Zarar: `{pnl_emoji} ${pnl_usd:.2f}` (`%{pnl_pct*100:.2f}`)\n" \
              f"Ödenen Komisyon: `${fees:.3f}`\n" \
              f"Neden: `{reason}`"
        send_telegram_alert(msg)
        
    except Exception as e:
        print(f"[Trader Error] Close position failed: {e}")

def run_trader_loop():
    print("Trader daemon active. Starting 10s monitoring loop...")
    
    # Initialize exchange
    exchange = ccxt.okx({
        'apiKey': config.OKX_API_KEY,
        'secret': config.OKX_SECRET_KEY,
        'password': config.OKX_PASSPHRASE,
        'enableRateLimit': True
    })
    if config.DEMO_MODE:
        exchange.set_sandbox_mode(True)
        
    while True:
        try:
            # Fetch active positions from database
            positions = db.get_active_positions()
            
            for pos in positions:
                if pos['status'] == 'PENDING':
                    manage_pending_orders(pos, exchange)
                elif pos['status'] == 'FILLED':
                    monitor_filled_positions(pos, exchange)
                    
        except Exception as e:
            print(f"[Trader Error] Loop exception: {e}")
            
        time.sleep(10)

if __name__ == "__main__":
    run_trader_loop()
