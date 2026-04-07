import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from sqlalchemy import and_, desc

from database.connection import db_manager
from database.models import (
    Fill, Lot, LotClosure, Position, Market,
    LotAccountingMethod
)
from config import PNL_ACCOUNTING_METHOD

logger = logging.getLogger(__name__)


class PnLEngine:
    """
    Multi-dimensional PnL calculation engine
    Handles: Realized PnL, Unrealized PnL, Final Settlement PnL
    Supports: FIFO, LIFO, Weighted Average lot accounting
    """
    
    def __init__(self, accounting_method: str = PNL_ACCOUNTING_METHOD):
        self.db = db_manager
        self.accounting_method = LotAccountingMethod(accounting_method)
    
    def process_fill(self, fill: Fill) -> Dict:
        """
        Process a fill and update positions/lots accordingly
        
        Returns dict with:
            - position_updated: bool
            - lot_created: Optional[Lot]
            - lot_closed: Optional[LotClosure]
            - realized_pnl: Optional[float]
        """
        result = {
            'position_updated': False,
            'lot_created': None,
            'lot_closed': None,
            'realized_pnl': None
        }
        
        try:
            with self.db.session_scope() as session:
                # Get or create position
                position = self._get_or_create_position(session, fill)
                
                if fill.side == 'BUY':
                    # Create new lot
                    lot = self._create_lot(session, fill)
                    result['lot_created'] = lot
                    
                    # Update position
                    position.total_size += fill.size
                    position.total_cost_basis += (fill.total_value + fill.total_fees)
                    position.average_entry_price = (
                        position.total_cost_basis / position.total_size
                    )
                    
                elif fill.side == 'SELL':
                    # Close lots
                    closures, total_pnl = self._close_lots(session, fill)
                    result['lot_closed'] = closures
                    result['realized_pnl'] = total_pnl
                    
                    # Update position
                    position.total_size -= fill.size
                    position.realized_pnl += total_pnl
                    
                    if position.total_size <= 0.001:  # Essentially zero
                        position.is_closed = True
                        position.total_size = 0
                
                # Update position metadata
                position.last_update_timestamp = fill.fill_timestamp
                if not position.first_entry_timestamp:
                    position.first_entry_timestamp = fill.fill_timestamp
                
                result['position_updated'] = True
                
                logger.info(
                    f"Processed fill {fill.fill_id}: {fill.side} {fill.size} shares, "
                    f"Position size now: {position.total_size}"
                )
                
        except Exception as e:
            logger.error(f"Error processing fill {fill.fill_id}: {e}")
            raise
        
        return result
    
    def _get_or_create_position(self, session, fill: Fill) -> Position:
        """Get existing position or create new one"""
        position = session.query(Position).filter(
            and_(
                Position.user_id == fill.user_id,
                Position.asset_id == fill.asset_id,
                Position.outcome == fill.outcome
            )
        ).first()
        
        if not position:
            position = Position(
                user_id=fill.user_id,
                asset_id=fill.asset_id,
                market_id=fill.market_id,
                outcome=fill.outcome,
                total_size=0,
                total_cost_basis=0,
                unrealized_pnl=0,
                realized_pnl=0
            )
            session.add(position)
            session.flush()
        
        return position
    
    def _create_lot(self, session, fill: Fill) -> Lot:
        """Create a new lot for a buy fill"""
        lot = Lot(
            lot_id=f"lot_{fill.fill_id}",
            user_id=fill.user_id,
            asset_id=fill.asset_id,
            outcome=fill.outcome,
            entry_fill_id=fill.id,
            entry_price=fill.price,
            original_size=fill.size,
            remaining_size=fill.size,
            entry_timestamp=fill.fill_timestamp,
            entry_fees=fill.total_fees,
            accounting_method=self.accounting_method,
            is_closed=False
        )
        
        session.add(lot)
        session.flush()
        
        logger.debug(f"Created lot {lot.lot_id} for fill {fill.fill_id}")
        return lot
    
    def _close_lots(
        self, 
        session, 
        sell_fill: Fill
    ) -> Tuple[List[LotClosure], float]:
        """
        Close lots according to accounting method
        
        Returns:
            (list of closures, total realized PnL)
        """
        # Get open lots for this asset
        open_lots = session.query(Lot).filter(
            and_(
                Lot.user_id == sell_fill.user_id,
                Lot.asset_id == sell_fill.asset_id,
                Lot.outcome == sell_fill.outcome,
                Lot.is_closed == False,
                Lot.remaining_size > 0
            )
        ).order_by(
            Lot.entry_timestamp.asc() if self.accounting_method == LotAccountingMethod.FIFO
            else Lot.entry_timestamp.desc()
        ).all()
        
        if not open_lots:
            logger.warning(
                f"No open lots found for sell fill {sell_fill.fill_id}. "
                f"This might be a short sale or data issue."
            )
            return [], 0
        
        closures = []
        total_pnl = 0
        remaining_to_close = sell_fill.size
        
        for lot in open_lots:
            if remaining_to_close <= 0:
                break
            
            # Determine how much of this lot to close
            size_to_close = min(remaining_to_close, lot.remaining_size)
            
            # Calculate PnL
            gross_pnl = (sell_fill.price - lot.entry_price) * size_to_close
            
            # Prorate fees
            exit_fees = (sell_fill.total_fees * size_to_close / sell_fill.size)
            entry_fees_prorated = (lot.entry_fees * size_to_close / lot.original_size)
            
            net_pnl = gross_pnl - exit_fees - entry_fees_prorated
            pnl_percentage = (net_pnl / (lot.entry_price * size_to_close)) * 100
            
            # Calculate holding period
            holding_seconds = int(
                (sell_fill.fill_timestamp - lot.entry_timestamp).total_seconds()
            )
            
            # Create closure record
            closure = LotClosure(
                lot_id=lot.id,
                exit_fill_id=sell_fill.id,
                size_closed=size_to_close,
                exit_price=sell_fill.price,
                exit_fees=exit_fees,
                exit_timestamp=sell_fill.fill_timestamp,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                pnl_percentage=pnl_percentage,
                holding_period_seconds=holding_seconds
            )
            
            session.add(closure)
            closures.append(closure)
            
            # Update lot
            lot.remaining_size -= size_to_close
            if lot.remaining_size <= 0.001:
                lot.is_closed = True
                lot.close_timestamp = sell_fill.fill_timestamp
            
            total_pnl += net_pnl
            remaining_to_close -= size_to_close
            
            logger.debug(
                f"Closed {size_to_close} from lot {lot.lot_id}, "
                f"PnL: ${net_pnl:.2f} ({pnl_percentage:.2f}%)"
            )
        
        if remaining_to_close > 0.001:
            logger.warning(
                f"Could not fully close sell fill {sell_fill.fill_id}. "
                f"Remaining: {remaining_to_close}"
            )
        
        return closures, total_pnl
    
    def update_unrealized_pnl(self, position: Position, current_price: float):
        """Update unrealized PnL for an open position"""
        try:
            with self.db.session_scope() as session:
                position = session.merge(position)
                
                if position.is_closed or position.total_size <= 0:
                    return
                
                # Calculate unrealized PnL
                current_value = position.total_size * current_price
                position.unrealized_pnl = current_value - position.total_cost_basis
                
                if position.total_cost_basis > 0:
                    position.unrealized_pnl_pct = (
                        position.unrealized_pnl / position.total_cost_basis
                    ) * 100
                
                position.current_mark_price = current_price
                position.last_mark_update = datetime.now()
                
                logger.debug(
                    f"Updated unrealized PnL for position {position.id}: "
                    f"${position.unrealized_pnl:.2f} ({position.unrealized_pnl_pct:.2f}%)"
                )
                
        except Exception as e:
            logger.error(f"Error updating unrealized PnL: {e}")
    
    def settle_position(self, position: Position, winning_outcome: str):
        """
        Settle position when market resolves
        Calculate final PnL based on outcome
        """
        try:
            with self.db.session_scope() as session:
                position = session.merge(position)
                
                if position.is_settled:
                    logger.warning(f"Position {position.id} already settled")
                    return
                
                # Determine settlement value
                if position.outcome == winning_outcome:
                    # Position wins: each share worth $1
                    settlement_value = position.total_size * 1.0
                else:
                    # Position loses: shares worth $0
                    settlement_value = 0.0
                
                # Calculate final PnL
                position.settlement_pnl = settlement_value - position.total_cost_basis
                position.is_settled = True
                position.settlement_timestamp = datetime.now()
                position.is_closed = True
                
                logger.info(
                    f"Settled position {position.id}: {position.outcome} "
                    f"(Market outcome: {winning_outcome}), "
                    f"Final PnL: ${position.settlement_pnl:.2f}"
                )
                
        except Exception as e:
            logger.error(f"Error settling position: {e}")
