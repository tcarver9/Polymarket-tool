# models/probability_estimator.py

import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timedelta
import re
from collections import defaultdict
import aiohttp
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
import pickle

if TYPE_CHECKING:
    from market_manager import MarketMetadata, OrderBookSnapshot

@dataclass
class ProbabilityEstimate:
    probability: float
    confidence: float  # 0-1, how confident we are in this estimate
    method: str  # which method produced this
    inputs: Dict  # what data went into this
    staleness: float  # how old is our data (in hours)

class BaseModel:
    """Base class for all probability models"""
    
    def __init__(self):
        self.calibration_history = []
    
    async def estimate(self, market: 'MarketMetadata', 
                      orderbook: 'OrderBookSnapshot',
                      context: Dict) -> Optional[ProbabilityEstimate]:
        raise NotImplementedError
    
    def update_calibration(self, predicted: float, actual: bool):
        """Update calibration tracking"""
        self.calibration_history.append((predicted, 1.0 if actual else 0.0))
    
    def get_calibration_score(self) -> float:
        """Calculate Brier score for calibration"""
        if len(self.calibration_history) < 10:
            return 0.5  # Not enough data
        
        predictions, actuals = zip(*self.calibration_history[-100:])
        brier = np.mean([(p - a)**2 for p, a in zip(predictions, actuals)])
        return 1 - brier  # Convert to score (higher is better)

class MarketConsensusModel(BaseModel):
    """
    Use the market's own probability as a baseline, adjusted for biases
    """
    
    def __init__(self):
        super().__init__()
        self.known_biases = {
            'longshot': 0.03,      # Markets overestimate low probability events
            'favorite': -0.02,     # Markets underestimate high probability favorites
            'recent_news': 0.05,   # Markets overreact to recent news
        }
    
    async def estimate(self, market: 'MarketMetadata',
                      orderbook: 'OrderBookSnapshot',
                      context: Dict) -> Optional[ProbabilityEstimate]:
        
        # Start with market mid price
        market_prob = orderbook.mid_price
        
        # Apply known bias corrections
        adjusted_prob = market_prob
        
        # Longshot bias: if prob < 0.2, market typically overestimates
        if market_prob < 0.2:
            adjusted_prob -= self.known_biases['longshot'] * (0.2 - market_prob)
        
        # Favorite bias: if prob > 0.8, market typically underestimates
        if market_prob > 0.8:
            adjusted_prob -= self.known_biases['favorite'] * (market_prob - 0.8)
        
        # Check for recent volume spike (potential overreaction)
        recent_volume_spike = context.get('volume_spike', False)
        if recent_volume_spike:
            # Mean revert slightly
            adjusted_prob = 0.7 * adjusted_prob + 0.3 * 0.5
        
        # Confidence based on liquidity and spread
        confidence = self._calculate_confidence(market, orderbook)
        
        # Calculate staleness
        staleness = 0.0  # Market prices are always fresh
        
        return ProbabilityEstimate(
            probability=np.clip(adjusted_prob, 0.01, 0.99),
            confidence=confidence,
            method="market_consensus",
            inputs={
                'market_mid': market_prob,
                'spread_bps': orderbook.spread_bps,
                'liquidity': market.liquidity
            },
            staleness=staleness
        )
    
    def _calculate_confidence(self, market: 'MarketMetadata',
                             orderbook: 'OrderBookSnapshot') -> float:
        """
        Higher confidence when:
        - Higher liquidity
        - Tighter spreads
        - More volume
        """
        confidence = 0.5
        
        # Liquidity contribution
        if market.liquidity > 50000:
            confidence += 0.2
        elif market.liquidity > 10000:
            confidence += 0.1
        elif market.liquidity < 1000:
            confidence -= 0.2
        
        # Spread contribution
        if orderbook.spread_bps < 30:
            confidence += 0.2
        elif orderbook.spread_bps < 100:
            confidence += 0.1
        elif orderbook.spread_bps > 300:
            confidence -= 0.2
        
        # Volume contribution
        if market.volume_24h > 100000:
            confidence += 0.1
        elif market.volume_24h < 1000:
            confidence -= 0.1
        
        return np.clip(confidence, 0.1, 0.9)

class HistoricalBaseRateModel(BaseModel):
    """
    Estimate probability based on historical base rates of similar events
    """
    
    def __init__(self):
        super().__init__()
        self.base_rates = self._load_base_rates()
    
    def _load_base_rates(self) -> Dict[str, float]:
        """
        Load historical base rates for common event types
        These would be calculated from historical Polymarket data
        """
        return {
            # Politics
            'presidential_approval_above': 0.35,
            'bill_passage': 0.28,
            'supreme_court_decision': 0.45,
            
            # Sports
            'nfl_home_win': 0.57,
            'nba_home_win': 0.60,
            'soccer_home_win': 0.46,
            'over_under': 0.48,
            
            # Crypto
            'bitcoin_above_threshold': 0.42,
            'ethereum_above_threshold': 0.40,
            'new_ath': 0.15,
            
            # Economics
            'rate_hike': 0.35,
            'recession': 0.25,
            'cpi_above': 0.45,
            
            # Technology
            'product_launch_by_date': 0.35,
            'acquisition_approval': 0.65,
            
            # Entertainment
            'box_office_threshold': 0.40,
            'awards_winner': 0.20,  # Depends on # of candidates
        }
    
    async def estimate(self, market: 'MarketMetadata',
                      orderbook: 'OrderBookSnapshot',
                      context: Dict) -> Optional[ProbabilityEstimate]:
        
        # Classify the market
        category = self._classify_market(market)
        
        if category not in self.base_rates:
            return None
        
        base_rate = self.base_rates[category]
        
        # Adjust based on specifics
        adjusted_prob = self._adjust_for_specifics(base_rate, market, context)
        
        # Confidence is medium for base rates (better than nothing)
        confidence = 0.6
        
        # Base rates can be stale if market conditions change
        staleness = self._calculate_staleness(market)
        
        return ProbabilityEstimate(
            probability=np.clip(adjusted_prob, 0.05, 0.95),
            confidence=confidence * (1 - staleness / 24),  # Reduce confidence if stale
            method="base_rate",
            inputs={
                'category': category,
                'base_rate': base_rate,
                'staleness_hours': staleness
            },
            staleness=staleness
        )
    
    def _classify_market(self, market: 'MarketMetadata') -> str:
        """Classify market into a category using keyword matching"""
        question_lower = market.question.lower()
        tags_lower = [t.lower() for t in market.tags]
        
        # Check tags first
        if 'politics' in tags_lower or 'election' in tags_lower:
            if 'approval' in question_lower:
                return 'presidential_approval_above'
            elif 'bill' in question_lower or 'pass' in question_lower:
                return 'bill_passage'
        
        if 'sports' in tags_lower:
            if 'nfl' in question_lower:
                return 'nfl_home_win'
            elif 'nba' in question_lower:
                return 'nba_home_win'
        
        if 'crypto' in tags_lower or 'bitcoin' in question_lower or 'ethereum' in question_lower:
            if 'bitcoin' in question_lower or 'btc' in question_lower:
                return 'bitcoin_above_threshold'
            elif 'ethereum' in question_lower or 'eth' in question_lower:
                return 'ethereum_above_threshold'
        
        return 'unknown'
    
    def _adjust_for_specifics(self, base_rate: float, 
                             market: 'MarketMetadata',
                             context: Dict) -> float:
        """Adjust base rate based on market specifics"""
        adjusted = base_rate
        
        # Time adjustment: events far in future have more uncertainty
        days_to_resolution = (market.end_date - datetime.utcnow()).days
        
        if days_to_resolution > 180:
            # Far future: mean revert towards 50%
            adjusted = 0.7 * adjusted + 0.3 * 0.5
        elif days_to_resolution < 7:
            # Near term: market price is likely more accurate
            # So we weight base rate less
            adjusted = 0.3 * adjusted + 0.7 * context.get('market_price', 0.5)
        
        return adjusted
    
    def _calculate_staleness(self, market: 'MarketMetadata') -> float:
        """
        Calculate how stale the base rate might be
        Returns hours of staleness
        """
        # Base rates become stale quickly for time-sensitive events
        days_to_resolution = (market.end_date - datetime.utcnow()).days
        
        if days_to_resolution < 1:
            return 12.0  # Very stale for day-of events
        elif days_to_resolution < 7:
            return 6.0
        else:
            return 1.0  # Fresh for longer-term events

class ExternalDataModel(BaseModel):
    """
    Fetch external data sources to inform probability estimates
    """
    
    def __init__(self):
        super().__init__()
        self.cache = {}
        self.cache_duration = timedelta(hours=1)
    
    async def estimate(self, market: 'MarketMetadata',
                      orderbook: 'OrderBookSnapshot',
                      context: Dict) -> Optional[ProbabilityEstimate]:
        
        # Determine what external data we need
        category = self._categorize_market(market)
        
        if category == 'sports':
            return await self._estimate_sports(market, context)
        elif category == 'crypto':
            return await self._estimate_crypto(market, context)
        elif category == 'weather':
            return await self._estimate_weather(market, context)
        elif category == 'politics':
            return await self._estimate_politics(market, context)
        
        return None
    
    async def _estimate_sports(self, market: 'MarketMetadata',
                               context: Dict) -> Optional[ProbabilityEstimate]:
        """
        Use sports betting odds as a probability source
        """
        # Extract teams/players from question
        teams = self._extract_entities(market.question, 'sports')
        
        if not teams:
            return None
        
        # Fetch odds from external API (e.g., The Odds API)
        odds_data = await self._fetch_sports_odds(teams, market.end_date)
        
        if not odds_data:
            return None
        
        # Convert odds to probability
        probability = self._odds_to_probability(odds_data)
        
        staleness = (datetime.utcnow() - odds_data.get('timestamp', datetime.utcnow())).total_seconds() / 3600
        
        return ProbabilityEstimate(
            probability=probability,
            confidence=0.75,  # Sports odds are generally well-calibrated
            method="external_sports_odds",
            inputs={
                'teams': teams,
                'odds': odds_data.get('odds'),
                'source': odds_data.get('source')
            },
            staleness=staleness
        )
    
    async def _estimate_crypto(self, market: 'MarketMetadata',
                               context: Dict) -> Optional[ProbabilityEstimate]:
        """
        Use crypto price data and technical analysis
        """
        # Extract crypto asset and threshold
        asset, threshold = self._extract_crypto_info(market.question)
        
        if not asset or not threshold:
            return None
        
        # Fetch current price and historical data
        price_data = await self._fetch_crypto_price(asset)
        
        if not price_data:
            return None
        
        current_price = price_data['price']
        
        # Simple probability model based on distance to threshold
        days_to_resolution = (market.end_date - datetime.utcnow()).days
        
        # Calculate historical volatility
        volatility = price_data.get('volatility_30d', 0.5)
        
        # Use log-normal model to estimate probability
        # P(price > threshold) based on current price, volatility, and time
        
        if threshold > current_price:
            # Need price to go up
            required_return = np.log(threshold / current_price)
            std_dev = volatility * np.sqrt(days_to_resolution / 365)
            
            # Assume drift of 0 (neutral)
            z_score = -required_return / std_dev if std_dev > 0 else 0
            probability = self._normal_cdf(z_score)
        else:
            # Need price to stay above threshold
            required_return = np.log(current_price / threshold)
            std_dev = volatility * np.sqrt(days_to_resolution / 365)
            
            z_score = required_return / std_dev if std_dev > 0 else 0
            probability = self._normal_cdf(z_score)
        
        staleness = (datetime.utcnow() - price_data.get('timestamp', datetime.utcnow())).total_seconds() / 3600
        
        return ProbabilityEstimate(
            probability=np.clip(probability, 0.05, 0.95),
            confidence=0.65,
            method="external_crypto_price",
            inputs={
                'asset': asset,
                'current_price': current_price,
                'threshold': threshold,
                'volatility': volatility,
                'days_to_resolution': days_to_resolution
            },
            staleness=staleness
        )
    
    async def _estimate_weather(self, market: 'MarketMetadata',
                                context: Dict) -> Optional[ProbabilityEstimate]:
        """
        Use weather forecast data
        """
        # Extract location and condition
        location, condition = self._extract_weather_info(market.question)
        
        if not location:
            return None
        
        # Fetch weather forecast
        forecast = await self._fetch_weather_forecast(location, market.end_date)
        
        if not forecast:
            return None
        
        # Calculate probability based on forecast
        probability = self._interpret_weather_forecast(forecast, condition)
        
        staleness = (datetime.utcnow() - forecast.get('timestamp', datetime.utcnow())).total_seconds() / 3600
        
        return ProbabilityEstimate(
            probability=probability,
            confidence=0.70,
            method="external_weather",
            inputs={
                'location': location,
                'condition': condition,
                'forecast': forecast.get('summary')
            },
            staleness=staleness
        )
    
    async def _estimate_politics(self, market: 'MarketMetadata',
                                 context: Dict) -> Optional[ProbabilityEstimate]:
        """
        Use polling data, prediction markets, etc.
        """
        # Extract political event details
        event_type = self._extract_political_event(market.question)
        
        # Fetch polling data or other political forecasts
        # Could use FiveThirtyEight, RealClearPolitics, etc.
        
        # For now, return None (would implement with actual data sources)
        return None
    
    def _categorize_market(self, market: 'MarketMetadata') -> str:
        """Categorize market to determine which external data to use"""
        question_lower = market.question.lower()
        tags_lower = [t.lower() for t in market.tags]
        
        if any(sport in question_lower for sport in ['nfl', 'nba', 'mlb', 'nhl', 'soccer', 'ufc']):
            return 'sports'
        
        if any(crypto in question_lower for crypto in ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto']):
            return 'crypto'
        
        if any(word in question_lower for word in ['temperature', 'rain', 'snow', 'weather']):
            return 'weather'
        
        if 'politics' in tags_lower or 'election' in tags_lower:
            return 'politics'
        
        return 'unknown'
    
    def _extract_entities(self, question: str, category: str) -> List[str]:
        """Extract relevant entities from question"""
        # Simple regex-based extraction (would use NLP in production)
        if category == 'sports':
            # Look for team names in question
            teams = []
            # This would be much more sophisticated with actual team name database
            return teams
        return []
    
    def _extract_crypto_info(self, question: str) -> Tuple[Optional[str], Optional[float]]:
        """Extract crypto asset and price threshold"""
        question_lower = question.lower()
        
        # Extract asset
        asset = None
        if 'bitcoin' in question_lower or 'btc' in question_lower:
            asset = 'BTC'
        elif 'ethereum' in question_lower or 'eth' in question_lower:
            asset = 'ETH'
        
        # Extract threshold using regex
        threshold = None
        # Look for patterns like "$50,000" or "50000" or "50K"
        import re
        patterns = [
            r'\$?([\d,]+(?:\.\d+)?)\s*k',  # 50K format
            r'\$?([\d,]+(?:\.\d+)?)',       # 50000 format
        ]
        
        for pattern in patterns:
            match = re.search(pattern, question_lower)
            if match:
                threshold_str = match.group(1).replace(',', '')
                threshold = float(threshold_str)
                if 'k' in match.group(0).lower():
                    threshold *= 1000
                break
        
        return asset, threshold
    
    def _extract_weather_info(self, question: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract location and weather condition"""
        # Placeholder - would use NLP for actual extraction
        return None, None
    
    def _extract_political_event(self, question: str) -> Optional[str]:
        """Extract political event type"""
        return None
    
    async def _fetch_sports_odds(self, teams: List[str], event_date: datetime) -> Optional[Dict]:
        """Fetch sports betting odds from external API"""
        # Placeholder - would call actual odds API
        return None
    
    async def _fetch_crypto_price(self, asset: str) -> Optional[Dict]:
        """Fetch crypto price from exchange API"""
        cache_key = f"crypto_{asset}"
        
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if datetime.utcnow() - cached_time < self.cache_duration:
                return cached_data
        
        try:
            async with aiohttp.ClientSession() as session:
                # Use CoinGecko API (free tier)
                url = f"https://api.coingecko.com/api/v3/simple/price"
                params = {
                    'ids': asset.lower(),
                    'vs_currencies': 'usd',
                    'include_24hr_vol': 'true',
                    'include_24hr_change': 'true'
                }
                
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        # Fetch historical data for volatility calculation
                        hist_url = f"https://api.coingecko.com/api/v3/coins/{asset.lower()}/market_chart"
                        hist_params = {'vs_currency': 'usd', 'days': '30'}
                        
                        async with session.get(hist_url, params=hist_params) as hist_resp:
                            if hist_resp.status == 200:
                                hist_data = await hist_resp.json()
                                prices = [p[1] for p in hist_data.get('prices', [])]
                                
                                # Calculate volatility
                                if len(prices) > 1:
                                    returns = np.diff(np.log(prices))
                                    volatility = np.std(returns) * np.sqrt(365)
                                else:
                                    volatility = 0.5
                        
                        result = {
                            'price': data[asset.lower()]['usd'],
                            'volatility_30d': volatility,
                            'timestamp': datetime.utcnow()
                        }
                        
                        self.cache[cache_key] = (result, datetime.utcnow())
                        return result
        except Exception as e:
            print(f"Error fetching crypto price: {e}")
        
        return None
    
    async def _fetch_weather_forecast(self, location: str, date: datetime) -> Optional[Dict]:
        """Fetch weather forecast from API"""
        # Placeholder - would call weather API
        return None
    
    def _odds_to_probability(self, odds_data: Dict) -> float:
        """Convert betting odds to probability"""
        # American odds conversion
        if 'american_odds' in odds_data:
            odds = odds_data['american_odds']
            if odds > 0:
                return 100 / (odds + 100)
            else:
                return (-odds) / (-odds + 100)
        
        # Decimal odds conversion
        if 'decimal_odds' in odds_data:
            return 1 / odds_data['decimal_odds']
        
        return 0.5
    
    def _interpret_weather_forecast(self, forecast: Dict, condition: str) -> float:
        """Interpret weather forecast for specific condition"""
        # Placeholder
        return 0.5
    
    def _normal_cdf(self, z: float) -> float:
        """Cumulative distribution function for standard normal"""
        from scipy.stats import norm
        return norm.cdf(z)

class EnsembleModel(BaseModel):
    """
    Combine multiple models using weighted average
    """
    
    def __init__(self, models: List[BaseModel]):
        super().__init__()
        self.models = models
        self.weights = self._initialize_weights()
    
    def _initialize_weights(self) -> Dict[str, float]:
        """Initialize weights for each model"""
        return {
            'market_consensus': 0.40,
            'base_rate': 0.20,
            'external_data': 0.40
        }
    
    async def estimate(self, market: 'MarketMetadata',
                      orderbook: 'OrderBookSnapshot',
                      context: Dict) -> Optional[ProbabilityEstimate]:
        
        # Get estimates from all models
        estimates = []
        
        for model in self.models:
            try:
                estimate = await model.estimate(market, orderbook, context)
                if estimate:
                    estimates.append(estimate)
            except Exception as e:
                print(f"Error in {model.__class__.__name__}: {e}")
        
        if not estimates:
            # Fallback: use market consensus if ensemble fails
            try:
                market_estimate = await self.models[0].estimate(market, orderbook, context)
                if market_estimate:
                    return market_estimate
            except:
                pass
            return None
        
        # Calculate weighted average
        total_weight = 0
        weighted_prob = 0
        weighted_confidence = 0
        
        for estimate in estimates:
            # Weight by confidence and model weight
            weight = self.weights.get(self._get_method_category(estimate.method), 0.33)
            weight *= estimate.confidence
            weight *= (1 - estimate.staleness / 24)  # Downweight stale estimates
            
            weighted_prob += estimate.probability * weight
            weighted_confidence += estimate.confidence * weight
            total_weight += weight
        
        if total_weight == 0:
            return None
        
        final_prob = weighted_prob / total_weight
        final_confidence = weighted_confidence / total_weight
        
        # Calculate maximum staleness
        max_staleness = max(e.staleness for e in estimates)
        
        return ProbabilityEstimate(
            probability=final_prob,
            confidence=final_confidence,
            method="ensemble",
            inputs={
                'models_used': [e.method for e in estimates],
                'individual_probs': [e.probability for e in estimates],
                'weights': [self.weights.get(self._get_method_category(e.method), 0.33) for e in estimates]
            },
            staleness=max_staleness
        )
    
    def _get_method_category(self, method: str) -> str:
        """Map method name to weight category"""
        if 'market' in method or 'consensus' in method:
            return 'market_consensus'
        elif 'base_rate' in method:
            return 'base_rate'
        elif 'external' in method:
            return 'external_data'
        return 'market_consensus'
    
    def update_weights_from_performance(self):
        """
        Update model weights based on historical performance
        Call this periodically (e.g., daily) to adapt to which models work best
        """
        # Calculate Brier score for each model
        scores = {}
        for model in self.models:
            score = model.get_calibration_score()
            method_category = self._get_method_category(model.__class__.__name__.lower())
            scores[method_category] = score
        
        # Normalize scores to weights
        total_score = sum(scores.values())
        if total_score > 0:
            for method, score in scores.items():
                self.weights[method] = score / total_score

class ProbabilityEstimator:
    """
    Main class that coordinates all probability models
    """
    
    def __init__(self):
        # Initialize individual models
        self.market_consensus = MarketConsensusModel()
        self.base_rate = HistoricalBaseRateModel()
        self.external_data = ExternalDataModel()
        
        # Create ensemble
        self.ensemble = EnsembleModel([
            self.market_consensus,
            self.base_rate,
            self.external_data
        ])
    
    async def estimate_probability(self, 
                                   market: 'MarketMetadata',
                                   orderbook: 'OrderBookSnapshot',
                                   context: Optional[Dict] = None) -> Optional[ProbabilityEstimate]:
        """
        Get probability estimate for a market
        """
        if context is None:
            context = {}
        
        # Add market price to context for other models to use
        context['market_price'] = orderbook.mid_price
        
        # Check for recent volume spike
        context['volume_spike'] = self._detect_volume_spike(market, context)
        
        # Use ensemble model
        estimate = await self.ensemble.estimate(market, orderbook, context)
        
        # Fallback: if ensemble fails, use market consensus directly
        if not estimate:
            try:
                estimate = await self.market_consensus.estimate(market, orderbook, context)
            except Exception as e:
                # Last resort: create a simple estimate from market price
                from datetime import datetime, timezone
                estimate = ProbabilityEstimate(
                    probability=orderbook.mid_price,
                    confidence=0.5,
                    method="fallback_market_price",
                    inputs={'market_mid': orderbook.mid_price},
                    staleness=0.0
                )
        
        return estimate
    
    def _detect_volume_spike(self, market: 'MarketMetadata', context: Dict) -> bool:
        """
        Detect if there's been a recent volume spike
        (Would need historical volume data)
        """
        # Placeholder
        return False
    
    async def update_calibration(self, market_id: str, 
                                predicted_prob: float,
                                actual_outcome: bool,
                                method: str):
        """
        Update calibration tracking when we know the outcome
        """
        # Find the model that made this prediction
        model_map = {
            'market_consensus': self.market_consensus,
            'base_rate': self.base_rate,
            'external_data': self.external_data,
            'ensemble': self.ensemble
        }
        
        model = model_map.get(method)
        if model:
            model.update_calibration(predicted_prob, actual_outcome)
