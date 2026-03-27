import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import ADMIN_IDS, BOT_TOKEN
from handlers.admin import register_admin_handlers
from handlers.auto_repeat import register_auto_repeat_handlers
from handlers.manage_post import register_manage_post_handlers
from handlers.start import register_start_handlers
from handlers.user import register_user_handlers
from utils.db import (
    find_legacy_orphan_posts,
    get_all_chats,
    init_db,
    list_schedulable_posts,
)
from utils.logger import logger
from utils.scheduler import schedule_post, scheduler


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set")
    if not ADMIN_IDS:
        raise ValueError("ADMIN_IDS is not set")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    await init_db()
    scheduler.start()

    chats = await get_all_chats()
    logger.info("Loaded %s chats from persistent storage", len(chats))

    for item in await list_schedulable_posts():
        run_at = item.get("next_run_at") or item["publish_time"]
        if not run_at:
            continue
        schedule_post(bot, item["id"], datetime.fromisoformat(run_at))

    legacy_orphans = await find_legacy_orphan_posts()
    if legacy_orphans:
        logger.warning("Found %s legacy orphan pending posts", len(legacy_orphans))

    register_start_handlers(dp)
    register_admin_handlers(dp)
    register_auto_repeat_handlers(dp)
    register_manage_post_handlers(dp)
    register_user_handlers(dp)

    logger.info("Bot is running")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
