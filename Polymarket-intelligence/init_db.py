#!/usr/bin/env python3
"""
Database initialization script.
Run this once to set up all database tables.
"""

import logging
from database.connection import db_manager
from config import DATABASE_URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Initialize the database by creating all tables"""
    logger.info(f"Connecting to database: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
    
    try:
        # Test connection first
        if not db_manager.health_check():
            logger.error("Database health check failed. Please ensure:")
            logger.error("1. PostgreSQL is running")
            logger.error("2. Database 'app_db' exists")
            logger.error("3. User 'app_user' exists with correct password")
            logger.error("4. DATABASE_URL in config.py is correct")
            return False
        
        logger.info("Database connection successful")
        
        # Create all tables
        logger.info("Creating database tables...")
        db_manager.create_all_tables()
        
        logger.info("✅ Database initialization completed successfully!")
        logger.info("All tables have been created and are ready to use.")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        logger.error("Please check your database configuration and try again.")
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
