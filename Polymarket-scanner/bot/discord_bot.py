# bot/discord_bot.py

import discord
from discord.ext import commands
import aiohttp
import os
from typing import List, Optional
from datetime import datetime, timezone
from collections import defaultdict
import asyncio

from core.opportunity_detection import Opportunity

class DiscordNotifier:
    """Handles both webhook and bot notifications"""
    
    def __init__(self, webhook_url: Optional[str] = None, 
                 bot_token: Optional[str] = None,
                 channel_id: Optional[int] = None):
        self.webhook_url = webhook_url
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.use_webhook = webhook_url is not None
        self.bot = None
        
        if bot_token and not webhook_url:
            self._setup_bot()
    
    def _setup_bot(self):
        """Setup Discord bot if using bot method"""
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix='!', intents=intents)
        
        @self.bot.event
        async def on_ready():
            print(f'Discord bot {self.bot.user} is ready!')
        
        @self.bot.command(name='stats')
        async def show_stats(ctx):
            """Show scanner statistics"""
            embed = discord.Embed(
                title="📊 Scanner Statistics",
                description="Statistics will be implemented",
                color=discord.Color.purple()
            )
            await ctx.send(embed=embed)
        
        @self.bot.command(name='shadow')
        async def toggle_shadow(ctx):
            """Toggle shadow mode"""
            await ctx.send("Shadow mode toggle - implement this in main scanner")
    
    async def start_bot(self):
        """Start the Discord bot"""
        if self.bot:
            await self.bot.start(self.bot_token)
    
    async def send_opportunities(self, opportunities: List['Opportunity']):
        """Send opportunities via webhook or bot"""
        if not opportunities:
            print("⚠ No opportunities to send to Discord")
            return
            
        print(f"📤 Preparing to send {len(opportunities)} opportunities to Discord...")
        
        if self.use_webhook:
            print(f"  Using webhook method (webhook_url={'set' if self.webhook_url else 'NOT SET'})")
            await self._send_via_webhook(opportunities)
        elif self.bot and self.channel_id:
            print(f"  Using bot method (channel_id={self.channel_id})")
            await self._send_via_bot(opportunities)
        else:
            print("❌ No valid Discord notification method configured!")
            print(f"   use_webhook={self.use_webhook}, webhook_url={'set' if self.webhook_url else 'NOT SET'}")
            print(f"   bot={'set' if self.bot else 'NOT SET'}, channel_id={self.channel_id}")
    
    async def _send_via_webhook(self, opportunities: List['Opportunity']):
        """Send alerts using Discord webhook (simpler, no bot needed)"""
        if not self.webhook_url:
            return
        
        # Group by engine
        grouped = defaultdict(list)
        for opp in opportunities:
            grouped[opp.engine].append(opp)
        
        async with aiohttp.ClientSession() as session:
            for engine, opps in grouped.items():
                # Split into chunks of 20 (max per embed)
                max_per_embed = 20
                for chunk_start in range(0, len(opps), max_per_embed):
                    chunk = opps[chunk_start:chunk_start + max_per_embed]
                    embed_dict = self._create_embed_dict(engine, chunk)
                    
                    payload = {
                        "embeds": [embed_dict]
                    }
                    
                    try:
                        async with session.post(self.webhook_url, json=payload) as resp:
                            # Discord webhooks return 204 (No Content) on success, sometimes 200
                            if resp.status in (200, 204):
                                print(f"✓ Sent {len(chunk)} {engine} opportunities via webhook (chunk {chunk_start//max_per_embed + 1})")
                            else:
                                print(f"✗ Webhook failed with status {resp.status}")
                                error_text = await resp.text()
                                print(f"Error response: {error_text[:500]}")
                                # Print the webhook URL (partially masked for security)
                                if self.webhook_url:
                                    masked_url = self.webhook_url[:50] + "..." if len(self.webhook_url) > 50 else self.webhook_url
                                    print(f"Webhook URL: {masked_url}")
                    except Exception as e:
                        print(f"❌ Exception sending webhook: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    # Rate limit: Discord allows 30 requests per minute per webhook
                    await asyncio.sleep(2)
    
    async def _send_via_bot(self, opportunities: List['Opportunity']):
        """Send alerts using Discord bot"""
        if not self.bot or not self.channel_id:
            return
        
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            print(f"Channel {self.channel_id} not found")
            return
        
        grouped = defaultdict(list)
        for opp in opportunities:
            grouped[opp.engine].append(opp)
        
        for engine, opps in grouped.items():
            # Split into chunks of 20 (max per embed)
            max_per_embed = 20
            for chunk_start in range(0, len(opps), max_per_embed):
                chunk = opps[chunk_start:chunk_start + max_per_embed]
                embed = self._create_embed(engine, chunk)
                await channel.send(embed=embed)
                await asyncio.sleep(1)
    
    def _create_embed_dict(self, engine: str, opportunities: List['Opportunity']) -> dict:
        """Create embed dictionary for webhook"""
        color_map = {
            "model": 0x3498db,  # Blue
            "cross_market": 0xf1c40f,  # Gold
            "market_making": 0x2ecc71  # Green
        }
        
        title_map = {
            "model": "🎯 Model Mispricing Opportunities",
            "cross_market": "⚡ Cross-Market Arbitrage",
            "market_making": "💹 Market Making Opportunities"
        }
        
        embed = {
            "title": title_map.get(engine, "Opportunities"),
            "color": color_map.get(engine, 0x3498db),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [],
            "footer": {
                "text": "Polymarket Scanner"
            }
        }
        
        # Discord embeds have a 6000 character limit total
        # We'll limit to 5-8 opportunities per embed to stay under the limit
        # If there are more, we'll send multiple messages
        max_per_embed = 8
        for i, opp in enumerate(opportunities[:max_per_embed], 1):
            field_name = f"#{i} - Score: {opp.score:.2f}"
            
            question = opp.metadata.get('question', opp.market_id)
            if len(question) > 100:
                question = question[:97] + "..."
            
            # Shorter field value to stay under Discord's 6000 character limit
            question = opp.metadata.get('question', opp.market_id)
            if len(question) > 60:
                question = question[:57] + "..."
            
            field_value = (
                f"**{question}**\n"
                f"**Direction:** `{opp.direction}` | "
                f"**Edge:** {opp.net_edge*100:.2f}% | "
                f"**Confidence:** {opp.confidence*100:.0f}%\n"
                f"**Entry:** ${opp.entry_price:.4f} → **Exit:** ${opp.exit_price:.4f} | "
                f"**Size:** ${opp.fillable_size:.0f}\n"
            )
            
            if engine == "model":
                field_value += f"Model Prob: {opp.metadata.get('model_prob', 0)*100:.1f}% | "
                field_value += f"Spread: {opp.metadata.get('spread_bps', 0):.0f}bps\n"
            elif engine == "cross_market":
                field_value += f"Type: {opp.metadata.get('type', 'unknown')}\n"
            
            field_value += f"[View Market](https://polymarket.com/event/{opp.market_id})"
            
            embed["fields"].append({
                "name": field_name,
                "value": field_value,
                "inline": False
            })
        
        return embed
    
    def _create_embed(self, engine: str, opportunities: List['Opportunity']) -> discord.Embed:
        """Create Discord embed for bot method"""
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
            timestamp=datetime.now(timezone.utc)
        )
        
        # Discord embeds have a 6000 character limit total
        # We'll limit to 5-8 opportunities per embed to stay under the limit
        # If there are more, we'll send multiple messages
        max_per_embed = 8
        for i, opp in enumerate(opportunities[:max_per_embed], 1):
            field_name = f"#{i} - Score: {opp.score:.2f}"
            
            question = opp.metadata.get('question', opp.market_id)
            if len(question) > 100:
                question = question[:97] + "..."
            
            # Shorter field value to stay under Discord's 6000 character limit
            question = opp.metadata.get('question', opp.market_id)
            if len(question) > 60:
                question = question[:57] + "..."
            
            field_value = (
                f"**{question}**\n"
                f"**Direction:** `{opp.direction}` | "
                f"**Edge:** {opp.net_edge*100:.2f}% | "
                f"**Confidence:** {opp.confidence*100:.0f}%\n"
                f"**Entry:** ${opp.entry_price:.4f} → **Exit:** ${opp.exit_price:.4f} | "
                f"**Size:** ${opp.fillable_size:.0f}\n"
            )
            
            if engine == "model":
                field_value += f"Model Prob: {opp.metadata.get('model_prob', 0)*100:.1f}% | "
                field_value += f"Spread: {opp.metadata.get('spread_bps', 0):.0f}bps\n"
            elif engine == "cross_market":
                field_value += f"Type: {opp.metadata.get('type', 'unknown')}\n"
            
            field_value += f"[View Market](https://polymarket.com/event/{opp.market_id})"
            
            embed.add_field(
                name=field_name,
                value=field_value,
                inline=False
            )
        
        return embed
