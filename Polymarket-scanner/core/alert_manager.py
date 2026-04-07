import discord
from discord.ext import commands
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, TYPE_CHECKING

from core.opportunity_detection import Opportunity

class AlertManager:
    def __init__(self, 
                 top_n_alerts: int = 5,
                 alert_interval_seconds: int = 60,
                 min_score_threshold: float = 10.0):
        self.top_n_alerts = top_n_alerts
        self.alert_interval = timedelta(seconds=alert_interval_seconds)
        self.min_score_threshold = min_score_threshold
        self.last_alerts: Dict[str, datetime] = {}
        self.alert_history: List['Opportunity'] = []
        # Track opportunities that have been sent to Discord (prevent duplicates for 24 hours)
        self.sent_opportunities: Dict[tuple, datetime] = {}  # Dict of (market_id, direction) -> last sent time
        self.duplicate_prevention_hours = 24  # Don't send same opportunity again for 24 hours
    
    def should_alert(self, opp: 'Opportunity') -> bool:
        """
        Decide if we should alert on this opportunity
        """
        # Score threshold
        if opp.score < self.min_score_threshold:
            return False
        
        # Check if we've already sent this opportunity recently (within 24 hours)
        # Use market_id + direction to identify unique opportunities
        opp_key = (opp.market_id, opp.direction)
        if opp_key in self.sent_opportunities:
            time_since_sent = datetime.now(timezone.utc) - self.sent_opportunities[opp_key]
            hours_since_sent = time_since_sent.total_seconds() / 3600
            if hours_since_sent < self.duplicate_prevention_hours:
                return False  # Already sent within last 24 hours, don't send again
        
        # Cooldown check (for same market+direction within alert_interval)
        key = f"{opp.market_id}_{opp.direction}"
        if key in self.last_alerts:
            time_since_last = datetime.now(timezone.utc) - self.last_alerts[key]
            if time_since_last < self.alert_interval:
                return False
        
        return True
    
    def select_top_opportunities(self, opportunities: List['Opportunity']) -> List['Opportunity']:
        """
        Select top N opportunities to alert on
        """
        if not opportunities:
            return []
        
        # Debug: show why opportunities are being filtered
        filtered = []
        filtered_out = {'low_score': 0, 'cooldown': 0, 'already_sent': 0}
        
        for opp in opportunities:
            if self.should_alert(opp):
                filtered.append(opp)
            else:
                # Track why it was filtered
                if opp.score < self.min_score_threshold:
                    filtered_out['low_score'] += 1
                else:
                    opp_key = (opp.market_id, opp.direction)
                    if opp_key in self.sent_opportunities:
                        filtered_out['already_sent'] += 1
                    else:
                        filtered_out['cooldown'] += 1
        
        if len(opportunities) > 0:
            print(f"    Filtered: {filtered_out['low_score']} low score, {filtered_out['cooldown']} cooldown, {filtered_out['already_sent']} already sent")
            print(f"    Passing filter: {len(filtered)} opportunities")
        
        if len(opportunities) > 0 and len(filtered) == 0:
            print(f"    ⚠ All {len(opportunities)} opportunities filtered out!")
            print(f"      Low score: {filtered_out['low_score']}, Cooldown: {filtered_out['cooldown']}, Already sent: {filtered_out['already_sent']}")
            if filtered_out['low_score'] > 0:
                sample_scores = [o.score for o in opportunities[:5]]
                print(f"      Sample scores: {sample_scores}")
        
        sorted_opps = sorted(filtered, key=lambda x: x.score, reverse=True)
        top = sorted_opps[:self.top_n_alerts]
        
        # Mark opportunities as sent (so we don't send them again for 24 hours)
        current_time = datetime.now(timezone.utc)
        for opp in top:
            # Mark as sent using market_id + direction (valid for 24 hours)
            opp_key = (opp.market_id, opp.direction)
            self.sent_opportunities[opp_key] = current_time
            
            # Clean up old entries (older than 24 hours) to prevent memory bloat
            keys_to_remove = [k for k, v in self.sent_opportunities.items() 
                            if (current_time - v).total_seconds() > self.duplicate_prevention_hours * 3600]
            for k in keys_to_remove:
                del self.sent_opportunities[k]
            
            # Also update last alert times for cooldown
            key = f"{opp.market_id}_{opp.direction}"
            self.last_alerts[key] = current_time
        
        return top
    
    def log_opportunity(self, opp: 'Opportunity'):
        """
        Log for shadow mode validation
        """
        self.alert_history.append(opp)

class PolymarketDiscordBot(commands.Bot):
    def __init__(self, alert_manager: AlertManager):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        self.alert_manager = alert_manager
        self.alert_channel_id = None  # Set this to your channel ID
    
    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
    
    async def send_opportunities(self, opportunities: List['Opportunity']):
        """
        Send formatted opportunity alerts to Discord
        """
        if not self.alert_channel_id:
            return
        
        channel = self.get_channel(self.alert_channel_id)
        if not channel:
            return
        
        # Group by engine type
        grouped = defaultdict(list)
        for opp in opportunities:
            grouped[opp.engine].append(opp)
        
        # Create embeds for each type
        for engine, opps in grouped.items():
            embed = self._create_embed(engine, opps)
            await channel.send(embed=embed)
    
    def _create_embed(self, engine: str, opportunities: List['Opportunity']) -> discord.Embed:
        """
        Create a Discord embed for opportunities
        """
        color_map = {
            "model": discord.Color.blue(),
            "cross_market": discord.Color.gold(),
            "market_making": discord.Color.green()
        }
        
        title_map = {
            "model": "🎯 Model Mispricing Opportunities",
            "cross_market": "⚡ Cross-Market Arbitrage",
            "market_making": "💹 Market Making Opportunities"
        }
        
        embed = discord.Embed(
            title=title_map.get(engine, "Opportunities"),
            color=color_map.get(engine, discord.Color.blue()),
            timestamp=datetime.utcnow()
        )
        
        for i, opp in enumerate(opportunities[:5], 1):
            field_name = f"#{i} - Score: {opp.score:.2f}"
            
            field_value = (
                f"**Market:** {opp.metadata.get('question', opp.market_id)[:100]}\n"
                f"**Direction:** {opp.direction}\n"
                f"**Entry:** ${opp.entry_price:.4f} → **Exit:** ${opp.exit_price:.4f}\n"
                f"**Net Edge:** {opp.net_edge*100:.2f}% ({opp.net_edge*10000:.0f} bps)\n"
                f"**Confidence:** {opp.confidence*100:.0f}%\n"
                f"**Fillable Size:** ${opp.fillable_size:.0f}\n"
            )
            
            if engine == "model":
                field_value += f"**Model Prob:** {opp.metadata.get('model_prob', 0)*100:.1f}%\n"
                field_value += f"**Spread:** {opp.metadata.get('spread_bps', 0):.0f} bps\n"
            elif engine == "cross_market":
                field_value += f"**Type:** {opp.metadata.get('type', 'unknown')}\n"
            
            field_value += f"[View Market](https://polymarket.com/event/{opp.market_id})"
            
            embed.add_field(
                name=field_name,
                value=field_value,
                inline=False
            )
        
        return embed
    
    @commands.command(name='stats')
    async def show_stats(self, ctx):
        """
        Show scanner statistics
        """
        total_alerts = len(self.alert_manager.alert_history)
        
        if total_alerts == 0:
            await ctx.send("No alerts yet!")
            return
        
        avg_score = sum(opp.score for opp in self.alert_manager.alert_history) / total_alerts
        
        engine_counts = defaultdict(int)
        for opp in self.alert_manager.alert_history:
            engine_counts[opp.engine] += 1
        
        embed = discord.Embed(
            title="📊 Scanner Statistics",
            color=discord.Color.purple()
        )
        embed.add_field(name="Total Alerts", value=str(total_alerts), inline=True)
        embed.add_field(name="Avg Score", value=f"{avg_score:.2f}", inline=True)
        
        for engine, count in engine_counts.items():
            embed.add_field(name=f"{engine.title()} Alerts", value=str(count), inline=True)
        
        await ctx.send(embed=embed)
