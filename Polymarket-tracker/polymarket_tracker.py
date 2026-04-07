import requests
import time
import hmac
import hashlib
import base64
from datetime import datetime
from typing import Dict, List, Optional
import json

class PolymarketTracker:
    def __init__(self, api_base: str, gamma_api: str, api_key: str = None, api_secret: str = None, api_passphrase: str = None, data_api: str = None):
        self.api_base = api_base  # CLOB API
        self.data_api = data_api or "https://data-api.polymarket.com"  # Data-API
        self.gamma_api = gamma_api
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_passphrase = api_passphrase
        self.tracked_trades = {}  # Store trades by trade_id
        self.position_cache = {}  # Cache positions for profit/loss calculation
        self._debug_printed = False  # Only print debug info once
    
    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """Generate HMAC-SHA256 signature for Polymarket Builder API"""
        if not self.api_secret:
            return ""
        
        # Polymarket secrets are typically base64 encoded - decode it
        try:
            secret_bytes = base64.b64decode(self.api_secret)
        except:
            # If base64 decode fails, try using as plain string
            try:
                secret_bytes = self.api_secret.encode('utf-8')
            except:
                return ""
        
        # Create prehash string: timestamp + method + requestPath + body
        # Note: No separators between components
        prehash_string = f"{timestamp}{method}{request_path}{body}"
        
        # Generate HMAC-SHA256 signature
        signature = hmac.new(
            secret_bytes,
            prehash_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def _get_auth_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """Generate authentication headers for Polymarket Builder API"""
        headers = {}
        
        if self.api_key and self.api_secret and self.api_passphrase:
            # Generate timestamp (Unix timestamp in milliseconds)
            timestamp = str(int(time.time() * 1000))
            
            # Generate signature
            signature = self._generate_signature(timestamp, method, request_path, body)
            
            # Use POLY_BUILDER_* format (Builder API format)
            headers['POLY_BUILDER_API_KEY'] = self.api_key.strip()
            headers['POLY_BUILDER_TIMESTAMP'] = timestamp
            headers['POLY_BUILDER_SIGNATURE'] = signature
            headers['POLY_BUILDER_PASSPHRASE'] = self.api_passphrase.strip()
        
        return headers
        
    def get_user_trades(self, address: str, limit: int = 100) -> List[Dict]:
        """Fetch recent trades for a specific address"""
        try:
            # Try Data-API endpoint first (this is the correct endpoint for fetching trades)
            # Data-API /trades accepts filtering parameters like user, market, eventId, etc.
            request_path = "/trades"
            url = f"{self.data_api}{request_path}"
            
            # Try with "user" parameter first (Data-API format)
            params = {
                "user": address,
                "limit": limit
            }
            
            # Try Data-API without authentication first (may be public)
            response = requests.get(url, params=params, timeout=10)
            
            # If that fails, try with "maker_address" parameter (CLOB API format)
            if response.status_code != 200:
                params = {
                    "maker_address": address,
                    "limit": limit
                }
                response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # Handle different response formats
                if isinstance(data, dict) and 'trades' in data:
                    return data['trades']
                elif isinstance(data, list):
                    return data
                return []
            
            # If not 200, return empty (401 will be handled below)
            if response.status_code != 200 and response.status_code != 401:
                return []
            
            # If 401, try with Builder API authentication
            if response.status_code == 401:
                query_string = f"?user={address}&limit={limit}"
                request_path_with_params = f"{request_path}{query_string}"
                headers = self._get_auth_headers("GET", request_path_with_params)
                response = requests.get(url, params=params, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and 'trades' in data:
                        return data['trades']
                    elif isinstance(data, list):
                        return data
                    return []
                
                # Try again with just the path (no query params in signature)
                if response.status_code == 401:
                    headers = self._get_auth_headers("GET", request_path)
                    response = requests.get(url, params=params, headers=headers)
                    
                    if response.status_code == 200:
                        data = response.json()
                        if isinstance(data, dict) and 'trades' in data:
                            return data['trades']
                        elif isinstance(data, list):
                            return data
                        return []
            
            # Fallback to CLOB API endpoint (requires L2 User API credentials, not Builder API)
            # This will likely fail with Builder API credentials, but we'll try it
            if response.status_code != 200:
                request_path = "/trades"
                url = f"{self.api_base}{request_path}"
                params = {
                    "maker_address": address,
                    "limit": limit
                }
                
                # Try CLOB API without authentication
                response = requests.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, list) else []
            
            # If 401, try with Builder API authentication
            if response.status_code == 401:
                # Try with query params in path for signature
                query_string = f"?maker_address={address}&limit={limit}"
                request_path_with_params = f"{request_path}{query_string}"
                headers = self._get_auth_headers("GET", request_path_with_params)
                response = requests.get(url, params=params, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    return data if isinstance(data, list) else []
                
                # Try again with just the path (no query params in signature)
                if response.status_code == 401:
                    headers = self._get_auth_headers("GET", request_path)
                    response = requests.get(url, params=params, headers=headers)
                    
                    if response.status_code == 200:
                        data = response.json()
                        return data if isinstance(data, list) else []
                
                # Still failing - provide error message
                if response.status_code == 401:
                    error_detail = response.text if hasattr(response, 'text') else 'No error details'
                    print(f"Error fetching trades: {response.status_code} - {error_detail[:200]}")
                    
                    if not self.api_secret or not self.api_passphrase:
                        print("⚠️  Builder API requires API_KEY, API_SECRET, and API_PASSPHRASE.")
                        print("   Please set all three in your .env file:")
                        print("   - POLYMARKET_API_KEY")
                        print("   - POLYMARKET_API_SECRET")
                        print("   - POLYMARKET_API_PASSPHRASE")
                    else:
                        print("⚠️  Authentication failed. Please verify your Builder API credentials.")
                        print("   The /trades endpoint may require different authentication or be unavailable.")
                        print("   Check: https://docs.polymarket.com/developers/CLOB/authentication")
            else:
                error_detail = response.text if hasattr(response, 'text') else 'No error details'
                print(f"Error fetching trades: {response.status_code} - {error_detail[:200]}")
            
            return []
        
        except Exception as e:
            print(f"Error in get_user_trades: {e}")
            return []
    
    def get_market_info(self, condition_id: str) -> Optional[Dict]:
        """Get market information including name"""
        if not condition_id:
            return None
            
        try:
            url = f"{self.gamma_api}/markets/{condition_id}"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                return data if isinstance(data, dict) else None
            return None
        
        except Exception as e:
            return None
    
    def get_user_positions(self, address: str) -> List[Dict]:
        """Get current positions for an address"""
        try:
            url = f"{self.gamma_api}/positions"
            params = {
                "user": address
            }
            
            # Gamma API might not require authentication
            response = requests.get(url, params=params)
            
            if response.status_code == 200:
                return response.json()
            return []
        
        except Exception as e:
            print(f"Error fetching positions: {e}")
            return []
    
    def parse_trade(self, trade: Dict, account: str) -> Dict:
        """Parse trade data into a readable format"""
        try:
            # Try multiple possible field names for the market identifier
            asset_id = trade.get('asset_id', '') or trade.get('conditionId', '') or trade.get('condition_id', '') or trade.get('market', '')
            
            # Debug: print what we're working with (only first time)
            if not self._debug_printed and not asset_id:
                print(f"⚠️  Debug: Trade keys: {list(trade.keys())}")
                print(f"   Trade sample: {json.dumps({k: str(v)[:50] for k, v in list(trade.items())[:5]}, indent=2)}")
                self._debug_printed = True
            
            if not asset_id:
                # Try to find any ID-like field
                for key in ['conditionId', 'condition_id', 'market', 'marketId', 'token', 'tokenId', 'tokenId']:
                    if key in trade:
                        asset_id = trade[key]
                        if not self._debug_printed:
                            print(f"   Using {key}: {asset_id}")
                        break
            
            # Get market info from Gamma API using asset_id/condition_id
            market_info = None
            if asset_id:
                market_info = self.get_market_info(asset_id)
                if not market_info:
                    # Try to extract condition ID from asset_id if it's a full token address
                    # Sometimes asset_id is a token address, we need the condition ID
                    # Format might be: 0x...-0 or 0x...-1 for binary markets
                    if '-' in asset_id:
                        condition_id = asset_id.split('-')[0]
                        market_info = self.get_market_info(condition_id)
                
                # If still no market info, try getting it from trade data directly
                if not market_info and 'market' in trade:
                    market_data = trade.get('market', {})
                    if isinstance(market_data, dict):
                        market_info = market_data
                        if not self._debug_printed:
                            print(f"   Found market info in trade data")
            
            # Extract market name - Gamma API provides 'question' field
            market_name = 'Unknown Market'
            if market_info:
                market_name = (market_info.get('question') or 
                             market_info.get('title') or 
                             market_info.get('name') or 
                             'Unknown Market')
            
            # Gamma API provides slug for market URLs
            market_slug = market_info.get('slug', '') if market_info else ''
            condition_id_from_market = (market_info.get('conditionId', '') or 
                                      market_info.get('condition_id', '') or
                                      market_info.get('id', '')) if market_info else ''
            
            # Don't create URLs - they're not working reliably
            # User can search for markets on Polymarket if needed
            market_url = None
            
            # Get market outcomes/tokens (for sports markets, this shows both predictions)
            outcomes = []
            if market_info:
                # Try tokens array first
                tokens = market_info.get('tokens', [])
                if tokens:
                    for token in tokens:
                        outcome_name = token.get('outcome', '') or token.get('name', '')
                        if outcome_name:
                            outcomes.append(outcome_name)
                
                # If no tokens, try outcomes field directly
                if not outcomes and 'outcomes' in market_info:
                    outcomes_raw = market_info.get('outcomes', [])
                    for outcome in outcomes_raw:
                        if isinstance(outcome, str):
                            outcomes.append(outcome)
                        elif isinstance(outcome, dict):
                            outcomes.append(outcome.get('name', '') or outcome.get('outcome', ''))
                
                # Try outcomes array with different structure
                if not outcomes and 'outcomeTokens' in market_info:
                    for token in market_info.get('outcomeTokens', []):
                        name = token.get('name', '') or token.get('outcome', '')
                        if name:
                            outcomes.append(name)
            
            # Get additional market details
            market_description = market_info.get('description', '') if market_info else ''
            market_end_date = market_info.get('endDate', '') if market_info else ''
            
            side = trade.get('side', 'Unknown')
            outcome = trade.get('outcome', 'Unknown')
            size = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            
            # Create market outcomes display (especially useful for sports)
            outcomes_display = ""
            if outcomes and len(outcomes) > 0:
                # Filter out empty outcomes
                outcomes = [o for o in outcomes if o]
                if len(outcomes) == 2:
                    # Binary market (like sports) - show both outcomes
                    outcomes_display = f"**Outcomes:** {outcomes[0]} vs {outcomes[1]}"
                elif len(outcomes) > 0:
                    # Multiple outcomes
                    outcomes_display = f"**Outcomes:** {', '.join(outcomes)}"
            
            # If we still don't have market name but have asset_id, use it as fallback
            if market_name == 'Unknown Market' and asset_id:
                # Try to construct a basic display from asset_id
                if '-' in asset_id:
                    # Binary market - show both sides
                    base_id = asset_id.split('-')[0]
                    outcome_num = asset_id.split('-')[1] if len(asset_id.split('-')) > 1 else ''
                    # For binary markets, typically 0 = first outcome, 1 = second outcome
                    if not outcomes_display:
                        if outcome_num in ['0', '1']:
                            # Common binary outcomes - but we don't know the actual outcomes
                            outcomes_display = "**Outcomes:** [Unknown] vs [Unknown]"
                    market_name = f"Market {base_id[:10]}..."
                # Don't create URLs without proper market info - they won't work
            
            parsed_trade = {
                'trade_id': trade.get('id'),
                'account': account,
                'market_name': market_name,
                'market_url': market_url,
                'market_slug': market_slug,
                'market_outcomes': outcomes,
                'market_outcomes_display': outcomes_display,
                'market_description': market_description,
                'market_end_date': market_end_date,
                'asset_id': asset_id,
                'side': side,
                'outcome': outcome,
                'size': size,
                'price': price,
                'timestamp': datetime.fromtimestamp(
                    int(trade.get('timestamp', time.time()))
                ).strftime('%Y-%m-%d %H:%M:%S'),
                'match_time': trade.get('match_time')
            }
            
            return parsed_trade
        
        except Exception as e:
            print(f"Error parsing trade: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def calculate_profit_loss(self, account: str, asset_id: str, exit_trade: Dict) -> Optional[Dict]:
        """Calculate profit/loss for a completed trade"""
        try:
            # Get position history or cached entry trade
            cache_key = f"{account}_{asset_id}"
            
            if cache_key in self.position_cache:
                entry_data = self.position_cache[cache_key]
                entry_price = entry_data['entry_price']
                entry_size = entry_data['size']
                
                exit_price = float(exit_trade.get('price', 0))
                exit_size = float(exit_trade.get('size', 0))
                
                # Calculate P/L based on trade direction
                if exit_trade.get('side') == 'SELL':
                    profit_loss = (exit_price - entry_price) * min(entry_size, exit_size)
                else:
                    profit_loss = (entry_price - exit_price) * min(entry_size, exit_size)
                
                profit_loss_pct = (profit_loss / (entry_price * min(entry_size, exit_size))) * 100
                
                return {
                    'account': account,
                    'asset_id': asset_id,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'size': min(entry_size, exit_size),
                    'profit_loss': profit_loss,
                    'profit_loss_pct': profit_loss_pct
                }
            
            return None
        
        except Exception as e:
            print(f"Error calculating P/L: {e}")
            return None
    
    def update_position_cache(self, account: str, trade: Dict):
        """Update the position cache with new trade data"""
        try:
            asset_id = trade.get('asset_id')
            cache_key = f"{account}_{asset_id}"
            
            if trade.get('side') == 'BUY':
                # Store entry data
                self.position_cache[cache_key] = {
                    'entry_price': float(trade.get('price', 0)),
                    'size': float(trade.get('size', 0)),
                    'timestamp': trade.get('timestamp')
                }
            elif trade.get('side') == 'SELL' and cache_key in self.position_cache:
                # Position closed or reduced
                entry_size = self.position_cache[cache_key]['size']
                exit_size = float(trade.get('size', 0))
                
                if exit_size >= entry_size:
                    # Position fully closed
                    del self.position_cache[cache_key]
                else:
                    # Position reduced
                    self.position_cache[cache_key]['size'] -= exit_size
        
        except Exception as e:
            print(f"Error updating position cache: {e}")
