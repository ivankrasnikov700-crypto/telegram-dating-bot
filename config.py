import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
LTC_ADDRESS = os.getenv("LTC_ADDRESS")
USDT_ADDRESS = os.getenv("USDT_ADDRESS")
MEDIA_CHANNEL_ID = int(os.getenv("MEDIA_CHANNEL_ID", "0"))
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID", "0"))
