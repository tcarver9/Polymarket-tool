# run_with_notifications.py
from polymarket_monitor import PolymarketMonitor
from alerting import AlertNotifier
from config import DEFAULT_CONFIG
from time import time, sleep

def main():
    config = DEFAULT_CONFIG.copy()
    monitor = PolymarketMonitor(config)
    
    # Setup notifications (optional)
    notifier = AlertNotifier(
        discord_webhook="YOUR_DISCORD_WEBHOOK_URL"  # Optional
    )
    
    print("Starting monitor with notifications...")
    
    while True:
        try:
            alerts = monitor.scan()
            
            # Send notifications for high-severity alerts
            high_alerts = [a for a in alerts if a.severity == 'high']
            if high_alerts:
                notifier.send_discord_alert(high_alerts)
            
            time.sleep(300)  # 5 minutes
            
        except KeyboardInterrupt:
            monitor.export_alerts()
            break

if __name__ == "__main__":
    main()
