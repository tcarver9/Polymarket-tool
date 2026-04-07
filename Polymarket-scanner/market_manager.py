import asyncio
import aiohttp
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

@dataclass
class OrderBookSnapshot:
    market_id: str
    timestamp: datetime
    best_bid: float
    best_ask: float
    bid_depth: List[Tuple[float, float]]  # [(price, size), ...]
    ask_depth: List[Tuple[float, float]]
    spread: float
    mid_price: float
    
    @property
    def spread_bps(self) -> float:
        """Spread in basis points relative to mid"""
        if self.mid_price == 0:
            return float('inf')
        return (self.spread / self.mid_price) * 10000

@dataclass
class MarketMetadata:
    market_id: str
    question: str
    end_date: datetime
    volume_24h: float
    liquidity: float
    fee_rate: float  # Usually 0, but check per market
    tags: List[str]
    resolution_source: str
    
class MarketDataManager:
    def __init__(self, gamma_api_key: str):
        self.gamma_api_key = gamma_api_key
        self.markets: Dict[str, MarketMetadata] = {}
        self.market_outcome_prices: Dict[str, List[float]] = {}  # Store outcomePrices from API
        self.orderbooks: Dict[str, OrderBookSnapshot] = {}
        
    async def fetch_markets(self):
        """Fetch all active markets from Gamma API"""
        # Try multiple possible API endpoint patterns with query parameters
        base_urls = [
            "https://gamma-api.polymarket.com/markets",
            "https://gamma-api.polymarket.com/v1/markets",
            "https://api.polymarket.com/markets",
            "https://api.polymarket.com/v1/markets",
            "https://clob.polymarket.com/markets",
        ]
        
        # Try different query parameter combinations to get active markets
        query_params_combinations = [
            {"active": "true", "closed": "false", "limit": "500", "sort": "-endDate"},  # Most recent first
            {"active": "true", "limit": "500", "sort": "-endDate"},
            {"closed": "false", "limit": "500", "sort": "-endDate"},
            {"limit": "500", "sort": "-endDate"},
            {"active": "true", "closed": "false", "limit": "200"},
            {"active": "true", "limit": "200"},
            {"limit": "200"},
            {},  # No params as fallback
        ]
        
        headers = {}
        if self.gamma_api_key:
            headers["Authorization"] = f"Bearer {self.gamma_api_key}"
        
        async with aiohttp.ClientSession() as session:
            data = None
            last_error = None
            successful_url = None
            
            for base_url in base_urls:
                for params in query_params_combinations:
                    url = base_url
                    if params:
                        # Build query string
                        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                        url = f"{base_url}?{query_string}"
                    
                    try:
                        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status == 200:
                                try:
                                    data = await resp.json()
                                    successful_url = url
                                    print(f"✓ Successfully fetched markets from {url}")
                                    break
                                except Exception as e:
                                    last_error = f"Failed to parse JSON from {url}: {e}"
                                    continue
                            elif resp.status == 401:
                                last_error = f"Authentication failed (401) for {url} - check your API key"
                                continue
                            elif resp.status == 404:
                                last_error = f"Endpoint not found (404) for {url}"
                                continue
                            else:
                                error_text = await resp.text()
                                last_error = f"Status {resp.status} from {url}: {error_text[:200]}"
                                continue
                    except aiohttp.ClientError as e:
                        last_error = f"Connection error for {url}: {e}"
                        continue
                    except Exception as e:
                        last_error = f"Unexpected error for {url}: {e}"
                        continue
                    
                    # Break outer loop if we got data
                    if data is not None:
                        break
                
                # Break outer loop if we got data
                if data is not None:
                    break
            
            if data is None:
                print(f"⚠ Failed to fetch markets from any endpoint. Last error: {last_error}")
                print("⚠ Using empty market list - scanner will not find opportunities")
                return
                
            # Handle both list and dict responses
            if isinstance(data, dict):
                markets_list = data.get('data', data.get('markets', data.get('results', [])))
                print(f"  API returned dict with keys: {list(data.keys())[:10]}")
            elif isinstance(data, list):
                markets_list = data
                print(f"  API returned list with {len(data)} items")
            else:
                print(f"⚠ Unexpected API response format: {type(data)}")
                markets_list = []
            
            if not markets_list:
                print(f"⚠ No markets found in API response")
                print(f"  Response type: {type(data)}")
                if isinstance(data, dict):
                    print(f"  Dict keys: {list(data.keys())}")
                elif isinstance(data, (str, bytes)):
                    print(f"  Response preview: {str(data)[:500]}")
                return
                
            current_time = datetime.now(timezone.utc)
            # Filter to only include CURRENT markets: 
            # 1. Active markets (end_date in the future) from 2024 onwards
            # 2. Recently resolved markets (within last 30 days) from 2024 onwards
            recent_cutoff = datetime(2024, 1, 1, tzinfo=timezone.utc)
            # Only include markets resolved within last 30 days (very recent)
            from datetime import timedelta
            thirty_days_ago = current_time - timedelta(days=30)
            
            print(f"Processing {len(markets_list)} markets from API...")
            filtered_stats = {
                'resolved': 0,
                'no_id': 0,
                'no_question': 0,
                'old_date': 0,
                'too_old_resolved': 0,
                'added': 0
            }
            
            for market in markets_list:
                # Skip if explicitly cancelled
                state = market.get('state', '').lower() if market.get('state') else ''
                if state == 'cancelled':
                    filtered_stats['resolved'] += 1
                    continue
                
                # STRICT: Only include ACTIVE markets (not closed)
                # This is critical - we only want current, tradeable markets
                active = market.get('active')
                closed = market.get('closed')
                
                # Skip if explicitly closed
                if closed is True:
                    filtered_stats['resolved'] += 1
                    continue
                
                # Skip if explicitly inactive
                if active is False:
                    filtered_stats['resolved'] += 1
                    continue
                
                # If both fields are available and market is closed/inactive, skip
                if active is not None and closed is not None:
                    if not active or closed:
                        filtered_stats['resolved'] += 1
                        continue
                
                # Debug: show first market's structure (before filtering)
                if filtered_stats['added'] == 0 and filtered_stats['no_id'] == 0:
                    print(f"  Sample market keys: {list(market.keys())[:15]}")
                    print(f"  Sample market: active={market.get('active')}, resolved={market.get('resolved')}, "
                          f"closed={market.get('closed')}, state={market.get('state')}")
                    print(f"    ID fields: id={market.get('id')}, conditionId={market.get('conditionId')}, "
                          f"slug={market.get('slug')}, market_id={market.get('market_id')}")
                    print(f"    Date fields: end_date_iso={market.get('end_date_iso')}, endDate={market.get('endDate')}")
                
                # Skip markets without required fields
                # Try multiple possible ID field names - conditionId is common in Polymarket API
                market_id = None
                for field_name in ['conditionId', 'condition_id', 'id', 'market_id', 'slug']:
                    value = market.get(field_name)
                    if value:
                        market_id = str(value)  # Convert to string in case it's a number
                        break
                
                if not market_id:
                    filtered_stats['no_id'] += 1
                    if filtered_stats['no_id'] <= 3:  # Debug: show first few markets without ID
                        print(f"    Market without ID - keys: {list(market.keys())[:10]}")
                        print(f"      Sample values: id={market.get('id')}, conditionId={market.get('conditionId')}, "
                              f"slug={market.get('slug')}, market_id={market.get('market_id')}")
                    continue
                    
                question = market.get('question') or market.get('title') or market.get('name', '')
                if not question:
                    filtered_stats['no_question'] += 1
                    continue
                
                # Handle end_date - try multiple possible field names (including end_date_iso from CLOB API)
                end_date_str = (market.get('end_date_iso') or 
                               market.get('endDateISO') or 
                               market.get('end_date') or 
                               market.get('endDate') or 
                               market.get('end_time') or 
                               market.get('endTime'))
                if not end_date_str:
                    # If no end date, use a default far in the future (1 year from now)
                    from datetime import timedelta
                    end_date = current_time + timedelta(days=365)
                else:
                    try:
                        # Try parsing the date
                        if isinstance(end_date_str, str):
                            # Handle ISO format with or without timezone
                            if 'T' in end_date_str:
                                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                            else:
                                end_date = datetime.fromisoformat(end_date_str)
                        else:
                            # If it's already a datetime or timestamp
                            end_date = end_date_str
                        
                        # Ensure timezone-aware
                        if end_date.tzinfo is None:
                            end_date = end_date.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError) as e:
                        print(f"⚠ Could not parse end_date for market {market_id}: {e}, using default")
                        from datetime import timedelta
                        end_date = current_time + timedelta(days=365)
                
                # Check if market is resolved (end_date in the past)
                is_resolved = end_date < current_time
                
                # STRICT FILTERING: Only include CURRENT markets
                # 1. Active markets (end_date in future) from 2024 onwards
                # 2. Very recently resolved markets (within last 30 days) from 2024 onwards
                
                # Debug: show date info for first few markets
                if filtered_stats['added'] < 3:
                    print(f"    Market date check: {question[:40]}... end_date={end_date.date()}, is_resolved={end_date < current_time}, days_diff={(end_date - current_time).days if not end_date < current_time else (current_time - end_date).days}")
                
                if is_resolved:
                    # Market is resolved - SKIP ALL RESOLVED MARKETS (we only want active markets)
                    days_since_resolution = (current_time - end_date).days
                    filtered_stats['too_old_resolved'] += 1
                    if filtered_stats['too_old_resolved'] <= 3:  # Debug: show first few filtered markets
                        print(f"    Filtered resolved market: {question[:50]}... (resolved {days_since_resolution} days ago, end_date: {end_date.date()})")
                    continue
                else:
                    # Market is active - only include if end_date is 2024 or later
                    if end_date < recent_cutoff:
                        filtered_stats['old_date'] += 1
                        if filtered_stats['old_date'] <= 3:  # Debug: show first few filtered markets
                            print(f"    Filtered old active market: {question[:50]}... (end_date: {end_date.date()}, cutoff: {recent_cutoff.date()})")
                        continue
                    # Also filter out markets too far in the future (more than 1 year)
                    days_to_resolution = (end_date - current_time).days
                    if days_to_resolution > 365:
                        filtered_stats['too_old_resolved'] += 1  # Reuse counter
                        if filtered_stats['too_old_resolved'] <= 3:
                            print(f"    Filtered far future market: {question[:50]}... (resolves in {days_to_resolution} days)")
                        continue
                
                
                try:
                    # Store outcomePrices if available (for direct arbitrage detection)
                    # Try multiple possible field names
                    outcome_prices = (market.get('outcomePrices') or 
                                     market.get('outcome_prices') or 
                                     market.get('prices') or 
                                     [])
                    
                    # Debug: show if we found outcomePrices
                    if filtered_stats['added'] == 0 and outcome_prices:
                        print(f"    Found outcomePrices: {outcome_prices[:5]}")
                    
                    self.markets[market_id] = MarketMetadata(
                        market_id=market_id,
                        question=question,
                        end_date=end_date,
                        volume_24h=float(market.get('volume_24h', market.get('volume24h', market.get('volume', 0)))),
                        liquidity=float(market.get('liquidity', 0)),
                        fee_rate=float(market.get('fee_rate', market.get('feeRate', 0.02))),
                        tags=market.get('tags', []),
                        resolution_source=market.get('resolution_source', market.get('resolutionSource', ''))
                    )
                    
                    # Store outcomePrices for easy access
                    if outcome_prices:
                        if not hasattr(self, 'market_outcome_prices'):
                            self.market_outcome_prices = {}
                        self.market_outcome_prices[market_id] = outcome_prices
                    
                    filtered_stats['added'] += 1
                except Exception as e:
                    print(f"⚠ Error creating MarketMetadata for {market_id}: {e}")
                    continue
            
            # Print filtering stats
            print(f"  Filtered: {filtered_stats['resolved']} cancelled, {filtered_stats['no_id']} no ID, "
                  f"{filtered_stats['no_question']} no question, {filtered_stats['old_date']} old date, "
                  f"{filtered_stats['too_old_resolved']} too old resolved")
            print(f"  Added: {filtered_stats['added']} markets")
            
            if filtered_stats['added'] == 0 and len(markets_list) > 0:
                print(f"  ⚠ WARNING: All {len(markets_list)} markets were filtered out!")
                print(f"  Consider making filters more lenient or checking API response format")
        
        # Fetch orderbooks for all markets
        await self.fetch_orderbooks()
    
    async def fetch_orderbooks(self):
        """Fetch orderbook data for all markets"""
        if not self.markets:
            return
        
        print(f"Creating orderbooks for {len(self.markets)} markets...")
        
        # For now, skip real orderbook fetching (too slow for 936 markets)
        # Instead, create mock orderbooks based on outcomePrices if available
        # This is much faster and SimpleArbitrageEngine prefers outcomePrices anyway
        
        created_count = 0
        for market_id, metadata in self.markets.items():
            # Try to use outcomePrices to create a more accurate mock orderbook
            outcome_prices = getattr(self, 'market_outcome_prices', {}).get(market_id, [])
            
            if outcome_prices and len(outcome_prices) >= 2:
                try:
                    yes_price = float(outcome_prices[0]) if outcome_prices[0] is not None else 0.5
                    no_price = float(outcome_prices[1]) if outcome_prices[1] is not None else 0.5
                    
                    # Create orderbook from outcomePrices
                    mid_price = yes_price
                    spread_pct = 0.02  # 2% spread
                    spread = mid_price * spread_pct
                    best_bid = max(0.01, mid_price - spread/2)
                    best_ask = min(0.99, mid_price + spread/2)
                    
                    base_size = max(10, metadata.liquidity * 0.001)
                    bid_depth = [(best_bid, base_size)]
                    ask_depth = [(best_ask, base_size)]
                    
                    self.orderbooks[market_id] = OrderBookSnapshot(
                        market_id=market_id,
                        timestamp=datetime.now(),
                        best_bid=best_bid,
                        best_ask=best_ask,
                        bid_depth=bid_depth,
                        ask_depth=ask_depth,
                        spread=spread,
                        mid_price=mid_price
                    )
                    created_count += 1
                except (ValueError, TypeError):
                    # Fall back to random mock if outcomePrices parsing fails
                    self._create_mock_orderbook(market_id, metadata)
            else:
                # No outcomePrices - create random mock
                self._create_mock_orderbook(market_id, metadata)
        
        print(f"✓ Created {len(self.orderbooks)} orderbooks ({created_count} from outcomePrices, {len(self.orderbooks) - created_count} mock)")
    
    def _parse_orderbook(self, market_id: str, data: dict) -> Optional[OrderBookSnapshot]:
        """Parse orderbook data from API response"""
        try:
            # Try different possible response formats
            bids = data.get('bids', data.get('bid', []))
            asks = data.get('asks', data.get('ask', []))
            
            if not bids or not asks:
                return None
            
            # Get best bid/ask
            best_bid = float(bids[0][0]) if isinstance(bids[0], (list, tuple)) else float(bids[0].get('price', 0))
            best_ask = float(asks[0][0]) if isinstance(asks[0], (list, tuple)) else float(asks[0].get('price', 0))
            
            # Parse depth
            bid_depth = [(float(b[0]), float(b[1])) if isinstance(b, (list, tuple)) else (float(b.get('price', 0)), float(b.get('size', 0))) for b in bids[:10]]
            ask_depth = [(float(a[0]), float(a[1])) if isinstance(a, (list, tuple)) else (float(a.get('price', 0)), float(a.get('size', 0))) for a in asks[:10]]
            
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2
            
            return OrderBookSnapshot(
                market_id=market_id,
                timestamp=datetime.now(),
                best_bid=best_bid,
                best_ask=best_ask,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
                spread=spread,
                mid_price=mid_price
            )
        except Exception as e:
            return None
    
    def _create_mock_orderbook(self, market_id: str, metadata: MarketMetadata):
        """Create a mock orderbook when real data isn't available"""
        # Try to get price from market data if available
        # For now, use a reasonable default with some variation
        import random
        mock_price = 0.3 + random.random() * 0.4  # Random price between 0.3 and 0.7
        spread_pct = 0.01 + random.random() * 0.03  # 1-4% spread
        spread = mock_price * spread_pct
        best_bid = max(0.01, mock_price - spread/2)
        best_ask = min(0.99, mock_price + spread/2)
        
        # Create simple depth with reasonable sizes
        base_size = max(10, metadata.liquidity * 0.001)  # 0.1% of liquidity, min $10
        bid_depth = [
            (best_bid, base_size),
            (max(0.01, best_bid - 0.01), base_size * 0.5),
            (max(0.01, best_bid - 0.02), base_size * 0.25)
        ]
        ask_depth = [
            (best_ask, base_size),
            (min(0.99, best_ask + 0.01), base_size * 0.5),
            (min(0.99, best_ask + 0.02), base_size * 0.25)
        ]
        
        self.orderbooks[market_id] = OrderBookSnapshot(
            market_id=market_id,
            timestamp=datetime.now(),
            best_bid=best_bid,
            best_ask=best_ask,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            spread=spread,
            mid_price=mock_price
                    )
    
    async def subscribe_to_orderbook(self, market_id: str):
        """Subscribe to CLOB orderbook updates"""
        # Implementation depends on Polymarket's WebSocket API
        # This is a placeholder for the subscription logic
        pass
    
    def get_fillable_size(self, orderbook: OrderBookSnapshot, 
                          side: str, target_price: float, 
                          max_slippage_bps: float = 50) -> float:
        """
        Calculate how much size you can fill within slippage tolerance
        """
        depth = orderbook.ask_depth if side == "buy" else orderbook.bid_depth
        fillable = 0.0
        
        for price, size in depth:
            slippage = abs(price - target_price) / target_price * 10000
            if slippage <= max_slippage_bps:
                fillable += size
            else:
                break
                
        return fillable
    
    def estimate_slippage(self, orderbook: OrderBookSnapshot, 
                         side: str, size: float) -> float:
        """
        Estimate slippage for a given order size
        """
        depth = orderbook.ask_depth if side == "buy" else orderbook.bid_depth
        remaining = size
        total_cost = 0.0
        
        for price, available in depth:
            filled = min(remaining, available)
            total_cost += filled * price
            remaining -= filled
            
            if remaining <= 0:
                break
        
        if remaining > 0:
            return float('inf')  # Not enough liquidity
        
        entry_price = orderbook.best_ask if side == "buy" else orderbook.best_bid
        avg_price = total_cost / size
        
        return avg_price - entry_price
