# simulator.py
# Simple backtest / dry-run simulator for strategy execution logic.

import random
import math
import logging
from datetime import datetime, timedelta
from typing import Optional

from strategy.execution_engine import ExecutionEngine
from ingestion.wallet_tracker import WalletTracker

logger = logging.getLogger(__name__)

class Simulator:
    """
    A lightweight simulator to test signals against historical-ish data.
    It feeds synthetic signals into the ExecutionEngine and records results.
    """
    def __init__(self, engine: ExecutionEngine, tracker: WalletTracker):
        self.engine = engine
        self.tracker = tracker

    def run(self, lookback_minutes: int = 60, seed: Optional[int] = None):
        if seed is not None:
            random.seed(seed)

        now = datetime.utcnow()
        end_time = now
        start_time = now - timedelta(minutes=lookback_minutes)

        signals = self._generate_synthetic_signals(start_time, end_time)

        stats = {
            "total": 0,
            "executed": 0,
            "filled": 0,
            "rejected": 0,
            "avg_confidence": 0.0
        }

        for sig in signals:
            stats["total"] += 1
            res = self.engine.execute_signal(sig, user_id=0)
            if not res:
                continue
            stats["executed"] += 1
            if res.get("status") == "FILLED":
                stats["filled"] += 1
            elif res.get("status") == "REJECTED":
                stats["rejected"] += 1

        # simple printout
        if stats["total"] > 0:
            stats["avg_confidence"] = sum(s.get("confidence", 0.5) for s in signals) / len(signals)

        logger.info(f"Simulation completed: {stats}")
        return stats

    def _generate_synthetic_signals(self, start_time: datetime, end_time: datetime):
        """
        Create a handful of synthetic signals to feed into engine.
        This is intentionally simplistic for architecture testing.
        """
        signals = []
        t = start_time
        while t < end_time:
            # random synthetic fill
            sig = {
                "signal_type": "COPY",
                "action": random.choice(["BUY", "SELL"]),
                "asset_id": f"asset_{random.randint(1, 5)}",
                "outcome": random.choice(["YES", "NO"]),
                "reference_price": round(random.uniform(0.2, 0.9), 4),
                "reference_size": random.randint(1, 10),
                "confidence": random.uniform(0.4, 0.9),
                "user_id": "synthetic_user",
                "timestamp": t,
                "source_fill_id": f"synthetic_{random.randint(1000,9999)}"
            }
            signals.append(sig)
            t += timedelta(minutes=random.randint(1, 5))
        return signals
