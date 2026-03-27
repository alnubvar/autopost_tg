import json
from datetime import datetime

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import DEFAULT_TIMEZONE
from handlers.admin import parse_buttons
from keyboards.inline_admin import build_posts_list_kb
from utils.access import AdminOnlyFilter
from utils.db import (
    delete_post,
    delete_post_buttons,
    disable_recurrence,
    get_active_recurrence,
    get_pending_posts_page,
    get_post,
    get_post_buttons,
    save_post_buttons,
    update_post,
)
from utils.posting import send_post_content
from utils.posting import build_text_storage_payload, serialize_entities
from utils.recurrence import describe_recurrence, get_timezone
from utils.scheduler import remove_scheduled_post, reschedule_post


router = Router()
router.message.filter(AdminOnlyFilter())
router.callback_query.filter(AdminOnlyFilter())
PAGE_SIZE = 5
TZ = get_timezone(DEFAULT_TIMEZONE)


class EditText(StatesGroup):
    waiting_new_text = State()


class EditMedia(StatesGroup):
    waiting_new_media = State()


class EditDate(StatesGroup):
    waiting_new_date = State()


class EditTime(StatesGroup):
    waiting_new_time = State()


class EditButtons(StatesGroup):
    waiting_new_buttons = State()


def register_manage_post_handlers(dp):
    dp.include_router(router)


def manage_keyboard(post_id: int, recurrence: dict | None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="✏️ Редактировать текст",
                callback_data=f"edit_text:{post_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="🖼 Редактировать медиа",
                callback_data=f"edit_media:{post_id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="🔘 Редактировать кнопки",
                callback_data=f"edit_buttons:{post_id}",
            )
        ],
    ]

    if recurrence:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗓 Изменить расписание",
                    callback_data=f"edit_schedule:{post_id}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏹ Остановить автоповтор",
                    callback_data=f"stop_repeat:{post_id}",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📅 Дата",
                    callback_data=f"edit_date:{post_id}",
                ),
                InlineKeyboardButton(
                    text="⏰ Время",
                    callback_data=f"edit_time:{post_id}",
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔁 Настроить повтор",
                    callback_data=f"edit_schedule:{post_id}",
                )
            ]
        )

    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="🗑 Удалить пост",
                    callback_data=f"delete_post:{post_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅ Назад к списку",
                    callback_data="back_to_list",
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_post_preview(bot: Bot, admin_id: int, post: dict):
    buttons = await get_post_buttons(post["id"])
    recurrence = await get_active_recurrence(post["id"])

    await send_post_content(
        bot=bot,
        chat_id=admin_id,
        content_type=post["type"],
        raw_content=post["content"],
        buttons=buttons,
        preview_mode=True,
    )

    summary_lines = [f"Управление постом #{post['id']}"]
    if recurrence:
        summary_lines.append(f"Следующая отправка: {recurrence['next_run_at']}")
        summary_lines.append(f"Правило: {describe_recurrence(recurrence['config'])}")
    else:
        summary_lines.append(f"Публикация: {post['publish_time']}")

    await bot.send_message(
        admin_id,
        "\n".join(summary_lines),
        reply_markup=manage_keyboard(post["id"], recurrence),
    )


@router.callback_query(F.data.startswith("post_open:"))
async def open_post(callback: types.CallbackQuery):
    _, post_id_str, _page = callback.data.split(":")
    post = await get_post(int(post_id_str))
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return

    await send_post_preview(callback.message.bot, callback.from_user.id, post)
    await callback.answer()


@router.callback_query(F.data.startswith("posts_page:"))
async def paginate_posts(callback: types.CallbackQuery):
    _, page_str = callback.data.split(":")
    page = int(page_str)
    posts = await get_pending_posts_page(PAGE_SIZE, (page - 1) * PAGE_SIZE)

    if not posts:
        await callback.message.edit_text("Нет запланированных постов.")
        await callback.answer()
        return

    await callback.message.edit_text(
        "Вот твои запланированные посты:",
        reply_markup=build_posts_list_kb(posts, page, PAGE_SIZE),
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_list")
async def back_to_list(callback: types.CallbackQuery):
    posts = await get_pending_posts_page(PAGE_SIZE, 0)
    if not posts:
        await callback.message.answer("У тебя нет запланированных постов.")
        await callback.answer()
        return

    await callback.message.answer(
        "Вот твои запланированные посты:",
        reply_markup=build_posts_list_kb(posts, page=1, page_size=PAGE_SIZE),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_text:"))
async def start_edit_text(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(edit_post_id=int(callback.data.split(":")[1]))
    await state.set_state(EditText.waiting_new_text)
    await callback.message.answer("Пришли новый текст поста.")
    await callback.answer()


@router.message(EditText.waiting_new_text)
async def save_new_text(message: types.Message, state: FSMContext):
    post_id = (await state.get_data())["edit_post_id"]
    post = await get_post(post_id)
    if not post:
        await message.answer("Пост не найден.")
        await state.clear()
        return

    if post["type"] == "text":
        new_content = build_text_storage_payload(message.text, message.entities)
    elif post["type"] == "media_group":
        payload = json.loads(post["content"])
        payload["caption"] = message.text
        payload["caption_entities"] = serialize_entities(message.entities)
        new_content = json.dumps(payload, ensure_ascii=False)
    else:
        payload = json.loads(post["content"])
        payload["caption"] = message.text
        payload["caption_entities"] = serialize_entities(message.entities)
        new_content = json.dumps(payload, ensure_ascii=False)

    await update_post(post_id, new_content=new_content)
    await message.answer("Текст обновлён.")
    await send_post_preview(message.bot, message.from_user.id, await get_post(post_id))
    await state.clear()


@router.callback_query(F.data.startswith("edit_media:"))
async def start_edit_media(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(edit_post_id=int(callback.data.split(":")[1]))
    await state.set_state(EditMedia.waiting_new_media)
    await callback.message.answer(
        "Пришли новое медиа.\n"
        "Для альбомов пока можно менять только текст и расписание."
    )
    await callback.answer()


@router.message(EditMedia.waiting_new_media)
async def save_new_media(message: types.Message, state: FSMContext):
    post_id = (await state.get_data())["edit_post_id"]
    post = await get_post(post_id)
    if not post:
        await message.answer("Пост не найден.")
        await state.clear()
        return

    if post["type"] == "media_group":
        await message.answer("Для альбома сейчас можно менять только текст.")
        await state.clear()
        return

    if message.photo:
        new_type = "photo"
        payload = {
            "file_id": message.photo[-1].file_id,
            "caption": message.caption,
            "caption_entities": serialize_entities(message.caption_entities),
        }
    elif message.video:
        new_type = "video"
        payload = {
            "file_id": message.video.file_id,
            "caption": message.caption,
            "caption_entities": serialize_entities(message.caption_entities),
        }
    elif message.document:
        new_type = "document"
        payload = {
            "file_id": message.document.file_id,
            "caption": message.caption,
            "caption_entities": serialize_entities(message.caption_entities),
        }
    elif message.animation:
        new_type = "animation"
        payload = {
            "file_id": message.animation.file_id,
            "caption": message.caption,
            "caption_entities": serialize_entities(message.caption_entities),
        }
    elif message.audio:
        new_type = "audio"
        payload = {
            "file_id": message.audio.file_id,
            "caption": message.caption,
            "caption_entities": serialize_entities(message.caption_entities),
        }
    elif message.voice:
        new_type = "voice"
        payload = {
            "file_id": message.voice.file_id,
            "caption": message.caption,
            "caption_entities": serialize_entities(message.caption_entities),
        }
    elif message.video_note:
        new_type = "video_note"
        payload = {"file_id": message.video_note.file_id}
    else:
        await message.answer("Этот тип медиа не поддерживается.")
        return

    await update_post(
        post_id,
        new_content=json.dumps(payload, ensure_ascii=False),
        new_type=new_type,
    )
    await message.answer("Медиа обновлено.")
    await send_post_preview(message.bot, message.from_user.id, await get_post(post_id))
    await state.clear()


@router.callback_query(F.data.startswith("edit_date:"))
async def start_edit_date(callback: types.CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[1])
    recurrence = await get_active_recurrence(post_id)
    if recurrence:
        await callback.answer("Для повторов меняй расписание целиком", show_alert=True)
        return

    await state.update_data(edit_post_id=post_id)
    await state.set_state(EditDate.waiting_new_date)
    await callback.message.answer("Введи новую дату в формате YYYY-MM-DD.")
    await callback.answer()


@router.message(EditDate.waiting_new_date)
async def save_new_date(message: types.Message, state: FSMContext):
    try:
        new_date = datetime.strptime(message.text, "%Y-%m-%d").date()
    except ValueError:
        await message.answer("Неверный формат. Пример: 2026-04-01")
        return

    post_id = (await state.get_data())["edit_post_id"]
    post = await get_post(post_id)
    old_dt = datetime.fromisoformat(post["publish_time"])
    new_dt = TZ.localize(
        datetime(new_date.year, new_date.month, new_date.day, old_dt.hour, old_dt.minute)
    )

    await update_post(post_id, new_publish_time=new_dt.isoformat(), new_status="pending")
    reschedule_post(post_id, new_dt)
    await message.answer("Дата обновлена.")
    await send_post_preview(message.bot, message.from_user.id, await get_post(post_id))
    await state.clear()


@router.callback_query(F.data.startswith("edit_time:"))
async def start_edit_time(callback: types.CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[1])
    recurrence = await get_active_recurrence(post_id)
    if recurrence:
        await callback.answer("Для повторов меняй расписание целиком", show_alert=True)
        return

    await state.update_data(edit_post_id=post_id)
    await state.set_state(EditTime.waiting_new_time)
    await callback.message.answer("Введи новое время в формате ЧЧ ММ.")
    await callback.answer()


@router.message(EditTime.waiting_new_time)
async def save_new_time(message: types.Message, state: FSMContext):
    try:
        hour, minute = map(int, message.text.split())
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await message.answer("Неверный формат. Пример: 14 30")
        return

    post_id = (await state.get_data())["edit_post_id"]
    post = await get_post(post_id)
    old_dt = datetime.fromisoformat(post["publish_time"])
    new_dt = TZ.localize(datetime(old_dt.year, old_dt.month, old_dt.day, hour, minute))

    await update_post(post_id, new_publish_time=new_dt.isoformat(), new_status="pending")
    reschedule_post(post_id, new_dt)
    await message.answer("Время обновлено.")
    await send_post_preview(message.bot, message.from_user.id, await get_post(post_id))
    await state.clear()


@router.callback_query(F.data.startswith("edit_buttons:"))
async def start_edit_buttons(callback: types.CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[1])
    post = await get_post(post_id)
    if post and post["type"] == "media_group":
        await callback.answer(
            "Для альбома inline-кнопки недоступны: это ограничение Telegram.",
            show_alert=True,
        )
        return

    await state.update_data(edit_post_id=post_id)
    await state.set_state(EditButtons.waiting_new_buttons)
    await callback.message.answer(
        "Отправь новые кнопки в формате:\n"
        "Текст - ссылка\n"
        "Текст - @username"
    )
    await callback.answer()


@router.message(EditButtons.waiting_new_buttons)
async def save_new_buttons(message: types.Message, state: FSMContext):
    post_id = (await state.get_data())["edit_post_id"]
    buttons = parse_buttons(message.text)
    if not buttons:
        await message.answer("Не удалось распознать кнопки.")
        return

    await delete_post_buttons(post_id)
    await save_post_buttons(post_id, buttons)
    await message.answer("Кнопки обновлены.")
    await send_post_preview(message.bot, message.from_user.id, await get_post(post_id))
    await state.clear()


@router.callback_query(F.data.startswith("stop_repeat:"))
async def stop_repeat(callback: types.CallbackQuery):
    post_id = int(callback.data.split(":")[1])
    await disable_recurrence(post_id)
    await callback.message.answer(
        "Автоповтор остановлен. Ближайшая запланированная публикация сохранена как одноразовая."
    )
    post = await get_post(post_id)
    if post:
        await send_post_preview(callback.message.bot, callback.from_user.id, post)
    await callback.answer()


@router.callback_query(F.data.startswith("delete_post:"))
async def delete_post_handler(callback: types.CallbackQuery):
    post_id = int(callback.data.split(":")[1])
    await delete_post(post_id)
    remove_scheduled_post(post_id)
    await callback.message.answer("Пост удалён.")
    await callback.answer()
