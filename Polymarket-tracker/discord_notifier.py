import requests
from datetime import datetime
from typing import Dict, Optional

class DiscordNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        # Import here to avoid circular imports
        from config import ACCOUNT_USERNAMES
        self.account_usernames = ACCOUNT_USERNAMES
    
    def _get_username(self, account: str) -> str:
        """Get username from account address"""
        return self.account_usernames.get(account.lower(), account[:10] + "..." + account[-8:])
    
    def send_new_trade_notification(self, trade_data: Dict) -> bool:
        """Send notification when a new trade is detected"""
        try:
            account = trade_data.get('account', 'Unknown')
            username = self._get_username(account)
            market_name = trade_data.get('market_name', 'Unknown Market')
            market_url = trade_data.get('market_url')
            market_outcomes_display = trade_data.get('market_outcomes_display', '')
            side = trade_data.get('side', 'Unknown')
            outcome = trade_data.get('outcome', 'Unknown')
            size = trade_data.get('size', 0)
            price = trade_data.get('price', 0)
            timestamp = trade_data.get('timestamp', datetime.now().isoformat())
            
            # Determine color based on trade side
            color = 0x00FF00 if side.upper() == 'BUY' else 0xFF0000
            
            # Create title - make it clickable by setting url
            title = f"🔔 New Trade: {market_name[:80]}"
            if len(market_name) > 80:
                title = f"🔔 New Trade: {market_name[:77]}..."
            
            # Build market field value with outcomes
            market_value = market_name
            if market_outcomes_display:
                market_value = f"{market_name}\n\n{market_outcomes_display}"
            
            embed = {
                "title": title,
                "description": f"**{side.upper()}** {float(size):.2f} shares of **{outcome}** at ${float(price):.4f}",
                "color": color,
                "fields": [
                    {
                        "name": "👤 Trader",
                        "value": f"**{username}**\n`{account[:10]}...{account[-8:]}`",
                        "inline": True
                    },
                    {
                        "name": "📊 Market Details",
                        "value": market_value[:1024] if market_value else "Unknown Market",
                        "inline": False
                    },
                    {
                        "name": "📈 Action",
                        "value": f"**{side.upper()}** {outcome}",
                        "inline": True
                    },
                    {
                        "name": "💰 Size",
                        "value": f"{float(size):.2f} shares",
                        "inline": True
                    },
                    {
                        "name": "💵 Price",
                        "value": f"${float(price):.4f}",
                        "inline": True
                    },
                    {
                        "name": "💲 Total Value",
                        "value": f"${float(size) * float(price):.2f}",
                        "inline": True
                    },
                    {
                        "name": "🕐 Time",
                        "value": timestamp,
                        "inline": False
                    }
                ],
                "footer": {
                    "text": "Polymarket Trade Tracker"
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Remove None values
            embed = {k: v for k, v in embed.items() if v is not None}
            
            payload = {
                "embeds": [embed]
            }
            
            response = requests.post(self.webhook_url, json=payload)
            return response.status_code == 204
        
        except Exception as e:
            print(f"Error sending new trade notification: {e}")
            return False
    
    def send_trade_result_notification(self, result_data: Dict) -> bool:
        """Send notification when a trade is concluded with profit/loss"""
        try:
            account = result_data.get('account', 'Unknown')
            username = self._get_username(account)
            market_name = result_data.get('market_name', 'Unknown Market')
            market_url = result_data.get('market_url')
            market_outcomes_display = result_data.get('market_outcomes_display', '')
            profit_loss = result_data.get('profit_loss', 0)
            profit_loss_pct = result_data.get('profit_loss_pct', 0)
            entry_price = result_data.get('entry_price', 0)
            exit_price = result_data.get('exit_price', 0)
            size = result_data.get('size', 0)
            outcome = result_data.get('outcome', 'Unknown')
            
            # Determine color and emoji based on profit/loss
            if profit_loss > 0:
                color = 0x00FF00  # Green
                result_emoji = "📈"
                result_text = "PROFIT"
            elif profit_loss < 0:
                color = 0xFF0000  # Red
                result_emoji = "📉"
                result_text = "LOSS"
            else:
                color = 0xFFFF00  # Yellow
                result_emoji = "➖"
                result_text = "BREAK EVEN"
            
            # Build market field value with outcomes
            market_value = market_name
            if market_outcomes_display:
                market_value = f"{market_name}\n\n{market_outcomes_display}"
            
            # Create title
            title = f"{result_emoji} Trade Concluded - {result_text}: {market_name[:60]}"
            if len(market_name) > 60:
                title = f"{result_emoji} Trade Concluded - {result_text}: {market_name[:57]}..."
            
            embed = {
                "title": title,
                "description": f"Closed position on **{outcome}**",
                "color": color,
                "fields": [
                    {
                        "name": "👤 Trader",
                        "value": f"**{username}**\n`{account[:10]}...{account[-8:]}`",
                        "inline": True
                    },
                    {
                        "name": "📊 Market Details",
                        "value": market_value[:1024] if market_value else "Unknown Market",
                        "inline": False
                    },
                    {
                        "name": "🎯 Outcome",
                        "value": outcome,
                        "inline": True
                    },
                    {
                        "name": "💰 Size",
                        "value": f"{float(size):.2f} shares",
                        "inline": True
                    },
                    {
                        "name": "📥 Entry Price",
                        "value": f"${float(entry_price):.4f}",
                        "inline": True
                    },
                    {
                        "name": "📤 Exit Price",
                        "value": f"${float(exit_price):.4f}",
                        "inline": True
                    },
                    {
                        "name": f"{result_emoji} Profit/Loss",
                        "value": f"**${float(profit_loss):.2f}** ({float(profit_loss_pct):.2f}%)",
                        "inline": False
                    }
                ],
                "footer": {
                    "text": "Polymarket Trade Tracker"
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Remove None values
            embed = {k: v for k, v in embed.items() if v is not None}
            
            payload = {
                "embeds": [embed]
            }
            
            response = requests.post(self.webhook_url, json=payload)
            return response.status_code == 204
        
        except Exception as e:
            print(f"Error sending trade result notification: {e}")
            return False
    
    def send_error_notification(self, error_message: str) -> bool:
        """Send error notification"""
        try:
            embed = {
                "title": "⚠️ Bot Error",
                "description": error_message,
                "color": 0xFF0000,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            payload = {
                "embeds": [embed]
            }
            
            response = requests.post(self.webhook_url, json=payload)
            return response.status_code == 204
        
        except Exception as e:
            print(f"Error sending error notification: {e}")
            return False
