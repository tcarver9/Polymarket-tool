import requests
import logging
from datetime import datetime
from typing import List, Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from config import (
    POLYMARKET_CLOB_API, 
    POLYMARKET_GAMMA_API,
    POLYMARKET_DATA_API,
    MAX_RETRIES,
    ADDRESS_TO_USER
)

logger = logging.getLogger(__name__)


class WalletTracker:
    """Track wallet activity using Polymarket Data API (public, no auth required)"""
    
    def __init__(self):
        self.clob_api = POLYMARKET_CLOB_API
        self.gamma_api = POLYMARKET_GAMMA_API
        self.data_api = POLYMARKET_DATA_API
        
        # Session for API requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'PolymarketIntelligence/1.0',
            'Accept': 'application/json'
        })
        
        logger.info(f"WalletTracker initialized with Data API: {self.data_api}")
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_trades(
        self, 
        address: str, 
        since_timestamp: Optional[int] = None,
        limit: int = 1000
    ) -> List[Dict]:
        """
        Fetch trades for an address using the public Data API
        
        Args:
            address: Wallet address
            since_timestamp: Unix timestamp to fetch trades after
            limit: Max number of trades to fetch
            
        Returns:
            List of trade dictionaries
        """
        try:
            # Use the public Data API - no authentication required
            url = f"{self.data_api}/trades"
            
            params = {
                "user": address,
                "limit": limit
            }
            
            # Data API uses startDate/endDate for time filtering
            if since_timestamp:
                # Convert timestamp to ISO format
                from datetime import datetime, timezone
                start_date = datetime.fromtimestamp(since_timestamp, tz=timezone.utc).isoformat()
                params["startDate"] = start_date
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            trades = data if isinstance(data, list) else []
            
            logger.info(f"Fetched {len(trades)} trades for {address[:10]}... (Data API)")
            return trades
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching trades for {address}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching trades for {address}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_positions(self, address: str) -> List[Dict]:
        """Fetch current positions for an address using the public Data API"""
        try:
            url = f"{self.data_api}/positions"
            params = {"user": address}
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            positions = data if isinstance(data, list) else []
            
            logger.info(f"Fetched {len(positions)} positions for {address[:10]}... (Data API)")
            return positions
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching positions for {address}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching positions for {address}: {e}")
            return []
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_activity(self, address: str, limit: int = 100) -> List[Dict]:
        """Fetch activity feed for an address (trades, claims, etc.)"""
        try:
            url = f"{self.data_api}/activity"
            params = {"user": address, "limit": limit}
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            activities = data if isinstance(data, list) else []
            
            logger.info(f"Fetched {len(activities)} activities for {address[:10]}... (Data API)")
            return activities
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching activity for {address}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching activity for {address}: {e}")
            return []
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_market_data(self, condition_id: str) -> Optional[Dict]:
        """Fetch market metadata"""
        try:
            url = f"{self.gamma_api}/markets/{condition_id}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching market data for {condition_id}: {e}")
            return None
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_market_orderbook(self, token_id: str) -> Optional[Dict]:
        """Fetch current orderbook for a token"""
        try:
            url = f"{self.clob_api}/book"
            params = {"token_id": token_id}
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching orderbook for {token_id}: {e}")
            return None
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_market_trades(
        self, 
        token_id: str, 
        since_timestamp: Optional[int] = None
    ) -> List[Dict]:
        """Fetch recent market trades for context"""
        try:
            url = f"{self.clob_api}/trades"
            params = {
                "asset_id": token_id,
                "limit": 100
            }
            
            if since_timestamp:
                params["after"] = since_timestamp
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            return data if isinstance(data, list) else []
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching market trades for {token_id}: {e}")
            return []
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_positions_with_pnl(self, address: str) -> List[Dict]:
        """
        Fetch positions with P&L data from Data API.
        This includes resolved market outcomes and actual profit/loss.
        
        Returns position data including:
        - outcome: What the user bet on (e.g., "Over", "Yes", "UCF")
        - curPrice: 0 = lost, 1 = won (for resolved markets)
        - cashPnl: Actual profit/loss in dollars
        - redeemable: True if market resolved
        """
        try:
            url = f"{self.data_api}/positions"
            params = {"user": address}
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            positions = data if isinstance(data, list) else []
            
            logger.info(f"Fetched {len(positions)} positions with P&L for {address[:10]}...")
            return positions
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching positions for {address}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching positions for {address}: {e}")
            return []

    def get_user_id_for_address(self, address: str) -> Optional[str]:
        """Map address to user ID"""
        return ADDRESS_TO_USER.get(address)



