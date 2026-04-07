import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from sqlalchemy import and_, func

from database.connection import db_manager
from database.models import Position, Fill, Market, User
from analytics.pnl_engine import PnLEngine

logger = logging.getLogger(__name__)


class PositionManager:
    """
    Manage positions across users and markets
    Provides aggregated views and risk metrics
    """
    
    def __init__(self):
        self.db = db_manager
        self.pnl_engine = PnLEngine()
    
    def get_open_positions_by_user(self, user_id: int) -> List[Position]:
        """Get all open positions for a user"""
        try:
            with self.db.session_scope() as session:
                return session.query(Position).filter(
                    and_(
                        Position.user_id == user_id,
                        Position.is_closed == False,
                        Position.total_size > 0
                    )
                ).all()
        except Exception as e:
            logger.error(f"Error getting open positions: {e}")
            return []
    
    def get_portfolio_summary(self, user_id: int) -> Dict:
        """
        Get portfolio summary for a user
        
        Returns:
            - total_positions: int
            - total_exposure_usd: float
            - total_unrealized_pnl: float
            - total_realized_pnl: float
            - positions_by_category: Dict
        """
        try:
            with self.db.session_scope() as session:
                positions = session.query(Position).filter(
                    and_(
                        Position.user_id == user_id,
                        Position.is_closed == False
                    )
                ).all()
                
                total_exposure = sum(p.total_cost_basis for p in positions)
                total_unrealized = sum(p.unrealized_pnl for p in positions)
                
                # Get realized PnL from all positions
                all_positions = session.query(Position).filter_by(
                    user_id=user_id
                ).all()
                total_realized = sum(p.realized_pnl for p in all_positions)
                
                # Group by category
                positions_by_category = {}
                for position in positions:
                    market = session.query(Market).get(position.market_id)
                    category = market.category if market else "Unknown"
                    
                    if category not in positions_by_category:
                        positions_by_category[category] = {
                            'count': 0,
                            'exposure': 0,
                            'unrealized_pnl': 0
                        }
                    
                    positions_by_category[category]['count'] += 1
                    positions_by_category[category]['exposure'] += position.total_cost_basis
                    positions_by_category[category]['unrealized_pnl'] += position.unrealized_pnl
                
                return {
                    'total_positions': len(positions),
                    'total_exposure_usd': total_exposure,
                    'total_unrealized_pnl': total_unrealized,
                    'total_realized_pnl': total_realized,
                    'total_pnl': total_unrealized + total_realized,
                    'positions_by_category': positions_by_category
                }
                
        except Exception as e:
            logger.error(f"Error getting portfolio summary: {e}")
            return {}
    
    def update_all_mark_prices(self):
        """Update mark prices for all open positions"""
        try:
            with self.db.session_scope() as session:
                open_positions = session.query(Position).filter(
                    and_(
                        Position.is_closed == False,
                        Position.total_size > 0
                    )
                ).all()
                
                logger.info(f"Updating mark prices for {len(open_positions)} positions")
                
                for position in open_positions:
                    # Get latest market price
                    # This would fetch from orderbook or last trade
                    current_price = self._get_current_market_price(
                        position.asset_id
                    )
                    
                    if current_price:
                        self.pnl_engine.update_unrealized_pnl(position, current_price)
                
        except Exception as e:
            logger.error(f"Error updating mark prices: {e}")
    
    def _get_current_market_price(self, asset_id: str) -> Optional[float]:
        """Get current market price for an asset"""
        try:
            with self.db.session_scope() as session:
                # Get most recent fill price as proxy
                recent_fill = session.query(Fill).filter_by(
                    asset_id=asset_id
                ).order_by(desc(Fill.fill_timestamp)).first()
                
                if recent_fill:
                    return recent_fill.price
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting current price: {e}")
            return None
    
    def check_position_risk(self, position: Position) -> Dict:
        """
        Check risk metrics for a position
        
        Returns risk flags and metrics
        """
        risks = {
            'max_loss_exceeded': False,
            'concentration_risk': False,
            'time_decay_risk': False,
            'risk_score': 0
        }
        
        try:
            with self.db.session_scope() as session:
                position = session.merge(position)
                
                # Check unrealized loss threshold
                if position.unrealized_pnl_pct < -15:  # 15% loss
                    risks['max_loss_exceeded'] = True
                    risks['risk_score'] += 3
                
                # Check concentration (position size vs total portfolio)
                user_positions = self.get_open_positions_by_user(position.user_id)
                total_exposure = sum(p.total_cost_basis for p in user_positions)
                
                if total_exposure > 0:
                    concentration = position.total_cost_basis / total_exposure
                    if concentration > 0.25:  # More than 25% in one position
                        risks['concentration_risk'] = True
                        risks['risk_score'] += 2
                
                # Check time to resolution
                market = session.query(Market).get(position.market_id)
                if market and market.end_date:
                    hours_remaining = (market.end_date - datetime.now()).total_seconds() / 3600
                    if hours_remaining < 24 and position.unrealized_pnl < 0:
                        risks['time_decay_risk'] = True
                        risks['risk_score'] += 1
                
        except Exception as e:
            logger.error(f"Error checking position risk: {e}")
        
        return risks
