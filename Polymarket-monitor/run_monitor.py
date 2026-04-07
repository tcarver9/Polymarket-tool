# run_monitor.py
from polymarket_monitor import PolymarketMonitor
from alerting import AlertNotifier
from config import DEFAULT_CONFIG, DISCORD_CONFIG, EMAIL_CONFIG
import time
from collections import defaultdict
from typing import Dict

def main():
    print("="*80)
    print("🔍 POLYMARKET INSIDER TRADING MONITOR")
    print("="*80)
    print()
    
    # Display configuration
    print("📊 Configuration:")
    print(f"   Fresh wallet threshold: ≤{DEFAULT_CONFIG['max_trades_fresh_wallet']} trades")
    print(f"   Minimum bet size: ${DEFAULT_CONFIG['min_bet_size_fresh_wallet']:,}")
    print(f"   Large bet threshold: {DEFAULT_CONFIG['bet_to_volume_threshold']}% of market volume")
    print(f"   Scan interval: Every 5 minutes")
    print()
    
    print("🔔 Notifications:")
    if DISCORD_CONFIG.get('enabled'):
        print(f"   ✅ Discord enabled (severity: {', '.join(DISCORD_CONFIG['notify_on'])})")
    else:
        print("   ❌ Discord disabled")
    
    if EMAIL_CONFIG.get('enabled'):
        print(f"   ✅ Email enabled (severity: {', '.join(EMAIL_CONFIG['notify_on'])})")
        print(f"   📧 Sending to: {EMAIL_CONFIG['to']}")
    else:
        print("   ❌ Email disabled")
    print()
    print("="*80)
    print()
    
    # Initialize monitor and notifier
    monitor = PolymarketMonitor(DEFAULT_CONFIG)
    notifier = AlertNotifier(
        email_config=EMAIL_CONFIG,
        discord_config=DISCORD_CONFIG
    )
    
    scan_count = 0
    
    print("🚀 Starting continuous monitoring...")
    print("   Press Ctrl+C to stop")
    print()
    
    while True:
        try:
            scan_count += 1
            print(f"[Scan #{scan_count}] {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Run scan
            alerts = monitor.scan()
            
            # Send notifications
            if alerts:
                notifier.send_alerts(alerts)
                print(f"   📤 Sent {len(alerts)} alert(s) via configured channels")
            
            print(f"   ⏰ Next scan in 5 minutes...")
            print()
            
            time.sleep(300)  # 5 minutes
            
        except KeyboardInterrupt:
            print("\n⚠️  Stopping monitor...")
            print(f"   Total scans performed: {scan_count}")
            print(f"   Total alerts generated: {len(monitor.alerts)}")
            
            # Export alerts before exit
            if monitor.alerts:
                filename = f"polymarket_alerts_{time.strftime('%Y%m%d_%H%M%S')}.json"
                monitor.export_alerts(filename)
                print(f"   💾 Alerts exported to {filename}")
            
            print("\n✅ Shutdown complete")
            break
            
        except Exception as e:
            print(f"❌ Error in main loop: {e}")
            print("   Retrying in 60 seconds...")
            time.sleep(60)

if __name__ == "__main__":
    main()

