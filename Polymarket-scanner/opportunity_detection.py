from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from market_manager import MarketDataManager, MarketMetadata, OrderBookSnapshot

@dataclass
class Opportunity:
    market_id: str
    engine: str  # "model", "cross_market", "market_making"
    direction: str  # "buy_yes", "buy_no", "make_both"
    entry_price: float
    exit_price: float
    raw_edge: float
    net_edge: float
    confidence: float
    fillable_size: float
    score: float
    metadata: Dict
    timestamp: datetime

class OpportunityEngine(ABC):
    @abstractmethod
    async def scan(self, market_data: MarketDataManager) -> List[Opportunity]:
        pass

class ModelMispricingEngine(OpportunityEngine):
    def __init__(self, 
                 min_edge_bps: float = 200,  # 2% minimum edge
                 min_liquidity: float = 1000,
                 max_spread_bps: float = 100):
        self.min_edge_bps = min_edge_bps
        self.min_liquidity = min_liquidity
        self.max_spread_bps = max_spread_bps
        
    async def scan(self, market_data: MarketDataManager) -> List[Opportunity]:
        opportunities = []
        
        for market_id, metadata in market_data.markets.items():
            if market_id not in market_data.orderbooks:
                continue
                
            orderbook = market_data.orderbooks[market_id]
            
            # Basic liquidity filter
            if metadata.liquidity < self.min_liquidity:
                continue
            
            # Spread filter
            if orderbook.spread_bps > self.max_spread_bps:
                continue
            
            # Get your model's probability estimate
            model_prob = await self.get_model_probability(metadata)
            
            if model_prob is None:
                continue
            
            # Calculate opportunity for YES position
            opp = self._evaluate_yes_position(
                market_id, metadata, orderbook, model_prob
            )
            
            if opp and opp.score > 0:
                opportunities.append(opp)
            
            # Calculate opportunity for NO position
            opp = self._evaluate_no_position(
                market_id, metadata, orderbook, 1 - model_prob
            )
            
            if opp and opp.score > 0:
                opportunities.append(opp)
        
        return opportunities
    
    def _evaluate_yes_position(self, market_id: str, 
                               metadata: MarketMetadata,
                               orderbook: OrderBookSnapshot,
                               model_prob: float) -> Optional[Opportunity]:
        """
        Evaluate buying YES
        """
        entry_price = orderbook.best_ask
        exit_price = orderbook.best_bid
        
        # Raw edge
        raw_edge = model_prob - entry_price
        
        # Calculate costs
        spread_cost = orderbook.spread
        fee_cost = entry_price * metadata.fee_rate
        
        # Estimate slippage for a reasonable trade size
        target_size = min(100, metadata.liquidity * 0.01)  # 1% of liquidity
        slippage = orderbook.estimate_slippage(orderbook, "buy", target_size)
        
        if slippage == float('inf'):
            return None
        
        # Net edge after all costs
        net_edge = raw_edge - spread_cost - fee_cost - slippage
        
        # Apply minimum edge threshold
        if net_edge * 10000 < self.min_edge_bps:
            return None
        
        # Check that edge exceeds spread + buffer
        required_edge = spread_cost + (spread_cost * 0.5)  # 50% buffer
        if raw_edge < required_edge:
            return None
        
        # Calculate fillable size within slippage tolerance
        # Note: market_data should be passed as parameter or accessed via self
        # For now, using a placeholder calculation
        fillable_size = min(100, metadata.liquidity * 0.01)
        
        # Calculate confidence based on model and market conditions
        confidence = self._calculate_confidence(
            model_prob, metadata, orderbook
        )
        
        # Calculate score
        score = self._calculate_score(
            net_edge, fillable_size, confidence, 
            orderbook.spread_bps, metadata.liquidity
        )
        
        return Opportunity(
            market_id=market_id,
            engine="model",
            direction="buy_yes",
            entry_price=entry_price,
            exit_price=exit_price,
            raw_edge=raw_edge,
            net_edge=net_edge,
            confidence=confidence,
            fillable_size=fillable_size,
            score=score,
            metadata={
                "question": metadata.question,
                "model_prob": model_prob,
                "spread_bps": orderbook.spread_bps,
                "liquidity": metadata.liquidity
            },
            timestamp=datetime.utcnow()
        )
    
    def _evaluate_no_position(self, market_id: str,
                              metadata: MarketMetadata,
                              orderbook: OrderBookSnapshot,
                              model_prob_no: float) -> Optional[Opportunity]:
        """
        Similar to _evaluate_yes_position but for NO side
        """
        # Implementation mirrors YES logic but for NO outcomes
        pass
    
    def _calculate_confidence(self, model_prob: float,
                             metadata: MarketMetadata,
                             orderbook: OrderBookSnapshot) -> float:
        """
        Calculate confidence score based on:
        - Model calibration history
        - Market conditions (liquidity, spread)
        - Time to resolution
        - Data freshness
        """
        confidence = 0.5  # Base confidence
        
        # Increase confidence with higher liquidity
        if metadata.liquidity > 10000:
            confidence += 0.2
        elif metadata.liquidity > 5000:
            confidence += 0.1
        
        # Decrease confidence with wide spreads
        if orderbook.spread_bps > 50:
            confidence -= 0.2
        
        # Decrease confidence close to resolution
        days_to_resolution = (metadata.end_date - datetime.utcnow()).days
        if days_to_resolution < 1:
            confidence -= 0.3
        elif days_to_resolution < 7:
            confidence -= 0.1
        
        return max(0, min(1, confidence))
    
    def _calculate_score(self, net_edge: float, fillable_size: float,
                        confidence: float, spread_bps: float,
                        liquidity: float) -> float:
        """
        Score = (edge after costs × fillable size × confidence) / risk_penalty
        """
        # Risk penalty increases with spread and low liquidity
        risk_penalty = 1.0
        risk_penalty += (spread_bps / 100) * 0.5  # Penalize wide spreads
        risk_penalty += max(0, (5000 - liquidity) / 5000)  # Penalize thin liquidity
        
        score = (net_edge * fillable_size * confidence) / risk_penalty
        
        return score
    
    async def get_model_probability(self, metadata: MarketMetadata) -> Optional[float]:
        """
        This is where you'd call your prediction model
        Could be:
        - A statistical model
        - An ML model
        - An aggregator of other sources
        - Manual probabilities you maintain
        """
        # Placeholder - implement your actual model here
        return None

class CrossMarketEngine(OpportunityEngine):
    """
    Detect arbitrage and inconsistencies across related markets
    """
    
    def __init__(self, min_edge_bps: float = 100):
        self.min_edge_bps = min_edge_bps
    
    async def scan(self, market_data: MarketDataManager) -> List[Opportunity]:
        opportunities = []
        
        # Find related market groups
        market_groups = self._find_related_markets(market_data)
        
        for group in market_groups:
            # Check for monotonic time violations
            time_arbs = self._check_time_monotonicity(group, market_data)
            opportunities.extend(time_arbs)
            
            # Check for partition violations (mutually exclusive outcomes)
            partition_arbs = self._check_partition_consistency(group, market_data)
            opportunities.extend(partition_arbs)
            
            # Check for same event different wrappers
            wrapper_arbs = self._check_wrapper_consistency(group, market_data)
            opportunities.extend(wrapper_arbs)
        
        return opportunities
    
    def _find_related_markets(self, market_data: MarketDataManager) -> List[List[str]]:
        """
        Group related markets by common keywords, dates, entities
        """
        # Implementation would use NLP/string matching to find related markets
        pass
    
    def _check_time_monotonicity(self, group: List[str],
                                  market_data: MarketDataManager) -> List[Opportunity]:
        """
        E.g., "Event by March 1" should not be cheaper than "Event by April 1"
        """
        opportunities = []
        
        # Sort markets by end date
        sorted_markets = sorted(
            [(mid, market_data.markets[mid]) for mid in group],
            key=lambda x: x[1].end_date
        )
        
        for i in range(len(sorted_markets) - 1):
            earlier_id, earlier_meta = sorted_markets[i]
            later_id, later_meta = sorted_markets[i + 1]
            
            if earlier_id not in market_data.orderbooks or \
               later_id not in market_data.orderbooks:
                continue
            
            earlier_book = market_data.orderbooks[earlier_id]
            later_book = market_data.orderbooks[later_id]
            
            # Earlier date YES should be >= later date YES
            if earlier_book.best_ask < later_book.best_bid:
                # Arbitrage: buy earlier, sell later
                net_edge = later_book.best_bid - earlier_book.best_ask
                net_edge -= (earlier_book.spread + later_book.spread)
                
                if net_edge * 10000 >= self.min_edge_bps:
                    # Get depth values safely
                    earlier_ask_depth = earlier_book.ask_depth[0][1] if hasattr(earlier_book, 'ask_depth') and earlier_book.ask_depth else 0
                    later_bid_depth = later_book.bid_depth[0][1] if hasattr(later_book, 'bid_depth') and later_book.bid_depth else 0
                    
                    opportunities.append(Opportunity(
                        market_id=f"{earlier_id}_{later_id}",
                        engine="cross_market",
                        direction="time_arb",
                        entry_price=earlier_book.best_ask,
                        exit_price=later_book.best_bid,
                        raw_edge=later_book.best_bid - earlier_book.best_ask,
                        net_edge=net_edge,
                        confidence=0.9,  # High confidence for structural arbs
                        fillable_size=min(earlier_ask_depth, later_bid_depth),
                        score=net_edge * 1000,  # High weight for arbs
                        metadata={
                            "earlier_market": earlier_meta.question,
                            "later_market": later_meta.question,
                            "type": "time_monotonicity"
                        },
                        timestamp=datetime.utcnow()
                    ))
        
        return opportunities
    
    def _check_partition_consistency(self, group: List[str],
                                     market_data: MarketDataManager) -> List[Opportunity]:
        """
        E.g., "Winner: A", "Winner: B", "Winner: C" should sum to ~1.0
        """
        # Implementation would check if YES prices sum correctly
        pass
    
    def _check_wrapper_consistency(self, group: List[str],
                                   market_data: MarketDataManager) -> List[Opportunity]:
        """
        Same event expressed differently should have consistent prices
        """
        pass

class MarketMakingEngine(OpportunityEngine):
    """
    Identify markets suitable for market making (wide spreads, balanced flow)
    """
    
    def __init__(self, 
                 min_spread_bps: float = 100,
                 min_liquidity: float = 5000):
        self.min_spread_bps = min_spread_bps
        self.min_liquidity = min_liquidity
    
    async def scan(self, market_data: MarketDataManager) -> List[Opportunity]:
        opportunities = []
        
        for market_id, metadata in market_data.markets.items():
            if market_id not in market_data.orderbooks:
                continue
            
            orderbook = market_data.orderbooks[market_id]
            
            # Check if spread is attractive
            if orderbook.spread_bps < self.min_spread_bps:
                continue
            
            # Check liquidity
            if metadata.liquidity < self.min_liquidity:
                continue
            
            # Check order flow balance (would need historical data)
            flow_balance = await self._check_flow_balance(market_id)
            
            if flow_balance < 0.3:  # Too imbalanced
                continue
            
            # Calculate expected profit from making market
            expected_profit = orderbook.spread * 0.5  # Capture half spread
            risk_penalty = 1.0 / flow_balance  # Higher risk if imbalanced
            
            score = (expected_profit / risk_penalty) * metadata.liquidity
            
            # Get depth values safely
            ask_depth = orderbook.ask_depth[0][1] if hasattr(orderbook, 'ask_depth') and orderbook.ask_depth else 0
            bid_depth = orderbook.bid_depth[0][1] if hasattr(orderbook, 'bid_depth') and orderbook.bid_depth else 0
            
            opportunities.append(Opportunity(
                market_id=market_id,
                engine="market_making",
                direction="make_both",
                entry_price=orderbook.mid_price,
                exit_price=orderbook.mid_price,
                raw_edge=orderbook.spread,
                net_edge=expected_profit,
                confidence=flow_balance,
                fillable_size=min(ask_depth, bid_depth),
                score=score,
                metadata={
                    "question": metadata.question,
                    "spread_bps": orderbook.spread_bps,
                    "flow_balance": flow_balance
                },
                timestamp=datetime.utcnow()
            ))
        
        return opportunities
    
    async def _check_flow_balance(self, market_id: str) -> float:
        """
        Check if order flow is balanced (0.5 = perfectly balanced)
        """
        # Would analyze recent trade history
        return 0.5  # Placeholder
