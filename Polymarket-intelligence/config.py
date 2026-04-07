import os
from dotenv import load_dotenv
from typing import List
from pydantic import BaseModel

load_dotenv()

# Database
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg2://app_user:bigt123@localhost:5432/app_db')

# APIs
POLYMARKET_CLOB_API = os.getenv('POLYMARKET_CLOB_API', 'https://clob.polymarket.com')
POLYMARKET_GAMMA_API = os.getenv('POLYMARKET_GAMMA_API', 'https://gamma-api.polymarket.com')
POLYMARKET_STRAPI_API = os.getenv('POLYMARKET_STRAPI_API', 'https://strapi-matic.poly.market')
# Data API - public endpoints for fetching wallet trades, positions, activity (no auth required)
POLYMARKET_DATA_API = os.getenv('POLYMARKET_DATA_API', 'https://data-api.polymarket.com')

# RPC
POLYGON_RPC_URL = os.getenv('POLYGON_RPC_URL', 'https://polygon-mainnet.g.alchemy.com/v2/NZnkQ7MslHF1XY3SxojW5')
ETHEREUM_RPC_URL = os.getenv('ETHEREUM_RPC_URL', 'https://eth-mainnet.g.alchemy.com/v2/NZnkQ7MslHF1XY3SxojW5')

# Discord
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', 'https://discordapp.com/api/webhooks/1460328814226702560/mNC_59atAAiLp7Kq1EHhEtTwMCphZ9imo0i5AAvEkqkcABnXFCLWhIVcXWFplsXF8h-B')

# Operational
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 30))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
RETRY_DELAY = int(os.getenv('RETRY_DELAY', 5))
ENABLE_MONITORING = os.getenv('ENABLE_MONITORING', 'true').lower() == 'true'
ALERT_ON_LAG_SECONDS = int(os.getenv('ALERT_ON_LAG_SECONDS', 300))

# Risk Parameters
MAX_POSITION_SIZE_USD = float(os.getenv('MAX_POSITION_SIZE_USD', 1000))
MAX_DAILY_VOLUME_USD = float(os.getenv('MAX_DAILY_VOLUME_USD', 5000))
MAX_CORRELATED_EXPOSURE = float(os.getenv('MAX_CORRELATED_EXPOSURE', 0.3))
STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', 0.15))

# User Attribution
class UserCluster(BaseModel):
    """A cluster of addresses attributed to one user/entity"""
    user_id: str
    primary_address: str
    secondary_addresses: List[str] = []
    tags: List[str] = []  # e.g., ["whale", "early_mover", "contrarian"]

# Define your tracked users/clusters
TRACKED_USERS = [
    UserCluster(
        user_id="SeriouslySirius",
        primary_address="0x16b29c50f2439faf627209b2ac0c7bbddaa8a881",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="Stupidity",
        primary_address="0xcb437c1cae90151d00fb55c014a9d3616ffd3c74",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="0p0jogggg",
        primary_address="0x6ac5bb06a9eb05641fd5e82640268b92f3ab4b6e",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="kch123",
        primary_address="0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="SwissMiss",
        primary_address="0xdbade4c82fb72780a0db9a38f821d8671aba9c95",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="0x9D3E989DD42030664e6157DAE42f6d549542C49E-1760165563991",
        primary_address="0x9d3e989dd42030664e6157dae42f6d549542c49e",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="Account88888",
        primary_address="0x7f69983eb28245bba0d5083502a78744a8f66162",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="0x8dxd",
        primary_address="0x63ce342161250d705dc0b16df89036c8e5f9ba9a",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="PurpleThunderBicycleMountain",
        primary_address="0x589222a5124a96765443b97a3498d89ffd824ad2",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="CRYINGLITTLEBABY",
        primary_address="0x961afce6bd9aec79c5cf09d2d4dac2b434b23361",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="gabagool22",
        primary_address="0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="distinct-baguette",
        primary_address="0xe00740bce98a594e26861838885ab310ec3b548c",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="sovereign2013",
        primary_address="0xee613b3fc183ee44f9da9c05f53e2da107e3debf",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="neobrother",
        primary_address="0x6297b93ea37ff92a57fd636410f3b71ebf74517e",
        secondary_addresses=[],
        tags=[]
    ),
    UserCluster(
        user_id="SemyonMarmeladov",
        primary_address="0x37e4728b3c4607fb2b3b205386bb1d1fb1a8c991",
        secondary_addresses=[],
        tags=[]
    ),
        UserCluster(
        user_id="TeemuTeemuTeemu",
        primary_address="0x5388bc8cb72eb19a3bec0e8f3db6a77f7cd54d5a",
        secondary_addresses=[],
        tags=[]
    ),    UserCluster(
        user_id="DrPufferfish",
        primary_address="0xdb27bf2ac5d428a9c63dbc914611036855a6c56e",
        secondary_addresses=[],
        tags=[]
    ),    UserCluster(
        user_id="",
        primary_address="",
        secondary_addresses=[],
        tags=[]
    ),
]

# Get all addresses to track
TRACKED_ADDRESSES = []
for user in TRACKED_USERS:
    TRACKED_ADDRESSES.append(user.primary_address)
    TRACKED_ADDRESSES.extend(user.secondary_addresses)

# Address to User ID mapping
ADDRESS_TO_USER = {}
for user in TRACKED_USERS:
    ADDRESS_TO_USER[user.primary_address] = user.user_id
    for addr in user.secondary_addresses:
        ADDRESS_TO_USER[addr] = user.user_id

# PnL Accounting Method
PNL_ACCOUNTING_METHOD = os.getenv('PNL_ACCOUNTING_METHOD', 'FIFO')  # FIFO, LIFO, or WAVG

# Fee Structure (Polymarket typical fees)
MAKER_FEE_BPS = 0  # 0 bps for maker
TAKER_FEE_BPS = 0  # 0 bps for taker (Polymarket currently 0)
GAS_ESTIMATE_USD = 0.01  # Approximate gas cost
