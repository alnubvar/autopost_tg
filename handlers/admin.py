from aiogram import Router, types, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAnimation,
)

from keyboards.main_menu import admin_menu
from keyboards.calendar_kb import build_date_choice_kb, build_calendar
from keyboards.inline_admin import build_posts_list_kb
from keyboards.chat_select import build_chat_select_kb

from datetime import datetime, timedelta
from asyncio import create_task, sleep
import pytz
import json
import re

from utils.db import (
    save_post,
    add_post_targets,
    get_all_chats,
    get_pending_posts_page,
    add_chat,
    save_post_buttons,
)
from utils.scheduler import schedule_post
from keyboards.post_button import build_post_buttons_kb

router = Router()

print("ADMIN ROUTER LOADED")

ADMIN_ID = [580759300, 8120213148, 7773812278]
PAGE_SIZE = 5
LA = pytz.timezone("America/New_York")


# ============================================================
#                    FSM
# ============================================================


class AddPost(StatesGroup):
    waiting_for_content = State()
    waiting_for_chats = State()
    waiting_for_action = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_buttons = State()
    waiting_for_schedule_input = State()  # ⬅ для автоповтора


def register_admin_handlers(dp):
    dp.include_router(router)


# ============================================================
#                    ВСПОМОГАТЕЛЬНЫЕ
# ============================================================


def build_publish_or_schedule_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Опубликовать сейчас", callback_data="post_action:now"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏳ Запланировать", callback_data="post_action:schedule"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔘 Добавить кнопки", callback_data="post_action:buttons"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data="post_action:cancel"
                )
            ],
        ]
    )


async def publish_now_to_chats(
    bot: Bot,
    chat_ids: list[str],
    content_type: str,
    raw_content: str,
    buttons: list[dict] | None = None,
):
    reply_markup = build_post_buttons_kb(buttons) if buttons else None

    # --- TEXT ---
    if content_type == "text":
        for chat_id in chat_ids:
            await bot.send_message(chat_id, raw_content, reply_markup=reply_markup)
        return

    # --- ALBUM ---
    if content_type == "media_group":
        album = json.loads(raw_content)
        caption = album.get("caption")
        items = album.get("items", [])

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
        return

    # --- SINGLE MEDIA ---
    data = json.loads(raw_content)
    file_id = data["file_id"]
    caption = data.get("caption")

    for chat_id in chat_ids:
        if content_type == "photo":
            await bot.send_photo(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif content_type == "video":
            await bot.send_video(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif content_type == "document":
            await bot.send_document(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif content_type == "voice":
            await bot.send_voice(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif content_type == "audio":
            await bot.send_audio(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif content_type == "animation":
            await bot.send_animation(
                chat_id, file_id, caption=caption, reply_markup=reply_markup
            )
        elif content_type == "video_note":
            await bot.send_video_note(chat_id, file_id)


async def show_chat_select(
    message_or_callback: types.Message | types.CallbackQuery, state: FSMContext
):
    chats = await get_all_chats()
    if not chats:
        text = (
            "❗️Нет добавленных чатов.\n\n"
            "Сначала добавь бота в канал/группу и дай ему права.\n"
            "Затем мы сделаем кнопку '➕ Добавить чат' (следующим шагом)."
        )
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.edit_text(text)
            await message_or_callback.answer()
        else:
            await message_or_callback.answer(text)
        await state.clear()
        return

    data = await state.get_data()
    selected = set(data.get("selected_chats", []))
    kb = build_chat_select_kb(chats, selected)

    text = "Выбери чаты для публикации:"
    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=kb)
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, reply_markup=kb)


# ============================================================
#                    1. ДОБАВИТЬ ПОСТ
# ============================================================


@router.message(F.text == "📝 Добавить пост")
async def add_post(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_ID:
        return

    await state.set_state(AddPost.waiting_for_content)
    await state.update_data(album=None)

    await message.answer(
        "Отправь мне пост, который нужно опубликовать.\n\n"
        "Поддерживается:\n"
        "— текст\n"
        "— фото / видео + текст\n"
        "— документы\n"
        "— голосовые, аудио, GIF\n"
        "— альбомы (2–10 медиа подряд)"
    )


# ============================================================
#                    2. СПИСОК ПОСТОВ
# ============================================================


@router.message(F.text == "📋 Мои запланированные")
async def list_my_posts(message: types.Message):
    if message.from_user.id not in ADMIN_ID:
        return

    page = 1
    posts = await get_pending_posts_page(PAGE_SIZE, 0)

    if not posts:
        await message.answer("У тебя нет запланированных постов 💤")
        return

    kb = build_posts_list_kb(posts, page, PAGE_SIZE)
    await message.answer("Вот твои запланированные посты:", reply_markup=kb)


# ============================================================
#         3. ПРИНЯТИЕ КОНТЕНТА + АЛЬБОМЫ
# ============================================================


@router.message(AddPost.waiting_for_content)
async def process_content(message: types.Message, state: FSMContext):
    data = await state.get_data()

    # ----------------------------------------------------------
    # Альбом (media_group)
    # ----------------------------------------------------------
    if message.media_group_id:
        album = data.get("album")

        if not album:
            album = {
                "media_group_id": message.media_group_id,
                "items": [],
                "caption": None,
            }

        if message.caption and not album["caption"]:
            album["caption"] = message.caption

        if message.photo:
            album["items"].append(
                {"type": "photo", "file_id": message.photo[-1].file_id}
            )
        elif message.video:
            album["items"].append({"type": "video", "file_id": message.video.file_id})
        elif message.document:
            album["items"].append(
                {"type": "document", "file_id": message.document.file_id}
            )
        elif message.animation:
            album["items"].append(
                {"type": "animation", "file_id": message.animation.file_id}
            )
        else:
            await message.answer(
                "В альбом можно добавлять только фото, видео, GIF и документы."
            )
            return

        album["items"] = album["items"][:10]
        await state.update_data(album=album)

        async def finish(group_id):
            await sleep(0.7)
            d = await state.get_data()
            last = d.get("album")

            if not last or last["media_group_id"] != group_id:
                return

            await state.update_data(
                content_type="media_group",
                content=json.dumps(
                    {"items": last["items"], "caption": last["caption"]},
                    ensure_ascii=False,
                ),
                album=None,
            )

            # ✅ после контента — выбор чатов
            await state.set_state(AddPost.waiting_for_chats)
            await state.update_data(selected_chats=[])
            await show_chat_select(message, state)

        create_task(finish(message.media_group_id))
        return

    # ----------------------------------------------------------
    # Альбом завершён, приходит новое сообщение
    # ----------------------------------------------------------
    if data.get("album"):
        album = data["album"]
        await state.update_data(
            content_type="media_group",
            content=json.dumps(
                {"items": album["items"], "caption": album["caption"]},
                ensure_ascii=False,
            ),
            album=None,
        )

        await state.set_state(AddPost.waiting_for_chats)
        await state.update_data(selected_chats=[])
        await show_chat_select(message, state)
        return

    # ----------------------------------------------------------
    # Одиночные медиа / текст
    # ----------------------------------------------------------
    if message.text:
        await state.update_data(content_type="text", content=message.text)

    elif message.photo:
        await state.update_data(
            content_type="photo",
            content=json.dumps(
                {"file_id": message.photo[-1].file_id, "caption": message.caption},
                ensure_ascii=False,
            ),
        )

    elif message.video:
        await state.update_data(
            content_type="video",
            content=json.dumps(
                {"file_id": message.video.file_id, "caption": message.caption},
                ensure_ascii=False,
            ),
        )

    elif message.document:
        await state.update_data(
            content_type="document",
            content=json.dumps(
                {"file_id": message.document.file_id, "caption": message.caption},
                ensure_ascii=False,
            ),
        )

    elif message.voice:
        await state.update_data(
            content_type="voice",
            content=json.dumps(
                {"file_id": message.voice.file_id, "caption": message.caption},
                ensure_ascii=False,
            ),
        )

    elif message.audio:
        await state.update_data(
            content_type="audio",
            content=json.dumps(
                {"file_id": message.audio.file_id, "caption": message.caption},
                ensure_ascii=False,
            ),
        )

    elif message.video_note:
        await state.update_data(
            content_type="video_note",
            content=json.dumps({"file_id": message.video_note.file_id}),
        )

    elif message.animation:
        await state.update_data(
            content_type="animation",
            content=json.dumps(
                {"file_id": message.animation.file_id, "caption": message.caption},
                ensure_ascii=False,
            ),
        )

    else:
        await message.answer("Этот тип контента пока не поддерживается.")
        return

    # ✅ после контента — выбор чатов
    await state.set_state(AddPost.waiting_for_chats)
    await state.update_data(selected_chats=[])
    await show_chat_select(message, state)


# ============================================================
#         3.2 ВЫБОР ЧАТОВ
# ============================================================


@router.callback_query(AddPost.waiting_for_chats, F.data.startswith("toggle_chat:"))
async def toggle_chat(callback: types.CallbackQuery, state: FSMContext):
    chat_id = callback.data.split(":")[1]

    data = await state.get_data()
    selected = set(data.get("selected_chats", []))

    if chat_id in selected:
        selected.remove(chat_id)
    else:
        selected.add(chat_id)

    await state.update_data(selected_chats=list(selected))

    chats = await get_all_chats()
    kb = build_chat_select_kb(chats, selected)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@router.callback_query(AddPost.waiting_for_chats, F.data == "select_all_chats")
async def select_all_chats(callback: types.CallbackQuery, state: FSMContext):
    chats = await get_all_chats()
    new_selected = {c["id"] for c in chats}

    data = await state.get_data()
    current_selected = set(data.get("selected_chats", []))

    # если уже всё выбрано — ничего не делаем
    if new_selected == current_selected:
        await callback.answer("Все чаты уже выбраны ✅")
        return

    await state.update_data(selected_chats=list(new_selected))

    kb = build_chat_select_kb(chats, new_selected)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@router.callback_query(AddPost.waiting_for_chats, F.data == "back_to_content")
async def back_to_content(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddPost.waiting_for_content)
    await callback.message.edit_text("Ок, пришли контент заново (текст/медиа/альбом).")
    await callback.answer()


@router.callback_query(AddPost.waiting_for_chats, F.data == "confirm_chats")
async def confirm_chats(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_chats", [])

    if not selected:
        await callback.answer("Выбери хотя бы один чат", show_alert=True)
        return

    await state.set_state(AddPost.waiting_for_action)
    await callback.message.edit_text(
        "Чаты выбраны. Как публикуем?", reply_markup=build_publish_or_schedule_kb()
    )
    await callback.answer()


# ============================================================
#               3.3 ВЫБОР ДЕЙСТВИЯ
# ============================================================


@router.callback_query(AddPost.waiting_for_action, F.data == "post_action:cancel")
async def cancel_post(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Пост отменён ❌")
    await callback.answer()


@router.callback_query(AddPost.waiting_for_action, F.data == "post_action:now")
async def publish_now(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chat_ids = data.get("selected_chats", [])

    await publish_now_to_chats(
        callback.message.bot,
        chat_ids,
        data["content_type"],
        data["content"],
        data.get("post_buttons"),
    )

    await state.clear()
    await callback.message.edit_text("Пост опубликован прямо сейчас ✅")
    await callback.message.answer("Что дальше?", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(AddPost.waiting_for_action, F.data == "post_action:schedule")
async def choose_schedule(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddPost.waiting_for_date)
    await callback.message.edit_text(
        "Выбери дату публикации:", reply_markup=build_date_choice_kb()
    )
    await callback.answer()


# ============================================================
#                4. БЫСТРЫЕ ДАТЫ + КАЛЕНДАРЬ
# ============================================================


@router.callback_query(AddPost.waiting_for_date, F.data.startswith("pick_date:"))
async def pick_quick_date(callback: types.CallbackQuery, state: FSMContext):
    kind = callback.data.split(":")[1]
    today = datetime.now(LA).date()

    if kind == "today":
        chosen = today
    elif kind == "tomorrow":
        chosen = today + timedelta(days=1)
    elif kind == "after2":
        chosen = today + timedelta(days=2)
    else:
        chosen = datetime.strptime(kind, "%Y-%m-%d").date()

    await state.update_data(chosen_date=str(chosen))
    await state.set_state(AddPost.waiting_for_time)

    await callback.message.answer(
        "Теперь введи время в формате: ЧЧ ММ (например 14 30)"
    )
    await callback.answer()


@router.callback_query(AddPost.waiting_for_date, F.data == "open_calendar")
async def open_calendar(callback: types.CallbackQuery):
    now = datetime.now(LA)
    kb = build_calendar(now.year, now.month)
    await callback.message.edit_text("Выбери дату:", reply_markup=kb)
    await callback.answer()


@router.callback_query(AddPost.waiting_for_date, F.data.startswith("calendar_prev:"))
async def prev_month(callback: types.CallbackQuery):
    _, year, month = callback.data.split(":")
    year = int(year)
    month = int(month) - 1
    if month == 0:
        month = 12
        year -= 1

    kb = build_calendar(year, month)
    await callback.message.edit_text("Выбери дату:", reply_markup=kb)
    await callback.answer()


@router.callback_query(AddPost.waiting_for_date, F.data.startswith("calendar_next:"))
async def next_month(callback: types.CallbackQuery):
    _, year, month = callback.data.split(":")
    year = int(year)
    month = int(month) + 1
    if month == 13:
        month = 1
        year += 1

    kb = build_calendar(year, month)
    await callback.message.edit_text("Выбери дату:", reply_markup=kb)
    await callback.answer()


@router.callback_query(AddPost.waiting_for_date, F.data == "calendar_close")
async def close_calendar(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "Выбери дату публикации (New York):", reply_markup=build_date_choice_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("calendar_pick:"), AddPost.waiting_for_date)
async def pick_calendar_date(callback: types.CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":")[1]

    data = await state.get_data()
    selected_dates = set(data.get("selected_dates", []))

    if date_str in selected_dates:
        selected_dates.remove(date_str)
    else:
        selected_dates.add(date_str)

    await state.update_data(selected_dates=list(selected_dates))

    await callback.answer(
        f"Выбрано дат: {len(selected_dates)}",
        show_alert=False,
    )


@router.callback_query(F.data == "calendar_confirm", AddPost.waiting_for_date)
async def calendar_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    dates = data.get("selected_dates", [])

    if not dates:
        await callback.answer("Выбери хотя бы одну дату", show_alert=True)
        return

    await state.set_state(AddPost.waiting_for_schedule_input)

    await callback.message.edit_text(
        "⏱ Введи время или интервал публикации:\n\n"
        "Примеры:\n"
        "• 12 30 — один раз в день\n"
        "• каждые 2 часа\n"
        "• каждые 30 минут"
    )
    await callback.answer()


# ============================================================
#                5. ВВОД ВРЕМЕНИ → СОХРАНЕНИЕ
# ============================================================


@router.message(AddPost.waiting_for_time)
async def choose_time(message: types.Message, state: FSMContext):
    try:
        hour, minute = map(int, message.text.split())
        if hour > 23 or minute > 59:
            raise ValueError
    except Exception:
        await message.answer("Неверный формат. Пример: 14 30")
        return

    data = await state.get_data()
    chosen_date = datetime.fromisoformat(data["chosen_date"])

    publish_dt = LA.localize(
        datetime(chosen_date.year, chosen_date.month, chosen_date.day, hour, minute)
    )

    content = data["content"]
    if isinstance(content, dict):
        content = json.dumps(content, ensure_ascii=False)

    # ✅ сохраняем пост (без channel_id)
    post_id = await save_post(data["content_type"], content, publish_dt.isoformat())

    # ✅ сохраняем цели (чаты)
    chat_ids = data.get("selected_chats", [])
    await add_post_targets(post_id, chat_ids)

    # ⬇️⬇️⬇️ ВОТ СЮДА ⬇️⬇️⬇️

    # ✅ сохраняем inline-кнопки (если есть)
    buttons = data.get("post_buttons")
    if buttons:
        await save_post_buttons(post_id, buttons)

    # ✅ планируем задачу
    schedule_post(message.bot, post_id, publish_dt)

    await message.answer(
        f"Готово! 🎉\nПост запланирован на {publish_dt.strftime('%Y-%m-%d %H:%M')} New York.\n"
        f"Чатов выбрано: {len(chat_ids)}",
        reply_markup=admin_menu(),
    )

    await state.clear()


@router.message(AddPost.waiting_for_schedule_input)
async def parse_schedule_input(message: types.Message, state: FSMContext):
    text = message.text.lower().strip()

    # ---- 12 30 ----
    m = re.match(r"^(\d{1,2})\s+(\d{1,2})$", text)
    if m:
        hour, minute = map(int, m.groups())
        if hour > 23 or minute > 59:
            await message.answer("❌ Неверное время")
            return

        await state.update_data(
            schedule_type="once_per_day",
            hour=hour,
            minute=minute,
        )

        await message.answer("✅ Принято. Публикация раз в день.")
        return

    # ---- каждые N часов ----
    m = re.match(r"каждые?\s+(\d+)\s*час", text)
    if m:
        hours = int(m.group(1))
        await state.update_data(
            schedule_type="interval_hours",
            value=hours,
        )
        await message.answer(f"✅ Принято. Каждые {hours} часа.")
        return

    # ---- каждые N минут ----
    m = re.match(r"каждые?\s+(\d+)\s*мин", text)
    if m:
        minutes = int(m.group(1))
        await state.update_data(
            schedule_type="interval_minutes",
            value=minutes,
        )
        await message.answer(f"✅ Принято. Каждые {minutes} минут.")
        return

    await message.answer(
        "❌ Не понял формат.\n\n"
        "Примеры:\n"
        "12 30\n"
        "каждые 2 часа\n"
        "каждые 30 минут"
    )


# ============================================================
#                 6. ПАГИНАЦИЯ СПИСКА
# ============================================================


@router.callback_query(F.data.startswith("posts_page:"))
async def paginate_posts(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_ID:
        return await callback.answer()

    _, page_str = callback.data.split(":")
    page = int(page_str)
    offset = (page - 1) * PAGE_SIZE

    posts = await get_pending_posts_page(PAGE_SIZE, offset)

    if not posts:
        await callback.message.edit_text("Нет постов 💤")
        return

    kb = build_posts_list_kb(posts, page, PAGE_SIZE)
    await callback.message.edit_text("Вот твои запланированные посты:", reply_markup=kb)
    await callback.answer()


@router.message(F.text == "➕ Добавить чат")
async def add_chat_start(message: types.Message):
    if message.from_user.id not in ADMIN_ID:
        return

    await message.answer(
        "Перешли сообщение из канала или группы, куда бот должен публиковать посты.\n\n"
        "❗️Важно:\n"
        "— бот должен быть добавлен в этот чат\n"
        "— у бота должны быть права на отправку сообщений"
    )


@router.message(F.forward_from_chat)
async def add_chat_forwarded(message: types.Message):
    if message.from_user.id not in ADMIN_ID:
        return

    chat = message.forward_from_chat

    chat_id = str(chat.id)
    title = chat.title
    chat_type = chat.type  # channel / group / supergroup

    await add_chat(chat_id, title, chat_type)

    await message.answer(
        f"✅ Чат добавлен!\n\n"
        f"📌 Название: {title}\n"
        f"🆔 ID: {chat_id}\n"
        f"📂 Тип: {chat_type}",
        reply_markup=admin_menu(),
    )


@router.my_chat_member()
async def bot_added_to_chat(event: types.ChatMemberUpdated):
    """
    Срабатывает, когда бота добавляют в чат / канал
    """
    new_status = event.new_chat_member.status

    # бот стал участником или админом
    if new_status in ("member", "administrator"):
        chat = event.chat

        from utils.db import add_chat

        await add_chat(chat_id=str(chat.id), title=chat.title, chat_type=chat.type)

        # если это личка админа — можем уведомить
        if event.from_user and event.from_user.id in ADMIN_ID:
            try:
                await event.bot.send_message(
                    event.from_user.id,
                    f"✅ Чат автоматически добавлен:\n\n"
                    f"📌 {chat.title}\n"
                    f"🆔 {chat.id}",
                )
            except:
                pass


@router.callback_query(AddPost.waiting_for_action, F.data == "post_action:buttons")
async def add_buttons_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddPost.waiting_for_buttons)

    await callback.message.edit_text(
        "ℹ️ Для создания кнопок соблюдай формат:\n\n"
        "Название - ссылка\n"
        "Название - ссылка\n\n"
        "Результат: кнопки в столбик\n\n"
        "Название - ссылка | Название - ссылка\n"
        "Результат: кнопки в ряд\n\n"
        "Отправь текст с кнопками 👇"
    )
    await callback.answer()


def normalize_url(raw: str) -> str:
    raw = raw.strip()

    # @username → https://t.me/username
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"

    # t.me/channel
    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        return f"https://{raw}"

    # обычная ссылка
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    # fallback (Telegram сам попробует)
    return raw


def parse_buttons(text: str) -> list[dict]:
    """
    Формат:
    Текст - ссылка
    Текст - @username
    Текст - ссылка | Текст - ссылка
    """

    buttons = []
    row_index = 0

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = [p.strip() for p in line.split("|")]

        for part in parts:
            if "-" not in part:
                continue

            left, right = part.split("-", 1)

            text_btn = left.strip()
            raw_link = right.strip()

            if not text_btn or not raw_link:
                continue

            buttons.append(
                {
                    "row": row_index,
                    "text": text_btn,
                    "url": normalize_url(raw_link),
                }
            )

        row_index += 1

    return buttons


@router.message(AddPost.waiting_for_buttons)
async def receive_buttons(message: types.Message, state: FSMContext):
    buttons = parse_buttons(message.text)

    if not buttons:
        await message.answer(
            "❌ Не удалось распознать кнопки.\n\n"
            "Пример:\n"
            "Написать мне - @username\n"
            "Канал - @channel | Сайт - https://site.com"
        )
        return

    data = await state.get_data()
    content_type = data["content_type"]
    raw_content = data["content"]

    kb = build_post_buttons_kb(buttons)

    # --- ТЕКСТ ---
    if content_type == "text":
        await message.answer(raw_content, reply_markup=kb)

    # --- ОДИНОЧНОЕ МЕДИА ---
    elif content_type in (
        "photo",
        "video",
        "document",
        "audio",
        "voice",
        "animation",
        "video_note",
    ):
        media = json.loads(raw_content)
        file_id = media["file_id"]
        caption = media.get("caption")

        if content_type == "photo":
            await message.answer_photo(file_id, caption=caption, reply_markup=kb)
        elif content_type == "video":
            await message.answer_video(file_id, caption=caption, reply_markup=kb)
        elif content_type == "document":
            await message.answer_document(file_id, caption=caption, reply_markup=kb)
        elif content_type == "audio":
            await message.answer_audio(file_id, caption=caption, reply_markup=kb)
        elif content_type == "voice":
            await message.answer_voice(file_id, caption=caption, reply_markup=kb)
        elif content_type == "animation":
            await message.answer_animation(file_id, caption=caption, reply_markup=kb)
        elif content_type == "video_note":
            await message.answer_video_note(file_id)

    # --- АЛЬБОМ ---
    elif content_type == "media_group":
        album = json.loads(raw_content)
        caption = album.get("caption", "")
        await message.answer(
            f"📸 Альбом из {len(album['items'])} медиа\n\n{caption}",
            reply_markup=kb,
        )

    # сохраняем кнопки в FSM
    await state.update_data(post_buttons=buttons)

    await state.set_state(AddPost.waiting_for_action)
    await message.answer(
        "✅ Предпросмотр готов. Что делаем дальше?",
        reply_markup=build_publish_or_schedule_kb(),
    )
