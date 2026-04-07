import logging
from datetime import datetime
from typing import Dict, Optional, List
from sqlalchemy.exc import IntegrityError

from database.connection import db_manager
from database.models import (
    User, WalletAddress, Market, Fill, 
    MarketSnapshot, IngestionLog
)
from config import (
    MAKER_FEE_BPS, TAKER_FEE_BPS, 
    GAS_ESTIMATE_USD, ADDRESS_TO_USER
)

logger = logging.getLogger(__name__)


class FillNormalizer:
    """
    Normalize raw trade data into canonical Fill records
    Handles partial fills, cancellations, and data quality
    Supports both CLOB API and Data API formats
    """
    
    def __init__(self):
        self.db = db_manager
    
    def _normalize_trade_data(self, raw_trade: Dict) -> Dict:
        """
        Normalize trade data from different API sources to a common format.
        Supports both CLOB API and Data API field names.
        """
        # Data API uses different field names than CLOB API
        # Map them to a common format
        
        # Generate a unique fill_id from transaction hash if 'id' not present
        fill_id = raw_trade.get('id') or raw_trade.get('transactionHash') or f"trade_{hash(str(raw_trade))}"
        
        # Asset ID: Data API uses 'asset', CLOB API uses 'asset_id'
        asset_id = raw_trade.get('asset_id') or raw_trade.get('asset')
        
        # Condition ID: Data API provides this directly
        condition_id = raw_trade.get('conditionId') or raw_trade.get('condition_id') or asset_id
        
        # Transaction hash
        tx_hash = raw_trade.get('transaction_hash') or raw_trade.get('transactionHash')
        
        # Market title from Data API (helpful for display)
        title = raw_trade.get('title') or raw_trade.get('question') or 'Unknown Market'
        
        return {
            'id': fill_id,
            'asset_id': asset_id,
            'condition_id': condition_id,
            'outcome': raw_trade.get('outcome', 'YES'),
            'side': raw_trade.get('side', 'BUY').upper(),
            'size': float(raw_trade.get('size', 0)),
            'price': float(raw_trade.get('price', 0)),
            'timestamp': raw_trade.get('timestamp'),
            'transaction_hash': tx_hash,
            'order_id': raw_trade.get('order_id'),
            'is_maker': raw_trade.get('is_maker', True),
            'title': title,
            'slug': raw_trade.get('slug'),
        }
    
    def normalize_and_store_trades(
        self, 
        raw_trades: List[Dict], 
        address: str
    ) -> tuple[int, int, int]:
        """
        Normalize trades and store in database
        
        Returns:
            (inserted, updated, failed) counts
        """
        inserted = 0
        updated = 0
        failed = 0
        
        for raw_trade in raw_trades:
            try:
                # Normalize the trade data first
                normalized = self._normalize_trade_data(raw_trade)
                success = self._process_single_trade(normalized, address)
                if success:
                    inserted += 1
                else:
                    updated += 1  # Already exists = update count
            except Exception as e:
                logger.error(f"Error processing trade {raw_trade.get('id') or raw_trade.get('transactionHash', 'unknown')}: {e}")
                failed += 1
        
        # Log ingestion results
        self._log_ingestion(
            data_source='DATA_API',
            endpoint='/trades',
            fetched=len(raw_trades),
            inserted=inserted,
            updated=updated,
            failed=failed
        )
        
        return inserted, updated, failed
    
    def _process_single_trade(self, normalized_trade: Dict, address: str) -> bool:
        """Process a single normalized trade into Fill record"""
        try:
            with self.db.session_scope() as session:
                # Check if fill already exists (idempotency)
                fill_id = normalized_trade['id']
                existing_fill = session.query(Fill).filter_by(fill_id=fill_id).first()
                
                if existing_fill:
                    logger.debug(f"Fill {fill_id[:20]}... already exists, skipping")
                    return False
                
                # Get or create user
                user = self._get_or_create_user(session, address)
                
                # Get or create market
                market = self._get_or_create_market(session, normalized_trade)
                
                # Calculate fees
                fees = self._calculate_fees(normalized_trade)
                
                # Parse timestamp
                timestamp = self._parse_timestamp(normalized_trade['timestamp'])
                
                # Calculate total value
                size = normalized_trade['size']
                price = normalized_trade['price']
                total_value = size * price
                
                # Create Fill record
                fill = Fill(
                    fill_id=fill_id,
                    user_id=user.id,
                    wallet_address=address,
                    market_id=market.id,
                    asset_id=normalized_trade['asset_id'],
                    outcome=normalized_trade['outcome'],
                    side=normalized_trade['side'],
                    size=size,
                    price=price,
                    total_value=total_value,
                    maker_fee=fees['maker_fee'],
                    taker_fee=fees['taker_fee'],
                    gas_cost_usd=fees['gas_cost'],
                    total_fees=fees['total'],
                    fill_timestamp=timestamp,
                    transaction_hash=normalized_trade['transaction_hash'],
                    order_id=normalized_trade.get('order_id'),
                    is_maker=normalized_trade.get('is_maker', True),
                    data_source='DATA_API',
                    verified_onchain=False
                )
                
                session.add(fill)
                session.flush()
                
                logger.info(
                    f"Fill: {fill.side} {fill.size:.2f} @ ${fill.price:.4f} "
                    f"(${total_value:.2f}) - {user.user_id}"
                )
                
                return True
                
        except IntegrityError as e:
            logger.warning(f"Integrity error for fill {normalized_trade['id'][:20]}...: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error processing trade: {e}")
            raise
    
    def _get_or_create_user(self, session, address: str) -> User:
        """Get existing user or create new one"""
        # Check if wallet exists
        wallet = session.query(WalletAddress).filter_by(address=address).first()
        
        if wallet:
            return wallet.user
        
        # Get user_id from config
        user_id = ADDRESS_TO_USER.get(address)
        if not user_id:
            # Create a default user_id
            user_id = f"user_{address[:10]}"
        
        # Check if user exists
        user = session.query(User).filter_by(user_id=user_id).first()
        
        if not user:
            # Create new user
            user = User(
                user_id=user_id,
                primary_address=address,
                tags=[]
            )
            session.add(user)
            session.flush()
        
        # Create wallet address entry
        wallet = WalletAddress(
            user_id=user.id,
            address=address,
            is_primary=(address == user.primary_address)
        )
        session.add(wallet)
        
        return user
    
    def _get_or_create_market(self, session, normalized_trade: Dict) -> Market:
        """Get existing market or create placeholder"""
        # Use condition_id as the primary market identifier
        condition_id = normalized_trade.get('condition_id') or normalized_trade.get('asset_id')
        
        if not condition_id:
            raise ValueError("Trade missing condition_id and asset_id")
        
        # Try to find by condition_id first
        market = session.query(Market).filter_by(condition_id=condition_id).first()
        
        if market:
            # Update title if we have a better one from Data API
            title = normalized_trade.get('title')
            if title and title != 'Unknown Market' and market.question == "Market metadata pending":
                market.question = title
            return market
        
        # Create market with data from the trade (Data API provides title)
        title = normalized_trade.get('title', 'Market metadata pending')
        slug = normalized_trade.get('slug', '')
        
        market = Market(
            market_id=slug if slug else f"market_{condition_id[:16]}",
            condition_id=condition_id,
            question=title,
            outcomes=["YES", "NO"],  # Will be updated with actual outcomes later
            resolved=False
        )
        session.add(market)
        session.flush()
        
        logger.info(f"Created market: {title[:50]}...")
        return market
    
    def _calculate_fees(self, normalized_trade: Dict) -> Dict[str, float]:
        """Calculate trading fees"""
        size = normalized_trade['size']
        price = normalized_trade['price']
        total_value = size * price
        
        is_maker = normalized_trade.get('is_maker', True)
        
        maker_fee = (total_value * MAKER_FEE_BPS / 10000) if is_maker else 0
        taker_fee = (total_value * TAKER_FEE_BPS / 10000) if not is_maker else 0
        gas_cost = GAS_ESTIMATE_USD
        
        return {
            'maker_fee': maker_fee,
            'taker_fee': taker_fee,
            'gas_cost': gas_cost,
            'total': maker_fee + taker_fee + gas_cost
        }
    
    def _parse_timestamp(self, timestamp) -> datetime:
        """Parse various timestamp formats"""
        if isinstance(timestamp, datetime):
            return timestamp
        elif isinstance(timestamp, (int, float)):
            return datetime.fromtimestamp(timestamp)
        elif isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except:
                return datetime.now()
        else:
            return datetime.now()
    
    def _log_ingestion(
        self, 
        data_source: str,
        endpoint: str,
        fetched: int,
        inserted: int,
        updated: int,
        failed: int
    ):
        """Log ingestion metrics"""
        try:
            with self.db.session_scope() as session:
                log = IngestionLog(
                    data_source=data_source,
                    endpoint=endpoint,
                    records_fetched=fetched,
                    records_inserted=inserted,
                    records_updated=updated,
                    records_failed=failed,
                    status='SUCCESS' if failed == 0 else 'PARTIAL'
                )
                session.add(log)
                
        except Exception as e:
            logger.error(f"Error logging ingestion: {e}")
