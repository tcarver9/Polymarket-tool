# order_executor.py
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from web3 import Web3
import time

class OrderExecutor:
    def __init__(self, config):
        self.config = config
        
        # Initialize Polymarket CLOB client
        self.client = ClobClient(
            key=config.PRIVATE_KEY,
            chain_id=137,  # Polygon mainnet
            host=config.CLOB_API_URL
        )
        
        self.active_positions = []
        self.daily_trades = 0
        self.last_reset = time.time()
        
    def reset_daily_counter(self):
        """Reset daily trade counter"""
        current_time = time.time()
        if current_time - self.last_reset > 86400:  # 24 hours
            self.daily_trades = 0
            self.last_reset = current_time
            print("🔄 Daily trade counter reset")
    
    def can_execute_trade(self) -> bool:
        """Check if we can execute a new trade"""
        self.reset_daily_counter()
        
        if self.daily_trades >= self.config.MAX_DAILY_TRADES:
            print(f"⚠️ Daily trade limit reached ({self.config.MAX_DAILY_TRADES})")
            return False
        
        if len(self.active_positions) >= self.config.MAX_OPEN_POSITIONS:
            print(f"⚠️ Max open positions reached ({self.config.MAX_OPEN_POSITIONS})")
            return False
        
        return True
    
    def calculate_shares(self, price: float, usd_amount: float) -> float:
        """Calculate number of shares to buy"""
        return usd_amount / price
    
    def execute_arbitrage_trade(self, opportunity: dict) -> bool:
        """Execute both legs of arbitrage trade"""
        if not self.can_execute_trade():
            return False
        
        try:
            print(f"\n💰 EXECUTING TRADE")
            print(f"Market: {opportunity['question']}")
            
            # Calculate shares for equal USD value
            yes_shares = self.calculate_shares(
                opportunity['yes_price'], 
                self.config.TRADE_SIZE_USD
            )
            no_shares = self.calculate_shares(
                opportunity['no_price'], 
                self.config.TRADE_SIZE_USD
            )
            
            # Place YES order
            yes_order = self.place_order(
                token_id=opportunity['yes_token'],
                side='BUY',
                price=opportunity['yes_price'],
                size=yes_shares
            )
            
            if not yes_order:
                print("❌ Failed to place YES order")
                return False
            
            print(f"✅ YES order placed: {yes_shares:.2f} shares @ ${opportunity['yes_price']:.4f}")
            
            # Place NO order
            no_order = self.place_order(
                token_id=opportunity['no_token'],
                side='BUY',
                price=opportunity['no_price'],
                size=no_shares
            )
            
            if not no_order:
                print("❌ Failed to place NO order")
                # TODO: Cancel YES order
                return False
            
            print(f"✅ NO order placed: {no_shares:.2f} shares @ ${opportunity['no_price']:.4f}")
            
            # Record position
            position = {
                'condition_id': opportunity['condition_id'],
                'question': opportunity['question'],
                'yes_shares': yes_shares,
                'no_shares': no_shares,
                'yes_cost': yes_shares * opportunity['yes_price'],
                'no_cost': no_shares * opportunity['no_price'],
                'total_cost': (yes_shares * opportunity['yes_price']) + (no_shares * opportunity['no_price']),
                'expected_profit': opportunity['expected_profit'] * min(yes_shares, no_shares),
                'timestamp': opportunity['timestamp']
            }
            
            self.active_positions.append(position)
            self.daily_trades += 1
            
            print(f"📈 Position opened | Total cost: ${position['total_cost']:.2f} | Expected profit: ${position['expected_profit']:.2f}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error executing trade: {e}")
            return False
    
    def place_order(self, token_id: str, side: str, price: float, size: float):
        """Place a single order on Polymarket"""
        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
                order_type=OrderType.GTC  # Good till cancelled
            )
            
            signed_order = self.client.create_order(order_args)
            resp = self.client.post_order(signed_order)
            
            return resp
            
        except Exception as e:
            print(f"Error placing order: {e}")
            return None
    
    def get_positions_summary(self):
        """Get summary of active positions"""
        if not self.active_positions:
            return "No active positions"
        
        summary = f"\n📊 ACTIVE POSITIONS ({len(self.active_positions)}):\n"
        total_cost = sum(p['total_cost'] for p in self.active_positions)
        total_expected = sum(p['expected_profit'] for p in self.active_positions)
        
        for i, pos in enumerate(self.active_positions, 1):
            summary += f"\n{i}. {pos['question'][:50]}..."
            summary += f"\n   Cost: ${pos['total_cost']:.2f} | Expected Profit: ${pos['expected_profit']:.2f}\n"
        
        summary += f"\n💼 TOTAL: ${total_cost:.2f} cost | ${total_expected:.2f} expected profit"
        return summary
