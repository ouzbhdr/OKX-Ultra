import ccxt
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'kodlar'))
import config
from holocron import DBHelper

def main():
    db = DBHelper()
    exchange = ccxt.okx({
        'apiKey': config.REAL_OKX_API_KEY,
        'secret': config.REAL_OKX_SECRET_KEY,
        'password': config.REAL_OKX_PASSPHRASE,
    })
    
    symbol = 'TAO-USDT-SWAP'
    print(f"Closing position for {symbol}...")
    
    try:
        # 1. Cancel the algo stop order on OKX
        algo_id = '3723143969841270784'
        try:
            exchange.privatePostTradeCancelAlgos([{'algoId': algo_id, 'instId': symbol}])
            print("Cancelled algo stop order.")
        except Exception as e:
            print("Failed to cancel algo order:", e)
            
        # 2. Place market order to close position
        # Retrieve position size first
        pos = exchange.fetch_positions([symbol])
        contracts = 0.0
        for p in pos:
            if p['symbol'] == symbol or p['info'].get('instId') == symbol:
                contracts = abs(float(p['contracts']))
                break
                
        if contracts > 0:
            print(f"Placing market order to sell {contracts} contracts...")
            # We are LONG, so we sell
            order = exchange.create_order(symbol, 'market', 'sell', contracts, None, {'tdMode': 'cross'})
            print("Market order filled:", order.get('id'))
        else:
            print("No active position found on OKX.")
            
        # 3. Clean up database
        db.delete_position(symbol)
        print("Removed position from database.")
        
    except Exception as e:
        print("Error during execution:", e)

if __name__ == '__main__':
    main()
