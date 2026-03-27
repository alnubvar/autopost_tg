import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def _resolve_data_dir() -> Path:
    raw_data_dir = os.getenv("DATA_DIR", str(BASE_DIR / "data"))
    data_dir = Path(raw_data_dir)
    if not data_dir.is_absolute():
        data_dir = (BASE_DIR / data_dir).resolve()
    return data_dir


def _resolve_db_path(data_dir: Path) -> Path:
    raw_db_path = os.getenv("DB_PATH", "").strip()
    if not raw_db_path:
        return (data_dir / "posts.db").resolve()

    db_path = Path(raw_db_path)
    if db_path.is_absolute():
        return db_path.resolve()

    # Runtime data must stay inside DATA_DIR on Railway and locally.
    # For legacy values like `data/posts.db` or `posts.db`, normalize them
    # to a single persistent target: DATA_DIR/posts.db.
    return (data_dir / db_path.name).resolve()


_data_dir = _resolve_data_dir()
_db_path = _resolve_db_path(_data_dir)

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
