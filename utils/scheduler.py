# utils/scheduler.py
import pytz
import json
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from utils.db import (
    get_scheduled_posts,
    get_post_targets,
    mark_post_as_sent,
    get_post_buttons,
)
from keyboards.post_button import build_post_buttons_kb

LA_TZ = pytz.timezone("America/New_York")

scheduler = AsyncIOScheduler(timezone=LA_TZ)


# ==========================================
#            PUBLISH POST
# ==========================================


async def publish_post(bot: Bot, post_id: int):
    post = await get_scheduled_posts(post_id)
    if not post:
        return

    post_type = post["type"]
    raw = post["content"]

    # чаты назначения
    chat_ids = await get_post_targets(post_id)
    if not chat_ids:
        return

    # кнопки
    buttons = await get_post_buttons(post_id)
    reply_markup = build_post_buttons_kb(buttons) if buttons else None

    # ---------- TEXT ----------
    if post_type == "text":
        for chat_id in chat_ids:
            await bot.send_message(chat_id, raw, reply_markup=reply_markup)
        await mark_post_as_sent(post_id)
        return

    # ---------- MEDIA GROUP ----------
    if post_type == "media_group":
        from aiogram.types import (
            InputMediaPhoto,
            InputMediaVideo,
            InputMediaDocument,
            InputMediaAnimation,
        )

        try:
            album = json.loads(raw)
        except Exception:
            await mark_post_as_sent(post_id)
            return

        items = album.get("items", [])
        caption = album.get("caption")

        for chat_id in chat_ids:
            media = []
            for idx, item in enumerate(items[:10]):
                cap = caption if idx == 0 else None
                if item["type"] == "photo":
                    media.append(InputMediaPhoto(item["file_id"], caption=cap))
                elif item["type"] == "video":
                    media.append(InputMediaVideo(item["file_id"], caption=cap))
                elif item["type"] == "document":
                    media.append(InputMediaDocument(item["file_id"], caption=cap))
                elif item["type"] == "animation":
                    media.append(InputMediaAnimation(item["file_id"], caption=cap))

            if media:
                await bot.send_media_group(chat_id, media)

        await mark_post_as_sent(post_id)
        return

    # ---------- SINGLE MEDIA ----------
    try:
        data = json.loads(raw)
        file_id = data["file_id"]
        caption = data.get("caption")
    except Exception:
        await mark_post_as_sent(post_id)
        return

    for chat_id in chat_ids:
        if post_type == "photo":
            await bot.send_photo(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif post_type == "video":
            await bot.send_video(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif post_type == "document":
            await bot.send_document(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif post_type == "voice":
            await bot.send_voice(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif post_type == "audio":
            await bot.send_audio(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif post_type == "animation":
            await bot.send_animation(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif post_type == "video_note":
            await bot.send_video_note(chat_id, file_id)

    await mark_post_as_sent(post_id)


# ==========================================
#          SCHEDULE POST
# ==========================================


def schedule_post(bot: Bot, post_id: int, dt: datetime):
    """
    ВАЖНО: никогда не планируем прошлое.
    Если dt <= now — просто не создаём job, чтобы не получать MISSED.
    """
    now = datetime.now(LA_TZ)

    # приводим dt к tz-aware в LA_TZ (на случай если прилетело naive)
    if dt.tzinfo is None:
        dt = LA_TZ.localize(dt)
    else:
        dt = dt.astimezone(LA_TZ)

    if dt <= now:
        return

    scheduler.add_job(
        publish_post,
        "date",
        args=[bot, post_id],
        run_date=dt,
        id=f"post_{post_id}",
        misfire_grace_time=3600,  # 1 hour
        replace_existing=True,
    )


# ==========================================
#       RESCHEDULE (CHANGE TIME)
# ==========================================


def reschedule_post(post_id: int, new_dt: datetime):
    job_id = f"post_{post_id}"

    if new_dt.tzinfo is None:
        new_dt = LA_TZ.localize(new_dt)
    else:
        new_dt = new_dt.astimezone(LA_TZ)

    now = datetime.now(LA_TZ)
    if new_dt <= now:
        # если уводят в прошлое — просто убираем job
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
        return

    try:
        scheduler.reschedule_job(job_id, trigger="date", run_date=new_dt)
    except Exception:
        pass


# ==========================================
#         REMOVE SCHEDULED POST
# ==========================================


def remove_scheduled_post(post_id: int):
    job_id = f"post_{post_id}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
