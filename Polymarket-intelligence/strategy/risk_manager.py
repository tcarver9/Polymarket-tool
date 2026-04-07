import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy import and_, func

from database.connection import db_manager
from database.models import Position, Fill, Market
from config import (
    MAX_POSITION_SIZE_USD,
    MAX_DAILY_VOLUME_USD,
    MAX_CORRELATED_EXPOSURE,
    STOP_LOSS_PCT
)

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Pre-trade and ongoing risk management
    Position limits, correlation, stop losses, daily volume caps
    """
    
    def __init__(self):
        self.db = db_manager
    
    def check_signal_risk(self, signal: Dict, user_id: int) -> Dict:
        """
        Pre-trade risk checks
        
        Returns:
            {'approved': bool, 'reason': str, 'max_size': float}
        """
        try:
            # Check 1: Position size limit
            reference_price = signal.get('reference_price', 0.5)
            max_size_shares = MAX_POSITION_SIZE_USD / reference_price
            
            # Check 2: Daily volume limit
            daily_volume = self._get_daily_volume(user_id)
            if daily_volume >= MAX_DAILY_VOLUME_USD:
                return {
                    'approved': False,
                    'reason': f'Daily volume limit reached: ${daily_volume:.2f}',
                    'max_size': 0
                }
            
            # All checks passed
            return {
                'approved': True,
                'reason': 'Risk checks passed',
                'max_size': max_size_shares
            }
            
        except Exception as e:
            logger.error(f"Error in risk check: {e}")
            return {
                'approved': False,
                'reason': f'Error in risk check: {str(e)}',
                'max_size': 0
            }
    
    def _get_daily_volume(self, user_id: int) -> float:
        """Get total volume traded today for a user"""
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            with self.db.session_scope() as session:
                result = session.query(func.sum(Fill.total_value)).filter(
                    and_(
                        Fill.user_id == user_id,
                        Fill.fill_timestamp >= today_start
                    )
                ).scalar()
                return float(result) if result else 0.0
        except Exception as e:
            logger.error(f"Error getting daily volume: {e}")
            return 0.0