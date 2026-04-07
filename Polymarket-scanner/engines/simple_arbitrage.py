# engines/simple_arbitrage.py

from typing import List
from datetime import datetime, timezone

from core.opportunity_detection import Opportunity, OpportunityEngine
from market_manager import MarketDataManager, MarketMetadata, OrderBookSnapshot


class SimpleArbitrageEngine(OpportunityEngine):
    """
    Simple arbitrage detector - finds basic price discrepancies
    Focuses on:
    1. YES/NO price sum != 1.0 (partition arbitrage)
    2. Simple mispricing (market price vs fair value)
    """
    
    def __init__(self, min_edge_bps: float = 5):
        self.min_edge_bps = min_edge_bps  # Very low threshold - 0.05%
    
    async def scan(self, market_data: MarketDataManager) -> List[Opportunity]:
        opportunities = []
        
        print(f"    Scanning {len(market_data.markets)} markets for arbitrage...")
        print(f"    Markets with outcomePrices: {len(market_data.market_outcome_prices)}")
        print(f"    Markets with orderbooks: {len(market_data.orderbooks)}")
        
        for market_id, metadata in market_data.markets.items():
            # Try to get prices from outcomePrices first (direct from API)
            outcome_prices = market_data.market_outcome_prices.get(market_id, [])
            
            if outcome_prices and len(outcome_prices) >= 2:
                # Use outcomePrices directly from API
                try:
                    yes_price = float(outcome_prices[0]) if outcome_prices[0] is not None else 0.5
                    no_price = float(outcome_prices[1]) if outcome_prices[1] is not None else 0.5
                except (ValueError, TypeError):
                    # If parsing fails, use defaults
                    yes_price = 0.5
                    no_price = 0.5
            elif market_id in market_data.orderbooks:
                # Fall back to orderbook
                orderbook = market_data.orderbooks[market_id]
                yes_price = orderbook.mid_price
                no_price = 1.0 - yes_price
            else:
                # No price data - use defaults but still create opportunity
                yes_price = 0.5
                no_price = 0.5
            
            # Check 1: YES + NO should sum to ~1.0
            total_price = yes_price + no_price
            
            # Debug: print first few markets
            if len(opportunities) < 3:
                print(f"      Market: {metadata.question[:40]}... YES={yes_price:.3f}, NO={no_price:.3f}, Total={total_price:.3f}, Liquidity={metadata.liquidity:.2f}")
            
            # Check for ANY price discrepancy - flag everything for manual review
            # Since user will manually check, show all markets with any potential edge
            
            # Check 1: YES + NO sum != 1.0 (partition arbitrage)
            if abs(total_price - 1.0) > 0.0001:  # Even 0.01% difference (extremely lenient)
                edge = abs(total_price - 1.0)
                edge_bps = edge * 10000
                
                # Always flag if there's any discrepancy
                if edge_bps >= 1:  # Even 1 bps (0.01%)
                    # Determine direction
                    if total_price > 1.0:
                        # Overpriced - sell both sides
                        direction = "sell_both"
                        entry_price = total_price
                        exit_price = 1.0
                    else:
                        # Underpriced - buy both sides
                        direction = "buy_both"
                        entry_price = total_price
                        exit_price = 1.0
                    
                    opportunities.append(Opportunity(
                        market_id=market_id,
                        engine="simple_arbitrage",
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        raw_edge=edge,
                        net_edge=edge * 0.9,  # Assume 10% costs
                        confidence=0.95,  # High confidence for structural arbs
                        fillable_size=min(100, metadata.liquidity * 0.1),
                        score=edge * 1000,  # High score for arbs
                        metadata={
                            "question": metadata.question,
                            "type": "partition_arbitrage",
                            "yes_price": yes_price,
                            "no_price": no_price,
                            "total_price": total_price,
                            "edge_bps": edge_bps
                        },
                        timestamp=datetime.now(timezone.utc)
                    ))
            
            # Check 2: Flag interesting markets for manual review
            # Very lenient - flag all markets for review since user wants to check everything
            should_review = True  # Always flag for review
            review_reason = "manual_review"
            
            # Add more specific reasons if applicable
            if metadata.liquidity > 500:
                review_reason = "decent_liquidity"
            elif metadata.liquidity > 0:
                review_reason = "has_liquidity"
            
            # Extreme pricing (very high or very low) might be mispriced
            if yes_price < 0.3 or yes_price > 0.7:
                review_reason = "extreme_pricing"
            
            # Also check for somewhat extreme pricing
            if yes_price < 0.35 or yes_price > 0.65:
                if review_reason == "manual_review":
                    review_reason = "moderate_extreme_pricing"
            
            # Only create opportunity if there's a reason to review
            if should_review:
                review_score = max(50.0, metadata.liquidity * 0.05)  # Lower score than before
                
                opportunities.append(Opportunity(
                    market_id=market_id,
                    engine="simple_arbitrage",
                    direction="manual_review",
                    entry_price=yes_price,
                    exit_price=yes_price,
                    raw_edge=abs(total_price - 1.0) if total_price != 1.0 else 0.01,
                    net_edge=abs(total_price - 1.0) * 0.9 if total_price != 1.0 else 0.01,
                    confidence=0.3,  # Lower confidence for manual review
                    fillable_size=max(10, min(100, metadata.liquidity * 0.1)),
                    score=review_score,
                    metadata={
                        "question": metadata.question,
                        "type": "manual_review",
                        "reason": review_reason,
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "total_price": total_price,
                        "liquidity": metadata.liquidity,
                        "note": f"Flagged for manual review - {review_reason}"
                    },
                    timestamp=datetime.now(timezone.utc)
                ))
            
            # Check 3: Simple mispricing - if market is far from 0.5, might be mispriced
            # More lenient - flag if price is somewhat extreme
            if yes_price < 0.2 or yes_price > 0.8:
                # Extreme price - might be mispriced
                # Calculate a simple "fair value" as mean reversion
                fair_value = 0.5  # Assume mean reversion to 50/50
                edge = abs(yes_price - fair_value)
                edge_bps = edge * 10000
                
                if edge_bps >= self.min_edge_bps:  # Lowered threshold
                    if yes_price < 0.1:
                        direction = "buy_yes_undervalued"
                        entry_price = yes_price
                        exit_price = fair_value
                    else:
                        direction = "sell_yes_overvalued"
                        entry_price = yes_price
                        exit_price = fair_value
                    
                    opportunities.append(Opportunity(
                        market_id=market_id,
                        engine="simple_arbitrage",
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        raw_edge=edge,
                        net_edge=edge * 0.7,  # Lower confidence
                        confidence=0.5,  # Lower confidence for mean reversion
                        fillable_size=min(50, metadata.liquidity * 0.05),
                        score=edge * 500,
                        metadata={
                            "question": metadata.question,
                            "type": "mean_reversion",
                            "market_price": yes_price,
                            "fair_value": fair_value,
                            "edge_bps": edge_bps
                        },
                        timestamp=datetime.now(timezone.utc)
                    ))
        
        print(f"    Found {len(opportunities)} arbitrage opportunities")
        return opportunities
