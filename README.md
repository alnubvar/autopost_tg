# Telegram Autopost Bot

A Telegram bot for creating, scheduling, and repeating posts across multiple chats and channels.

The project is built with `aiogram`, `APScheduler`, and `SQLite`. It supports one-time posting, repeat rules, post editing, inline buttons, and chat management.

## Features

- Create posts for multiple target chats
- Support text, photo, video, document, audio, voice, animation, and media groups
- Schedule a post once at a specific date and time
- Configure recurring rules:
  - specific dates
  - weekdays
  - month days
  - fixed times
  - interval mode such as `30m` or `1h 30m`
- Edit scheduled posts
- Stop recurring posts without deleting the base post
- Manage supported chats from inside the bot
- Restrict access with `ADMIN_IDS`
- Preserve runtime data in a persistent data directory

## Project Structure

```text
autopost_tg/
├── bot.py
├── config.py
├── .env.example
├── requirements.txt
├── README.md
├── LICENCE
├── handlers/
├── keyboards/
├── utils/
└── data/
```

Key modules:

- `bot.py`: application entrypoint
- `config.py`: environment loading and runtime path configuration
- `handlers/`: bot interaction flows
- `keyboards/`: reply and inline keyboard builders
- `utils/db.py`: SQLite access layer
- `utils/scheduler.py`: APScheduler integration
- `utils/recurrence.py`: recurrence rule engine
- `utils/posting.py`: Telegram send helpers

## Requirements

- Python 3.10+
- Telegram Bot API token

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Variables

Required:

- `BOT_TOKEN`: Telegram bot token
- `ADMIN_IDS`: comma-separated Telegram user IDs allowed to use the bot

Optional:

- `DEFAULT_TIMEZONE`: bot timezone, default is `Europe/Moscow`
- `DATA_DIR`: directory for runtime data, default is `./data` locally
- `DB_PATH`: optional custom SQLite file path; if omitted, the bot uses `DATA_DIR/posts.db`

Example:

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789,987654321
DEFAULT_TIMEZONE=Europe/Moscow
DATA_DIR=./data
```

## Local Run

1. Create and activate a virtual environment
2. Install dependencies
3. Copy `.env.example` to `.env`
4. Fill in your variables
5. Run:

```bash
python bot.py
```

The bot creates the runtime data directory automatically if it does not exist.

## Data Storage

The project uses a persistent data directory for runtime files.

By default:

- local development uses `./data`
- Railway should use `/data` through a mounted Volume

By default, the SQLite database path is:

```text
DATA_DIR/posts.db
```

You can still override it with `DB_PATH` if needed.

## Railway Deployment

### Recommended Setup

Deploy from GitHub and attach a Railway Volume mounted at:

```text
/data
```

Set the following variables in Railway:

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789
DEFAULT_TIMEZONE=Europe/Moscow
DATA_DIR=/data
```

Usually you do not need to set `DB_PATH` on Railway, because the bot will automatically use:

```text
/data/posts.db
```

### Start Command

```bash
python bot.py
```

### Railway Volume Note

SQLite is file-based. Without a persistent Volume, your database can be lost after redeploys or container restarts.

For Railway production usage:

- attach a Volume
- mount it to `/data`
- set `DATA_DIR=/data`

## Security Notes

- Do not commit `.env`
- Do not commit any `*.db` files
- Restrict access with `ADMIN_IDS`
- The bot refuses to start if `BOT_TOKEN` or `ADMIN_IDS` are missing

## Git Ignore

The repository is configured to ignore:

- `.env`
- `*.db`
- virtual environments
- `__pycache__`
- editor files and local artifacts

## Manual Pre-Deploy Checklist

- Verify `ADMIN_IDS`
- Verify `DEFAULT_TIMEZONE`
- Create one post locally
- Create one one-time schedule
- Create one recurring schedule
- Restart the bot and confirm scheduled items are restored
- Confirm the bot can write to the configured `DATA_DIR`

## Author

- Telegram: [@alnub_work](https://t.me/alnub_work)
- GitHub: [alnubvar](https://github.com/alnubvar)
- Email: alnubwork@gmail.com

## License

MIT License
