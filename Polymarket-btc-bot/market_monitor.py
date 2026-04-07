# market_monitor.py
import json
import websocket
import threading
import time
from typing import Dict, Callable
import requests

class MarketMonitor:
    def __init__(self, config, callback: Callable):
        self.config = config
        self.callback = callback
        self.ws = None
        self.active_markets = {}
        self.running = False
        
    def get_active_btc_markets(self):
        """Fetch active BTC 15-minute markets from Polymarket"""
        url = f"{self.config.CLOB_API_URL}/markets"
        params = {
            "active": True,
            "closed": False
        }
        
        try:
            response = requests.get(url, params=params)
            markets = response.json()
            
            # Filter for BTC 15-minute UP/DOWN markets
            btc_markets = []
            for market in markets:
                title = market.get('question', '').upper()
                if 'BTC' in title and '15' in title and ('UP' in title or 'DOWN' in title):
                    # Check if market has both YES and NO outcomes
                    if len(market.get('tokens', [])) >= 2:
                        btc_markets.append({
                            'condition_id': market['condition_id'],
                            'question': market['question'],
                            'tokens': market['tokens'],
                            'end_date': market.get('end_date_iso')
                        })
            
            return btc_markets
        except Exception as e:
            print(f"Error fetching markets: {e}")
            return []
    
    def get_current_prices(self, condition_id: str) -> Dict:
        """Get current orderbook prices for a market"""
        url = f"{self.config.CLOB_API_URL}/price"
        params = {"condition_id": condition_id}
        
        try:
            response = requests.get(url, params=params)
            data = response.json()
            
            # Extract best bid/ask for YES and NO
            prices = {}
            for token_id, orderbook in data.items():
                best_bid = float(orderbook.get('bid', 0))
                best_ask = float(orderbook.get('ask', 1))
                mid_price = (best_bid + best_ask) / 2
                
                prices[token_id] = {
                    'bid': best_bid,
                    'ask': best_ask,
                    'mid': mid_price
                }
            
            return prices
        except Exception as e:
            print(f"Error fetching prices: {e}")
            return {}
    
    def check_arbitrage_opportunity(self, market):
        """Check if current prices present arbitrage opportunity"""
        condition_id = market['condition_id']
        prices = self.get_current_prices(condition_id)
        
        if len(prices) < 2:
            return None
        
        # Get token IDs for YES and NO
        token_ids = list(prices.keys())
        yes_token = token_ids[0]
        no_token = token_ids[1]
        
        # We buy at ASK prices
        yes_ask = prices[yes_token]['ask']
        no_ask = prices[no_token]['ask']
        total_cost = yes_ask + no_ask
        
        if total_cost <= self.config.MAX_TOTAL_COST:
            opportunity = {
                'condition_id': condition_id,
                'question': market['question'],
                'yes_token': yes_token,
                'no_token': no_token,
                'yes_price': yes_ask,
                'no_price': no_ask,
                'total_cost': total_cost,
                'expected_profit': 1.0 - total_cost,
                'profit_pct': ((1.0 - total_cost) / total_cost) * 100,
                'timestamp': time.time()
            }
            return opportunity
        
        return None
    
    def monitor_loop(self):
        """Main monitoring loop"""
        print("🔍 Starting market monitor...")
        
        while self.running:
            try:
                markets = self.get_active_btc_markets()
                print(f"📊 Monitoring {len(markets)} BTC 15-min markets")
                
                for market in markets:
                    opportunity = self.check_arbitrage_opportunity(market)
                    if opportunity:
                        print(f"\n🎯 OPPORTUNITY FOUND!")
                        print(f"Market: {opportunity['question']}")
                        print(f"YES: ${opportunity['yes_price']:.4f} | NO: ${opportunity['no_price']:.4f}")
                        print(f"Total Cost: ${opportunity['total_cost']:.4f}")
                        print(f"Expected Profit: ${opportunity['expected_profit']:.4f} ({opportunity['profit_pct']:.2f}%)")
                        
                        # Trigger callback to execute trade
                        self.callback(opportunity)
                
                time.sleep(self.config.CHECK_INTERVAL)
                
            except Exception as e:
                print(f"❌ Error in monitor loop: {e}")
                time.sleep(5)
    
    def start(self):
        """Start monitoring in background thread"""
        self.running = True
        self.thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.thread.start()
        print("✅ Market monitor started")
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
        if self.thread:
            self.thread.join()
        print("🛑 Market monitor stopped")
