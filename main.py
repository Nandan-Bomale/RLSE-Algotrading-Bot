import time
import MetaTrader5 as mt5
from config import ACCOUNT_ID, PASSWORD, SERVER, SYMBOLS
import mt5_engine
import journal
from strategy import SweepStrategy
import server

def main():
    import json, os
    settings_path = 'settings.json'
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r') as f:
                saved_settings = json.load(f)
                for sym, params in saved_settings.items():
                    if sym in SYMBOLS:
                        SYMBOLS[sym].update(params)
                        print(f"Loaded saved settings for {sym}: {params}")
        except Exception as e:
            print("Failed to load settings.json:", e)
            
    print("========================================")
    print("   RLSE ALGOTRADING BOT STARTED      ")
    print("========================================")
    
        # 1. Initialize MT5 (Check accounts.json first, fallback to config)
    accounts_path = 'accounts.json'
    active_acc = None
    if os.path.exists(accounts_path):
        try:
            with open(accounts_path, 'r') as f:
                acc_data = json.load(f)
                active_id = acc_data.get('active')
                if active_id:
                    active_acc = next((a for a in acc_data.get('saved', []) if a['id'] == active_id), None)
        except: pass
        
    if active_acc:
        if not mt5_engine.initialize(active_acc['id'], active_acc['password'], active_acc['server']):
            print("Exiting...")
            return
    else:
        # Fallback to config.py
        if not mt5_engine.initialize(ACCOUNT_ID, PASSWORD, SERVER):
            print("Exiting...")
            return
        
    # Start the Dashboard Web Server
    server.run_server()
    print("🌐 Live Dashboard running at: http://localhost:5000")
    
    # 2. Initialize Journal
    journal.init_journal()
    
    # 3. Setup Strategies per symbol
    active_strategies = {}
    
    for symbol, params in SYMBOLS.items():
        if params['enabled']:
            # Ensure symbol is selected in Market Watch
            mt5.symbol_select(symbol, True)
            
            pdh, pdl = mt5_engine.get_daily_high_low(symbol)
            if pdh is None or pdl is None:
                print(f"[{symbol}] Failed to get Daily High/Low. Skipping.")
                continue
                
            # Fetch TODAY's High/Low so far to handle mid-day bot starts
            rates_today = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 1)
            if rates_today is not None and len(rates_today) > 0:
                today_high = rates_today[0]['high']
                today_low = rates_today[0]['low']
                
                # If today's price already broke the PDH earlier, the new target is today's absolute high
                active_high = today_high if today_high > pdh else pdh
                # Same for the low
                active_low = today_low if today_low < pdl else pdl
            else:
                active_high = pdh
                active_low = pdl
                
            print(f"[{symbol}] Initialized. PDH: {pdh} | PDL: {pdl} | Active High Target: {active_high} | Active Low Target: {active_low}")
            active_strategies[symbol] = SweepStrategy(symbol, pdh, pdl, active_high, active_low, params['sl_buffer'])

    if not active_strategies:
        print("No active symbols configured or loaded. Exiting...")
        mt5.shutdown()
        return

    print("\nBot is now actively monitoring ticks and 1m candles. Press Ctrl+C to stop.")
    
    # 4. Main Loop
    try:
        while True:
            # Check for Account Switch
            if server.SHARED_STATE.get("account_switched"):
                print("\n[SYSTEM] Account switch detected! Resetting strategy states...")
                server.SHARED_STATE["account_switched"] = False
                active_strategies = {}
                for symbol, config in SYMBOLS.items():
                    if config["enabled"]:
                        dh, dl = mt5_engine.get_daily_high_low(symbol)
                        if dh is not None and dl is not None:
                            # Quick fetch of today's high/low
                            today_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 1)
                            ah, al = dh, dl
                            if today_rates is not None and len(today_rates) > 0:
                                th = today_rates[0]['high']
                                tl = today_rates[0]['low']
                                ah = th if th > dh else dh
                                al = tl if tl < dl else dl
                            active_strategies[symbol] = SweepStrategy(symbol, dh, dl, ah, al, config["sl_buffer"])
                print("[SYSTEM] Strategies reset. Resuming trading.\n")
                continue

            for symbol, strategy in active_strategies.items():
                # Get current bid/ask for sweep tracking
                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    continue
                    
                current_price = tick.bid # Using bid price for tracking
                
                # Get last few 1m candles for confirmation
                df_1m = mt5_engine.get_last_closed_candles(symbol, count=5)
                if df_1m is None:
                    continue
                
                # Pull live parameter updates from dashboard if any
                if "updates" in server.SHARED_STATE and symbol in server.SHARED_STATE["updates"]:
                    new_params = server.SHARED_STATE["updates"][symbol]
                    if "sl_buffer" in new_params:
                        strategy.sl_buffer = new_params["sl_buffer"]
                        SYMBOLS[symbol]["sl_buffer"] = new_params["sl_buffer"]
                    if "lot_size" in new_params:
                        SYMBOLS[symbol]["lot_size"] = new_params["lot_size"]
                    if "tp1" in new_params:
                        SYMBOLS[symbol]["tp1"] = new_params["tp1"]
                    if "tp2" in new_params:
                        SYMBOLS[symbol]["tp2"] = new_params["tp2"]
                    if "tp3" in new_params:
                        SYMBOLS[symbol]["tp3"] = new_params["tp3"]
                    if "trail" in new_params:
                        SYMBOLS[symbol]["trail"] = new_params["trail"]
                    del server.SHARED_STATE["updates"][symbol]
                    print(f"[{symbol}] ⚙️ Live parameters updated: SL Buffer = {strategy.sl_buffer}, Lot Size = {SYMBOLS[symbol]['lot_size']}")

                # Update strategy state
                signal = strategy.update(current_price, df_1m)
                
                # Push real-time targets to dashboard server
                server.SHARED_STATE["targets"][symbol] = {
                    "pdh": strategy.pdh,
                    "pdl": strategy.pdl,
                    "active_high": strategy.active_high_target,
                    "active_low": strategy.active_low_target,
                    "sweep_high_active": strategy.sweep_high_active,
                    "sweep_low_active": strategy.sweep_low_active
                }
                
                if signal:
                    execute_trades_for_signal(symbol, signal, SYMBOLS[symbol])
                    

            # Manage trailing stops and break evens
            manage_open_trades()
            
            # Wait 1 second before checking again
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
    finally:
        mt5.shutdown()


def manage_open_trades():
    for symbol, config in SYMBOLS.items():
        if not config.get("enabled"): continue
        magic = config.get("magic_number")
        
        positions = mt5.positions_get(symbol=symbol)
        if not positions: continue
        
        our_pos = [p for p in positions if p.magic == magic]
        if not our_pos: continue
        
        trail_amount = config.get("trail", 12.5)
        
        # Determine if TP1 has been closed (hit)
        # If there are TP2 or TP3 positions, but no TP1 position, TP1 is hit.
        has_tp2_or_tp3 = any(p.comment in ["Sweep TP2", "Sweep TP3"] for p in our_pos)
        tp1_open = any(p.comment == "Sweep TP1" for p in our_pos)
        tp1_hit = has_tp2_or_tp3 and not tp1_open
        
        for p in our_pos:
            is_buy = p.type == mt5.ORDER_TYPE_BUY
            
            # Check Break Even (ONLY IF TP1 IS HIT)
            if p.comment in ["Sweep TP2", "Sweep TP3"]:
                if tp1_hit:
                    # Move to BE if not already at BE or better
                    if (is_buy and p.sl < p.price_open) or (not is_buy and p.sl > p.price_open):
                        print(f"[{symbol}] TP1 Hit! Moving {p.comment} to Break-Even!")
                        mt5_engine.modify_position(symbol, p.ticket, p.price_open)
                        
            # Check Trailing Stop for TP3 (ONLY AFTER TP1 IS HIT)
            if p.comment == "Sweep TP3" and tp1_hit:
                if is_buy:
                    new_sl = p.price_current - trail_amount
                    if new_sl > p.sl and new_sl >= p.price_open:
                        print(f"[{symbol}] Trailing TP3 SL up to {new_sl}!")
                        mt5_engine.modify_position(symbol, p.ticket, new_sl)
                else:
                    new_sl = p.price_current + trail_amount
                    if (new_sl < p.sl or p.sl == 0.0) and new_sl <= p.price_open:
                        print(f"[{symbol}] Trailing TP3 SL down to {new_sl}!")
                        mt5_engine.modify_position(symbol, p.ticket, new_sl)


def execute_trades_for_signal(symbol, signal, config):
    action = signal['action']
    sl = signal['sl']
    runner_tp = signal['tp_target']
    
    lot_size = config['lot_size']
    magic = config['magic_number']
    
    # Get current entry price (Bid for Short, Ask for Long)
    tick = mt5.symbol_info_tick(symbol)
    entry_price = tick.bid if action == "SHORT" else tick.ask
    
    # Calculate Risk (Distance between Entry and SL)
    risk = abs(entry_price - sl)
    if risk == 0:
        print(f"[{symbol}] Risk is 0, skipping trade.")
        return
        
    # Read TP Configs (Default to old behavior if not set)
    rr_tp1 = config.get('tp1', 1.0)
    rr_tp2 = config.get('tp2', 2.0)
    rr_tp3 = config.get('tp3', 0.0)
        
    # Helper to calculate TP price
    def get_tp(rr_multiplier):
        if rr_multiplier == 0.0:
            return runner_tp
        if action == "SHORT":
            return entry_price - (risk * float(rr_multiplier))
        else:
            return entry_price + (risk * float(rr_multiplier))

    tp1 = get_tp(rr_tp1)
    tp2 = get_tp(rr_tp2)
    tp3 = get_tp(rr_tp3)
    
    order_type = mt5.ORDER_TYPE_SELL if action == "SHORT" else mt5.ORDER_TYPE_BUY

    print(f"\n==============================")

    print(f"EXECUTING {action} ON {symbol}")
    print(f"Entry: {entry_price} | SL: {sl}")
    print(f"TP1: {tp1} | TP2: {tp2} | TP3: {tp3}")
    
    # Divide lot size among 3 trades
    lot1 = round(lot_size / 3.0, 2)
    lot2 = round(lot_size / 3.0, 2)
    lot3 = round(lot_size - lot1 - lot2, 2)
    
    # Ensure minimum lot size (usually 0.01) just in case
    if lot1 <= 0: lot1 = 0.01
    if lot2 <= 0: lot2 = 0.01
    if lot3 <= 0: lot3 = 0.01

    # Open 3 separate positions
    trades = [
        {"name": "TP1", "tp": tp1, "lot": lot1},
        {"name": "TP2", "tp": tp2, "lot": lot2},
        {"name": "TP3", "tp": tp3, "lot": lot3}
    ]
    
    for t in trades:
        res = mt5_engine.execute_trade(
            symbol=symbol,
            order_type=order_type,
            lots=t['lot'],
            sl=sl,
            tp=t['tp'],
            magic=magic,
            comment=f"Sweep {t['name']}"
        )
        
        status = "SUCCESS" if res and res.retcode == mt5.TRADE_RETCODE_DONE else "FAILED"
        journal.log_trade(symbol, action, lot_size, entry_price, sl, t['tp'], status)
        
    print(f"==============================\n")


if __name__ == "__main__":
    main()
