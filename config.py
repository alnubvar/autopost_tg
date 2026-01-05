# config.py
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "data/posts.db")
# CHANNEL_ID = os.getenv("CHANNEL_ID")
# HANNEL_ID = "@testformybotirinaa"
# DB_PATH = "data/posts.db"
