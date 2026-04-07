import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy import and_, func
import statistics

from database.connection import db_manager
from database.models import (
    User, Fill, Position, LotClosure, 
    PerformanceMetrics, TradeFeatures, TradeLabel
)

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """
    Calculate comprehensive performance metrics
    Win rate, Sharpe, edge realization, calibration, etc.
    """
    
    def __init__(self):
        self.db = db_manager
    
    def calculate_user_metrics(
        self, 
        user_id: int, 
        lookback_days: int = 30
    ) -> PerformanceMetrics:
        """Calculate performance metrics for a user over a time period"""
        try:
            with self.db.session_scope() as session:
                cutoff_date = datetime.now() - timedelta(days=lookback_days)
                
                # Get fills in period
                fills = session.query(Fill).filter(
                    and_(
                        Fill.user_id == user_id,
                        Fill.fill_timestamp >= cutoff_date
                    )
                ).all()
                
                # Get closed positions in period
                closures = session.query(LotClosure).join(
                    Fill, LotClosure.exit_fill_id == Fill.id
                ).filter(
                    and_(
                        Fill.user_id == user_id,
                        LotClosure.exit_timestamp >= cutoff_date
                    )
                ).all()
                
                # Calculate metrics
                metrics = PerformanceMetrics(
                    user_id=user_id,
                    metric_date=datetime.now(),
                    lookback_days=lookback_days
                )
                
                # Trade statistics
                metrics.total_fills = len(fills)
                metrics.total_volume_usd = sum(f.total_value for f in fills)
                
                buy_fills = [f for f in fills if f.side == 'BUY']
                sell_fills = [f for f in fills if f.side == 'SELL']
                
                metrics.positions_opened = len(buy_fills)
                metrics.positions_closed = len(closures)
                
                # Holding time
                if closures:
                    avg_hold = statistics.mean(
                        c.holding_period_seconds for c in closures
                    )
                    metrics.avg_hold_time_hours = avg_hold / 3600
                
                # PnL metrics
                if closures:
                    pnls = [c.net_pnl for c in closures]
                    metrics.realized_pnl = sum(pnls)
                    
                    winning = [p for p in pnls if p > 0]
                    losing = [p for p in pnls if p < 0]
                    
                    metrics.winning_trades = len(winning)
                    metrics.losing_trades = len(losing)
                    metrics.breakeven_trades = len([p for p in pnls if p == 0])
                    
                    if closures:
                        metrics.win_rate = (metrics.winning_trades / len(closures)) * 100
                    
                    # Profit factor
                    if losing:
                        gross_profit = sum(winning) if winning else 0
                        gross_loss = abs(sum(losing))
                        metrics.profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
                    
                    # Average profit/loss
                    metrics.avg_profit = sum(winning) / len(winning) if winning else 0
                    metrics.avg_loss = sum(losing) / len(losing) if losing else 0
                    
                    # Sharpe ratio (simplified)
                    if len(pnls) > 1:
                        avg_return = statistics.mean(pnls)
                        std_return = statistics.stdev(pnls)
                        if std_return > 0:
                            # Annualized Sharpe (assuming daily trades)
                            metrics.sharpe_ratio = (avg_return / std_return) * (252 ** 0.5)
                    
                    # Max drawdown
                    metrics.max_drawdown = self._calculate_max_drawdown(closures)
                
                # Edge metrics
                edge_stats = self._calculate_edge_metrics(user_id, cutoff_date)
                metrics.avg_edge_per_trade = edge_stats['avg_edge']
                metrics.edge_realization_rate = edge_stats['realization_rate']
                
                # Prediction accuracy
                accuracy_stats = self._calculate_prediction_accuracy(user_id, cutoff_date)
                metrics.prediction_accuracy = accuracy_stats['accuracy']
                metrics.calibration_score = accuracy_stats['calibration']
                
                session.add(metrics)
                
                logger.info(
                    f"Calculated metrics for user {user_id}: "
                    f"Win rate: {metrics.win_rate:.2f}%, "
                    f"Realized PnL: ${metrics.realized_pnl:.2f}"
                )
                
                return metrics
                
        except Exception as e:
            logger.error(f"Error calculating user metrics: {e}")
            return None
    
    def _calculate_max_drawdown(self, closures: List[LotClosure]) -> float:
        """Calculate maximum drawdown from closures"""
        if not closures:
            return 0
        
        # Sort by exit timestamp
        sorted_closures = sorted(closures, key=lambda x: x.exit_timestamp)
        
        cumulative_pnl = 0
        peak = 0
        max_dd = 0
        
        for closure in sorted_closures:
            cumulative_pnl += closure.net_pnl
            peak = max(peak, cumulative_pnl)
            drawdown = peak - cumulative_pnl
            max_dd = max(max_dd, drawdown)
        
        return max_dd
    
    def _calculate_edge_metrics(
        self, 
        user_id: int, 
        since: datetime
    ) -> Dict:
        """Calculate edge estimation and realization metrics"""
        try:
            with self.db.session_scope() as session:
                # Get trade features with edge estimates
                features = session.query(TradeFeatures).join(
                    Fill, TradeFeatures.fill_id == Fill.id
                ).filter(
                    and_(
                        Fill.user_id == user_id,
                        Fill.fill_timestamp >= since,
                        TradeFeatures.estimated_edge.isnot(None)
                    )
                ).all()
                
                if not features:
                    return {'avg_edge': None, 'realization_rate': None}
                
                # Average edge
                avg_edge = statistics.mean(f.estimated_edge for f in features)
                
                # Edge realization: how often positive edge led to profit
                labeled_features = [f for f in features if f.label is not None]
                if labeled_features:
                    positive_edge_profitable = sum(
                        1 for f in labeled_features
                        if f.estimated_edge > 0 and f.label == TradeLabel.PROFITABLE
                    )
                    positive_edge_total = sum(
                        1 for f in labeled_features if f.estimated_edge > 0
                    )
                    
                    realization_rate = (
                        (positive_edge_profitable / positive_edge_total) * 100
                        if positive_edge_total > 0 else None
                    )
                else:
                    realization_rate = None
                
                return {
                    'avg_edge': avg_edge,
                    'realization_rate': realization_rate
                }
                
        except Exception as e:
            logger.error(f"Error calculating edge metrics: {e}")
            return {'avg_edge': None, 'realization_rate': None}
    
    def _calculate_prediction_accuracy(
        self, 
        user_id: int, 
        since: datetime
    ) -> Dict:
        """Calculate prediction accuracy and calibration"""
        try:
            with self.db.session_scope() as session:
                # Get fills with final outcomes
                features = session.query(TradeFeatures).join(
                    Fill, TradeFeatures.fill_id == Fill.id
                ).filter(
                    and_(
                        Fill.user_id == user_id,
                        Fill.fill_timestamp >= since,
                        TradeFeatures.final_outcome_correct.isnot(None)
                    )
                ).all()
                
                if not features:
                    return {'accuracy': None, 'calibration': None}
                
                # Simple accuracy
                correct = sum(1 for f in features if f.final_outcome_correct)
                accuracy = (correct / len(features)) * 100
                
                # Calibration: compare implied probabilities to actual outcomes
                # Group by probability buckets
                calibration = self._calculate_calibration_score(features)
                
                return {
                    'accuracy': accuracy,
                    'calibration': calibration
                }
                
        except Exception as e:
            logger.error(f"Error calculating prediction accuracy: {e}")
            return {'accuracy': None, 'calibration': None}
    
    def _calculate_calibration_score(self, features: List[TradeFeatures]) -> Optional[float]:
        """
        Calculate calibration score using Brier score
        Lower is better (0 = perfect calibration)
        """
        try:
            scores = []
            for f in features:
                if f.implied_probability is not None:
                    actual = 1.0 if f.final_outcome_correct else 0.0
                    predicted = f.implied_probability
                    scores.append((predicted - actual) ** 2)
            
            if scores:
                return statistics.mean(scores)
            return None
            
        except Exception as e:
            logger.error(f"Error calculating calibration: {e}")
            return None
