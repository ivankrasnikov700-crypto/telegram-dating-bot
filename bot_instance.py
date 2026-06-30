# bot_instance.py
# Single shared bot instance — imported by main.py and api/server.py (webhook)
import telebot
from config import BOT_TOKEN

bot = telebot.TeleBot(BOT_TOKEN)
