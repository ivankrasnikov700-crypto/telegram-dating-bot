import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
LTC_ADDRESS = os.getenv("LTC_ADDRESS")
USDT_ADDRESS = os.getenv("USDT_ADDRESS")
