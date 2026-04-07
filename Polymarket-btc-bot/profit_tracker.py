# profit_tracker.py
import json
import time
from datetime import datetime

class ProfitTracker:
    def __init__(self):
        self.trades = []
        self.total_profit = 0
        self.total_trades = 0
        
    def record_trade(self, position: dict, actual_profit: float):
        """Record completed trade"""
        trade = {
            'timestamp': datetime.now().isoformat(),
            'market': position['question'],
            'cost': position['total_cost'],
            'expected_profit': position['expected_profit'],
            'actual_profit': actual_profit,
            'roi_pct': (actual_profit / position['total_cost']) * 100
        }
        
        self.trades.append(trade)
        self.total_profit += actual_profit
        self.total_trades += 1
        
        self.save_to_file()
        
    def get_daily_stats(self):
        """Get statistics for today"""
        today = datetime.now().date()
        today_trades = [t for t in self.trades if datetime.fromisoformat(t['timestamp']).date() == today]
        
        if not today_trades:
            return "No trades today"
        
        daily_profit = sum(t['actual_profit'] for t in today_trades)
        avg_roi = sum(t['roi_pct'] for t in today_trades) / len(today_trades)
        
        return f"""
📅 TODAY'S STATS:
   Trades: {len(today_trades)}
   Profit: ${daily_profit:.2f}
   Avg ROI: {avg_roi:.2f}%
        """
    
    def get_all_time_stats(self):
        """Get all-time statistics"""
        if not self.trades:
            return "No trades recorded"
        
        avg_profit = self.total_profit / self.total_trades
        avg_roi = sum(t['roi_pct'] for t in self.trades) / len(self.trades)
        
        return f"""
🏆 ALL-TIME STATS:
   Total Trades: {self.total_trades}
   Total Profit: ${self.total_profit:.2f}
   Avg Profit/Trade: ${avg_profit:.2f}
   Avg ROI: {avg_roi:.2f}%
        """
    
    def save_to_file(self):
        """Save trades to JSON file"""
        with open('trade_history.json', 'w') as f:
            json.dump({
                'trades': self.trades,
                'total_profit': self.total_profit,
                'total_trades': self.total_trades
            }, f, indent=2)
    
    def load_from_file(self):
        """Load trades from JSON file"""
        try:
            with open('trade_history.json', 'r') as f:
                data = json.load(f)
                self.trades = data.get('trades', [])
                self.total_profit = data.get('total_profit', 0)
                self.total_trades = data.get('total_trades', 0)
        except FileNotFoundError:
            pass
