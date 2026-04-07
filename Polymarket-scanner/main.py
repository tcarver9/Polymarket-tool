# main.py

import asyncio
import os
import yaml
from dotenv import load_dotenv
from datetime import datetime, timezone
from typing import Optional

# Import all your modules
from models.probability_estimator import ProbabilityEstimator
from engines.model_mispricing import ModelMispricingEngine
from engines.cross_market import CrossMarketEngine
from engines.market_making import MarketMakingEngine
from engines.simple_arbitrage import SimpleArbitrageEngine
from market_manager import MarketDataManager
from core.alert_manager import AlertManager
from bot.discord_bot import DiscordNotifier

class PolymarketScanner:
    def __init__(self, config_path: str = "config.yaml"):
        # Load environment variables
        load_dotenv()
        
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Check if shadow mode from env overrides config
        shadow_mode_env = os.getenv('SHADOW_MODE', '').lower()
        if shadow_mode_env in ['true', 'false']:
            self.shadow_mode = shadow_mode_env == 'true'
        else:
            self.shadow_mode = self.config['scanner']['shadow_mode']
        
        print(f"{'='*60}")
        print(f"Polymarket Scanner Starting")
        print(f"Shadow Mode: {self.shadow_mode}")
        print(f"{'='*60}\n")
        
        # Initialize components
        self.market_data = MarketDataManager(
            gamma_api_key=os.getenv('GAMMA_API_KEY')
        )
        
        self.alert_manager = AlertManager(
            top_n_alerts=self.config['alert']['top_n'],
            alert_interval_seconds=self.config['alert']['interval_seconds'],
            min_score_threshold=self.config['alert']['min_score_threshold']
        )
        
        # Initialize Discord notifier
        webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        bot_token = os.getenv('DISCORD_BOT_TOKEN')
        channel_id = os.getenv('ALERT_CHANNEL_ID')
        
        use_webhook = self.config['alert'].get('use_webhook', True)
        
        if use_webhook and webhook_url:
            print("✓ Using Discord webhook for notifications")
            print(f"  Webhook URL: {webhook_url[:50]}..." if len(webhook_url) > 50 else f"  Webhook URL: {webhook_url}")
            self.discord_notifier = DiscordNotifier(webhook_url=webhook_url)
        elif bot_token and channel_id:
            print("✓ Using Discord bot for notifications")
            self.discord_notifier = DiscordNotifier(
                bot_token=bot_token,
                channel_id=int(channel_id)
            )
        else:
            print("⚠ No Discord notification method configured!")
            self.discord_notifier = None
        
        # Initialize probability estimator
        self.prob_estimator = ProbabilityEstimator()
        
        # Initialize engines based on config
        self.engines = []
        
        if self.config['model_engine']['enabled']:
            print("✓ Model Mispricing Engine enabled")
            self.engines.append(
                ModelMispricingEngine(
                    probability_estimator=self.prob_estimator,
                    min_edge_bps=self.config['model_engine']['min_edge_bps'],
                    min_liquidity=self.config['model_engine']['min_liquidity'],
                    max_spread_bps=self.config['model_engine']['max_spread_bps'],
                    min_confidence=self.config['model_engine']['min_confidence'],
                    max_staleness_hours=self.config['model_engine'].get('max_staleness_hours', 168)
                )
            )
        
        if self.config.get('cross_market_engine', {}).get('enabled', False):
            print("✓ Cross-Market Engine enabled")
            self.engines.append(
                CrossMarketEngine(
                    min_edge_bps=self.config['cross_market_engine']['min_edge_bps']
                )
            )
        
        if self.config.get('simple_arbitrage_engine', {}).get('enabled', False):
            print("✓ Simple Arbitrage Engine enabled")
            self.engines.append(
                SimpleArbitrageEngine(
                    min_edge_bps=self.config['simple_arbitrage_engine']['min_edge_bps']
                )
            )
        
        if self.config['market_making_engine']['enabled']:
            print("✓ Market Making Engine enabled")
            self.engines.append(
                MarketMakingEngine(
                    min_spread_bps=self.config['market_making_engine']['min_spread_bps'],
                    min_liquidity=self.config['market_making_engine']['min_liquidity'],
                    min_flow_balance=self.config['market_making_engine'].get('min_flow_balance', 0.0),
                    max_volatility=self.config['market_making_engine'].get('max_volatility', 1.0)
                )
            )
        
        self.scan_count = 0
        self.total_opportunities_found = 0
    
    async def start(self):
        """Start the scanner"""
        print(f"\n{'='*60}")
        print(f"Scanner initialized successfully!")
        print(f"Starting scan loop (every {self.config['scanner']['scan_interval_seconds']}s)")
        print(f"{'='*60}\n")
        
        # Start Discord bot in background if using bot method
        if self.discord_notifier and hasattr(self.discord_notifier, 'bot') and self.discord_notifier.bot:
            asyncio.create_task(self.discord_notifier.start_bot())
            await asyncio.sleep(3)  # Wait for bot to be ready
        
        # Main scanning loop
        while True:
            try:
                await self.scan_cycle()
            except KeyboardInterrupt:
                print("\n\nShutting down scanner...")
                break
            except Exception as e:
                print(f"❌ Error in scan cycle: {e}")
                import traceback
                traceback.print_exc()
            
            await asyncio.sleep(self.config['scanner']['scan_interval_seconds'])
    
    async def scan_cycle(self):
        """One complete scan cycle"""
        self.scan_count += 1
        cycle_start = datetime.now(timezone.utc)
        
        print(f"\n{'─'*60}")
        # Format datetime for display (remove timezone info for cleaner output)
        cycle_start_str = cycle_start.replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"Scan #{self.scan_count} - {cycle_start_str}")
        print(f"{'─'*60}")
        
        # Update market data
        print("Fetching market data...")
        await self.market_data.fetch_markets()
        print(f"✓ Loaded {len(self.market_data.markets)} active markets")
        
        if len(self.market_data.markets) == 0:
            print("⚠ WARNING: No markets loaded! Check date filters and API response.")
            return
        
        # Run all engines
        all_opportunities = []
        for engine in self.engines:
            engine_name = engine.__class__.__name__
            print(f"Running {engine_name}...")
            try:
                opps = await engine.scan(self.market_data)
                all_opportunities.extend(opps)
                print(f"  Found {len(opps)} opportunities")
                if len(opps) > 0:
                    print(f"    Sample scores: {[o.score for o in opps[:3]]}")
            except Exception as e:
                print(f"  ❌ Error: {e}")
                import traceback
                traceback.print_exc()
        
        self.total_opportunities_found += len(all_opportunities)
        
        # Select top opportunities
        print(f"\n🔍 Filtering opportunities...")
        print(f"  Before filtering: {len(all_opportunities)} opportunities")
        print(f"  Min score threshold: {self.alert_manager.min_score_threshold}")
        
        top_opportunities = self.alert_manager.select_top_opportunities(
            all_opportunities
        )
        
        # Log all opportunities (for shadow mode validation)
        for opp in top_opportunities:
            self.alert_manager.log_opportunity(opp)
        
        # Display results
        print(f"\n📊 Results:")
        print(f"  Total opportunities found: {len(all_opportunities)}")
        print(f"  Top opportunities selected: {len(top_opportunities)}")
        
        if len(all_opportunities) > 0 and len(top_opportunities) == 0:
            print(f"  ⚠ All opportunities were filtered out!")
            print(f"    Sample scores: {[o.score for o in all_opportunities[:5]]}")
            print(f"    Sample filtered reasons:")
            for opp in all_opportunities[:3]:
                if opp.score < self.alert_manager.min_score_threshold:
                    print(f"      - Score {opp.score:.2f} < threshold {self.alert_manager.min_score_threshold}")
                key = f"{opp.market_id}_{opp.direction}"
                if key in self.alert_manager.last_alerts:
                    time_since = (datetime.now(timezone.utc) - self.alert_manager.last_alerts[key]).total_seconds()
                    print(f"      - Cooldown: {time_since:.0f}s since last alert (need {self.alert_manager.alert_interval.total_seconds()}s)")
        
        if top_opportunities:
            print(f"\n🎯 Top Opportunities:")
            for i, opp in enumerate(top_opportunities, 1):
                print(f"  {i}. [{opp.engine}] {opp.metadata.get('question', '')[:60]}...")
                print(f"     Score: {opp.score:.2f}, Edge: {opp.net_edge*10000:.0f}bps, "
                      f"Confidence: {opp.confidence*100:.0f}%")
        
        # Send alerts
        if not self.shadow_mode and top_opportunities and self.discord_notifier:
            print(f"\n📤 Sending {len(top_opportunities)} alerts to Discord...")
            try:
                await self.discord_notifier.send_opportunities(top_opportunities)
                print("✓ Alerts sent successfully")
            except Exception as e:
                print(f"❌ Error sending alerts: {e}")
                import traceback
                traceback.print_exc()
        elif self.shadow_mode and top_opportunities:
            print(f"\n[SHADOW MODE] Would have sent {len(top_opportunities)} alerts")
        elif not self.shadow_mode and top_opportunities and not self.discord_notifier:
            print(f"\n⚠ Found {len(top_opportunities)} opportunities but Discord notifier is not configured!")
        elif not self.shadow_mode and not top_opportunities:
            print(f"\n[No opportunities to send]")
        
        cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        print(f"\n⏱  Cycle completed in {cycle_duration:.2f}s")
        print(f"📈 Total opportunities found: {self.total_opportunities_found}")

async def main():
    scanner = PolymarketScanner()
    await scanner.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Scanner stopped by user")


#py -m venv .venv
#.venv\Scripts\activate
#pip install -r requirements.txt