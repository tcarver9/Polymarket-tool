import time
import signal
import sys
from config import (
    DISCORD_WEBHOOK_URL,
    TRACKED_ACCOUNTS,
    CHECK_INTERVAL,
    POLYMARKET_API_BASE,
    POLYMARKET_GAMMA_API,
    POLYMARKET_DATA_API,
    POLYMARKET_API_KEY,
    POLYMARKET_API_SECRET,
    POLYMARKET_API_PASSPHRASE
)
from discord_notifier import DiscordNotifier
from polymarket_tracker import PolymarketTracker

class PolymarketBot:
    def __init__(self):
        self.notifier = DiscordNotifier(DISCORD_WEBHOOK_URL)
        self.tracker = PolymarketTracker(
            POLYMARKET_API_BASE, 
            POLYMARKET_GAMMA_API, 
            POLYMARKET_API_KEY,
            POLYMARKET_API_SECRET,
            POLYMARKET_API_PASSPHRASE,
            POLYMARKET_DATA_API
        )
        self.last_trade_timestamps = {account: {} for account in TRACKED_ACCOUNTS}
        self.running = True
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        print("\n🛑 Shutting down bot gracefully...")
        self.running = False
        sys.exit(0)
    
    def check_trades(self):
        """Check for new trades from tracked accounts"""
        print(f"🔍 Checking trades at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        for account in TRACKED_ACCOUNTS:
            try:
                trades = self.tracker.get_user_trades(account, limit=50)
                
                if not trades:
                    continue  # No trades for this account, skip
                
                for trade in trades:
                    trade_id = trade.get('id') or trade.get('trade_id')
                    
                    # Skip if we've already processed this trade for this account
                    if trade_id and trade_id in self.last_trade_timestamps.get(account, {}):
                        continue
                    
                    # Parse trade data
                    parsed_trade = self.tracker.parse_trade(trade, account)
                    
                    if parsed_trade:
                        # Send new trade notification
                        print(f"📢 New trade detected for {account[:10]}...")
                        self.notifier.send_new_trade_notification(parsed_trade)
                        
                        # Update position cache
                        self.tracker.update_position_cache(account, trade)
                        
                        # Check if this is a closing trade and calculate P/L
                        if trade.get('side') == 'SELL':
                            pnl_data = self.tracker.calculate_profit_loss(
                                account, 
                                trade.get('asset_id'),
                                trade
                            )
                            
                            if pnl_data:
                                # Add market info to P/L data
                                market_info = self.tracker.get_market_info(trade.get('asset_id'))
                                pnl_data['market_name'] = market_info.get('question', 'Unknown Market') if market_info else 'Unknown Market'
                                pnl_data['market_url'] = None  # URLs not working reliably
                                
                                # Get market outcomes
                                outcomes = []
                                if market_info:
                                    tokens = market_info.get('tokens', [])
                                    for token in tokens:
                                        outcome_name = token.get('outcome', '') or token.get('name', '')
                                        if outcome_name:
                                            outcomes.append(outcome_name)
                                
                                if outcomes and len(outcomes) > 0:
                                    if len(outcomes) == 2:
                                        pnl_data['market_outcomes_display'] = f"**Outcomes:** {outcomes[0]} vs {outcomes[1]}"
                                    else:
                                        pnl_data['market_outcomes_display'] = f"**Outcomes:** {', '.join(outcomes)}"
                                else:
                                    pnl_data['market_outcomes_display'] = ''
                                
                                pnl_data['outcome'] = trade.get('outcome', 'Unknown')
                                
                                print(f"💰 Trade concluded with P/L: ${pnl_data['profit_loss']:.2f}")
                                self.notifier.send_trade_result_notification(pnl_data)
                        
                        # Mark trade as processed
                        if account not in self.last_trade_timestamps:
                            self.last_trade_timestamps[account] = {}
                        self.last_trade_timestamps[account][trade_id] = trade.get('timestamp')
            
            except Exception as e:
                error_msg = f"Error checking trades for {account}: {str(e)}"
                print(f"❌ {error_msg}")
                self.notifier.send_error_notification(error_msg)
    
    def run(self):
        """Main bot loop"""
        print("🤖 Polymarket Trade Tracker Bot Started")
        print(f"📊 Tracking {len(TRACKED_ACCOUNTS)} account(s)")
        print(f"⏱️  Check interval: {CHECK_INTERVAL} seconds")
        
        # Check if Builder API credentials are configured
        if not POLYMARKET_API_KEY:
            print("⚠️  WARNING: POLYMARKET_API_KEY not set in .env file")
        elif not POLYMARKET_API_SECRET:
            print("⚠️  WARNING: POLYMARKET_API_SECRET not set in .env file")
            print("   Builder API requires API_KEY, API_SECRET, and API_PASSPHRASE.")
        elif not POLYMARKET_API_PASSPHRASE:
            print("⚠️  WARNING: POLYMARKET_API_PASSPHRASE not set in .env file")
            print("   Builder API requires API_KEY, API_SECRET, and API_PASSPHRASE.")
        else:
            print(f"🔑 Builder API credentials configured")
            print(f"   API Key: {POLYMARKET_API_KEY[:10]}...")
        
        print("-" * 50)
        
        # Send startup notification
        startup_message = f"Bot started! Tracking {len(TRACKED_ACCOUNTS)} Polymarket account(s)."
        self.notifier.send_error_notification(startup_message)
        
        while self.running:
            try:
                self.check_trades()
                time.sleep(CHECK_INTERVAL)
            
            except Exception as e:
                error_msg = f"Critical error in main loop: {str(e)}"
                print(f"❌ {error_msg}")
                self.notifier.send_error_notification(error_msg)
                time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    bot = PolymarketBot()
    bot.run()
