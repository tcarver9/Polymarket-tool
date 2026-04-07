# alerting.py
# Simple alerting wrapper using Discord webhook (or extend to Slack/Email).

import requests
import logging
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class AlertManager:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_alert(self, title: str, message: str, severity: str = "WARNING", details: Optional[Dict] = None) -> bool:
        """Send a Discord embed alert."""
        if not self.webhook_url:
            logger.warning("No webhook URL configured for alerts.")
            return False

        color = {
            "INFO": 0x3498db,
            "WARNING": 0xffa500,
            "ERROR": 0xe74c3c,
            "CRITICAL": 0x8b0000
        }.get(severity, 0x3498db)

        embed = {
            "title": title,
            "description": message,
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "fields": []
        }

        if details:
            for k, v in details.items():
                embed["fields"].append({"name": str(k), "value": str(v), "inline": True})

        payload = {"embeds": [embed]}
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code == 204
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False

def main():
    am = AlertManager("https://discord.com/api/webhooks/your_webhook_url_here")
    am.send_alert(
        title="Polymarket Ingestion Lag",
        message="Ingestion lag detected: no new trades in last 5 minutes.",
        severity="WARNING",
        details={"lag_seconds": 320}
    )

if __name__ == "__main__":
    main()
