import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy import and_, desc

from database.connection import db_manager
from database.models import Fill, Position, Market, TradeFeatures, User
from analytics.performance_metrics import PerformanceAnalyzer

logger = logging.getLogger(__name__)


class SignalGenerator:
    """
    Generate trading signals based on tracked user activity
    Different signal types: Copy, Fade, Information Event
    """
    
    def __init__(self):
        self.db = db_manager
        self.analyzer = PerformanceAnalyzer()
    
    def generate_copy_signal(
        self, 
        fill: Fill, 
        user: User,
        confidence_threshold: float = 0.6
    ) -> Optional[Dict]:
        """
        Generate a copy trading signal
        Only signal if user has good track record
        
        Returns signal dict or None
        """
        try:
            # Get user's recent performance
            metrics = self.analyzer.calculate_user_metrics(user.id, lookback_days=30)
            
            if not metrics:
                logger.debug(f"No metrics available for user {user.user_id}")
                return None
            
            # Calculate confidence score
            confidence = self._calculate_user_confidence(metrics)
            
            if confidence < confidence_threshold:
                logger.debug(
                    f"User {user.user_id} confidence {confidence:.2f} "
                    f"below threshold {confidence_threshold}"
                )
                return None
            
            # Generate signal
            signal = {
                'signal_type': 'COPY',
                'action': fill.side,
                'asset_id': fill.asset_id,
                'outcome': fill.outcome,
                'reference_price': fill.price,
                'reference_size': fill.size,
                'confidence': confidence,
                'user_id': user.user_id,
                'reason': f"Following {user.user_id} (Win rate: {metrics.win_rate:.1f}%)",
                'timestamp': datetime.now(),
                'source_fill_id': fill.fill_id
            }
            
            logger.info(
                f"Generated COPY signal: {signal['action']} {signal['outcome']} "
                f"on asset {signal['asset_id'][:10]}... (confidence: {confidence:.2f})"
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"Error generating copy signal: {e}")
            return None
    
    def generate_fade_signal(
        self, 
        fill: Fill, 
        user: User
    ) -> Optional[Dict]:
        """
        Generate a fade signal (trade opposite)
        For users with poor track record
        """
        try:
            metrics = self.analyzer.calculate_user_metrics(user.id, lookback_days=30)
            
            if not metrics:
                return None
            
            # Only