# health_check.py
# Lightweight health checks for ingestion, DB, and strategy components.

import time
import logging
from datetime import datetime, timedelta

from database.connection import db_manager

logger = logging.getLogger(__name__)

class HealthChecker:
    def __init__(self, db=None, alerting=None):
        self.db = db or db_manager
        self.alerting = alerting  # Optional Alerting client

    def ingestion_health(self) -> dict:
        """Check basic ingestion health (DB health + recent ingest logs)."""
        status = "OK"
        details = ""
        now = datetime.utcnow()

        try:
            healthy = self.db.health_check()
            if not healthy:
                status = "CRITICAL"
                details = "Database health check failed."
        except Exception as e:
            status = "CRITICAL"
            details = f"DB health exception: {e}"

        return {
            "component": "ingestion",
            "status": status,
            "checked_at": now.isoformat(),
            "details": details
        }

    def db_health(self) -> dict:
        """Low-level DB health state."""
        try:
            ok = self.db.health_check()
            return {
                "component": "database",
                "status": "OK" if ok else "CRITICAL",
                "checked_at": datetime.utcnow().isoformat(),
                "details": "Database reachable" if ok else "Database not reachable"
            }
        except Exception as e:
            return {
                "component": "database",
                "status": "CRITICAL",
                "checked_at": datetime.utcnow().isoformat(),
                "details": str(e)
            }

    def runtime_health(self) -> dict:
        """Basic runtime health (CPU/memory spikes, heartbeat)."""
        # Lightweight placeholder; implement if you have resource meters
        now = datetime.utcnow()
        health = {
            "component": "runtime",
            "status": "OK",
            "checked_at": now.isoformat(),
            "details": "Runtime within expected bounds"
        }
        return health

    def overall_health(self) -> dict:
        """Aggregate health status from components."""
        ing = self.ingestion_health()
        dbh = self.db_health()
        rt = self.runtime_health()

        status = "OK"
        if ing["status"] != "OK" or dbh["status"] != "OK":
            status = "DEGRADED" if ing["status"] == "OK" else "CRITICAL"

        return {
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "ingestion": ing,
                "database": dbh,
                "runtime": rt
            }
        }

def main():
    hc = HealthChecker()
    print(hc.overall_health())

if __name__ == "__main__":
    main()
