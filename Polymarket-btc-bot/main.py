# main.py
import time
import signal
import sys
from config import Config
from market_monitor import MarketMonitor
from order_executor import OrderExecutor
from profit_tracker import ProfitTracker

class PolymarketArbitrageBot:
    def __init__(self):
        self.config = Config()
        self.executor = OrderExecutor(self.config)
        self.tracker = ProfitTracker()
        self.monitor = MarketMonitor(self.config, self.on_opportunity_found)
        self.running = False
        
        # Load historical data
        self.tracker.load_from_file()
        
    def on_opportunity_found(self, opportunity: dict):
        """Callback when arbitrage opportunity is found"""
        success = self.executor.execute_arbitrage_trade(opportunity)
        
        if success:
            print(f"\n✅ Trade executed successfully!")
            print(self.executor.get_positions_summary())
        else:
            print(f"\n❌ Trade execution failed")
    
    def print_status(self):
        """Print current bot status"""
        print("\n" + "="*60)
        print("🤖 POLYMARKET BTC 15-MIN ARBITRAGE BOT")
        print("="*60)
        print(self.tracker.get_daily_stats())
        print(self.tracker.get_all_time_stats())
        print(self.executor.get_positions_summary())
        print("="*60 + "\n")
    
    def start(self):
        """Start the bot"""
        print("\n🚀 Starting Polymarket Arbitrage Bot...")
        print(f"📊 Strategy: BTC 15-min UP/DOWN arbitrage")
        print(f"💰 Trade Size: ${self.config.TRADE_SIZE_USD} per leg")
        print(f"🎯 Max Entry Cost: ${self.config.MAX_TOTAL_COST}")
        print(f"📈 Min Profit Target: {((1.0 - self.config.MAX_TOTAL_COST) / self.config.MAX_TOTAL_COST) * 100:.2f}%\n")
        
        self.running = True
        self.monitor.start()
        
        # Status update loop
        try:
            while self.running:
                self.print_status()
                time.sleep(300)  # Print status every 5 minutes
                
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop the bot"""
        print("\n🛑 Stopping bot...")
        self.running = False
        self.monitor.stop()
        print("👋 Bot stopped. Goodbye!")
        sys.exit(0)

def main():
    bot = PolymarketArbitrageBot()
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        bot.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    bot.start()

if __name__ == "__main__":
    main()
