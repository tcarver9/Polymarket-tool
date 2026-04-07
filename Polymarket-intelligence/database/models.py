from sqlalchemy import (
    Column, String, Float, Integer, DateTime, Boolean, Text, 
    ForeignKey, Index, UniqueConstraint, Enum as SQLEnum, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from enum import Enum

Base = declarative_base()


class LotAccountingMethod(str, Enum):
    FIFO = "FIFO"
    LIFO = "LIFO"
    WAVG = "WAVG"


class TradeLabel(str, Enum):
    """Trade outcome labels for ML"""
    PROFITABLE = "PROFITABLE"
    UNPROFITABLE = "UNPROFITABLE"
    BREAKEVEN = "BREAKEVEN"
    PENDING = "PENDING"


# ==================== CORE TABLES ====================

class User(Base):
    """User/entity being tracked"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), unique=True, nullable=False, index=True)
    primary_address = Column(String(42), unique=True, nullable=False, index=True)
    tags = Column(JSON, nullable=True)  # ["whale", "politics", etc.]
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    addresses = relationship("WalletAddress", back_populates="user")
    fills = relationship("Fill", back_populates="user")


class WalletAddress(Base):
    """All wallet addresses associated with a user"""
    __tablename__ = 'wallet_addresses'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    address = Column(String(42), unique=True, nullable=False, index=True)
    is_primary = Column(Boolean, default=False)
    
    first_seen = Column(DateTime, default=func.now())
    last_active = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="addresses")
    
    __table_args__ = (
        Index('idx_wallet_user', 'user_id', 'address'),
    )


class Market(Base):
    """Market metadata and state snapshots"""
    __tablename__ = 'markets'
    
    id = Column(Integer, primary_key=True)
    market_id = Column(String(255), unique=True, nullable=False, index=True)
    condition_id = Column(String(255), nullable=True, index=True)
    question = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    
    # Market characteristics
    category = Column(String(100), nullable=True, index=True)
    tags = Column(JSON, nullable=True)
    outcomes = Column(JSON, nullable=False)  # ["YES", "NO"] or multiple outcomes
    
    # Resolution
    resolved = Column(Boolean, default=False, index=True)
    resolution_outcome = Column(String(50), nullable=True)
    resolution_timestamp = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.now())
    end_date = Column(DateTime, nullable=True)
    
    # Relationships
    snapshots = relationship("MarketSnapshot", back_populates="market")
    fills = relationship("Fill", back_populates="market")


class MarketSnapshot(Base):
    """Market state at a point in time (for feature engineering)"""
    __tablename__ = 'market_snapshots'
    
    id = Column(Integer, primary_key=True)
    market_id = Column(Integer, ForeignKey('markets.id'), nullable=False)
    snapshot_timestamp = Column(DateTime, nullable=False, index=True)
    
    # Price and spread per outcome
    outcome_prices = Column(JSON, nullable=False)  # {"YES": 0.52, "NO": 0.48}
    outcome_spreads = Column(JSON, nullable=True)  # {"YES": 0.02, "NO": 0.02}
    
    # Liquidity and volume
    total_liquidity_usd = Column(Float, nullable=True)
    volume_24h_usd = Column(Float, nullable=True)
    
    # Volatility metrics
    price_volatility_1h = Column(Float, nullable=True)
    price_change_24h = Column(Float, nullable=True)
    
    # Time features
    hours_to_resolution = Column(Float, nullable=True)
    
    # External probability (if available)
    external_probability = Column(Float, nullable=True)  # From polls, models, etc.
    
    market = relationship("Market", back_populates="snapshots")
    
    __table_args__ = (
        Index('idx_market_snapshot_time', 'market_id', 'snapshot_timestamp'),
    )


class Fill(Base):
    """Canonical fill table - atomic execution units"""
    __tablename__ = 'fills'
    
    id = Column(Integer, primary_key=True)
    fill_id = Column(String(255), unique=True, nullable=False, index=True)
    
    # Attribution
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    wallet_address = Column(String(42), nullable=False, index=True)
    
    # Market reference
    market_id = Column(Integer, ForeignKey('markets.id'), nullable=False, index=True)
    asset_id = Column(String(255), nullable=False, index=True)
    outcome = Column(String(50), nullable=False)
    
    # Fill details
    side = Column(String(10), nullable=False)  # BUY or SELL
    size = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    total_value = Column(Float, nullable=False)
    
    # Fees
    maker_fee = Column(Float, default=0)
    taker_fee = Column(Float, default=0)
    gas_cost_usd = Column(Float, default=0)
    total_fees = Column(Float, nullable=False)
    
    # Timing
    fill_timestamp = Column(DateTime, nullable=False, index=True)
    block_number = Column(Integer, nullable=True)
    transaction_hash = Column(String(66), nullable=True, index=True)
    
    # Market context at fill time
    market_snapshot_id = Column(Integer, ForeignKey('market_snapshots.id'), nullable=True)
    market_mid_price = Column(Float, nullable=True)
    market_spread = Column(Float, nullable=True)
    
    # Order tracking
    order_id = Column(String(255), nullable=True, index=True)
    is_maker = Column(Boolean, default=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.now())
    ingestion_timestamp = Column(DateTime, default=func.now())
    
    # Data quality
    verified_onchain = Column(Boolean, default=False)
    data_source = Column(String(50), default='API')  # API, ONCHAIN, MANUAL
    
    # Relationships
    user = relationship("User", back_populates="fills")
    market = relationship("Market", back_populates="fills")
    lots = relationship("Lot", back_populates="fill")
    
    __table_args__ = (
        Index('idx_fill_user_time', 'user_id', 'fill_timestamp'),
        Index('idx_fill_market_time', 'market_id', 'fill_timestamp'),
        Index('idx_fill_asset_side', 'asset_id', 'side'),
    )


class Lot(Base):
    """Position lots for proper PnL accounting"""
    __tablename__ = 'lots'
    
    id = Column(Integer, primary_key=True)
    lot_id = Column(String(255), unique=True, nullable=False, index=True)
    
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    asset_id = Column(String(255), nullable=False, index=True)
    outcome = Column(String(50), nullable=False)
    
    # Lot details
    entry_fill_id = Column(Integer, ForeignKey('fills.id'), nullable=False)
    entry_price = Column(Float, nullable=False)
    original_size = Column(Float, nullable=False)
    remaining_size = Column(Float, nullable=False)
    entry_timestamp = Column(DateTime, nullable=False)
    entry_fees = Column(Float, default=0)
    
    # Lot status
    is_closed = Column(Boolean, default=False, index=True)
    close_timestamp = Column(DateTime, nullable=True)
    
    # Accounting method used
    accounting_method = Column(SQLEnum(LotAccountingMethod), nullable=False)
    
    created_at = Column(DateTime, default=func.now())
    
    fill = relationship("Fill", back_populates="lots")
    closures = relationship("LotClosure", back_populates="lot")
    
    __table_args__ = (
        Index('idx_lot_user_asset', 'user_id', 'asset_id', 'is_closed'),
    )


class LotClosure(Base):
    """Records of lot closures (partial or full)"""
    __tablename__ = 'lot_closures'
    
    id = Column(Integer, primary_key=True)
    lot_id = Column(Integer, ForeignKey('lots.id'), nullable=False)
    exit_fill_id = Column(Integer, ForeignKey('fills.id'), nullable=False)
    
    # Closure details
    size_closed = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    exit_fees = Column(Float, default=0)
    exit_timestamp = Column(DateTime, nullable=False)
    
    # Realized PnL
    gross_pnl = Column(Float, nullable=False)
    net_pnl = Column(Float, nullable=False)  # After fees
    pnl_percentage = Column(Float, nullable=False)
    
    # Holding period
    holding_period_seconds = Column(Integer, nullable=False)
    
    created_at = Column(DateTime, default=func.now())
    
    lot = relationship("Lot", back_populates="closures")


class Position(Base):
    """Aggregated position view per user per asset"""
    __tablename__ = 'positions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    asset_id = Column(String(255), nullable=False)
    market_id = Column(Integer, ForeignKey('markets.id'), nullable=False)
    outcome = Column(String(50), nullable=False)
    
    # Current position
    total_size = Column(Float, default=0)
    average_entry_price = Column(Float, nullable=True)
    total_cost_basis = Column(Float, default=0)
    
    # Unrealized PnL (mark to market)
    current_mark_price = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, default=0)
    unrealized_pnl_pct = Column(Float, default=0)
    last_mark_update = Column(DateTime, nullable=True)
    
    # Position lifecycle
    first_entry_timestamp = Column(DateTime, nullable=True)
    last_update_timestamp = Column(DateTime, nullable=True)
    is_closed = Column(Boolean, default=False, index=True)
    
    # Realized PnL (from closed lots)
    realized_pnl = Column(Float, default=0)
    realized_pnl_pct = Column(Float, default=0)
    
    # Final settlement
    is_settled = Column(Boolean, default=False)
    settlement_timestamp = Column(DateTime, nullable=True)
    settlement_pnl = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint('user_id', 'asset_id', 'outcome', name='uq_user_asset_outcome'),
        Index('idx_position_user', 'user_id', 'is_closed'),
    )


class TradeFeatures(Base):
    """Feature engineering for ML - computed per fill"""
    __tablename__ = 'trade_features'
    
    id = Column(Integer, primary_key=True)
    fill_id = Column(Integer, ForeignKey('fills.id'), unique=True, nullable=False)
    
    # Price features
    price_vs_mid = Column(Float, nullable=True)  # How far from mid
    spread_at_trade = Column(Float, nullable=True)
    price_momentum_1h = Column(Float, nullable=True)
    price_momentum_24h = Column(Float, nullable=True)
    
    # Volume features
    size_vs_avg_24h = Column(Float, nullable=True)
    volume_rank_percentile = Column(Float, nullable=True)
    
    # Timing features
    hours_before_resolution = Column(Float, nullable=True)
    is_during_volatility_spike = Column(Boolean, default=False)
    
    # Edge estimation
    implied_probability = Column(Float, nullable=True)
    external_probability = Column(Float, nullable=True)
    estimated_edge = Column(Float, nullable=True)  # implied - external
    
    # User behavior
    user_position_before = Column(Float, default=0)
    is_position_increase = Column(Boolean, default=True)
    is_reversal = Column(Boolean, default=False)
    
    # Labels (for supervised learning)
    label = Column(SQLEnum(TradeLabel), nullable=True, index=True)
    label_horizon_hours = Column(Float, nullable=True)  # How far ahead we looked
    final_outcome_correct = Column(Boolean, nullable=True)
    
    # Avoid leakage - timestamp when label was assigned
    label_assigned_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=func.now())


class PerformanceMetrics(Base):
    """Rolling performance metrics per user"""
    __tablename__ = 'performance_metrics'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    metric_date = Column(DateTime, nullable=False)
    lookback_days = Column(Integer, nullable=False)  # 7, 30, 90, etc.
    
    # Trade statistics
    total_fills = Column(Integer, default=0)
    total_volume_usd = Column(Float, default=0)
    
    # Position statistics
    positions_opened = Column(Integer, default=0)
    positions_closed = Column(Integer, default=0)
    avg_hold_time_hours = Column(Float, nullable=True)
    
    # PnL
    realized_pnl = Column(Float, default=0)
    realized_pnl_pct = Column(Float, default=0)
    win_rate = Column(Float, default=0)
    profit_factor = Column(Float, nullable=True)  # gross_profit / gross_loss
    sharpe_ratio = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    
    # Edge metrics
    avg_edge_per_trade = Column(Float, nullable=True)
    edge_realization_rate = Column(Float, nullable=True)  # How often edge → profit
    
    # Market prediction accuracy
    prediction_accuracy = Column(Float, nullable=True)
    calibration_score = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=func.now())
    
    __table_args__ = (
        UniqueConstraint('user_id', 'metric_date', 'lookback_days', name='uq_user_date_lookback'),
        Index('idx_perf_user_date', 'user_id', 'metric_date'),
    )


class IngestionLog(Base):
    """Track data ingestion health"""
    __tablename__ = 'ingestion_logs'
    
    id = Column(Integer, primary_key=True)
    ingestion_timestamp = Column(DateTime, default=func.now(), index=True)
    
    data_source = Column(String(50), nullable=False)  # CLOB_API, GAMMA_API, ONCHAIN
    endpoint = Column(String(255), nullable=True)
    
    # Health metrics
    records_fetched = Column(Integer, default=0)
    records_inserted = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)
    
    lag_seconds = Column(Integer, nullable=True)  # Data freshness
    duration_seconds = Column(Float, nullable=True)
    
    status = Column(String(20), default='SUCCESS')  # SUCCESS, PARTIAL, FAILED
    error_message = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('idx_ingestion_timestamp', 'ingestion_timestamp'),
    )


class Alert(Base):
    """System alerts and monitoring"""
    __tablename__ = 'alerts'
    
    id = Column(Integer, primary_key=True)
    alert_timestamp = Column(DateTime, default=func.now(), index=True)
    severity = Column(String(20), nullable=False)  # INFO, WARNING, ERROR, CRITICAL
    
    alert_type = Column(String(50), nullable=False, index=True)
    message = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)
    
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)
    
    notified_discord = Column(Boolean, default=False)
