import json
from asyncio import create_task, sleep
from datetime import datetime

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS, DEFAULT_TIMEZONE
from keyboards.calendar_kb import build_calendar
from keyboards.chat_select import build_chat_select_kb
from keyboards.inline_admin import build_posts_list_kb
from keyboards.main_menu import admin_menu
from keyboards.post_flow import (
    build_action_kb,
    build_editor_kb,
    build_month_days_kb,
    build_repeat_confirm_kb,
    build_repeat_mode_kb,
    build_weekdays_kb,
)
from utils.access import AdminOnlyFilter
from utils.db import (
    add_chat,
    add_post_targets,
    delete_chat,
    delete_post_buttons,
    disable_recurrence,
    get_active_recurrence,
    get_all_chats,
    get_pending_posts_page,
    get_post,
    get_post_buttons,
    get_post_targets,
    replace_post_targets,
    save_post,
    save_post_buttons,
    update_post,
    upsert_recurrence_rule,
)
from utils.posting import (
    build_text_storage_payload,
    publish_to_targets,
    send_post_content,
    serialize_entities,
)
from utils.recurrence import (
    build_recurrence_config,
    describe_recurrence,
    get_timezone,
    summarize_recurrence,
)
from utils.repeat_time_parser import parse_repeat_time
from utils.scheduler import schedule_post


router = Router()
router.message.filter(AdminOnlyFilter())
router.callback_query.filter(AdminOnlyFilter())
PAGE_SIZE = 5


class PostFlow(StatesGroup):
    choosing_chats = State()
    waiting_initial_content = State()
    editing_post = State()
    waiting_text = State()
    waiting_media = State()
    waiting_buttons = State()
    choosing_action = State()
    choosing_repeat_mode = State()
    choosing_dates = State()
    choosing_weekdays = State()
    choosing_month_days = State()
    waiting_repeat_time = State()
    confirming_repeat = State()


def register_admin_handlers(dp):
    dp.include_router(router)


def normalize_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"
    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        return f"https://{raw}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return raw


def parse_buttons(text: str) -> list[dict]:
    buttons = []
    row_index = 0

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = [part.strip() for part in line.split("|")]
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


def _has_content(data: dict) -> bool:
    return bool(data.get("draft_text") or data.get("draft_media_type"))


def _compose_post_from_draft(data: dict) -> tuple[str, str]:
    draft_text = data.get("draft_text")
    draft_text_entities = data.get("draft_text_entities")
    media_type = data.get("draft_media_type")
    media_payload = data.get("draft_media_payload")

    if not media_type:
        if not draft_text:
            raise ValueError("Сначала добавь текст или медиа")
        return "text", build_text_storage_payload(draft_text, draft_text_entities)

    if media_type == "media_group":
        payload = {
            "items": media_payload["items"],
            "caption": draft_text,
            "caption_entities": draft_text_entities,
        }
        return media_type, json.dumps(payload, ensure_ascii=False)

    payload = dict(media_payload)
    payload["caption"] = draft_text
    payload["caption_entities"] = draft_text_entities
    return media_type, json.dumps(payload, ensure_ascii=False)


def _build_editor_summary(data: dict) -> str:
    selected_chats = data.get("selected_chats", [])
    buttons = data.get("draft_buttons", [])
    text_status = "есть" if data.get("draft_text") else "нет"
    media_type = data.get("draft_media_type")

    if media_type == "media_group":
        media_status = "альбом"
    elif media_type:
        media_status = media_type
    else:
        media_status = "нет"

    return (
        "Редактирование поста:\n\n"
        f"Чатов выбрано: {len(selected_chats)}\n"
        f"Текст: {text_status}\n"
        f"Медиа: {media_status}\n"
        f"Кнопок: {len(buttons)}"
    )


def build_manage_chats_kb(chats: list[dict]) -> types.InlineKeyboardMarkup:
    rows = []
    for chat in chats:
        title = chat.get("title") or chat["id"]
        rows.append(
            [
                types.InlineKeyboardButton(
                    text=f"🗑 {title}",
                    callback_data=f"delete_chat:{chat['id']}",
                )
            ]
        )

    rows.append(
        [
            types.InlineKeyboardButton(
                text="⬅ Закрыть",
                callback_data="manage_chats:close",
            )
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_draft_preview(bot: Bot, chat_id: int, data: dict):
    if not _has_content(data):
        return

    content_type, raw_content = _compose_post_from_draft(data)
    await send_post_content(
        bot=bot,
        chat_id=chat_id,
        content_type=content_type,
        raw_content=raw_content,
        buttons=data.get("draft_buttons"),
        preview_mode=True,
    )


async def _show_editor(chat: types.Message | types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bot = chat.bot if isinstance(chat, types.Message) else chat.message.bot
    chat_id = chat.chat.id if isinstance(chat, types.Message) else chat.message.chat.id

    await _send_draft_preview(bot, chat_id, data)

    text = _build_editor_summary(data)
    keyboard = build_editor_kb(
        has_text=bool(data.get("draft_text")),
        has_media=bool(data.get("draft_media_type")),
        has_buttons=bool(data.get("draft_buttons")),
    )

    if isinstance(chat, types.CallbackQuery):
        await chat.message.edit_text(text, reply_markup=keyboard)
        await chat.answer()
    else:
        await chat.answer(text, reply_markup=keyboard)


async def _show_chat_selector(
    target: types.Message | types.CallbackQuery,
    state: FSMContext,
):
    chats = await get_all_chats()
    if not chats:
        text = (
            "Нет добавленных чатов.\n\n"
            "Добавь чат через кнопку `➕ Добавить чат`, "
            "или просто добавь бота в нужный канал/группу."
        )
        if isinstance(target, types.CallbackQuery):
            await target.message.edit_text(text)
            await target.answer()
        else:
            await target.answer(text)
        await state.clear()
        return

    data = await state.get_data()
    selected = set(data.get("selected_chats", []))
    kb = build_chat_select_kb(chats, selected)

    text = "Сначала выбери чаты, куда будет публиковаться пост:"
    if isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb)


async def _hydrate_existing_post(post_id: int, state: FSMContext):
    post = await get_post(post_id)
    if not post:
        raise ValueError("Пост не найден")

    buttons = await get_post_buttons(post_id)
    targets = await get_post_targets(post_id)

    draft_data = {
        "editing_post_id": post_id,
        "selected_chats": targets,
        "draft_buttons": buttons,
        "draft_text_entities": None,
    }

    if post["type"] == "text":
        try:
            payload = json.loads(post["content"])
            if isinstance(payload, dict) and "text" in payload:
                draft_data["draft_text"] = payload.get("text")
                draft_data["draft_text_entities"] = payload.get("entities")
            else:
                draft_data["draft_text"] = post["content"]
        except Exception:
            draft_data["draft_text"] = post["content"]
        draft_data["draft_media_type"] = None
        draft_data["draft_media_payload"] = None
    elif post["type"] == "media_group":
        payload = json.loads(post["content"])
        draft_data["draft_text"] = payload.get("caption")
        draft_data["draft_text_entities"] = payload.get("caption_entities")
        draft_data["draft_media_type"] = "media_group"
        draft_data["draft_media_payload"] = {"items": payload.get("items", [])}
    else:
        payload = json.loads(post["content"])
        draft_data["draft_text"] = payload.get("caption")
        draft_data["draft_text_entities"] = payload.get("caption_entities")
        draft_data["draft_media_type"] = post["type"]
        payload.pop("caption", None)
        payload.pop("caption_entities", None)
        draft_data["draft_media_payload"] = payload

    await state.update_data(**draft_data)


async def _save_or_update_post(
    bot: Bot,
    state: FSMContext,
    recurrence_config: dict | None,
    first_run_at: datetime,
    end_at: datetime | None,
):
    data = await state.get_data()
    post_type, raw_content = _compose_post_from_draft(data)
    buttons = data.get("draft_buttons", [])
    chat_ids = data.get("selected_chats", [])
    editing_post_id = data.get("editing_post_id")

    if editing_post_id:
        await update_post(
            editing_post_id,
            new_content=raw_content,
            new_type=post_type,
            new_publish_time=first_run_at.isoformat(),
            new_status="pending",
        )
        await replace_post_targets(editing_post_id, chat_ids)
        await delete_post_buttons(editing_post_id)
        if buttons:
            await save_post_buttons(editing_post_id, buttons)
        post_id = editing_post_id
    else:
        post_id = await save_post(post_type, raw_content, first_run_at.isoformat())
        await add_post_targets(post_id, chat_ids)
        if buttons:
            await save_post_buttons(post_id, buttons)

    if recurrence_config:
        await upsert_recurrence_rule(
            post_id=post_id,
            config=recurrence_config,
            next_run_at=first_run_at.isoformat(),
            end_at=end_at.isoformat() if end_at else None,
            timezone_name=recurrence_config.get("timezone", DEFAULT_TIMEZONE),
        )
    else:
        await disable_recurrence(post_id)

    schedule_post(bot, post_id, first_run_at)
    return post_id


def _format_dt(value: datetime | None) -> str:
    if not value:
        return "Без окончания"
    return value.strftime("%Y-%m-%d %H:%M")


def _build_repeat_confirmation_text(config: dict, summary: dict) -> str:
    total = summary["total_publications"]
    total_text = str(total) if total is not None else "не ограничено"

    return (
        "Подтверждение расписания:\n\n"
        f"Правило: {describe_recurrence(config)}\n"
        f"Первая отправка: {_format_dt(summary['first_run_at'])}\n"
        f"Дата окончания: {_format_dt(summary['end_at'])}\n"
        f"Количество публикаций: {total_text}"
    )


@router.callback_query(F.data == "draft_cancel")
async def draft_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Создание поста отменено.")
    await callback.message.answer("Что дальше?", reply_markup=admin_menu())
    await callback.answer()


@router.message(F.text == "📝 Добавить пост")
async def add_post(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    now = datetime.now(get_timezone(DEFAULT_TIMEZONE))
    await state.clear()
    await state.set_state(PostFlow.choosing_chats)
    await state.update_data(
        selected_chats=[],
        draft_text=None,
        draft_text_entities=None,
        draft_media_type=None,
        draft_media_payload=None,
        draft_buttons=[],
        editing_post_id=None,
        awaiting_initial_content=False,
        calendar_year=now.year,
        calendar_month=now.month,
    )
    await _show_chat_selector(message, state)


@router.message(F.text == "📋 Мои запланированные")
async def list_my_posts(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    posts = await get_pending_posts_page(PAGE_SIZE, 0)
    if not posts:
        await message.answer("У тебя нет активных запланированных постов.")
        return

    await message.answer(
        "Вот твои запланированные посты:",
        reply_markup=build_posts_list_kb(posts, page=1, page_size=PAGE_SIZE),
    )


@router.callback_query(PostFlow.choosing_chats, F.data.startswith("toggle_chat:"))
async def toggle_chat(callback: types.CallbackQuery, state: FSMContext):
    chat_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = set(data.get("selected_chats", []))

    if chat_id in selected:
        selected.remove(chat_id)
    else:
        selected.add(chat_id)

    await state.update_data(selected_chats=list(selected))
    chats = await get_all_chats()
    await callback.message.edit_reply_markup(
        reply_markup=build_chat_select_kb(chats, selected)
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_chats, F.data == "select_all_chats")
async def select_all_chats(callback: types.CallbackQuery, state: FSMContext):
    chats = await get_all_chats()
    selected = {chat["id"] for chat in chats}
    await state.update_data(selected_chats=list(selected))
    await callback.message.edit_reply_markup(
        reply_markup=build_chat_select_kb(chats, selected)
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_chats, F.data == "confirm_chats")
async def confirm_chats(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("selected_chats"):
        await callback.answer("Выбери хотя бы один чат", show_alert=True)
        return

    await state.update_data(awaiting_initial_content=True)
    await state.set_state(PostFlow.waiting_initial_content)
    await callback.message.edit_text(
        "Теперь отправь сам пост целиком.\n\n"
        "Можно прислать:\n"
        "текст,\n"
        "фото с текстом,\n"
        "видео,\n"
        "документ,\n"
        "альбом."
    )
    await callback.answer()


@router.callback_query(PostFlow.editing_post, F.data == "draft_back:chats")
async def back_to_chats(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PostFlow.choosing_chats)
    await _show_chat_selector(callback, state)


@router.callback_query(PostFlow.editing_post, F.data == "draft_edit:text")
async def start_edit_text(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PostFlow.waiting_text)
    await callback.message.answer("Пришли новый текст поста.")
    await callback.answer()


@router.message(PostFlow.waiting_text)
async def receive_text(message: types.Message, state: FSMContext):
    await state.update_data(
        draft_text=message.text,
        draft_text_entities=serialize_entities(message.entities),
    )
    await state.set_state(PostFlow.editing_post)
    await _show_editor(message, state)


@router.callback_query(PostFlow.editing_post, F.data == "draft_edit:media")
async def start_edit_media(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PostFlow.waiting_media)
    await state.update_data(album=None)
    await callback.message.answer(
        "Пришли медиа.\n"
        "Поддерживается фото, видео, документ, аудио, voice, GIF и альбомы."
    )
    await callback.answer()


@router.message(PostFlow.waiting_initial_content)
@router.message(PostFlow.waiting_media)
async def receive_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    awaiting_initial_content = bool(data.get("awaiting_initial_content"))

    if message.text and awaiting_initial_content:
        await state.update_data(
            draft_text=message.text,
            draft_text_entities=serialize_entities(message.entities),
            draft_media_type=None,
            draft_media_payload=None,
            awaiting_initial_content=False,
        )
        await state.set_state(PostFlow.editing_post)
        await _show_editor(message, state)
        return

    if message.text and not awaiting_initial_content:
        await message.answer("Для замены медиа пришли именно медиафайл, а не текст.")
        return

    if message.media_group_id:
        album = data.get("album") or {
            "media_group_id": message.media_group_id,
            "items": [],
            "caption": None,
            "caption_entities": None,
        }

        if message.caption and not album["caption"]:
            album["caption"] = message.caption
            album["caption_entities"] = serialize_entities(message.caption_entities)

        if message.photo:
            album["items"].append({"type": "photo", "file_id": message.photo[-1].file_id})
        elif message.video:
            album["items"].append({"type": "video", "file_id": message.video.file_id})
        elif message.document:
            album["items"].append({"type": "document", "file_id": message.document.file_id})
        elif message.animation:
            album["items"].append({"type": "animation", "file_id": message.animation.file_id})
        else:
            await message.answer("В альбом можно добавлять только фото, видео, GIF и документы.")
            return

        await state.update_data(album=album)

        async def finalize_album(group_id: str):
            await sleep(0.7)
            latest = await state.get_data()
            buffered = latest.get("album")
            if not buffered or buffered["media_group_id"] != group_id:
                return

            await state.update_data(
                draft_media_type="media_group",
                draft_media_payload={"items": buffered["items"][:10]},
                draft_text=buffered["caption"] or latest.get("draft_text"),
                draft_text_entities=buffered.get("caption_entities"),
                album=None,
                awaiting_initial_content=False,
            )
            await state.set_state(PostFlow.editing_post)
            await _show_editor(message, state)

        create_task(finalize_album(message.media_group_id))
        return

    if message.photo:
        await state.update_data(
            draft_media_type="photo",
            draft_media_payload={"file_id": message.photo[-1].file_id},
            draft_text=message.caption or data.get("draft_text"),
            draft_text_entities=serialize_entities(message.caption_entities),
            awaiting_initial_content=False,
        )
    elif message.video:
        await state.update_data(
            draft_media_type="video",
            draft_media_payload={"file_id": message.video.file_id},
            draft_text=message.caption or data.get("draft_text"),
            draft_text_entities=serialize_entities(message.caption_entities),
            awaiting_initial_content=False,
        )
    elif message.document:
        await state.update_data(
            draft_media_type="document",
            draft_media_payload={"file_id": message.document.file_id},
            draft_text=message.caption or data.get("draft_text"),
            draft_text_entities=serialize_entities(message.caption_entities),
            awaiting_initial_content=False,
        )
    elif message.audio:
        await state.update_data(
            draft_media_type="audio",
            draft_media_payload={"file_id": message.audio.file_id},
            draft_text=message.caption or data.get("draft_text"),
            draft_text_entities=serialize_entities(message.caption_entities),
            awaiting_initial_content=False,
        )
    elif message.voice:
        await state.update_data(
            draft_media_type="voice",
            draft_media_payload={"file_id": message.voice.file_id},
            draft_text=message.caption or data.get("draft_text"),
            draft_text_entities=serialize_entities(message.caption_entities),
            awaiting_initial_content=False,
        )
    elif message.animation:
        await state.update_data(
            draft_media_type="animation",
            draft_media_payload={"file_id": message.animation.file_id},
            draft_text=message.caption or data.get("draft_text"),
            draft_text_entities=serialize_entities(message.caption_entities),
            awaiting_initial_content=False,
        )
    elif message.video_note:
        await state.update_data(
            draft_media_type="video_note",
            draft_media_payload={"file_id": message.video_note.file_id},
            draft_text_entities=None,
            awaiting_initial_content=False,
        )
    else:
        await message.answer("Не удалось распознать медиа. Попробуй ещё раз.")
        return

    await state.set_state(PostFlow.editing_post)
    await _show_editor(message, state)


@router.callback_query(PostFlow.editing_post, F.data == "draft_edit:buttons")
async def start_edit_buttons(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("draft_media_type") == "media_group":
        await callback.answer(
            "Telegram не поддерживает inline-кнопки прямо у альбома. "
            "Для альбома кнопки сейчас недоступны.",
            show_alert=True,
        )
        return

    await state.set_state(PostFlow.waiting_buttons)
    await callback.message.answer(
        "Отправь кнопки в формате:\n\n"
        "Название - ссылка\n"
        "Название - ссылка | Название - ссылка"
    )
    await callback.answer()


@router.message(PostFlow.waiting_buttons)
async def receive_buttons(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("draft_media_type") == "media_group":
        await message.answer(
            "Для альбомов inline-кнопки недоступны: это ограничение Telegram Bot API."
        )
        await state.set_state(PostFlow.editing_post)
        return

    buttons = parse_buttons(message.text)
    if not buttons:
        await message.answer(
            "Не удалось распознать кнопки.\n"
            "Пример: Канал - @channel | Сайт - https://site.com"
        )
        return

    await state.update_data(draft_buttons=buttons)
    await state.set_state(PostFlow.editing_post)
    await _show_editor(message, state)


@router.callback_query(PostFlow.editing_post, F.data == "draft_next:actions")
async def open_action_menu(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not _has_content(data):
        await callback.answer("Сначала добавь текст или медиа", show_alert=True)
        return

    await state.set_state(PostFlow.choosing_action)
    await callback.message.edit_text("Что делаем с постом дальше?", reply_markup=build_action_kb())
    await callback.answer()


@router.callback_query(PostFlow.choosing_action, F.data == "draft_action:back")
async def action_back(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PostFlow.editing_post)
    await _show_editor(callback, state)


@router.callback_query(PostFlow.choosing_action, F.data == "draft_action:publish_now")
async def publish_now(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    content_type, raw_content = _compose_post_from_draft(data)

    await publish_to_targets(
        bot=callback.message.bot,
        chat_ids=data.get("selected_chats", []),
        content_type=content_type,
        raw_content=raw_content,
        buttons=data.get("draft_buttons"),
    )

    await state.clear()
    await callback.message.edit_text("Пост опубликован прямо сейчас.")
    await callback.message.answer("Что дальше?", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(PostFlow.choosing_action, F.data == "draft_action:schedule_once")
async def start_once_schedule(callback: types.CallbackQuery, state: FSMContext):
    now = datetime.now(get_timezone(DEFAULT_TIMEZONE))
    await state.update_data(
        schedule_kind="once",
        repeat_selection={"mode": "dates"},
        repeat_dates=[],
        calendar_year=now.year,
        calendar_month=now.month,
    )
    await state.set_state(PostFlow.choosing_dates)
    await callback.message.edit_text(
        "Выбери одну дату для публикации:",
        reply_markup=build_calendar(now.year, now.month, selected_dates=set()),
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_action, F.data == "draft_action:auto_repeat")
async def start_repeat_setup(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(schedule_kind="repeat")
    await state.set_state(PostFlow.choosing_repeat_mode)
    await callback.message.edit_text(
        "Выбери тип расписания:",
        reply_markup=build_repeat_mode_kb(),
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_repeat_mode, F.data == "repeat_mode:back")
async def repeat_mode_back(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PostFlow.choosing_action)
    await callback.message.edit_text("Что делаем с постом дальше?", reply_markup=build_action_kb())
    await callback.answer()


@router.callback_query(PostFlow.choosing_repeat_mode, F.data == "repeat_mode:dates")
async def repeat_mode_dates(callback: types.CallbackQuery, state: FSMContext):
    now = datetime.now(get_timezone(DEFAULT_TIMEZONE))
    data = await state.get_data()
    selected_dates = set(data.get("repeat_dates", []))

    await state.update_data(
        repeat_selection={"mode": "dates"},
        calendar_year=now.year,
        calendar_month=now.month,
    )
    await state.set_state(PostFlow.choosing_dates)
    await callback.message.edit_text(
        "Выбери одну или несколько дат, затем нажми `Далее`.",
        reply_markup=build_calendar(now.year, now.month, selected_dates=selected_dates),
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_repeat_mode, F.data == "repeat_mode:weekdays")
async def repeat_mode_weekdays(callback: types.CallbackQuery, state: FSMContext):
    selected = set((await state.get_data()).get("repeat_weekdays", []))
    await state.update_data(
        repeat_selection={
            "mode": "weekdays",
            "start_date": datetime.now(get_timezone(DEFAULT_TIMEZONE)).date().isoformat(),
        }
    )
    await state.set_state(PostFlow.choosing_weekdays)
    await callback.message.edit_text(
        "Выбери дни недели:",
        reply_markup=build_weekdays_kb(selected),
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_repeat_mode, F.data == "repeat_mode:month_days")
async def repeat_mode_month_days(callback: types.CallbackQuery, state: FSMContext):
    selected = set((await state.get_data()).get("repeat_month_days", []))
    await state.update_data(
        repeat_selection={
            "mode": "month_days",
            "start_date": datetime.now(get_timezone(DEFAULT_TIMEZONE)).date().isoformat(),
        }
    )
    await state.set_state(PostFlow.choosing_month_days)
    await callback.message.edit_text(
        "Выбери дни месяца:",
        reply_markup=build_month_days_kb(selected),
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_dates, F.data.startswith("calendar_prev:"))
async def repeat_prev_month(callback: types.CallbackQuery, state: FSMContext):
    _, year, month = callback.data.split(":")
    year = int(year)
    month = int(month) - 1
    if month == 0:
        month = 12
        year -= 1

    selected_dates = set((await state.get_data()).get("repeat_dates", []))
    await state.update_data(calendar_year=year, calendar_month=month)
    await callback.message.edit_reply_markup(
        reply_markup=build_calendar(year, month, selected_dates=selected_dates)
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_dates, F.data.startswith("calendar_next:"))
async def repeat_next_month(callback: types.CallbackQuery, state: FSMContext):
    _, year, month = callback.data.split(":")
    year = int(year)
    month = int(month) + 1
    if month == 13:
        month = 1
        year += 1

    selected_dates = set((await state.get_data()).get("repeat_dates", []))
    await state.update_data(calendar_year=year, calendar_month=month)
    await callback.message.edit_reply_markup(
        reply_markup=build_calendar(year, month, selected_dates=selected_dates)
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_dates, F.data.startswith("calendar_pick:"))
async def repeat_pick_date(callback: types.CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected_dates = set(data.get("repeat_dates", []))
    schedule_kind = data.get("schedule_kind", "repeat")

    if schedule_kind == "once":
        selected_dates = {date_str}
    elif date_str in selected_dates:
        selected_dates.remove(date_str)
    else:
        selected_dates.add(date_str)

    await state.update_data(repeat_dates=sorted(selected_dates))
    await callback.message.edit_reply_markup(
        reply_markup=build_calendar(
            data.get("calendar_year"),
            data.get("calendar_month"),
            selected_dates=selected_dates,
        )
    )
    await callback.answer(f"Выбрано дат: {len(selected_dates)}")


@router.callback_query(PostFlow.choosing_dates, F.data == "calendar_close")
async def repeat_dates_back(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PostFlow.choosing_repeat_mode)
    await callback.message.edit_text("Выбери тип расписания:", reply_markup=build_repeat_mode_kb())
    await callback.answer()


@router.callback_query(PostFlow.choosing_dates, F.data == "calendar_confirm")
async def repeat_dates_confirm(callback: types.CallbackQuery, state: FSMContext):
    dates = (await state.get_data()).get("repeat_dates", [])
    if not dates:
        await callback.answer("Выбери хотя бы одну дату", show_alert=True)
        return

    await state.update_data(
        repeat_selection={"mode": "dates", "dates": dates},
    )
    await state.set_state(PostFlow.waiting_repeat_time)
    await callback.message.edit_text(
        "Теперь введи время или интервал.\n\n"
        "Примеры:\n"
        "12:00\n"
        "12 00, 15 00, 18 00\n"
        "30m\n"
        "12h\n"
        "1h 30m"
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_weekdays, F.data.startswith("repeat_weekday:"))
async def toggle_weekday(callback: types.CallbackQuery, state: FSMContext):
    weekday = int(callback.data.split(":")[1])
    selected = set((await state.get_data()).get("repeat_weekdays", []))
    if weekday in selected:
        selected.remove(weekday)
    else:
        selected.add(weekday)

    await state.update_data(repeat_weekdays=sorted(selected))
    await callback.message.edit_reply_markup(reply_markup=build_weekdays_kb(selected))
    await callback.answer()


@router.callback_query(PostFlow.choosing_month_days, F.data.startswith("repeat_month_day:"))
async def toggle_month_day(callback: types.CallbackQuery, state: FSMContext):
    day = int(callback.data.split(":")[1])
    selected = set((await state.get_data()).get("repeat_month_days", []))
    if day in selected:
        selected.remove(day)
    else:
        selected.add(day)

    await state.update_data(repeat_month_days=sorted(selected))
    await callback.message.edit_reply_markup(reply_markup=build_month_days_kb(selected))
    await callback.answer()


@router.callback_query(PostFlow.choosing_weekdays, F.data == "repeat_select:back")
@router.callback_query(PostFlow.choosing_month_days, F.data == "repeat_select:back")
async def repeat_select_back(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PostFlow.choosing_repeat_mode)
    await callback.message.edit_text("Выбери тип расписания:", reply_markup=build_repeat_mode_kb())
    await callback.answer()


@router.callback_query(PostFlow.choosing_weekdays, F.data == "repeat_select:confirm")
async def weekdays_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    weekdays = data.get("repeat_weekdays", [])
    if not weekdays:
        await callback.answer("Выбери хотя бы один день недели", show_alert=True)
        return

    await state.update_data(
        repeat_selection={
            "mode": "weekdays",
            "weekdays": weekdays,
            "start_date": datetime.now(get_timezone(DEFAULT_TIMEZONE)).date().isoformat(),
        }
    )
    await state.set_state(PostFlow.waiting_repeat_time)
    await callback.message.edit_text(
        "Теперь введи время или интервал.\nПримеры: 12:00, 12 00, 30m, 1h 30m"
    )
    await callback.answer()


@router.callback_query(PostFlow.choosing_month_days, F.data == "repeat_select:confirm")
async def month_days_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    days = data.get("repeat_month_days", [])
    if not days:
        await callback.answer("Выбери хотя бы один день месяца", show_alert=True)
        return

    await state.update_data(
        repeat_selection={
            "mode": "month_days",
            "days": days,
            "start_date": datetime.now(get_timezone(DEFAULT_TIMEZONE)).date().isoformat(),
        }
    )
    await state.set_state(PostFlow.waiting_repeat_time)
    await callback.message.edit_text(
        "Теперь введи время или интервал.\nПримеры: 12:00, 12 00, 30m, 1h 30m"
    )
    await callback.answer()


@router.message(PostFlow.waiting_repeat_time)
async def receive_repeat_time(message: types.Message, state: FSMContext):
    try:
        time_selection = parse_repeat_time(message.text)
    except ValueError as exc:
        await message.answer(f"Ошибка: {exc}")
        return

    data = await state.get_data()
    repeat_selection = data.get("repeat_selection")
    if not repeat_selection:
        await message.answer("Сначала выбери тип расписания.")
        return

    recurrence_config = build_recurrence_config(
        date_selection=repeat_selection,
        time_selection=time_selection,
        timezone_name=DEFAULT_TIMEZONE,
    )
    summary = summarize_recurrence(
        recurrence_config,
        now=datetime.now(get_timezone(DEFAULT_TIMEZONE)),
    )

    if not summary["first_run_at"]:
        await message.answer("Нет будущих публикаций. Выбери другое расписание.")
        return

    if data.get("schedule_kind") == "once" and summary["total_publications"] != 1:
        await message.answer(
            "Для одноразового планирования нужна ровно одна дата и одно время."
        )
        return

    await state.update_data(
        recurrence_config=recurrence_config,
        recurrence_summary={
            "first_run_at": summary["first_run_at"].isoformat(),
            "end_at": summary["end_at"].isoformat() if summary["end_at"] else None,
            "total_publications": summary["total_publications"],
        },
    )
    await state.set_state(PostFlow.confirming_repeat)
    await message.answer(
        _build_repeat_confirmation_text(recurrence_config, summary),
        reply_markup=build_repeat_confirm_kb(),
    )


@router.callback_query(PostFlow.confirming_repeat, F.data == "repeat_confirm:back")
async def repeat_confirm_back(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PostFlow.waiting_repeat_time)
    await callback.message.edit_text(
        "Введи новое время или интервал.\nПримеры: 12:00, 12 00, 30m, 1h 30m"
    )
    await callback.answer()


@router.callback_query(PostFlow.confirming_repeat, F.data == "repeat_confirm:yes")
async def repeat_confirm_yes(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    summary = data["recurrence_summary"]
    first_run_at = datetime.fromisoformat(summary["first_run_at"])
    end_at = datetime.fromisoformat(summary["end_at"]) if summary["end_at"] else None
    total_publications = summary["total_publications"]
    recurrence_config = data["recurrence_config"]

    if total_publications == 1:
        recurrence_config = None
        end_at = None

    post_id = await _save_or_update_post(
        bot=callback.message.bot,
        state=state,
        recurrence_config=recurrence_config,
        first_run_at=first_run_at,
        end_at=end_at,
    )

    await state.clear()
    if total_publications == 1:
        text = (
            f"Пост #{post_id} запланирован на {first_run_at.strftime('%Y-%m-%d %H:%M')}."
        )
    else:
        text = (
            f"Пост #{post_id} сохранён.\n"
            f"Первая отправка: {first_run_at.strftime('%Y-%m-%d %H:%M')}"
        )

    await callback.message.edit_text(text)
    await callback.message.answer("Что дальше?", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("edit_schedule:"))
async def edit_existing_schedule(callback: types.CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[1])
    try:
        await state.clear()
        await _hydrate_existing_post(post_id, state)
    except ValueError:
        await callback.answer("Пост не найден", show_alert=True)
        return

    recurrence = await get_active_recurrence(post_id)
    if recurrence:
        config = recurrence["config"]
        selection = config["date_selection"]
        await state.update_data(
            repeat_selection=selection,
            repeat_dates=selection.get("dates", []),
            repeat_weekdays=selection.get("weekdays", []),
            repeat_month_days=selection.get("days", []),
            recurrence_config=config,
        )

    await state.set_state(PostFlow.choosing_repeat_mode)
    await callback.message.answer(
        f"Настраиваем расписание для поста #{post_id}.",
        reply_markup=build_repeat_mode_kb(),
    )
    await callback.answer()


@router.message(F.text == "➕ Добавить чат")
async def add_chat_start(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        "Перешли сообщение из канала или группы, куда бот должен публиковать посты.\n\n"
        "Важно:\n"
        "бот должен быть добавлен в этот чат и иметь право писать сообщения."
    )


@router.message(F.text == "🗂 Управление чатами")
async def manage_chats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    chats = await get_all_chats()
    if not chats:
        await message.answer("Список поддерживаемых чатов пуст.")
        return

    await message.answer(
        "Нажми на чат, который нужно удалить из поддерживаемых:",
        reply_markup=build_manage_chats_kb(chats),
    )


@router.callback_query(F.data.startswith("delete_chat:"))
async def delete_chat_handler(callback: types.CallbackQuery):
    chat_id = callback.data.split(":", 1)[1]
    chats = await get_all_chats()
    chat = next((item for item in chats if item["id"] == chat_id), None)

    await delete_chat(chat_id)

    remaining = await get_all_chats()
    if remaining:
        await callback.message.edit_text(
            f"Чат удалён: {chat['title'] if chat else chat_id}",
            reply_markup=build_manage_chats_kb(remaining),
        )
    else:
        await callback.message.edit_text("Все чаты удалены из поддерживаемых.")
    await callback.answer()


@router.callback_query(F.data == "manage_chats:close")
async def close_manage_chats(callback: types.CallbackQuery):
    await callback.message.edit_text("Управление чатами закрыто.")
    await callback.answer()


@router.message(F.forward_from_chat)
async def add_chat_forwarded(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    chat = message.forward_from_chat
    await add_chat(str(chat.id), chat.title, chat.type)
    await message.answer(
        f"Чат добавлен.\n\nНазвание: {chat.title}\nID: {chat.id}\nТип: {chat.type}",
        reply_markup=admin_menu(),
    )


@router.my_chat_member()
async def bot_added_to_chat(event: types.ChatMemberUpdated):
    new_status = event.new_chat_member.status
    if new_status not in ("member", "administrator"):
        return

    chat = event.chat
    await add_chat(chat_id=str(chat.id), title=chat.title, chat_type=chat.type)

    if event.from_user and event.from_user.id in ADMIN_IDS:
        try:
            await event.bot.send_message(
                event.from_user.id,
                f"Чат автоматически добавлен:\n{chat.title}\n{chat.id}",
            )
        except Exception:
            pass
