# config.py - ADVANCED VERSION

# ===== CORE DETECTION SETTINGS =====
DEFAULT_CONFIG = {
    # === Fresh Wallet Detection ===
    'max_trades_fresh_wallet': 5,  # Increase to 5-10 to catch more wallets
    'min_bet_size_fresh_wallet': 500,  # Lower to $500 to catch smaller bets
    'fresh_wallet_time_window_hours': 24,  # Consider wallets created in last 24h as fresh
    
    # === Large Bet Detection ===
    'bet_to_volume_threshold': 3,  # Lower to 3% to be more sensitive
    'absolute_bet_threshold': 5000,  # Flag any single bet over $5k regardless of market size
    'whale_threshold': 50000,  # Flag massive bets over $50k
    
    # === Repeated Entry Detection ===
    'repeated_market_entries': 2,  # Lower to 2 entries to catch earlier
    'time_window_repeated_entries_hours': 12,  # Within 12 hours
    'repeated_entry_velocity_threshold': 3,  # 3+ trades within 1 hour
    
    # === Timing Pattern Detection (NEW) ===
    'suspicious_timing_window_minutes': 30,  # Detect trades 30min before big news
    'night_trading_start_hour': 23,  # 11 PM
    'night_trading_end_hour': 6,  # 6 AM (unusual trading hours)
    
    # === Profit Pattern Detection (NEW) ===
    'suspicious_win_rate_threshold': 0.75,  # 75%+ win rate is suspicious
    'min_trades_for_win_rate': 5,  # Need at least 5 trades to calculate
    
    # === Market Manipulation Detection (NEW) ===
    'price_impact_threshold': 5,  # Flag if single trade moves price >5%
    'coordinated_trading_window_seconds': 60,  # Multiple wallets within 60s
    
    # === Scanning Parameters ===
    'scan_interval_minutes': 5,  # Scan every 5 minutes
    'lookback_window_minutes': 10,  # Look at last 10 minutes of trades
    'max_markets_to_scan': 100,  # Increase to scan more markets
    'min_market_volume': 50,  # Lower threshold to include smaller markets
    
    # === Advanced Filters ===
    'track_wallet_relationships': True,  # Track if wallets trade together
    'analyze_order_book_depth': True,  # Check if bets are absorbing liquidity
    'monitor_rapid_position_changes': True,  # Detect quick flip-flopping
}

# ===== MARKET CATEGORIES TO MONITOR =====
MONITORED_CATEGORIES = {
    'politics': {
        'enabled': True,
        'keywords': [
            'election', 'president', 'senate', 'congress', 'governor',
            'trump', 'biden', 'desantis', 'harris', 'primary',
            'vote', 'poll', 'debate', 'campaign', 'democrat', 'republican',
            'swing state', 'electoral', 'midterm', 'nomination'
        ],
        'min_bet_threshold': 1000,  # Lower threshold for political markets
    },
    'crypto': {
        'enabled': True,
        'keywords': [
            'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'sec approval',
            'etf', 'coinbase', 'binance', 'regulation', 'halving'
        ],
        'min_bet_threshold': 2000,
    },
    'finance': {
        'enabled': True,
        'keywords': [
            'fed', 'interest rate', 'inflation', 'cpi', 'jobs report',
            'recession', 'gdp', 'unemployment', 'powell', 'stock market',
            'sp500', 's&p', 'dow jones'
        ],
        'min_bet_threshold': 3000,
    },
    'tech': {
        'enabled': True,
        'keywords': [
            'openai', 'gpt', 'ai', 'apple', 'google', 'meta', 'amazon',
            'tesla', 'spacex', 'nvidia', 'microsoft', 'earnings'
        ],
        'min_bet_threshold': 2000,
    },
    'sports': {
        'enabled': False,  # Set to True if you want sports betting monitoring
        'keywords': [
            'nfl', 'nba', 'super bowl', 'world series', 'finals',
            'championship', 'mvp', 'playoffs'
        ],
        'min_bet_threshold': 5000,  # Higher threshold for sports
    }
}

# ===== ADVANCED ALERT SETTINGS =====
ALERT_SEVERITY_RULES = {
    'critical': {
        'conditions': [
            'fresh_wallet_over_20k',
            'whale_bet',
            'coordinated_trading',
            'suspicious_win_rate',
        ],
        'notify_immediately': True,
    },
    'high': {
        'conditions': [
            'fresh_wallet_over_5k',
            'large_bet_percentage',
            'rapid_repeated_entries',
            'night_trading',
        ],
        'notify_immediately': True,
    },
    'medium': {
        'conditions': [
            'fresh_wallet',
            'repeated_entries',
            'price_impact',
        ],
        'notify_immediately': False,  # Batch these
    },
    'low': {
        'conditions': [
            'unusual_timing',
            'small_fresh_wallet',
        ],
        'notify_immediately': False,
    }
}

# ===== NOTIFICATION SETTINGS =====
DISCORD_CONFIG = {
    'enabled': True,
    'webhook_url': 'https://discordapp.com/api/webhooks/1457763467472932996/BTY5Q-fS-xDo-xbxFMpzS6XQQZwN4Jn9DFXm7LqbqgR-eA5vsi23bviPFhVAMVdCdsoM',
    'notify_on': ['critical', 'high', 'medium'],  # Add 'low' if you want everything
    'batch_alerts': True,  # Send multiple alerts at once
    'batch_interval_seconds': 300,  # Batch alerts every 5 minutes
}

EMAIL_CONFIG = {
    'enabled': True,
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'username': 'tylercarver60@gmail.com',
    'password': 'arxj plwx kkhc tcpz',
    'from': 'tylercarver60@gmail.com',
    'to': 'tylercarver60@gmail.com',
    'notify_on': ['critical', 'high'],  # Only important alerts via email
    'daily_summary': True,  # Send daily summary of all alerts
    'summary_time': '09:00',  # Send at 9 AM
}

# ===== WHALE WALLET TRACKING =====
KNOWN_WHALES = {
    'enabled': True,
    'auto_detect': True,  # Automatically identify whales
    'whale_criteria': {
        'total_volume': 100000,  # $100k+ total volume
        'average_bet_size': 5000,  # $5k+ average bet
        'win_rate': 0.6,  # 60%+ win rate
    },
    'notify_on_whale_activity': True,
}

# ===== DATA PERSISTENCE =====
STORAGE_CONFIG = {
    'save_all_trades': True,  # Keep database of all trades
    'database_file': 'polymarket_trades.db',  # SQLite database
    'export_alerts_csv': True,  # Export to CSV for analysis
    'export_interval_hours': 24,  # Export daily
}
