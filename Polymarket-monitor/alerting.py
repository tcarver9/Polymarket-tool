# alerting.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from typing import List
from datetime import datetime

class AlertNotifier:
    def __init__(self, email_config: dict = None, discord_config: dict = None):
        self.email_config = email_config if email_config and email_config.get('enabled') else None
        self.discord_config = discord_config if discord_config and discord_config.get('enabled') else None
    
    def should_notify(self, alert, config_notify_on):
        """Check if alert severity matches notification settings"""
        return alert.severity in config_notify_on
    
    def send_email_alert(self, alerts: List):
        """Send email notification"""
        if not self.email_config:
            return
        
        # Filter alerts based on email notification settings
        alerts_to_send = [a for a in alerts if self.should_notify(a, self.email_config['notify_on'])]
        
        if not alerts_to_send:
            return
        
        msg = MIMEMultipart('alternative')
        msg['From'] = self.email_config['from']
        msg['To'] = self.email_config['to']
        msg['Subject'] = f"🚨 Polymarket Alert: {len(alerts_to_send)} Suspicious Activities"
        
        # Create HTML email
        html_body = """
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                .alert { 
                    border: 1px solid #ddd; 
                    padding: 15px; 
                    margin: 10px 0; 
                    border-radius: 5px;
                }
                .high { border-left: 4px solid #dc3545; background-color: #f8d7da; }
                .medium { border-left: 4px solid #ffc107; background-color: #fff3cd; }
                .low { border-left: 4px solid #28a745; background-color: #d4edda; }
                .label { font-weight: bold; color: #333; }
                .value { color: #666; }
                .wallet { 
                    font-family: monospace; 
                    background: #f4f4f4; 
                    padding: 2px 5px;
                    border-radius: 3px;
                }
            </style>
        </head>
        <body>
            <h2>🔍 Polymarket Insider Trading Alert</h2>
            <p>Detected {} suspicious activities:</p>
        """.format(len(alerts_to_send))
        
        for alert in alerts_to_send:
            severity_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
            
            html_body += f"""
            <div class="alert {alert.severity}">
                <h3>{severity_emoji[alert.severity]} {alert.alert_type}</h3>
                <p><span class="label">Description:</span> {alert.description}</p>
                <p><span class="label">Wallet:</span> <span class="wallet">{alert.wallet_address}</span></p>
                <p><span class="label">Bet Amount:</span> ${alert.bet_amount:,.2f}</p>
                <p><span class="label">Time:</span> {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
            """
            
            if alert.additional_data:
                html_body += "<p><span class='label'>Additional Info:</span></p><ul>"
                for key, value in alert.additional_data.items():
                    html_body += f"<li><strong>{key}:</strong> {value}</li>"
                html_body += "</ul>"
            
            html_body += "</div>"
        
        html_body += """
            <hr>
            <p style="color: #888; font-size: 12px;">
                This is an automated alert from your Polymarket Monitor.
            </p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html_body, 'html'))
        
        try:
            server = smtplib.SMTP(self.email_config['smtp_server'], 
                                 self.email_config['smtp_port'])
            server.starttls()
            server.login(self.email_config['username'], 
                        self.email_config['password'])
            server.send_message(msg)
            server.quit()
            print(f"✅ Email alert sent to {self.email_config['to']}")
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
    
    def send_discord_alert(self, alerts: List):
        """Send Discord webhook notification"""
        if not self.discord_config:
            return
        
        # Filter alerts based on Discord notification settings
        alerts_to_send = [a for a in alerts if self.should_notify(a, self.discord_config['notify_on'])]
        
        if not alerts_to_send:
            return
        
        for alert in alerts_to_send:
            color_map = {'high': 15158332, 'medium': 16776960, 'low': 3066993}  # Red, Yellow, Green
            emoji_map = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
            
            # Create embed
            embed = {
                "title": f"{emoji_map[alert.severity]} {alert.alert_type}",
                "description": alert.description,
                "color": color_map.get(alert.severity, 3066993),
                "fields": [
                    {
                        "name": "💰 Bet Amount",
                        "value": f"${alert.bet_amount:,.2f}",
                        "inline": True
                    },
                    {
                        "name": "⚠️ Severity",
                        "value": alert.severity.upper(),
                        "inline": True
                    },
                    {
                        "name": "👛 Wallet",
                        "value": f"`{alert.wallet_address[:10]}...{alert.wallet_address[-8:]}`",
                        "inline": False
                    }
                ],
                "timestamp": alert.timestamp.isoformat(),
                "footer": {
                    "text": "Polymarket Insider Monitor"
                }
            }
            
            # Add additional data as fields
            if alert.additional_data:
                for key, value in list(alert.additional_data.items())[:3]:  # Limit to 3 extra fields
                    # Format value nicely
                    if isinstance(value, (int, float)):
                        if key.endswith('volume') or key.endswith('position'):
                            formatted_value = f"${value:,.2f}"
                        else:
                            formatted_value = f"{value:,.2f}"
                    else:
                        formatted_value = str(value)[:100]  # Truncate long strings
                    
                    embed["fields"].append({
                        "name": key.replace('_', ' ').title(),
                        "value": formatted_value,
                        "inline": True
                    })
            
            payload = {
                "embeds": [embed],
                "username": "Polymarket Monitor",
                "avatar_url": "https://polymarket.com/favicon.ico"
            }
            
            try:
                response = requests.post(self.discord_config['webhook_url'], json=payload)
                if response.status_code == 204:
                    print(f"✅ Discord alert sent: {alert.alert_type}")
                else:
                    print(f"❌ Discord webhook failed: {response.status_code}")
            except Exception as e:
                print(f"❌ Failed to send Discord alert: {e}")
    
    def send_alerts(self, alerts: List):
        """Send alerts via all enabled channels"""
        if not alerts:
            return
        
        if self.email_config:
            self.send_email_alert(alerts)
        
        if self.discord_config:
            self.send_discord_alert(alerts)

