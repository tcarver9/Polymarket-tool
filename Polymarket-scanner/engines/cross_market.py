# engines/cross_market.py

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict
import re
from difflib import SequenceMatcher

from core.opportunity_detection import Opportunity, OpportunityEngine
from market_manager import MarketDataManager, MarketMetadata, OrderBookSnapshot


class CrossMarketEngine(OpportunityEngine):
    """
    Detect arbitrage and inconsistencies across related markets
    """
    
    def __init__(self, min_edge_bps: float = 100):
        self.min_edge_bps = min_edge_bps
        self.market_groups_cache = {}
        self.cache_timestamp = None
    
    async def scan(self, market_data: MarketDataManager) -> List[Opportunity]:
        opportunities = []
        
        # Find related market groups
        market_groups = self._find_related_markets(market_data)
        
        print(f"  Found {len(market_groups)} related market groups")
        
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
        # Use cache if fresh (less than 5 minutes old)
        if self.cache_timestamp and (datetime.now(timezone.utc) - self.cache_timestamp).seconds < 300:
            return list(self.market_groups_cache.values())
        
        # Group markets by similarity
        market_groups = defaultdict(list)
        
        for market_id, metadata in market_data.markets.items():
            # Create a signature for this market
            signature = self._create_market_signature(metadata)
            
            # Find existing groups that match
            matched = False
            for group_sig, group_markets in list(market_groups.items()):
                if self._signatures_match(signature, group_sig):
                    group_markets.append(market_id)
                    matched = True
                    break
            
            if not matched:
                market_groups[signature] = [market_id]
        
        # Filter out single-market groups
        filtered_groups = [group for group in market_groups.values() if len(group) > 1]
        
        # Update cache
        self.market_groups_cache = {i: group for i, group in enumerate(filtered_groups)}
        self.cache_timestamp = datetime.now(timezone.utc)
        
        return filtered_groups
    
    def _create_market_signature(self, metadata: MarketMetadata) -> str:
        """
        Create a signature for market grouping
        """
        question = metadata.question.lower()
        
        # Extract key entities
        entities = []
        
        # Remove common words
        stop_words = {'will', 'be', 'the', 'a', 'an', 'by', 'on', 'at', 'in', 'before', 'after', 'above', 'below'}
        words = [w for w in re.findall(r'\b\w+\b', question) if w not in stop_words and len(w) > 2]
        
        # Keep important words (names, dates, numbers)
        for word in words[:10]:  # Take first 10 significant words
            entities.append(word)
        
        # Add tags
        entities.extend(metadata.tags)
        
        # Create signature
        signature = '|'.join(sorted(set(entities)))
        
        return signature
    
    def _signatures_match(self, sig1: str, sig2: str, threshold: float = 0.6) -> bool:
        """
        Check if two market signatures match
        """
        # Use sequence matcher to find similarity
        ratio = SequenceMatcher(None, sig1, sig2).ratio()
        return ratio >= threshold
    
    def _check_time_monotonicity(self, group: List[str],
                                  market_data: MarketDataManager) -> List[Opportunity]:
        """
        Check for time-based arbitrage opportunities
        E.g., "Event by March 1" should not be cheaper than "Event by April 1"
        """
        opportunities = []
        
        # Filter markets with time-based conditions
        time_markets = []
        for market_id in group:
            if market_id not in market_data.markets:
                continue
            
            metadata = market_data.markets[market_id]
            
            # Look for time indicators in question
            if self._has_time_condition(metadata.question):
                time_markets.append((market_id, metadata))
        
        if len(time_markets) < 2:
            return opportunities
        
        # Filter out resolved markets first
        current_time = datetime.now(timezone.utc)
        active_time_markets = [(mid, meta) for mid, meta in time_markets if meta.end_date > current_time]
        
        if len(active_time_markets) < 2:
            return opportunities
        
        # Sort by end date
        sorted_markets = sorted(active_time_markets, key=lambda x: x[1].end_date)
        
        # Check for violations
        for i in range(len(sorted_markets) - 1):
            earlier_id, earlier_meta = sorted_markets[i]
            later_id, later_meta = sorted_markets[i + 1]
            
            if earlier_id not in market_data.orderbooks or \
               later_id not in market_data.orderbooks:
                continue
            
            earlier_book = market_data.orderbooks[earlier_id]
            later_book = market_data.orderbooks[later_id]
            
            # Earlier date YES should be >= later date YES
            # If we can buy earlier cheaper than we can sell later, that's an arb
            if earlier_book.best_ask < later_book.best_bid:
                # Arbitrage opportunity
                gross_edge = later_book.best_bid - earlier_book.best_ask
                
                # Account for spreads and fees
                spread_cost = earlier_book.spread + later_book.spread
                fee_cost = (earlier_book.best_ask * earlier_meta.fee_rate + 
                           later_book.best_bid * later_meta.fee_rate)
                
                net_edge = gross_edge - spread_cost - fee_cost
                
                if net_edge * 10000 >= self.min_edge_bps:
                    # Calculate fillable size (limited by both markets)
                    fillable_size = min(
                        self._get_depth_at_price(earlier_book.ask_depth, earlier_book.best_ask),
                        self._get_depth_at_price(later_book.bid_depth, later_book.best_bid)
                    )
                    
                    opportunities.append(Opportunity(
                        market_id=f"time_arb_{earlier_id}_{later_id}",
                        engine="cross_market",
                        direction="time_arb",
                        entry_price=earlier_book.best_ask,
                        exit_price=later_book.best_bid,
                        raw_edge=gross_edge,
                        net_edge=net_edge,
                        confidence=0.90,  # High confidence for structural arbs
                        fillable_size=fillable_size,
                        score=net_edge * fillable_size * 1000,  # High weight for arbs
                        metadata={
                            "question": f"Time Arb: {earlier_meta.question[:50]}...",
                            "earlier_market": earlier_meta.question,
                            "earlier_date": earlier_meta.end_date.strftime('%Y-%m-%d'),
                            "later_market": later_meta.question,
                            "later_date": later_meta.end_date.strftime('%Y-%m-%d'),
                            "type": "time_monotonicity",
                            "earlier_id": earlier_id,
                            "later_id": later_id
                        },
                        timestamp=datetime.now(timezone.utc)
                    ))
        
        return opportunities
    
    def _check_partition_consistency(self, group: List[str],
                                     market_data: MarketDataManager) -> List[Opportunity]:
        """
        Check if mutually exclusive outcomes sum to approximately 1.0
        E.g., "Winner: A", "Winner: B", "Winner: C" should sum to ~1.0
        """
        opportunities = []
        
        # Look for markets that appear to be partitions
        partition_sets = self._identify_partitions(group, market_data)
        
        for partition in partition_sets:
            if len(partition) < 2:
                continue
            
            # Calculate sum of YES prices
            total_yes_ask = 0.0
            total_yes_bid = 0.0
            all_available = True
            min_fillable = float('inf')
            
            market_details = []
            
            for market_id in partition:
                if market_id not in market_data.orderbooks:
                    all_available = False
                    break
                
                orderbook = market_data.orderbooks[market_id]
                metadata = market_data.markets[market_id]
                
                total_yes_ask += orderbook.best_ask
                total_yes_bid += orderbook.best_bid
                
                fillable = self._get_depth_at_price(orderbook.ask_depth, orderbook.best_ask)
                min_fillable = min(min_fillable, fillable)
                
                market_details.append({
                    'id': market_id,
                    'question': metadata.question,
                    'ask': orderbook.best_ask,
                    'bid': orderbook.best_bid
                })
            
            if not all_available:
                continue
            
            # Check for over-pricing (sum > 1.0)
            if total_yes_ask > 1.05:  # 5% buffer for spreads
                # Opportunity: sell all outcomes
                edge = total_yes_bid - 1.0
                
                if edge * 10000 >= self.min_edge_bps:
                    opportunities.append(Opportunity(
                        market_id=f"partition_over_{partition[0]}",
                        engine="cross_market",
                        direction="sell_all",
                        entry_price=total_yes_bid,
                        exit_price=1.0,
                        raw_edge=edge,
                        net_edge=edge * 0.9,  # Conservative estimate
                        confidence=0.85,
                        fillable_size=min_fillable,
                        score=edge * min_fillable * 800,
                        metadata={
                            "question": f"Partition Over-priced: {len(partition)} outcomes",
                            "type": "partition_overpriced",
                            "markets": market_details,
                            "total_ask": total_yes_ask,
                            "total_bid": total_yes_bid
                        },
                        timestamp=datetime.now(timezone.utc)
                    ))
            
            # Check for under-pricing (sum < 1.0)
            elif total_yes_bid < 0.95:  # 5% buffer
                # Opportunity: buy all outcomes
                edge = 1.0 - total_yes_ask
                
                if edge * 10000 >= self.min_edge_bps:
                    opportunities.append(Opportunity(
                        market_id=f"partition_under_{partition[0]}",
                        engine="cross_market",
                        direction="buy_all",
                        entry_price=total_yes_ask,
                        exit_price=1.0,
                        raw_edge=edge,
                        net_edge=edge * 0.9,
                        confidence=0.85,
                        fillable_size=min_fillable,
                        score=edge * min_fillable * 800,
                        metadata={
                            "question": f"Partition Under-priced: {len(partition)} outcomes",
                            "type": "partition_underpriced",
                            "markets": market_details,
                            "total_ask": total_yes_ask,
                            "total_bid": total_yes_bid
                        },
                        timestamp=datetime.now(timezone.utc)
                    ))
        
        return opportunities
    
    def _check_wrapper_consistency(self, group: List[str],
                                   market_data: MarketDataManager) -> List[Opportunity]:
        """
        Check if the same event expressed differently has consistent prices
        E.g., "BTC > $50k" vs "BTC < $50k" should sum to 1.0
        """
        opportunities = []
        
        # Look for complementary markets (YES in one = NO in another)
        for i, market_id_1 in enumerate(group):
            for market_id_2 in group[i+1:]:
                if market_id_1 not in market_data.markets or market_id_2 not in market_data.markets:
                    continue
                
                meta_1 = market_data.markets[market_id_1]
                meta_2 = market_data.markets[market_id_2]
                
                # Check if they're complementary
                if not self._are_complementary(meta_1.question, meta_2.question):
                    continue
                
                if market_id_1 not in market_data.orderbooks or market_id_2 not in market_data.orderbooks:
                    continue
                
                book_1 = market_data.orderbooks[market_id_1]
                book_2 = market_data.orderbooks[market_id_2]
                
                # For complementary markets: P(A) + P(B) should = 1.0
                # YES in market 1 + YES in market 2 should = 1.0
                
                total_yes = book_1.mid_price + book_2.mid_price
                
                # Check for arbitrage
                if book_1.best_ask + book_2.best_ask < 0.98:
                    # Can buy both for less than $1
                    edge = 1.0 - (book_1.best_ask + book_2.best_ask)
                    
                    if edge * 10000 >= self.min_edge_bps:
                        fillable = min(
                            self._get_depth_at_price(book_1.ask_depth, book_1.best_ask),
                            self._get_depth_at_price(book_2.ask_depth, book_2.best_ask)
                        )
                        
                        opportunities.append(Opportunity(
                            market_id=f"complement_{market_id_1}_{market_id_2}",
                            engine="cross_market",
                            direction="buy_both",
                            entry_price=book_1.best_ask + book_2.best_ask,
                            exit_price=1.0,
                            raw_edge=edge,
                            net_edge=edge * 0.9,
                            confidence=0.88,
                            fillable_size=fillable,
                            score=edge * fillable * 900,
                            metadata={
                                "question": f"Complementary Markets Arb",
                                "type": "complementary_wrapper",
                                "market_1": meta_1.question,
                                "market_2": meta_2.question,
                                "id_1": market_id_1,
                                "id_2": market_id_2
                            },
                            timestamp=datetime.now(timezone.utc)
                        ))
        
        return opportunities
    
    def _has_time_condition(self, question: str) -> bool:
        """Check if question has a time-based condition"""
        time_keywords = [
            'by', 'before', 'after', 'in', 'during', 'end of', 'start of',
            'january', 'february', 'march', 'april', 'may', 'june',
            'july', 'august', 'september', 'october', 'november', 'december',
            '2024', '2025', '2026', 'q1', 'q2', 'q3', 'q4'
        ]
        
        question_lower = question.lower()
        return any(keyword in question_lower for keyword in time_keywords)
    
    def _identify_partitions(self, group: List[str], 
                            market_data: MarketDataManager) -> List[List[str]]:
        """
        Identify sets of markets that form a partition (mutually exclusive, exhaustive)
        """
        # Look for patterns like "Winner: X" or "Price range: X-Y"
        partition_sets = []
        
        # Group by common prefix
        prefix_groups = defaultdict(list)
        
        for market_id in group:
            if market_id not in market_data.markets:
                continue
            
            question = market_data.markets[market_id].question
            
            # Extract prefix (everything before a colon or hyphen)
            match = re.match(r'^([^::\-]+)[:\-]', question)
            if match:
                prefix = match.group(1).strip().lower()
                prefix_groups[prefix].append(market_id)
        
        # Keep groups with 2+ markets
        for prefix, markets in prefix_groups.items():
            if len(markets) >= 2:
                partition_sets.append(markets)
        
        return partition_sets
    
    def _are_complementary(self, question1: str, question2: str) -> bool:
        """
        Check if two questions are complementary (YES in one = NO in other)
        """
        q1_lower = question1.lower()
        q2_lower = question2.lower()
        
        # Look for opposite conditions
        opposite_pairs = [
            ('above', 'below'),
            ('over', 'under'),
            ('more than', 'less than'),
            ('greater than', 'less than'),
            ('win', 'lose'),
            ('yes', 'no'),
            ('pass', 'fail')
        ]
        
        for word1, word2 in opposite_pairs:
            if (word1 in q1_lower and word2 in q2_lower) or \
               (word2 in q1_lower and word1 in q2_lower):
                # Check if the rest is similar
                q1_clean = q1_lower.replace(word1, '').replace(word2, '')
                q2_clean = q2_lower.replace(word1, '').replace(word2, '')
                
                similarity = SequenceMatcher(None, q1_clean, q2_clean).ratio()
                if similarity > 0.7:
                    return True
        
        return False
    
    def _get_depth_at_price(self, depth: List[Tuple[float, float]], price: float) -> float:
        """Get available size at a specific price level"""
        for p, size in depth:
            if abs(p - price) < 0.0001:  # Float comparison
                return size
        return 0.0
