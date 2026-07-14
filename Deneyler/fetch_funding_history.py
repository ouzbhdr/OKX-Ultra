import ccxt
import pandas as pd
import time

def main():
    exchange = ccxt.okx()
    symbol = 'BTC-USDT-SWAP'
    
    print(f"Fetching funding rate history for {symbol}...")
    try:
        # Fetch funding rate history
        # OKX returns up to 100 records per request. We can paginate using "before" parameter (which is the funding rate time).
        all_funding = []
        before_ts = None
        
        # We want to fetch about 1000 records (approx 1 year since funding is 8-hourly)
        for i in range(10):
            params = {}
            if before_ts:
                # OKX historical funding rate accepts "before" parameter (as a timestamp in ms)
                params['before'] = before_ts
                
            # OKX public API: /api/v5/public/funding-rate-history
            res = exchange.publicGetPublicFundingRateHistory({
                'instId': symbol,
                'limit': 100,
                **params
            })
            
            data = res.get('data', [])
            if not data:
                break
                
            for d in data:
                all_funding.append({
                    'timestamp': int(d['fundingTime']),
                    'funding_rate': float(d['fundingRate'])
                })
                
            # Set the "before" parameter to the oldest timestamp in the current batch minus 1ms
            before_ts = min([int(d['fundingTime']) for d in data]) - 1
            print(f"  Batch {i+1} fetched. Total records: {len(all_funding)}. Oldest timestamp: {pd.to_datetime(before_ts, unit='ms')}")
            time.sleep(0.5)
            
        df_funding = pd.DataFrame(all_funding)
        df_funding = df_funding.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        df_funding.to_csv('btc_funding_history.csv', index=False)
        print("Successfully saved btc_funding_history.csv")
        
    except Exception as e:
        print("Error fetching funding history:", e)

if __name__ == '__main__':
    main()
