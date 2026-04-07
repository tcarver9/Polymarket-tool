# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Polymarket API
    POLYMARKET_API_KEY = os.getenv('POLYMARKET_API_KEY')
    POLYMARKET_SECRET = os.getenv('POLYMARKET_SECRET')
    PRIVATE_KEY = os.getenv('WALLET_PRIVATE_KEY')  # Your wallet private key
    
    # Trading Parameters
    MAX_TOTAL_COST = 0.985  # Maximum combined cost for entry (1.5% guaranteed profit)
    IDEAL_TOTAL_COST = 0.980  # Ideal entry point (2% profit)
    TRADE_SIZE_USD = 10.0  # Size per trade leg
    
    # Market Settings
    MARKET_TYPE = "BTC_15MIN"
    CHECK_INTERVAL = 2  # seconds between price checks
    
    # Risk Management
    MAX_DAILY_TRADES = 20
    MAX_OPEN_POSITIONS = 3
    MIN_LIQUIDITY_USD = 500  # Minimum market liquidity
    
    # WebSocket
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    # CLOB API
    CLOB_API_URL = "https://clob.polymarket.com"


# pip install -r requirements.txt
# .venv\Scripts\activate