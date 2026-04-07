import os
from dotenv import load_dotenv

load_dotenv()

# Discord Configuration
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

# Polymarket Configuration (Builder API credentials)
POLYMARKET_API_KEY = os.getenv('POLYMARKET_API_KEY', '')
POLYMARKET_API_SECRET = os.getenv('POLYMARKET_API_SECRET', '')
POLYMARKET_API_PASSPHRASE = os.getenv('POLYMARKET_API_PASSPHRASE', '')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 60))  # seconds

# Accounts to track (add Polymarket wallet addresses here)
TRACKED_ACCOUNTS = [
    "0x16b29c50f2439faf627209b2ac0c7bbddaa8a881", # SeriouslySirius
    "0xcb437c1cae90151d00fb55c014a9d3616ffd3c74", # Stupidity
    "0x6ac5bb06a9eb05641fd5e82640268b92f3ab4b6e", # 0p0jogggg
    "0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee", # kch123
    "0xdbade4c82fb72780a0db9a38f821d8671aba9c95", # SwissMiss
    "0x9d3e989dd42030664e6157dae42f6d549542c49e", # 0x9D3E989DD42030664e6157DAE42f6d549542C49E-1760165563991
    "0x7f69983eb28245bba0d5083502a78744a8f66162", # Account88888
    "0x63ce342161250d705dc0b16df89036c8e5f9ba9a", # 0x8dxd
    "0x589222a5124a96765443b97a3498d89ffd824ad2", # PurpleThunderBicycleMountain
    "0x961afce6bd9aec79c5cf09d2d4dac2b434b23361", # CRYINGLITTLEBABY
    "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d", # gabagool22
    "0xe00740bce98a594e26861838885ab310ec3b548c", # distinct-baguette 
    # Add more addresses here
]

# Username mapping for accounts (extracted from comments above)
ACCOUNT_USERNAMES = {
    "0x16b29c50f2439faf627209b2ac0c7bbddaa8a881": "SeriouslySirius",
    "0xcb437c1cae90151d00fb55c014a9d3616ffd3c74": "Stupidity",
    "0x6ac5bb06a9eb05641fd5e82640268b92f3ab4b6e": "0p0jogggg",
    "0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee": "kch123",
    "0xdbade4c82fb72780a0db9a38f821d8671aba9c95": "SwissMiss",
    "0x9d3e989dd42030664e6157dae42f6d549542c49e": "0x9D3E989DD42030664e6157DAE42f6d549542C49E-1760165563991",
    "0x7f69983eb28245bba0d5083502a78744a8f66162": "Account88888",
    "0x63ce342161250d705dc0b16df89036c8e5f9ba9a": "0x8dxd",
    "0x589222a5124a96765443b97a3498d89ffd824ad2": "PurpleThunderBicycleMountain",
    "0x961afce6bd9aec79c5cf09d2d4dac2b434b23361": "CRYINGLITTLEBABY",
    "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d": "gabagool22",
    "0xe00740bce98a594e26861838885ab310ec3b548c": "distinct-baguette",
}

# API Endpoints
POLYMARKET_API_BASE = "https://clob.polymarket.com"  # CLOB API (requires L2 User API credentials)
POLYMARKET_DATA_API = "https://data-api.polymarket.com"  # Data-API (may be public or use Builder API)
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
