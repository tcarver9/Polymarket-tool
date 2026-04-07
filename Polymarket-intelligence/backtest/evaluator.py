# evaluator.py
# Simple evaluation harness to compare live strategy vs baseline.

import statistics
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class Evaluator:
    """
    Backtest/evaluate a strategy against historical-like data.
    This is a scaffold; you should wire real data sources for production.
    """
    def __init__(self, pricing_fn=None):
        self.pricing_fn = pricing_fn or (lambda asset_id, ts: 0.5)

    def evaluate_strategy(self, signals, price_stream, fees_fn=None):
        """
        signals: list of dict signals (copy signals)
        price_stream: function(asset_id, ts) -> price
        """
        total = len(signals)
        if total == 0:
            return {"success": 0}

        results = []
        for sig in signals:
            asset = sig.get("asset_id")
            ts = sig.get("timestamp", datetime.utcnow())
            price = price_stream(asset, ts)
            # naive evaluation: assume if signal is BUY and price goes up after, it's profitable
            # This is a placeholder; replace with your real logic.
            outcome = "profit" if random.choice([True, False]) else "loss"
            results.append({"sig": sig, "outcome": outcome, "price": price})

        profits = [1 if r["outcome"] == "profit" else -1 for r in results]
        total_profit = sum(profits)
        win_rate = sum(1 for p in profits if p > 0) / len(profits) * 100
        try:
            sharpe = (statistics.mean(profits) / statistics.pstdev(profits)) * (252 ** 0.5)
        except Exception:
            sharpe = None

        return {
            "total_signals": total,
            "total_profit": total_profit,
            "win_rate_pct": win_rate,
            "sharpe": sharpe,
            "results": results
        }
