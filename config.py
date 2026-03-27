import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
_data_dir = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
if not _data_dir.is_absolute():
    _data_dir = (BASE_DIR / _data_dir).resolve()

_default_db_path = _data_dir / "posts.db"
_db_path = Path(os.getenv("DB_PATH", str(_default_db_path)))
if not _db_path.is_absolute():
    _db_path = (BASE_DIR / _db_path).resolve()

DATA_DIR = str(_data_dir)
DB_PATH = str(_db_path)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow")

_raw_admin_ids = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [
    int(item.strip())
    for item in _raw_admin_ids.split(",")
    if item.strip()
]
