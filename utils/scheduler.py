from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from config import DEFAULT_TIMEZONE
from utils.db import (
    advance_recurrence_rule,
    disable_recurrence,
    get_active_recurrence,
    get_post,
    get_post_buttons,
    get_post_targets,
    mark_post_as_sent,
    update_post,
)
from utils.logger import logger
from utils.posting import publish_to_targets
from utils.recurrence import ensure_timezone, get_next_occurrence, get_timezone


LA_TZ = get_timezone(DEFAULT_TIMEZONE)
scheduler = AsyncIOScheduler(timezone=LA_TZ)


async def publish_post(bot: Bot, post_id: int):
    post = await get_post(post_id)
    if not post:
        return

    recurrence = await get_active_recurrence(post_id)
    chat_ids = await get_post_targets(post_id)
    buttons = await get_post_buttons(post_id)

    if not chat_ids:
        logger.warning("Post %s has no targets and will be marked as sent", post_id)
        if recurrence:
            await disable_recurrence(post_id)
        await mark_post_as_sent(post_id)
        return

    await publish_to_targets(
        bot=bot,
        chat_ids=chat_ids,
        content_type=post["type"],
        raw_content=post["content"],
        buttons=buttons,
    )

    if not recurrence:
        await mark_post_as_sent(post_id)
        return

    current_run_at = recurrence.get("next_run_at") or post["publish_time"]
    next_dt = get_next_occurrence(
        recurrence["config"],
        ensure_timezone(datetime.fromisoformat(current_run_at), recurrence.get("timezone")),
    )

    if next_dt is None:
        await advance_recurrence_rule(
            post_id=post_id,
            last_run_at=current_run_at,
            next_run_at=None,
            is_active=False,
        )
        await mark_post_as_sent(post_id)
        return

    await update_post(
        post_id=post_id,
        new_publish_time=next_dt.isoformat(),
        new_status="pending",
    )
    await advance_recurrence_rule(
        post_id=post_id,
        last_run_at=current_run_at,
        next_run_at=next_dt.isoformat(),
        is_active=True,
    )
    schedule_post(bot, post_id, next_dt)


def schedule_post(bot: Bot, post_id: int, dt: datetime):
    run_at = ensure_timezone(dt, DEFAULT_TIMEZONE)
    now = datetime.now(get_timezone(DEFAULT_TIMEZONE))

    if run_at <= now:
        logger.warning("Skip scheduling post %s in the past: %s", post_id, run_at)
        return

    scheduler.add_job(
        publish_post,
        "date",
        args=[bot, post_id],
        run_date=run_at,
        id=f"post_{post_id}",
        misfire_grace_time=3600,
        replace_existing=True,
    )


def reschedule_post(post_id: int, new_dt: datetime):
    job_id = f"post_{post_id}"
    run_at = ensure_timezone(new_dt, DEFAULT_TIMEZONE)
    now = datetime.now(get_timezone(DEFAULT_TIMEZONE))

    if run_at <= now:
        try:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        except Exception:
            logger.exception("Failed to remove outdated job %s", job_id)
        return

    try:
        scheduler.reschedule_job(job_id, trigger="date", run_date=run_at)
    except Exception:
        logger.exception("Failed to reschedule job %s", job_id)


def remove_scheduled_post(post_id: int):
    job_id = f"post_{post_id}"
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception:
        logger.exception("Failed to remove job %s", job_id)
