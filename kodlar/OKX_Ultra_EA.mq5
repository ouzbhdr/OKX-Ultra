//+------------------------------------------------------------------+
//|                                                 OKX_Ultra_EA.mq5 |
//|                                  Copyright 2026, Antigravity AI  |
//|                                             https://antigravity  |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Antigravity AI"
#property link      "https://antigravity"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//--- Input parameters
input double   Input_RiskPct        = 0.10;     // Risk fraction per trade (e.g. 10%)
input double   Input_MinSlPct       = 0.005;    // Minimum Stop Loss % (e.g. 0.5%)
input int      Input_LookbackBars   = 720;      // Lookback bars for WFO (e.g. 720 bars = ~7.5 days)
input int      Input_WfoStepBars    = 168;      // WFO step interval (e.g. 168 bars = ~1.75 days)

//--- Structures
struct ParamCombo {
   int most_period;
   double most_pct;
   int stoch_period;
   int wma_period;
};

//--- Global Variables
ParamCombo G_Combos[192];
ParamCombo G_ActiveParam;
datetime   G_LastBarTime;
int        G_BarCounter = 0;
bool       G_OptimizerInitialized = false;

//+------------------------------------------------------------------+
//| Helper Function: Calculate Weighted Moving Average               |
//+------------------------------------------------------------------+
void CalculateWMA(const double &series[], int period, double &wma[]) {
   int n = ArraySize(series);
   ArrayResize(wma, n);
   double denom = period * (period + 1) / 2.0;
   for(int i = 0; i < n; i++) {
      if(i < period - 1) {
         wma[i] = 0.0;
         continue;
      }
      double sum = 0;
      for(int j = 0; j < period; j++) {
         sum += series[i - j] * (period - j);
      }
      wma[i] = sum / denom;
   }
}

//+------------------------------------------------------------------+
//| Helper Function: Calculate Exponential Moving Average            |
//+------------------------------------------------------------------+
void CalculateEMA(const double &close[], int period, double &ema[]) {
   int n = ArraySize(close);
   ArrayResize(ema, n);
   double k = 2.0 / (period + 1);
   ema[0] = close[0];
   for(int i = 1; i < n; i++) {
      ema[i] = close[i] * k + ema[i-1] * (1.0 - k);
   }
}

//+------------------------------------------------------------------+
//| Helper Function: Calculate MOST Trailing Stop and Trend          |
//+------------------------------------------------------------------+
void CalculateMOST(const double &ema[], double pct, double &line1[], double &line2[], bool &k1[], bool &k2[], bool &trend[]) {
   int n = ArraySize(ema);
   ArrayResize(line1, n);
   ArrayResize(line2, n);
   ArrayResize(k1, n);
   ArrayResize(k2, n);
   ArrayResize(trend, n);
   
   double ortp, ortm;
   line1[0] = ema[0] * (1.0 - pct);
   line2[0] = ema[0] * (1.0 + pct);
   k1[0] = false;
   k2[0] = false;
   trend[0] = true;
   
   for(int i = 1; i < n; i++) {
      ortp = ema[i] * (1.0 - pct);
      ortm = ema[i] * (1.0 + pct);
      
      line1[i] = (ema[i] < line1[i-1]) ? ortp : ((line1[i-1] > ortp) ? line1[i-1] : ortp);
      line2[i] = (ema[i] > line2[i-1]) ? ortm : ((line2[i-1] < ortm) ? line2[i-1] : ortm);
      
      k1[i] = (ema[i-1] <= line2[i-1] && ema[i] > line2[i-1]);
      k2[i] = (ema[i-1] >= line1[i-1] && ema[i] < line1[i-1]);
      
      if(k1[i]) trend[i] = true;
      else if(k2[i]) trend[i] = false;
      else trend[i] = trend[i-1];
   }
}

//+------------------------------------------------------------------+
//| Helper Function: Calculate IFT Stochastics                       |
//+------------------------------------------------------------------+
void CalculateIFTStoch(const double &high[], const double &low[], const double &close[], int slen, int wlen, double &ift[]) {
   int n = ArraySize(close);
   ArrayResize(ift, n);
   
   double stoch[];
   double v2_in[];
   ArrayResize(stoch, n);
   ArrayResize(v2_in, n);
   
   for(int i = 0; i < n; i++) {
      if(i < slen - 1) {
         stoch[i] = 50.0;
         v2_in[i] = 0.0;
         continue;
      }
      double hh = high[i];
      double ll = low[i];
      for(int j = 1; j < slen; j++) {
         if(high[i-j] > hh) hh = high[i-j];
         if(low[i-j] < ll) ll = low[i-j];
      }
      if(hh == ll) stoch[i] = 50.0;
      else stoch[i] = 100.0 * (close[i] - ll) / (hh - ll);
      v2_in[i] = 0.1 * (stoch[i] - 50.0);
   }
   
   double v2[];
   CalculateWMA(v2_in, wlen, v2);
   
   for(int i = 0; i < n; i++) {
      double e2v = exp(2.0 * v2[i]);
      ift[i] = (e2v - 1.0) / (e2v + 1.0);
   }
}

//+------------------------------------------------------------------+
//| Simulation Evaluator for a slice of history                      |
//+------------------------------------------------------------------+
double EvaluateSlice(int start, int end,
                     const double &line1[], const double &line2[],
                     const bool &k1[], const bool &k2[],
                     const bool &trend[], const double &ift[],
                     const double &close[], const double &low[], const double &high[]) {
   double cap = 100.0;
   bool inp = false;
   char pt = ' ';
   double ep = 0.0;
   double ps = 0.0;
   double sl = 0.0;
   
   int last_k1 = -999;
   int last_k2 = -999;
   
   for(int i = start; i < end; i++) {
      if(k1[i]) last_k1 = i;
      if(k2[i]) last_k2 = i;
      
      if(!inp) {
         // LONG Entry conditions
         if(trend[i] && last_k1 >= 0 && (i - last_k1 <= 20)) {
            int w_start = (last_k1 - 3 < 0) ? 0 : last_k1 - 3;
            int count_under = 0;
            int count_over = 0;
            for(int j = w_start; j <= i; j++) {
               if(ift[j] <= -0.5) count_under++;
               else count_over++;
            }
            if(count_under >= 2 && count_over >= 1) {
               ep = close[i];
               double sl_pct = (ep - line1[i]) / ep;
               if(sl_pct < Input_MinSlPct) sl_pct = Input_MinSlPct;
               ps = cap * Input_RiskPct / sl_pct;
               sl = line1[i];
               cap -= ps * 0.0002;
               inp = true;
               pt = 'L';
               continue;
            }
         }
         // SHORT Entry conditions
         if(!trend[i] && last_k2 >= 0 && (i - last_k2 <= 20)) {
            int w_start = (last_k2 - 3 < 0) ? 0 : last_k2 - 3;
            int count_over = 0;
            int count_under = 0;
            for(int j = w_start; j <= i; j++) {
               if(ift[j] >= 0.5) count_over++;
               else count_under++;
            }
            if(count_over >= 2 && count_under >= 1) {
               ep = close[i];
               double sl_pct = (line2[i] - ep) / ep;
               if(sl_pct < Input_MinSlPct) sl_pct = Input_MinSlPct;
               ps = cap * Input_RiskPct / sl_pct;
               sl = line2[i];
               cap -= ps * 0.0002;
               inp = true;
               pt = 'S';
               continue;
            }
         }
      } else {
         if(pt == 'L') {
            if(line1[i] > sl) sl = line1[i];
            if(low[i] <= sl) {
               double pnl_pct = (sl - ep) / ep;
               cap += ps * pnl_pct - ps * (1.0 + pnl_pct) * 0.0002;
               inp = false;
            }
         } else {
            if(line2[i] < sl) sl = line2[i];
            if(high[i] >= sl) {
               double pnl_pct = (ep - sl) / ep;
               cap += ps * pnl_pct - ps * (1.0 + pnl_pct) * 0.0002;
               inp = false;
            }
         }
      }
   }
   return cap;
}

//+------------------------------------------------------------------+
//| Initialize Combinations Grid                                     |
//+------------------------------------------------------------------+
void InitializeCombos() {
   int idx = 0;
   int most_p[] = {8, 13, 21, 34};
   double most_pct[] = {0.003, 0.005, 0.008, 0.010, 0.012, 0.015};
   int stoch_p[] = {7, 14, 21, 28};
   int wma_p[] = {5, 9};
   
   for(int p = 0; p < 4; p++) {
      for(int pct = 0; pct < 6; pct++) {
         for(int s = 0; s < 4; s++) {
            for(int w = 0; w < 2; w++) {
               G_Combos[idx].most_period = most_p[p];
               G_Combos[idx].most_pct = most_pct[pct];
               G_Combos[idx].stoch_period = stoch_p[s];
               G_Combos[idx].wma_period = wma_p[w];
               idx++;
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Run Grid Search self-optimization on the latest Lookback bars    |
//+------------------------------------------------------------------+
void OptimizeParameters() {
   int lookback = Input_LookbackBars;
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(Symbol(), Period(), 0, lookback + 50, rates);
   if(copied < lookback + 50) {
      Print("Not enough bars to run optimization. Copied: ", copied);
      return;
   }
   
   // Reverse rates arrays to be in chronological order
   double close[], high[], low[];
   int n = lookback + 50;
   ArrayResize(close, n);
   ArrayResize(high, n);
   ArrayResize(low, n);
   
   for(int i = 0; i < n; i++) {
      close[i] = rates[n - 1 - i].close;
      high[i] = rates[n - 1 - i].high;
      low[i] = rates[n - 1 - i].low;
   }
   
   double best_pnl = -999999.0;
   int best_idx = 0;
   
   // Grid search in memory
   for(int c = 0; c < 192; c++) {
      ParamCombo combo = G_Combos[c];
      
      double ema[];
      CalculateEMA(close, combo.most_period, ema);
      
      double line1[], line2[];
      bool k1[], k2[], trend[];
      CalculateMOST(ema, combo.most_pct, line1, line2, k1, k2, trend);
      
      double ift[];
      CalculateIFTStoch(high, low, close, combo.stoch_period, combo.wma_period, ift);
      
      double pnl = EvaluateSlice(50, n, line1, line2, k1, k2, trend, ift, close, low, high);
      if(pnl > best_pnl) {
         best_pnl = pnl;
         best_idx = c;
      }
   }
   
   G_ActiveParam = G_Combos[best_idx];
   Print("WFO Optimization Completed. Best Combo PnL: ", best_pnl, 
         " | MOST(", G_ActiveParam.most_period, ", ", G_ActiveParam.most_pct, 
         ") | IFTSTOCH(", G_ActiveParam.stoch_period, ", ", G_ActiveParam.wma_period, ")");
}

//+------------------------------------------------------------------+
//| EA Initialization                                                |
//+------------------------------------------------------------------+
int OnInit() {
   trade.SetDeviationInPoints(10);
   InitializeCombos();
   G_LastBarTime = 0;
   G_BarCounter = 0;
   G_OptimizerInitialized = false;
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EA Deinitialization                                              |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
}

//+------------------------------------------------------------------+
//| EA Tick Event                                                    |
//+------------------------------------------------------------------+
void OnTick() {
   // Run only on new candle open to align with python bot's signal timing
   datetime currentBarTime = iTime(Symbol(), Period(), 0);
   if(currentBarTime == G_LastBarTime) return;
   G_LastBarTime = currentBarTime;
   
   // Keep count of bars. Recalculate parameters every WfoStepBars
   G_BarCounter++;
   if(!G_OptimizerInitialized || (G_BarCounter >= Input_WfoStepBars)) {
      OptimizeParameters();
      G_BarCounter = 0;
      G_OptimizerInitialized = true;
   }
   
   // Load data for active trading signal check
   int required_bars = G_ActiveParam.most_period + 50;
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(Symbol(), Period(), 0, required_bars, rates);
   if(copied < required_bars) return;
   
   double close[], high[], low[];
   ArrayResize(close, required_bars);
   ArrayResize(high, required_bars);
   ArrayResize(low, required_bars);
   
   for(int i = 0; i < required_bars; i++) {
      close[i] = rates[required_bars - 1 - i].close;
      high[i] = rates[required_bars - 1 - i].high;
      low[i] = rates[required_bars - 1 - i].low;
   }
   
   // Calculate active indicators on latest closed bars
   double ema[];
   CalculateEMA(close, G_ActiveParam.most_period, ema);
   
   double line1[], line2[];
   bool k1[], k2[], trend[];
   CalculateMOST(ema, G_ActiveParam.most_pct, line1, line2, k1, k2, trend);
   
   double ift[];
   CalculateIFTStoch(high, low, close, G_ActiveParam.stoch_period, G_ActiveParam.wma_period, ift);
   
   int last_idx = required_bars - 1; // latest closed bar
   int prev_idx = last_idx - 1;
   
   // Trace trend start signals
   int last_k1 = -999;
   int last_k2 = -999;
   for(int i = 0; i <= last_idx; i++) {
      if(k1[i]) last_k1 = i;
      if(k2[i]) last_k2 = i;
   }
   
   // Check Position Status
   bool is_open = false;
   ulong ticket = 0;
   double current_sl = 0.0;
   double entry_price = 0.0;
   double position_volume = 0.0;
   
   if(PositionSelect(Symbol())) {
      is_open = true;
      ticket = PositionGetInteger(POSITION_TICKET);
      current_sl = PositionGetDouble(POSITION_SL);
      entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
      position_volume = PositionGetDouble(POSITION_VOLUME);
   }
   
   if(!is_open) {
      //--- Check Entry Signals
      
      // LONG Signal
      if(trend[last_idx] && last_k1 >= 0 && (last_idx - last_k1 <= 20)) {
         int w_start = (last_k1 - 3 < 0) ? 0 : last_k1 - 3;
         int count_under = 0, count_over = 0;
         for(int j = w_start; j <= last_idx; j++) {
            if(ift[j] <= -0.5) count_under++;
            else count_over++;
         }
         if(count_under >= 2 && count_over >= 1) {
            double target_entry = close[last_idx];
            double raw_sl = line1[last_idx];
            double sl_pct = (target_entry - raw_sl) / target_entry;
            if(sl_pct < Input_MinSlPct) sl_pct = Input_MinSlPct;
            
            // Correct stop loss price (ensure it's below entry)
            double final_sl = target_entry * (1.0 - sl_pct);
            
            // Calculate lot size
            double balance = AccountInfoDouble(ACCOUNT_BALANCE);
            double risk_value = balance * Input_RiskPct;
            double contract_size = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_CONTRACT_SIZE);
            double lot_step = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP);
            double min_lot = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN);
            
            double desired_pos_usd = risk_value / sl_pct;
            double lots = desired_pos_usd / (contract_size * target_entry);
            lots = MathFloor(lots / lot_step) * lot_step;
            if(lots < min_lot) lots = min_lot;
            
            // Open Buy Position
            trade.Buy(lots, Symbol(), SymbolInfoDouble(Symbol(), SYMBOL_ASK), final_sl, 0.0, "OKX Ultra Long");
         }
      }
      
      // SHORT Signal
      if(!trend[last_idx] && last_k2 >= 0 && (last_idx - last_k2 <= 20)) {
         int w_start = (last_k2 - 3 < 0) ? 0 : last_k2 - 3;
         int count_over = 0, count_under = 0;
         for(int j = w_start; j <= last_idx; j++) {
            if(ift[j] >= 0.5) count_over++;
            else count_under++;
         }
         if(count_over >= 2 && count_under >= 1) {
            double target_entry = close[last_idx];
            double raw_sl = line2[last_idx];
            double sl_pct = (raw_sl - target_entry) / target_entry;
            if(sl_pct < Input_MinSlPct) sl_pct = Input_MinSlPct;
            
            // Correct stop loss price (ensure it's above entry)
            double final_sl = target_entry * (1.0 + sl_pct);
            
            // Calculate lot size
            double balance = AccountInfoDouble(ACCOUNT_BALANCE);
            double risk_value = balance * Input_RiskPct;
            double contract_size = SymbolInfoDouble(Symbol(), SYMBOL_TRADE_CONTRACT_SIZE);
            double lot_step = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP);
            double min_lot = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN);
            
            double desired_pos_usd = risk_value / sl_pct;
            double lots = desired_pos_usd / (contract_size * target_entry);
            lots = MathFloor(lots / lot_step) * lot_step;
            if(lots < min_lot) lots = min_lot;
            
            // Open Sell Position
            trade.Sell(lots, Symbol(), SymbolInfoDouble(Symbol(), SYMBOL_BID), final_sl, 0.0, "OKX Ultra Short");
         }
      }
   }
   else {
      //--- Check Trailing Stop updates
      long pos_type = PositionGetInteger(POSITION_TYPE);
      if(pos_type == POSITION_TYPE_BUY) {
         double calculated_sl = line1[last_idx];
         // Only move stop loss upwards
         if(calculated_sl > current_sl) {
            trade.PositionModify(ticket, calculated_sl, 0.0);
            Print("Trailing Stop Updated for LONG. New SL: ", calculated_sl);
         }
      }
      else if(pos_type == POSITION_TYPE_SELL) {
         double calculated_sl = line2[last_idx];
         // Only move stop loss downwards
         if(calculated_sl < current_sl || current_sl == 0.0) {
            trade.PositionModify(ticket, calculated_sl, 0.0);
            Print("Trailing Stop Updated for SHORT. New SL: ", calculated_sl);
         }
      }
   }
}
