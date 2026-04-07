# polymarket_monitor.py
import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
from dataclasses import dataclass
from collections import defaultdict

@dataclass
class Alert:
    severity: str  # 'high', 'medium', 'low'
    alert_type: str
    description: str
    wallet_address: str
    market_id: str
    timestamp: datetime
    bet_amount: float
    additional_data: Dict

class PolymarketMonitor:
    def __init__(self, config: Dict):
        self.config = config
        self.base_url = "https://clob.polymarket.com"
        self.gamma_url = "https://gamma-api.polymarket.com"
        self.alerts = []
        self.wallet_history = defaultdict(list)
        self.market_cache = {}
        self.whale_wallets = set()  # Track identified whales
        self.coordinated_groups = defaultdict(list)  # Track coordinated trading

    def get_recent_trades(self, lookback_minutes: int = 10) -> List[Dict]:
        """Fetch recent trades from Polymarket"""
        try:
            # Get active markets
            markets_response = requests.get(
                f"{self.gamma_url}/markets",
                params={"active": "true", "closed": "false"}
            )
            markets = markets_response.json()
            
            all_trades = []
            for market in markets[:50]:  # Limit to top 50 markets
                market_id = market.get('id') or market.get('conditionId')
                if not market_id:
                    continue
                    
                # Get trades for this market
                trades_response = requests.get(
                    f"{self.base_url}/trades",
                    params={
                        "market": market_id,
                        "limit": 100
                    }
                )
                
                if trades_response.status_code == 200:
                    trades = trades_response.json()
                    for trade in trades:
                        trade['market_info'] = market
                        all_trades.append(trade)
                        
                time.sleep(0.1)  # Rate limiting
                
            return all_trades
            
        except Exception as e:
            print(f"Error fetching trades: {e}")
            return []
    
    def get_wallet_history(self, wallet_address: str) -> List[Dict]:
        """Get trading history for a specific wallet"""
        try:
            response = requests.get(
                f"{self.base_url}/trades",
                params={
                    "maker": wallet_address,
                    "limit": 1000
                }
            )
            
            if response.status_code == 200:
                return response.json()
            return []
            
        except Exception as e:
            print(f"Error fetching wallet history: {e}")
            return []
    
    def analyze_fresh_wallet(self, trade: Dict) -> Optional[Alert]:
        """Detect wallets with no/minimal history making large bets"""
        wallet = trade.get('maker_address')
        bet_size = float(trade.get('size', 0))
        
        # Skip small bets
        if bet_size < self.config['min_bet_size_fresh_wallet']:
            return None
        
        # Check if we've analyzed this wallet recently
        if wallet in self.wallet_history:
            return None
            
        # Fetch wallet history
        history = self.get_wallet_history(wallet)
        self.wallet_history[wallet] = history
        
        # Fresh wallet criteria
        total_trades = len(history)
        wallet_age_trades = total_trades
        
        if wallet_age_trades <= self.config['max_trades_fresh_wallet']:
            # Calculate total volume
            total_volume = sum(float(h.get('size', 0)) for h in history)
            
            return Alert(
                severity='high' if bet_size > 10000 else 'medium',
                alert_type='FRESH_WALLET',
                description=f"Fresh wallet (only {wallet_age_trades} trades) placed ${bet_size:.2f} bet",
                wallet_address=wallet,
                market_id=trade.get('market'),
                timestamp=datetime.now(),
                bet_amount=bet_size,
                additional_data={
                    'total_trades': total_trades,
                    'total_volume': total_volume,
                    'first_trade_size': bet_size
                }
            )
        
        return None
        
    def analyze_abnormal_bet_size(self, trade: Dict) -> Optional[Alert]:
        """Detect abnormally large bets relative to market volume"""
        bet_size = float(trade.get('size', 0))
        market_info = trade.get('market_info', {})
        market_volume = float(market_info.get('volume', 0))
        
        if market_volume == 0:
            return None
        
        # Calculate bet as percentage of market volume
        bet_percentage = (bet_size / market_volume) * 100
        
        # Alert if bet is significant portion of market
        if bet_percentage > self.config['bet_to_volume_threshold']:
            return Alert(
                severity='high' if bet_percentage > 10 else 'medium',
                alert_type='LARGE_BET',
                description=f"Large bet: ${bet_size:.2f} ({bet_percentage:.2f}% of market volume)",
                wallet_address=trade.get('maker_address'),
                market_id=trade.get('market'),
                timestamp=datetime.now(),
                bet_amount=bet_size,
                additional_data={
                    'market_volume': market_volume,
                    'bet_percentage': bet_percentage,
                    'market_title': market_info.get('question', 'Unknown')
                }
            )
        
        return None
    
    def analyze_tight_market_activity(self, trade: Dict) -> Optional[Alert]:
        """Detect repeated entries into tight/political markets"""
        wallet = trade.get('maker_address')
        market_info = trade.get('market_info', {})
        market_id = trade.get('market')
        
        # Check if it's a political market
        market_title = market_info.get('question', '').lower()
        tags = [tag.lower() for tag in market_info.get('tags', [])]
        
        political_keywords = ['election', 'president', 'senate', 'congress', 
                             'trump', 'biden', 'politics', 'vote', 'poll']
        
        is_political = any(keyword in market_title for keyword in political_keywords) or \
                      'politics' in tags
        
        if not is_political:
            return None
        
        # Get wallet's recent trades
        wallet_trades = self.wallet_history.get(wallet, [])
        if not wallet_trades:
            wallet_trades = self.get_wallet_history(wallet)
            self.wallet_history[wallet] = wallet_trades
        
        # Count trades in this specific market
        market_trades = [t for t in wallet_trades if t.get('market') == market_id]
        
        if len(market_trades) >= self.config['repeated_market_entries']:
            total_position = sum(float(t.get('size', 0)) for t in market_trades)
            
            return Alert(
                severity='high',
                alert_type='REPEATED_POLITICAL_ENTRY',
                description=f"Wallet made {len(market_trades)} trades in political market (${total_position:.2f} total)",
                wallet_address=wallet,
                market_id=market_id,
                timestamp=datetime.now(),
                bet_amount=float(trade.get('size', 0)),
                additional_data={
                    'market_title': market_info.get('question'),
                    'total_entries': len(market_trades),
                    'total_position': total_position,
                    'tags': market_info.get('tags', [])
                }
            )
        
        return None
    
        # ADD THIS NEW METHOD
    def analyze_timing_patterns(self, trade: Dict) -> Optional[Alert]:
        """Detect suspicious timing patterns"""
        from datetime import datetime
        
        trade_time = datetime.fromisoformat(trade.get('timestamp', datetime.now().isoformat()))
        hour = trade_time.hour
        
        # Night trading detection
        if (hour >= self.config['night_trading_start_hour'] or 
            hour <= self.config['night_trading_end_hour']):
            
            bet_size = float(trade.get('size', 0))
            if bet_size > 2000:  # Significant bet at unusual hour
                return Alert(
                    severity='medium',
                    alert_type='NIGHT_TRADING',
                    description=f"Large bet (${bet_size:.2f}) placed at unusual hour ({hour}:00)",
                    wallet_address=trade.get('maker_address'),
                    market_id=trade.get('market'),
                    timestamp=datetime.now(),
                    bet_amount=bet_size,
                    additional_data={
                        'trade_hour': hour,
                        'is_overnight': True
                    }
                )
        
        return None
    
    # ADD THIS NEW METHOD
    def analyze_win_rate(self, trade: Dict) -> Optional[Alert]:
        """Track wallet win rates to detect potential insider trading"""
        wallet = trade.get('maker_address')
        
        # Get wallet's historical trades
        history = self.wallet_history.get(wallet, [])
        if not history or len(history) < self.config['min_trades_for_win_rate']:
            return None
        
        # Calculate wins (simplified - you'd need to track actual outcomes)
        # This is a placeholder - real implementation would need market resolution data
        winning_trades = sum(1 for t in history if self._is_winning_position(t))
        win_rate = winning_trades / len(history)
        
        if win_rate >= self.config['suspicious_win_rate_threshold']:
            return Alert(
                severity='high',
                alert_type='SUSPICIOUS_WIN_RATE',
                description=f"Wallet has unusually high win rate: {win_rate*100:.1f}% ({winning_trades}/{len(history)} trades)",
                wallet_address=wallet,
                market_id=trade.get('market'),
                timestamp=datetime.now(),
                bet_amount=float(trade.get('size', 0)),
                additional_data={
                    'win_rate': win_rate,
                    'total_trades': len(history),
                    'winning_trades': winning_trades
                }
            )
        
        return None
    
    # ADD THIS NEW METHOD
    def analyze_coordinated_trading(self, trades: List[Dict]) -> List[Alert]:
        """Detect multiple wallets trading together (potential coordination)"""
        alerts = []
        
        # Group trades by market and time window
        market_trades = defaultdict(list)
        for trade in trades:
            market_id = trade.get('market')
            timestamp = trade.get('timestamp')
            market_trades[market_id].append(trade)
        
        # Check each market for coordinated activity
        for market_id, market_trade_list in market_trades.items():
            if len(market_trade_list) < 3:  # Need at least 3 trades
                continue
            
            # Sort by time
            sorted_trades = sorted(market_trade_list, 
                                 key=lambda x: x.get('timestamp', ''))
            
            # Check for multiple large bets within short window
            window_trades = []
            for i, trade in enumerate(sorted_trades):
                if float(trade.get('size', 0)) > 1000:  # Significant bets only
                    window_trades.append(trade)
                    
                    # Check if we have 3+ bets within 60 seconds
                    if len(window_trades) >= 3:
                        unique_wallets = set(t.get('maker_address') for t in window_trades)
                        
                        if len(unique_wallets) >= 3:  # Different wallets
                            total_volume = sum(float(t.get('size', 0)) for t in window_trades)
                            
                            alerts.append(Alert(
                                severity='critical',
                                alert_type='COORDINATED_TRADING',
                                description=f"{len(unique_wallets)} wallets placed ${total_volume:.2f} in coordinated trades",
                                wallet_address=", ".join(list(unique_wallets)[:3]),
                                market_id=market_id,
                                timestamp=datetime.now(),
                                bet_amount=total_volume,
                                additional_data={
                                    'num_wallets': len(unique_wallets),
                                    'num_trades': len(window_trades),
                                    'total_volume': total_volume,
                                    'time_window_seconds': 60
                                }
                            ))
                            break
        
        return alerts
    
    # ADD THIS NEW METHOD
    def analyze_whale_activity(self, trade: Dict) -> Optional[Alert]:
        """Track and flag whale wallet activity"""
        wallet = trade.get('maker_address')
        bet_size = float(trade.get('size', 0))
        
        # Check if this is a whale bet
        if bet_size >= self.config.get('whale_threshold', 50000):
            
            # Check if this is a known whale
            is_known_whale = wallet in self.whale_wallets
            
            if not is_known_whale:
                self.whale_wallets.add(wallet)
            
            return Alert(
                severity='critical',
                alert_type='WHALE_BET',
                description=f"{'Known whale' if is_known_whale else 'New whale'} placed ${bet_size:,.2f} bet",
                wallet_address=wallet,
                market_id=trade.get('market'),
                timestamp=datetime.now(),
                bet_amount=bet_size,
                additional_data={
                    'is_known_whale': is_known_whale,
                    'bet_amount': bet_size,
                    'market_title': trade.get('market_info', {}).get('question', 'Unknown')
                }
            )
        
        return None
    
    # ADD THIS NEW METHOD
    def analyze_category_specific(self, trade: Dict) -> Optional[Alert]:
        """Apply category-specific detection rules"""
        from config import MONITORED_CATEGORIES
        
        market_info = trade.get('market_info', {})
        market_title = market_info.get('question', '').lower()
        tags = [tag.lower() for tag in market_info.get('tags', [])]
        bet_size = float(trade.get('size', 0))
        
        # Check each category
        for category_name, category_config in MONITORED_CATEGORIES.items():
            if not category_config['enabled']:
                continue
            
            # Check if market matches this category
            matches_category = any(
                keyword in market_title or keyword in ' '.join(tags)
                for keyword in category_config['keywords']
            )
            
            if matches_category and bet_size >= category_config['min_bet_threshold']:
                return Alert(
                    severity='high',
                    alert_type=f'LARGE_{category_name.upper()}_BET',
                    description=f"Large ${bet_size:,.2f} bet in {category_name} market",
                    wallet_address=trade.get('maker_address'),
                    market_id=trade.get('market'),
                    timestamp=datetime.now(),
                    bet_amount=bet_size,
                    additional_data={
                        'category': category_name,
                        'market_title': market_info.get('question'),
                        'threshold': category_config['min_bet_threshold']
                    }
                )
        
        return None

# UPDATE THE analyze_trade METHOD to include new analyzers
    def analyze_trade(self, trade: Dict) -> List[Alert]:
        """Run all analysis functions on a trade"""
        alerts = []
        
        # Run each analyzer
        analyzers = [
            self.analyze_fresh_wallet,
            self.analyze_abnormal_bet_size,
            self.analyze_tight_market_activity,
            self.analyze_timing_patterns,  # NEW
            self.analyze_win_rate,  # NEW
            self.analyze_whale_activity,  # NEW
            self.analyze_category_specific,  # NEW
        ]
        
        for analyzer in analyzers:
            try:
                alert = analyzer(trade)
                if alert:
                    alerts.append(alert)
            except Exception as e:
                print(f"Error in analyzer {analyzer.__name__}: {e}")
        
        return alerts
       
       # HELPER METHOD (placeholder)
    def _is_winning_position(self, trade: Dict) -> bool:
        """
        Determine if a trade was profitable
        NOTE: This requires market resolution data from Polymarket API
        For now, returns random for demonstration
        """
        # TODO: Implement actual win/loss tracking using market outcomes
        import random
        return random.random() > 0.5  # Placeholder

       # UPDATE scan method to include coordinated trading detection
    def scan(self):
        """Main scanning loop"""
        print(f"[{datetime.now()}] Starting scan...")
        
        trades = self.get_recent_trades(
            lookback_minutes=self.config['lookback_window_minutes']
        )
        
        print(f"Found {len(trades)} recent trades")
        
        new_alerts = []
        
        # Individual trade analysis
        for trade in trades:
            alerts = self.analyze_trade(trade)
            new_alerts.extend(alerts)
        
        # Group analysis (coordinated trading)
        coordinated_alerts = self.analyze_coordinated_trading(trades)
        new_alerts.extend(coordinated_alerts)
        
        # Add to alert history
        self.alerts.extend(new_alerts)
        
        # Display new alerts
        if new_alerts:
            print(f"\n{'='*80}")
            print(f"🚨 {len(new_alerts)} NEW ALERTS DETECTED")
            print(f"{'='*80}\n")
            
            for alert in new_alerts:
                self.display_alert(alert)
        else:
            print("No suspicious activity detected")
        
        return new_alerts
    
    def display_alert(self, alert: Alert):
        """Display alert in formatted way"""
        severity_emoji = {
            'high': '🔴',
            'medium': '🟡',
            'low': '🟢'
        }
        
        print(f"{severity_emoji[alert.severity]} {alert.severity.upper()} - {alert.alert_type}")
        print(f"   {alert.description}")
        print(f"   Wallet: {alert.wallet_address[:8]}...{alert.wallet_address[-6:]}")
        print(f"   Market: {alert.market_id}")
        print(f"   Amount: ${alert.bet_amount:.2f}")
        print(f"   Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if alert.additional_data:
            print(f"   Additional Info:")
            for key, value in alert.additional_data.items():
                print(f"      {key}: {value}")
        
        print()
    
    def run_continuous(self, interval_seconds: int = 300):
        """Run continuous monitoring"""
        print("Starting Polymarket Insider Monitor")
        print(f"Scan interval: {interval_seconds} seconds")
        print(f"Configuration: {json.dumps(self.config, indent=2)}\n")
        
        while True:
            try:
                self.scan()
                print(f"Next scan in {interval_seconds} seconds...\n")
                time.sleep(interval_seconds)
                
            except KeyboardInterrupt:
                print("\nStopping monitor...")
                break
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(60)  # Wait before retrying
    
    def export_alerts(self, filename: str = "alerts.json"):
        """Export alerts to JSON file"""
        alerts_data = []
        for alert in self.alerts:
            alerts_data.append({
                'severity': alert.severity,
                'type': alert.alert_type,
                'description': alert.description,
                'wallet': alert.wallet_address,
                'market_id': alert.market_id,
                'timestamp': alert.timestamp.isoformat(),
                'bet_amount': alert.bet_amount,
                'additional_data': alert.additional_data
            })
        
        with open(filename, 'w') as f:
            json.dump(alerts_data, f, indent=2)
        
        print(f"Exported {len(alerts_data)} alerts to {filename}")
