import os
from dotenv import load_dotenv

load_dotenv()

def _parse_admin_ids():
    raw = os.getenv("ADMIN_IDS", "")
    result = []
    for x in raw.replace('"', '').replace("'", '').split(","):
        x = x.strip()
        if x.isdigit():
            result.append(int(x))
    return result

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = _parse_admin_ids()
LTC_ADDRESS = os.getenv("LTC_ADDRESS")
USDT_ADDRESS = os.getenv("USDT_ADDRESS")
MEDIA_CHANNEL_ID    = int(os.getenv("MEDIA_CHANNEL_ID",    "0"))
ADMIN_CHANNEL_ID    = int(os.getenv("ADMIN_CHANNEL_ID",    "0"))
VIP_CHANNEL_ID      = int(os.getenv("VIP_CHANNEL_ID",      "0"))
CONTACT_MANAGER_ID  = int(os.getenv("CONTACT_MANAGER_ID",  "0"))
