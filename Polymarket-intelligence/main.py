# main.py
# Orchestrates health checks, ingestion, P&L tracking, and alerting.

import time
import logging
from datetime import datetime, timedelta, timezone
from typing import List
from sqlalchemy import desc

from monitoring.health_check import HealthChecker
from monitoring.alerting import AlertManager
from ingestion.wallet_tracker import WalletTracker
from ingestion.fill_normalizer import FillNormalizer
from ingestion.market_snapshot import MarketSnapshotEngine
from analytics.pnl_engine import PnLEngine
from analytics.position_manager import PositionManager
from database.connection import db_manager
from database.models import Fill, Position, User
from config import (
    DATABASE_URL,
    DISCORD_WEBHOOK_URL,
    POLYMARKET_CLOB_API,
    POLYMARKET_GAMMA_API,
    TRACKED_ADDRESSES,
    CHECK_INTERVAL,
    ADDRESS_TO_USER
)

logger = logging.getLogger(__name__)


def process_fills_for_pnl(db_manager, pnl_engine, address: str, num_fills: int) -> float:
    """
    Process recently inserted fills through the P&L engine.
    
    Returns total realized P&L from sells in this batch.
    """
    total_realized_pnl = 0.0
    
    try:
        with db_manager.session_scope() as session:
            # Get the most recent fills for this address that haven't been processed
            recent_fills = session.query(Fill).filter_by(
                wallet_address=address
            ).order_by(desc(Fill.fill_timestamp)).limit(num_fills).all()
            
            # Process in chronological order (oldest first)
            for fill in reversed(recent_fills):
                try:
                    result = pnl_engine.process_fill(fill)
                    
                    if result.get('realized_pnl'):
                        total_realized_pnl += result['realized_pnl']
                        logger.debug(
                            f"P&L: {fill.side} {fill.size:.2f} @ ${fill.price:.4f} "
                            f"-> Realized: ${result['realized_pnl']:+.2f}"
                        )
                    elif result.get('lot_created'):
                        logger.debug(
                            f"Position opened: {fill.side} {fill.size:.2f} @ ${fill.price:.4f}"
                        )
                        
                except Exception as e:
                    logger.warning(f"Error processing fill {fill.fill_id[:20]}... for P&L: {e}")
                    continue
                    
    except Exception as e:
        logger.error(f"Error in P&L processing for {address[:10]}...: {e}")
    
    return total_realized_pnl


def main_loop(poll_interval: int = 60):
    # Initialize database tables (if they don't exist)
    logger.info("Initializing database tables...")
    try:
        db_manager.create_all_tables()
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}")
        raise
    
    # Initialize components
    health = HealthChecker(db=db_manager)
    alert = AlertManager(DISCORD_WEBHOOK_URL) if DISCORD_WEBHOOK_URL else None
    tracker = WalletTracker()
    normalizer = FillNormalizer()
    snapshot_engine = MarketSnapshotEngine()
    pnl_engine = PnLEngine()
    position_manager = PositionManager()

    # Simple startup health ping
    logger.info("Starting Polymarket Intelligence Main Loop")
    logger.info("P&L tracking enabled - positions and profits will be calculated")
    logger.info(f"Tracking {len(TRACKED_ADDRESSES)} wallet addresses")
    health_report = health.overall_health()
    logger.info(f"Health: {health_report['status']} at {health_report['timestamp']}")

    if alert and health_report.get("status") != "OK":
        alert.send_alert("Health Alert", f"Initial health check status: {health_report['status']}")

    while True:
        now = datetime.now(timezone.utc)
        logger.info(f"Tick at {now.isoformat()} - running data ingestion cycle")

        # Ingestion health check
        ing_health = health.ingestion_health()
        if ing_health["status"] != "OK" and alert:
            alert.send_alert("Ingestion Lag", ing_health["details"], severity="WARNING")

        # Fetch and process trades for all tracked addresses
        total_inserted = 0
        total_failed = 0
        total_realized_pnl = 0.0
        
        for address in TRACKED_ADDRESSES:
            if not address:  # Skip empty addresses
                continue
                
            try:
                # Get last processed timestamp for this address
                since_timestamp = None
                with db_manager.session_scope() as session:
                    last_fill = session.query(Fill).filter_by(
                        wallet_address=address
                    ).order_by(desc(Fill.fill_timestamp)).first()
                    
                    if last_fill:
                        # Start from 1 hour before last fill to catch any overlaps
                        since_timestamp = int((last_fill.fill_timestamp - timedelta(hours=1)).timestamp())
                    else:
                        # First run: fetch last 7 days of data
                        since_timestamp = int((now - timedelta(days=7)).timestamp())
                
                # Fetch trades
                user_id = ADDRESS_TO_USER.get(address, address[:10])
                logger.info(f"Fetching trades for {user_id}... since {since_timestamp}")
                raw_trades = tracker.fetch_trades(address, since_timestamp=since_timestamp, limit=1000)
                
                if raw_trades:
                    logger.info(f"Processing {len(raw_trades)} trades for {user_id}...")
                    inserted, updated, failed = normalizer.normalize_and_store_trades(raw_trades, address)
                    total_inserted += inserted
                    total_failed += failed
                    
                    # Process new fills through P&L engine
                    if inserted > 0:
                        realized_pnl = process_fills_for_pnl(
                            db_manager, pnl_engine, address, inserted
                        )
                        total_realized_pnl += realized_pnl
                        
                        if realized_pnl != 0:
                            logger.info(f"💰 {user_id} realized P&L: ${realized_pnl:+.2f}")
                    
                    logger.info(f"Processed {user_id}: {inserted} new fills, {updated} duplicates")
                else:
                    logger.debug(f"No new trades for {user_id}...")
                    
            except Exception as e:
                logger.error(f"Error processing address {address[:10]}...: {e}")
                total_failed += 1
                if alert:
                    alert.send_alert("Ingestion Error", f"Error processing {address[:10]}...: {str(e)}", severity="ERROR")

        # Log cycle summary
        logger.info(f"Ingestion cycle complete: {total_inserted} fills inserted, {total_failed} failed")
        if total_realized_pnl != 0:
            logger.info(f"💰 Total realized P&L this cycle: ${total_realized_pnl:+.2f}")
        
        # Periodic position summary (every cycle, log open positions count)
        try:
            with db_manager.session_scope() as session:
                open_positions = session.query(Position).filter(
                    Position.is_closed == False,
                    Position.total_size > 0
                ).count()
                
                total_unrealized = session.query(
                    Position.unrealized_pnl
                ).filter(
                    Position.is_closed == False
                ).all()
                
                unrealized_sum = sum(p[0] or 0 for p in total_unrealized)
                
                if open_positions > 0:
                    logger.info(
                        f"📊 Open positions: {open_positions} | "
                        f"Unrealized P&L: ${unrealized_sum:+.2f}"
                    )
        except Exception as e:
            logger.debug(f"Could not get position summary: {e}")
        
        time.sleep(poll_interval)

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    main_loop(30)


#py -m venv .venv
#.venv\Scripts\activate
#pip install -r requirements.txt
# streamlit run dashboard.py