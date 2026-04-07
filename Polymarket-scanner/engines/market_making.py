# engines/market_making.py

from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from collections import deque

from core.opportunity_detection import Opportunity, OpportunityEngine
from market_manager import MarketDataManager, MarketMetadata, OrderBookSnapshot


class MarketMakingEngine(OpportunityEngine):
    """
    Identify markets suitable for market making (wide spreads, balanced flow)
    """
    
    def __init__(self, 
                 min_spread_bps: float = 100,
                 min_liquidity: float = 5000,
                 min_flow_balance: float = 0.3,
                 max_volatility: float = 0.3):
        self.min_spread_bps = min_spread_bps
        self.min_liquidity = min_liquidity
        self.min_flow_balance = min_flow_balance
        self.max_volatility = max_volatility
        
        # Track market history for flow analysis
        self.market_history: Dict[str, deque] = {}
        self.max_history_length = 100
    
    async def scan(self, market_data: MarketDataManager) -> List[Opportunity]:
        opportunities = []
        
        for market_id, metadata in market_data.markets.items():
            if market_id not in market_data.orderbooks:
                continue
            
            orderbook = market_data.orderbooks[market_id]
            
            # Update market history
            self._update_history(market_id, orderbook)
            
            # Check if spread is attractive
            if orderbook.spread_bps < self.min_spread_bps:
                continue
            
            # Check liquidity
            if metadata.liquidity < self.min_liquidity:
                continue
            
            # Check if market is too close to resolution or already resolved
            days_to_resolution = (metadata.end_date - datetime.now(timezone.utc)).days
            # Skip markets that resolved more than 30 days ago (but allow recently resolved)
            if days_to_resolution < -30:
                continue
            
            # Skip markets from before 2023 (clearly old)
            old_cutoff = datetime(2023, 1, 1, tzinfo=timezone.utc)
            if metadata.end_date < old_cutoff:
                continue
            
            # Calculate volatility
            volatility = self._calculate_volatility(market_id)
            if volatility > self.max_volatility:
                continue  # Too volatile for market making
            
            # Check order flow balance
            flow_balance = self._check_flow_balance(market_id)
            
            if flow_balance < 0.1:  # More lenient - was 0.3
                continue
            
            # Check inventory risk
            inventory_risk = self._assess_inventory_risk(metadata, orderbook)
            
            # Calculate expected profit from making market
            expected_profit_per_unit = orderbook.spread * 0.5  # Capture half spread on average
            
            # Adjust for turnover rate (how quickly can we recycle capital)
            turnover_multiplier = self._estimate_turnover(metadata, orderbook)
            
            expected_profit = expected_profit_per_unit * turnover_multiplier
            
            # Risk penalty
            risk_penalty = 1.0
            risk_penalty += (orderbook.spread_bps / 100) * 0.3  # Wider spread = more risk
            risk_penalty += (1 - flow_balance) * 2.0  # Imbalanced flow = more risk
            risk_penalty += inventory_risk * 1.5
            risk_penalty += volatility * 3.0
            
            # Calculate score
            score = (expected_profit / risk_penalty) * (metadata.liquidity / 1000)
            
            # Minimum score threshold - very lenient
            if score < 0.1:
                continue
            
            # Calculate recommended position size
            recommended_size = self._calculate_position_size(
                metadata, orderbook, flow_balance, inventory_risk
            )
            
            opportunities.append(Opportunity(
                market_id=market_id,
                engine="market_making",
                direction="make_both_sides",
                entry_price=orderbook.mid_price,
                exit_price=orderbook.mid_price,  # Neutral position
                raw_edge=orderbook.spread,
                net_edge=expected_profit,
                confidence=flow_balance,
                fillable_size=recommended_size,
                score=score,
                metadata={
                    "question": metadata.question,
                    "spread_bps": orderbook.spread_bps,
                    "spread_dollars": orderbook.spread,
                    "flow_balance": flow_balance,
                    "volatility": volatility,
                    "inventory_risk": inventory_risk,
                    "liquidity": metadata.liquidity,
                    "volume_24h": metadata.volume_24h,
                    "days_to_resolution": days_to_resolution,
                    "expected_daily_profit": expected_profit * turnover_multiplier,
                    "recommended_bid": orderbook.best_bid + 0.01,
                    "recommended_ask": orderbook.best_ask - 0.01,
                    "recommended_size": recommended_size
                },
                timestamp=datetime.now(timezone.utc)
            ))
        
        return opportunities
    
    def _update_history(self, market_id: str, orderbook: OrderBookSnapshot):
        """Update market price history for analysis"""
        if market_id not in self.market_history:
            self.market_history[market_id] = deque(maxlen=self.max_history_length)
        
        self.market_history[market_id].append({
            'timestamp': datetime.utcnow(),
            'mid_price': orderbook.mid_price,
            'spread': orderbook.spread,
            'best_bid': orderbook.best_bid,
            'best_ask': orderbook.best_ask
        })
    
    def _calculate_volatility(self, market_id: str) -> float:
        """
        Calculate recent price volatility
        Returns standard deviation of price changes
        """
        if market_id not in self.market_history:
            return 0.5  # Unknown, assume moderate volatility
        
        history = list(self.market_history[market_id])
        
        if len(history) < 10:
            return 0.3  # Not enough data
        
        # Calculate price changes
        prices = [h['mid_price'] for h in history]
        price_changes = []
        
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                change = abs(prices[i] - prices[i-1]) / prices[i-1]
                price_changes.append(change)
        
        if not price_changes:
            return 0.3
        
        # Calculate standard deviation
        import numpy as np
        volatility = float(np.std(price_changes))
        
        return volatility
    
    def _check_flow_balance(self, market_id: str) -> float:
        """
        Check if order flow is balanced
        Returns a score from 0 (very imbalanced) to 1 (perfectly balanced)
        """
        if market_id not in self.market_history:
            return 0.5  # Unknown, assume neutral
        
        history = list(self.market_history[market_id])
        
        if len(history) < 5:
            return 0.5  # Not enough data
        
        # Analyze price movements
        up_moves = 0
        down_moves = 0
        
        for i in range(1, len(history)):
            if history[i]['mid_price'] > history[i-1]['mid_price']:
                up_moves += 1
            elif history[i]['mid_price'] < history[i-1]['mid_price']:
                down_moves += 1
        
        total_moves = up_moves + down_moves
        
        if total_moves == 0:
            return 0.5  # No movement
        
        # Calculate balance (closer to 0.5 is more balanced)
        up_ratio = up_moves / total_moves
        balance = 1.0 - abs(up_ratio - 0.5) * 2.0
        
        return balance
    
    def _assess_inventory_risk(self, metadata: MarketMetadata, 
                               orderbook: OrderBookSnapshot) -> float:
        """
        Assess risk of being stuck with inventory
        Higher score = higher risk
        """
        risk = 0.0
        
        # Risk increases as we get closer to resolution
        days_to_resolution = (metadata.end_date - datetime.now(timezone.utc)).days
        
        if days_to_resolution < 7:
            risk += 0.3
        elif days_to_resolution < 30:
            risk += 0.1
        
        # Risk increases with extreme prices (likely to be one-sided)
        if orderbook.mid_price < 0.2 or orderbook.mid_price > 0.8:
            risk += 0.2
        
        # Risk increases with low liquidity
        if metadata.liquidity < 10000:
            risk += 0.2
        elif metadata.liquidity < 20000:
            risk += 0.1
        
        # Risk increases with low volume (hard to exit)
        if metadata.volume_24h < 1000:
            risk += 0.3
        elif metadata.volume_24h < 5000:
            risk += 0.1
        
        return min(risk, 1.0)
    
    def _estimate_turnover(self, metadata: MarketMetadata,
                          orderbook: OrderBookSnapshot) -> float:
        """
        Estimate how many times per day we can turn over our capital
        Based on volume and spread
        """
        if metadata.liquidity == 0:
            return 1.0
        
        # Daily volume as a fraction of liquidity
        turnover_ratio = metadata.volume_24h / metadata.liquidity
        
        # Adjust for spread (wider spread = slower turnover)
        spread_penalty = 1.0 / (1.0 + orderbook.spread_bps / 100)
        
        estimated_turnover = turnover_ratio * spread_penalty * 10  # Scale factor
        
        # Cap at reasonable values
        return min(max(estimated_turnover, 0.5), 20.0)
    
    def _calculate_position_size(self, metadata: MarketMetadata,
                                 orderbook: OrderBookSnapshot,
                                 flow_balance: float,
                                 inventory_risk: float) -> float:
        """
        Calculate recommended position size for market making
        """
        # Start with 1% of liquidity as base
        base_size = metadata.liquidity * 0.01
        
        # Adjust based on flow balance (more balanced = larger size)
        size = base_size * flow_balance
        
        # Adjust based on inventory risk (higher risk = smaller size)
        size *= (1.0 - inventory_risk)
        
        # Adjust based on spread (wider spread = can afford larger size)
        if orderbook.spread_bps > 200:
            size *= 1.5
        elif orderbook.spread_bps > 150:
            size *= 1.2
        
        # Cap at reasonable limits
        max_size = min(metadata.liquidity * 0.05, 10000)  # Max 5% of liquidity or $10k
        min_size = 100  # Minimum $100
        
        return min(max(size, min_size), max_size)
