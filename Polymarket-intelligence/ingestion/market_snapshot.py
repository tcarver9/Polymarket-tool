import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import statistics

from database.connection import db_manager
from database.models import Market, MarketSnapshot, Fill
from ingestion.wallet_tracker import WalletTracker

logger = logging.getLogger(__name__)


class MarketSnapshotEngine:
    """
    Capture market state for feature engineering
    Tracks price, liquidity, volume, volatility at specific points in time
    """
    
    def __init__(self):
        self.db = db_manager
        self.tracker = WalletTracker()
    
    def capture_snapshot_for_fill(
        self, 
        fill: Fill, 
        market: Market
    ) -> Optional[MarketSnapshot]:
        """
        Capture market state at the time of a fill
        This is critical for avoiding look-ahead bias
        """
        try:
            with self.db.session_scope() as session:
                # Get orderbook state
                orderbook = self.tracker.fetch_market_orderbook(fill.asset_id)
                
                # Get recent market trades for volatility
                since_timestamp = int((fill.fill_timestamp - timedelta(hours=1)).timestamp())
                recent_trades = self.tracker.fetch_market_trades(
                    fill.asset_id,
                    since_timestamp=since_timestamp
                )
                
                # Calculate market metrics
                metrics = self._calculate_market_metrics(
                    orderbook, 
                    recent_trades,
                    market
                )
                
                # Create snapshot
                snapshot = MarketSnapshot(
                    market_id=market.id,
                    snapshot_timestamp=fill.fill_timestamp,
                    outcome_prices=metrics['prices'],
                    outcome_spreads=metrics['spreads'],
                    total_liquidity_usd=metrics['liquidity'],
                    volume_24h_usd=metrics['volume_24h'],
                    price_volatility_1h=metrics['volatility_1h'],
                    price_change_24h=metrics['price_change_24h'],
                    hours_to_resolution=metrics['hours_to_resolution']
                )
                
                session.add(snapshot)
                session.flush()
                
                # Update fill with snapshot reference
                fill.market_snapshot_id = snapshot.id
                fill.market_mid_price = metrics.get('mid_price')
                fill.market_spread = metrics.get('spread')
                
                logger.info(
                    f"Captured market snapshot for fill {fill.fill_id} at "
                    f"{snapshot.snapshot_timestamp}"
                )
                
                return snapshot
                
        except Exception as e:
            logger.error(f"Error capturing market snapshot: {e}")
            return None
    
    def capture_current_snapshots(self, markets: List[Market]):
        """Capture snapshots for all active markets"""
        for market in markets:
            if market.resolved:
                continue
            
            try:
                self._capture_market_snapshot(market)
            except Exception as e:
                logger.error(f"Error capturing snapshot for market {market.market_id}: {e}")
    
    def _capture_market_snapshot(self, market: Market):
        """Capture a single market snapshot"""
        try:
            with self.db.session_scope() as session:
                # Get orderbook for primary asset
                orderbook = self.tracker.fetch_market_orderbook(market.condition_id)
                recent_trades = self.tracker.fetch_market_trades(market.condition_id)
                
                metrics = self._calculate_market_metrics(
                    orderbook,
                    recent_trades,
                    market
                )
                
                snapshot = MarketSnapshot(
                    market_id=market.id,
                    snapshot_timestamp=datetime.now(),
                    outcome_prices=metrics['prices'],
                    outcome_spreads=metrics['spreads'],
                    total_liquidity_usd=metrics['liquidity'],
                    volume_24h_usd=metrics['volume_24h'],
                    price_volatility_1h=metrics['volatility_1h'],
                    price_change_24h=metrics['price_change_24h'],
                    hours_to_resolution=metrics['hours_to_resolution']
                )
                
                session.add(snapshot)
                
        except Exception as e:
            logger.error(f"Error in _capture_market_snapshot: {e}")
    
    def _calculate_market_metrics(
        self,
        orderbook: Optional[Dict],
        recent_trades: List[Dict],
        market: Market
    ) -> Dict:
        """Calculate market metrics from orderbook and trades"""
        metrics = {
            'prices': {},
            'spreads': {},
            'mid_price': None,
            'spread': None,
            'liquidity': 0,
            'volume_24h': 0,
            'volatility_1h': None,
            'price_change_24h': None,
            'hours_to_resolution': None
        }
        
        try:
            # Parse orderbook
            if orderbook:
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                if bids and asks:
                    best_bid = float(bids[0]['price']) if bids else 0
                    best_ask = float(asks[0]['price']) if asks else 0
                    
                    metrics['mid_price'] = (best_bid + best_ask) / 2
                    metrics['spread'] = best_ask - best_bid
                    metrics['prices'] = {'mid': metrics['mid_price']}
                    metrics['spreads'] = {'spread': metrics['spread']}
                    
                    # Calculate liquidity (sum of top 5 levels)
                    bid_liquidity = sum(
                        float(b['price']) * float(b['size']) 
                        for b in bids[:5]
                    )
                    ask_liquidity = sum(
                        float(a['price']) * float(a['size'])
                        for a in asks[:5]
                    )
                    metrics['liquidity'] = bid_liquidity + ask_liquidity
            
            # Calculate volume from recent trades
            if recent_trades:
                metrics['volume_24h'] = sum(
                    float(t.get('size', 0)) * float(t.get('price', 0))
                    for t in recent_trades
                )
                
                # Calculate volatility (std dev of prices)
                prices = [float(t.get('price', 0)) for t in recent_trades]
                if len(prices) > 1:
                    metrics['volatility_1h'] = statistics.stdev(prices)
                
                # Price change
                if len(prices) > 0:
                    first_price = prices[-1]  # Oldest
                    last_price = prices[0]    # Newest
                    if first_price > 0:
                        metrics['price_change_24h'] = (
                            (last_price - first_price) / first_price
                        )
            
            # Time to resolution
            if market.end_date:
                time_to_resolution = market.end_date - datetime.now()
                metrics['hours_to_resolution'] = time_to_resolution.total_seconds() / 3600
            
        except Exception as e:
            logger.error(f"Error calculating market metrics: {e}")
        
        return metrics
