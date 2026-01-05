# bot.py
import asyncio
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN

from handlers.start import register_start_handlers
from handlers.user import register_user_handlers
from handlers.admin import register_admin_handlers

from utils.scheduler import scheduler, schedule_post
from utils.db import init_db, get_all_pending_posts

from datetime import datetime, timedelta
import pytz
from handlers.manage_post import register_manage_post_handlers
from handlers.auto_repeat import register_auto_repeat_handlers


LA = pytz.timezone("America/New_York")


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not set")

    bot = Bot(token=BOT_TOKEN)

    dp = Dispatcher()

    await init_db()  # создаём таблицы

    # Запускаем планировщик
    scheduler.start()

    # ВАЖНО: при рестарте подгружаем все незавершённые задачи
    pending_posts = await get_all_pending_posts()
    for post in pending_posts:
        publish_dt = datetime.fromisoformat(post["publish_time"])
        schedule_post(bot, post["id"], publish_dt)

    # Регистрируем хендлеры
    register_start_handlers(dp)
    register_admin_handlers(dp)  # ← admin должен быть раньше user!
    register_auto_repeat_handlers(dp)
    register_manage_post_handlers(dp)
    register_user_handlers(dp)

    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
