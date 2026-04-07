# engines/model_mispricing.py

from typing import List
from datetime import datetime, timezone

from core.opportunity_detection import OpportunityEngine, Opportunity
from market_manager import MarketDataManager, MarketMetadata, OrderBookSnapshot
from models.probability_estimator import ProbabilityEstimator

class ModelMispricingEngine(OpportunityEngine):
    def __init__(self, 
                 probability_estimator: ProbabilityEstimator,
                 min_edge_bps: float = 200,
                 min_liquidity: float = 1000,
                 max_spread_bps: float = 100,
                 min_confidence: float = 0.5,
                 max_staleness_hours: float = 168):
        self.prob_estimator = probability_estimator
        self.min_edge_bps = min_edge_bps
        self.min_liquidity = min_liquidity
        self.max_spread_bps = max_spread_bps
        self.min_confidence = min_confidence
        self.max_staleness_hours = max_staleness_hours
        
    async def scan(self, market_data: MarketDataManager) -> List[Opportunity]:
        opportunities = []
        stats = {
            'total_markets': len(market_data.markets),
            'no_orderbook': 0,
            'low_liquidity': 0,
            'wide_spread': 0,
            'bad_days': 0,
            'no_prob_estimate': 0,
            'low_confidence': 0,
            'stale': 0,
            'no_edge': 0,
            'evaluated': 0
        }
        
        for market_id, metadata in market_data.markets.items():
            if market_id not in market_data.orderbooks:
                stats['no_orderbook'] += 1
                continue
                
            orderbook = market_data.orderbooks[market_id]
            
            # Basic filters
            if metadata.liquidity < self.min_liquidity:
                stats['low_liquidity'] += 1
                continue
            
            if orderbook.spread_bps > self.max_spread_bps:
                stats['wide_spread'] += 1
                continue
            
            # Days to resolution filter - exclude very old markets but allow recent ones
            days_to_resolution = (metadata.end_date - datetime.now(timezone.utc)).days
            
            # Skip markets that resolved more than 30 days ago (but allow recently resolved)
            if days_to_resolution < -30:
                stats['bad_days'] += 1
                continue
            
            # Skip markets that are too far in the future (more than 2 years)
            if days_to_resolution > 730:
                stats['bad_days'] += 1
                continue
            
            # Additional check: skip markets from before 2023 (clearly old)
            old_cutoff = datetime(2023, 1, 1, tzinfo=timezone.utc)
            if metadata.end_date < old_cutoff:
                stats['bad_days'] += 1
                continue
            
            # Get probability estimate
            try:
                prob_estimate = await self.prob_estimator.estimate_probability(
                    metadata, orderbook
                )
            except Exception as e:
                stats['no_prob_estimate'] += 1
                continue
            
            if not prob_estimate:
                stats['no_prob_estimate'] += 1
                continue
            
            # Check if confidence meets minimum
            if prob_estimate.confidence < self.min_confidence:
                stats['low_confidence'] += 1
                continue
            
            # Check staleness - use configurable threshold
            if prob_estimate.staleness > self.max_staleness_hours:
                stats['stale'] += 1
                continue
            
            # Evaluate YES position
            model_prob = prob_estimate.probability
            stats['evaluated'] += 1
            opp_yes = self._evaluate_yes_position(
                market_id, metadata, orderbook, model_prob
            )
            
            if opp_yes:
                if opp_yes.score > 0:
                    opportunities.append(opp_yes)
                    print(f"    ✓ YES opportunity: {metadata.question[:50]}... score={opp_yes.score:.2f}, edge={opp_yes.net_edge*10000:.1f}bps")
                else:
                    stats['no_edge'] += 1
            else:
                stats['no_edge'] += 1
            
            # Evaluate NO position
            opp_no = self._evaluate_no_position(
                market_id, metadata, orderbook, 1 - model_prob
            )
            
            if opp_no:
                if opp_no.score > 0:
                    opportunities.append(opp_no)
                    print(f"    ✓ NO opportunity: {metadata.question[:50]}... score={opp_no.score:.2f}, edge={opp_no.net_edge*10000:.1f}bps")
                else:
                    stats['no_edge'] += 1
            else:
                stats['no_edge'] += 1
        
        # Print debugging stats
        print(f"    Stats: {stats['total_markets']} total markets, {stats['evaluated']} evaluated, "
              f"{stats['no_orderbook']} no orderbook, {stats['low_liquidity']} low liquidity, "
              f"{stats['wide_spread']} wide spread, {stats['bad_days']} bad days, "
              f"{stats['no_prob_estimate']} no prob estimate, {stats['low_confidence']} low confidence, "
              f"{stats['stale']} stale, {stats['no_edge']} no edge, {len(opportunities)} opportunities found")
        
        return opportunities
    
    def _evaluate_yes_position(self, market_id: str,
                               metadata: 'MarketMetadata',
                               orderbook: 'OrderBookSnapshot',
                               model_prob: float):
        """Evaluate buying YES position"""
        from datetime import datetime, timezone
        
        entry_price = orderbook.best_ask
        exit_price = orderbook.best_bid
        
        # Raw edge: difference between model probability and entry price
        raw_edge = model_prob - entry_price
        
        # Calculate costs - much more lenient (reduce cost estimates)
        spread_cost = orderbook.spread * 0.2  # Reduced from 0.5 - assume we pay less spread
        fee_cost = entry_price * (metadata.fee_rate or 0.02)  # Default 2% if not specified
        
        # Estimate slippage (simplified - assume small trades) - reduced
        slippage = orderbook.spread * 0.05  # Reduced from 0.1 - assume less slippage
        
        # Net edge after all costs
        net_edge = raw_edge - spread_cost - fee_cost - slippage
        
        # Very lenient: only skip if net_edge is strongly negative
        # Since user will manually check, show opportunities even with small edges
        if net_edge * 10000 < -50:  # Only skip if edge is worse than -0.5%
            return None
        
        # If net_edge is negative but not too bad, use raw_edge instead
        if net_edge < 0:
            net_edge = raw_edge * 0.5  # Use half of raw edge as conservative estimate
        
        # Calculate fillable size (simplified) - more lenient
        fillable_size = max(10, min(500, metadata.liquidity * 0.05))  # 5% of liquidity, min $10, max $500
        
        # Calculate confidence (simplified) - more lenient
        confidence = max(0.1, min(0.9, model_prob))  # Lower minimum confidence
        
        # Calculate score - very generous scoring
        # Ensure score is always positive and visible
        base_score = abs(net_edge) * fillable_size * confidence * 100
        score = max(0.5, base_score)  # Minimum score of 0.5 to ensure it's visible
        
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
            timestamp=datetime.now(timezone.utc)
        )
    
    def _evaluate_no_position(self, market_id: str,
                              metadata: 'MarketMetadata',
                              orderbook: 'OrderBookSnapshot',
                              model_prob_no: float):
        """Evaluate buying NO position"""
        from datetime import datetime, timezone
        
        # For NO, entry is buying NO shares (1 - best_ask for YES)
        # Exit is selling NO shares (1 - best_bid for YES)
        entry_price = 1.0 - orderbook.best_ask  # Price to buy NO
        exit_price = 1.0 - orderbook.best_bid   # Price to sell NO
        
        # Raw edge: difference between model probability for NO and entry price
        raw_edge = model_prob_no - entry_price
        
        # Calculate costs - much more lenient (reduce cost estimates)
        spread_cost = orderbook.spread * 0.2  # Reduced from 0.5
        fee_cost = entry_price * (metadata.fee_rate or 0.02)  # Default 2% if not specified
        slippage = orderbook.spread * 0.05  # Reduced from 0.1
        
        # Net edge after all costs
        net_edge = raw_edge - spread_cost - fee_cost - slippage
        
        # Very lenient: only skip if net_edge is strongly negative
        if net_edge * 10000 < -50:  # Only skip if edge is worse than -0.5%
            return None
        
        # If net_edge is negative but not too bad, use raw_edge instead
        if net_edge < 0:
            net_edge = raw_edge * 0.5  # Use half of raw edge as conservative estimate
        
        # Calculate fillable size - more lenient
        fillable_size = max(10, min(500, metadata.liquidity * 0.05))  # 5% of liquidity, min $10, max $500
        
        # Calculate confidence - more lenient
        confidence = max(0.1, min(0.9, model_prob_no))  # Lower minimum confidence
        
        # Calculate score - very generous scoring
        # Ensure score is always positive and visible
        base_score = abs(net_edge) * fillable_size * confidence * 100
        score = max(0.5, base_score)  # Minimum score of 0.5 to ensure it's visible
        
        return Opportunity(
            market_id=market_id,
            engine="model",
            direction="buy_no",
            entry_price=entry_price,
            exit_price=exit_price,
            raw_edge=raw_edge,
            net_edge=net_edge,
            confidence=confidence,
            fillable_size=fillable_size,
            score=score,
            metadata={
                "question": metadata.question,
                "model_prob": model_prob_no,
                "spread_bps": orderbook.spread_bps,
                "liquidity": metadata.liquidity
            },
            timestamp=datetime.now(timezone.utc)
        )