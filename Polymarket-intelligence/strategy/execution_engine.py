import logging
from datetime import datetime
from typing import Dict, Optional, List
from enum import Enum

from database.connection import db_manager
from database.models import Fill, Position, Market
from strategy.risk_manager import RiskManager
from ingestion.wallet_tracker import WalletTracker

logger = logging.getLogger(__name__)


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class ExecutionEngine:
    """
    Handle order execution with slippage, fill probability, and latency modeling
    Paper trading mode for simulation
    """
    
    def __init__(self, paper_trading: bool = True):
        self.db = db_manager
        self.risk_manager = RiskManager()
        self.tracker = WalletTracker()
        self.paper_trading = paper_trading
        self.execution_log = []
    
    def execute_signal(self, signal: Dict, user_id: int) -> Optional[Dict]:
        """
        Execute a trading signal with risk checks
        
        Args:
            signal: Signal dict from SignalGenerator
            user_id: Bot's user ID (not the tracked user)
            
        Returns:
            Execution result dict or None if rejected
        """
        try:
            # Pre-execution risk checks
            risk_check = self.risk_manager.check_signal_risk(signal, user_id)
            
            if not risk_check['approved']:
                logger.warning(
                    f"Signal rejected by risk manager: {risk_check['reason']}"
                )
                return {
                    'status': 'REJECTED',
                    'reason': risk_check['reason'],
                    'signal': signal
                }
            
            # Calculate position size
            position_size = self._calculate_position_size(
                signal, 
                user_id,
                risk_check
            )
            
            if position_size <= 0:
                logger.warning("Position size calculated as 0, skipping execution")
                return None
            
            # Determine order type and price
            order_params = self._determine_order_params(signal, position_size)
            
            # Execute order (paper or live)
            if self.paper_trading:
                execution_result = self._execute_paper_order(order_params)
            else:
                execution_result = self._execute_live_order(order_params)
            
            # Log execution
            self._log_execution(signal, execution_result)
            
            return execution_result
            
        except Exception as e:
            logger.error(f"Error executing signal: {e}")
            return None
    
    def _calculate_position_size(
        self, 
        signal: Dict, 
        user_id: int,
        risk_check: Dict
    ) -> float:
        """
        Calculate appropriate position size
        Uses Kelly Criterion with fractional sizing
        """
        try:
            # Get current portfolio value (using default for simulation)
            # In production, this would query PositionManager for actual portfolio value
            total_capital = 10000  # Default 10k for simulation
            
            # Base size on signal confidence
            confidence = signal.get('confidence', 0.5)
            
            # Kelly fraction (conservative: use 1/4 Kelly)
            kelly_fraction = 0.25
            win_rate = confidence
            avg_win = 1.0  # Assume 1:1 risk/reward for simplicity
            avg_loss = 1.0
            
            if win_rate > 0 and avg_loss > 0:
                kelly_pct = ((win_rate * avg_win) - ((1 - win_rate) * avg_loss)) / avg_win
                kelly_pct = max(0, min(kelly_pct, 0.25))  # Cap at 25%
            else:
                kelly_pct = 0.05  # Default to 5%
            
            # Calculate position size
            position_value = total_capital * kelly_pct * kelly_fraction
            
            # Convert to shares
            reference_price = signal.get('reference_price', 0.5)
            position_size = position_value / reference_price
            
            # Apply risk limits
            max_size = risk_check.get('max_size', float('inf'))
            position_size = min(position_size, max_size)
            
            logger.info(
                f"Calculated position size: {position_size:.2f} shares "
                f"(${position_value:.2f} at ${reference_price:.4f})"
            )
            
            return position_size
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0
    
    def _determine_order_params(self, signal: Dict, size: float) -> Dict:
        """Determine order type and limit price"""
        # For copy trading, use limit orders near reference price
        reference_price = signal.get('reference_price', 0.5)
        
        # Add small slippage buffer for limit orders
        if signal['action'] == 'BUY':
            limit_price = reference_price * 1.01  # 1% above reference
        else:
            limit_price = reference_price * 0.99  # 1% below reference
        
        return {
            'order_type': OrderType.LIMIT,
            'side': signal['action'],
            'asset_id': signal['asset_id'],
            'outcome': signal['outcome'],
            'size': size,
            'limit_price': limit_price,
            'reference_price': reference_price,
            'signal_confidence': signal.get('confidence'),
            'source_user': signal.get('user_id')
        }
    
    def _execute_paper_order(self, order_params: Dict) -> Dict:
        """
        Simulate order execution for paper trading
        Models fill probability, slippage, and latency
        """
        try:
            # Get current market state
            orderbook = self.tracker.fetch_market_orderbook(order_params['asset_id'])
            
            # Simulate fill probability based on order type
            if order_params['order_type'] == OrderType.MARKET:
                fill_probability = 1.0
                execution_price = self._simulate_market_execution(
                    order_params, 
                    orderbook
                )
            else:
                fill_probability = self._simulate_fill_probability(
                    order_params, 
                    orderbook
                )
                execution_price = order_params['limit_price']
            
            # Simulate latency (signals are delayed)
            import random
            latency_seconds = random.uniform(1, 5)
            
            # Determine if order would fill
            filled = random.random() < fill_probability
            
            if filled:
                # Calculate slippage
                slippage = execution_price - order_params['reference_price']
                slippage_bps = (slippage / order_params['reference_price']) * 10000
                
                result = {
                    'status': 'FILLED',
                    'fill_price': execution_price,
                    'fill_size': order_params['size'],
                    'slippage_bps': slippage_bps,
                    'latency_seconds': latency_seconds,
                    'timestamp': datetime.now(),
                    'order_params': order_params
                }
                
                logger.info(
                    f"Paper order FILLED: {order_params['side']} "
                    f"{order_params['size']:.2f} @ ${execution_price:.4f} "
                    f"(slippage: {slippage_bps:.1f} bps)"
                )
            else:
                result = {
                    'status': 'UNFILLED',
                    'reason': 'No fill at limit price',
                    'latency_seconds': latency_seconds,
                    'timestamp': datetime.now(),
                    'order_params': order_params
                }
                
                logger.info(
                    f"Paper order UNFILLED: {order_params['side']} "
                    f"{order_params['size']:.2f} @ ${order_params['limit_price']:.4f}"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error in paper order execution: {e}")
            return {
                'status': 'ERROR',
                'error': str(e),
                'order_params': order_params
            }
    
    def _execute_live_order(self, order_params: Dict) -> Dict:
        """
        Execute live order via Polymarket API
        NOT IMPLEMENTED - Requires API keys and wallet integration
        """
        logger.error("Live trading not implemented. Use paper_trading=True")
        return {
            'status': 'ERROR',
            'error': 'Live trading not implemented',
            'order_params': order_params
        }
    
    def _simulate_market_execution(
        self, 
        order_params: Dict, 
        orderbook: Optional[Dict]
    ) -> float:
        """Simulate market order execution with slippage"""
        reference_price = order_params['reference_price']
        
        if not orderbook:
            # Assume 2% slippage without orderbook data
            if order_params['side'] == 'BUY':
                return reference_price * 1.02
            else:
                return reference_price * 0.98
        
        # Calculate VWAP from orderbook
        if order_params['side'] == 'BUY':
            asks = orderbook.get('asks', [])
            vwap = self._calculate_vwap(asks, order_params['size'])
        else:
            bids = orderbook.get('bids', [])
            vwap = self._calculate_vwap(bids, order_params['size'])
        
        return vwap if vwap > 0 else reference_price
    
    def _calculate_vwap(self, levels: List[Dict], size: float) -> float:
        """Calculate volume-weighted average price"""
        try:
            remaining = size
            total_cost = 0
            
            for level in levels:
                level_price = float(level['price'])
                level_size = float(level['size'])
                
                fill_size = min(remaining, level_size)
                total_cost += fill_size * level_price
                remaining -= fill_size
                
                if remaining <= 0:
                    break
            
            filled_size = size - remaining
            if filled_size > 0:
                return total_cost / filled_size
            return 0
            
        except Exception as e:
            logger.error(f"Error calculating VWAP: {e}")
            return 0
    
    def _simulate_fill_probability(
        self, 
        order_params: Dict, 
        orderbook: Optional[Dict]
    ) -> float:
        """
        Simulate probability of limit order filling
        Based on how aggressive the limit price is
        """
        if not orderbook:
            return 0.5  # 50% without data
        
        try:
            limit_price = order_params['limit_price']
            
            if order_params['side'] == 'BUY':
                asks = orderbook.get('asks', [])
                if not asks:
                    return 0.3
                best_ask = float(asks[0]['price'])
                
                if limit_price >= best_ask:
                    return 0.9  # Very likely to fill
                elif limit_price >= best_ask * 0.98:
                    return 0.6  # Likely to fill
                else:
                    return 0.2  # Unlikely to fill
            else:
                bids = orderbook.get('bids', [])
                if not bids:
                    return 0.3
                best_bid = float(bids[0]['price'])
                
                if limit_price <= best_bid:
                    return 0.9
                elif limit_price <= best_bid * 1.02:
                    return 0.6
                else:
                    return 0.2
                    
        except Exception as e:
            logger.error(f"Error simulating fill probability: {e}")
            return 0.5
    
    def _log_execution(self, signal: Dict, result: Dict):
        """Log execution for analysis"""
        self.execution_log.append({
            'timestamp': datetime.now(),
            'signal': signal,
            'result': result
        })
        
        # Keep last 1000 executions in memory
        if len(self.execution_log) > 1000:
            self.execution_log = self.execution_log[-1000:]
    
    def get_execution_stats(self) -> Dict:
        """Get execution statistics"""
        if not self.execution_log:
            return {}
        
        total = len(self.execution_log)
        filled = sum(1 for e in self.execution_log if e['result']['status'] == 'FILLED')
        rejected = sum(1 for e in self.execution_log if e['result']['status'] == 'REJECTED')
        
        filled_executions = [
            e for e in self.execution_log 
            if e['result']['status'] == 'FILLED'
        ]
        
        avg_slippage = 0
        if filled_executions:
            avg_slippage = sum(
                e['result'].get('slippage_bps', 0) 
                for e in filled_executions
            ) / len(filled_executions)
        
        return {
            'total_signals': total,
            'filled': filled,
            'rejected': rejected,
            'fill_rate': (filled / total * 100) if total > 0 else 0,
            'avg_slippage_bps': avg_slippage
        }
