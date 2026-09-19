class SweepStrategy:
    def __init__(self, symbol, pdh, pdl, sl_buffer):
        self.symbol = symbol
        
        # Initial Targets (Passed from main.py, already accounts for today's highs)
        self.pdh = pdh
        self.pdl = pdl
        self.active_high_target = pdh
        self.active_low_target = pdl
        self.sl_buffer = sl_buffer
        
        # Sweep State Tracking
        self.sweep_high_active = False
        self.sweep_low_active = False
        
        # Track the highest/lowest price reached during a sweep
        self.current_swing_high = 0.0
        self.current_swing_low = float('inf')
        
        # V-Shape Time tracking
        self.high_candle_time = None
        self.low_candle_time = None
        self.last_checked_candle_time = None
        
    def update(self, current_price, df_1m):
        """
        Takes the current tick price and the recent 1m dataframe.
        Returns a dictionary with trade signal if triggered, else None.
        """
        signal = None
        
        if df_1m is None or len(df_1m) < 4:
            return signal
            
        current_candle_time = df_1m.iloc[-1]['time']
        
        # 1. Check for sweeps
        if current_price > self.active_high_target:
            if not self.sweep_high_active:
                print(f"[{self.symbol}] 🚨 Price SWEPT the High Target ({self.active_high_target})! Watching for V-Shape reversal...")
            self.sweep_high_active = True
            
            # Update the highest point reached so far & record WHEN it happened
            if current_price > self.current_swing_high:
                self.current_swing_high = current_price
                self.high_candle_time = current_candle_time
                
        if current_price < self.active_low_target:
            if not self.sweep_low_active:
                print(f"[{self.symbol}] 🚨 Price SWEPT the Low Target ({self.active_low_target})! Watching for V-Shape reversal...")
            self.sweep_low_active = True
            
            # Update the lowest point reached so far & record WHEN it happened
            if current_price < self.current_swing_low:
                self.current_swing_low = current_price
                self.low_candle_time = current_candle_time

        # 2. Check 2-candle confirmation if a sweep is active
        c2 = df_1m.iloc[-2] # Last fully closed candle
        c1 = df_1m.iloc[-3] # The candle before it
        c0 = df_1m.iloc[-4] # The candle before that
        
        # Only evaluate the pattern once per closed candle
        if self.last_checked_candle_time != c2['time']:
            self.last_checked_candle_time = c2['time']
            
            is_c1_red = c1['close'] < c1['open']
            is_c2_red = c2['close'] < c2['open']
            
            is_c1_green = c1['close'] > c1['open']
            is_c2_green = c2['close'] > c2['open']
            
            # Short Setup (After High Sweep)
            if self.sweep_high_active:
                # Did we get the 2 Red Candle pattern?
                if is_c1_red and is_c2_red and (c2['close'] < c1['low']):
                    # Yes! But was it an immediate V-Shape reversal?
                    if self.high_candle_time in [c0['time'], c1['time']]:
                        print(f"[{self.symbol}] 🎯 SHORT Setup Confirmed! (Immediate V-Shape 2 Red Candles)")
                        
                        sl = self.current_swing_high + self.sl_buffer
                        signal = {
                            "action": "SHORT",
                            "sl": sl,
                            "tp_target": self.active_low_target # The runner TP
                        }
                        
                        # Reset state for the NEXT potential swing high
                        self.active_high_target = self.current_swing_high
                        self.sweep_high_active = False
                        self.current_swing_high = 0.0 
                    else:
                        print(f"[{self.symbol}] ❌ Sweep rejected (Sideways/Too Late). Target updated to {self.current_swing_high}")
                        self.active_high_target = self.current_swing_high
                        self.sweep_high_active = False
                        self.current_swing_high = 0.0
                else:
                    # Pattern not found yet. Has it been too long since the high?
                    if self.high_candle_time is not None and self.high_candle_time < c0['time']:
                        print(f"[{self.symbol}] ❌ Sweep timed out (No immediate red candles). Target updated to {self.current_swing_high}")
                        self.active_high_target = self.current_swing_high
                        self.sweep_high_active = False
                        self.current_swing_high = 0.0
            
            # Long Setup (After Low Sweep)
            if self.sweep_low_active:
                # Did we get the 2 Green Candle pattern?
                if is_c1_green and is_c2_green and (c2['close'] > c1['high']):
                    # Yes! But was it an immediate V-Shape reversal?
                    if self.low_candle_time in [c0['time'], c1['time']]:
                        print(f"[{self.symbol}] 🎯 LONG Setup Confirmed! (Immediate V-Shape 2 Green Candles)")
                        
                        sl = self.current_swing_low - self.sl_buffer
                        signal = {
                            "action": "LONG",
                            "sl": sl,
                            "tp_target": self.active_high_target # The runner TP
                        }
                        
                        # Reset state for the NEXT potential swing low
                        self.active_low_target = self.current_swing_low
                        self.sweep_low_active = False
                        self.current_swing_low = float('inf') 
                    else:
                        print(f"[{self.symbol}] ❌ Sweep rejected (Sideways/Too Late). Target updated to {self.current_swing_low}")
                        self.active_low_target = self.current_swing_low
                        self.sweep_low_active = False
                        self.current_swing_low = float('inf')
                else:
                    # Pattern not found yet. Has it been too long since the low?
                    if self.low_candle_time is not None and self.low_candle_time < c0['time']:
                        print(f"[{self.symbol}] ❌ Sweep timed out (No immediate green candles). Target updated to {self.current_swing_low}")
                        self.active_low_target = self.current_swing_low
                        self.sweep_low_active = False
                        self.current_swing_low = float('inf')
                    
        return signal
