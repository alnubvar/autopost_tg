# handlers/auto_repeat.py
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from datetime import datetime, time, timedelta
import pytz

from keyboards.calendar_kb import build_calendar
from utils.repeat_time_parser import parse_repeat_time
from utils.db import create_scheduled_post
from utils.scheduler import schedule_post

router = Router()
LA = pytz.timezone("America/New_York")


# ============================================================
#                     FSM АВТОПОВТОРА
# ============================================================


class AutoRepeat(StatesGroup):
    choosing_dates = State()
    choosing_time = State()
    confirm = State()


# ============================================================
#               СТАРТ АВТОПОВТОРА
# ============================================================


@router.callback_query(F.data.startswith("post_action:auto_repeat:"))
async def start_auto_repeat(callback: types.CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split(":")[-1])

    await state.clear()
    await state.set_state(AutoRepeat.choosing_dates)

    now = datetime.now(LA)

    await state.update_data(
        post_id=post_id,
        repeat_dates=set(),
        year=now.year,
        month=now.month,
    )

    await callback.message.answer(
        "📆 <b>Выбери даты автоповтора</b>\n\n"
        "Можно выбрать несколько дат.\n"
        "После выбора нажми ➡ Далее",
        reply_markup=build_calendar(now.year, now.month),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#            ПЕРЕКЛЮЧЕНИЕ МЕСЯЦЕВ
# ============================================================


@router.callback_query(AutoRepeat.choosing_dates, F.data.startswith("calendar_prev:"))
async def prev_month(callback: types.CallbackQuery, state: FSMContext):
    _, year, month = callback.data.split(":")
    year, month = int(year), int(month) - 1
    if month == 0:
        month = 12
        year -= 1

    await state.update_data(year=year, month=month)
    await callback.message.edit_reply_markup(reply_markup=build_calendar(year, month))
    await callback.answer()


@router.callback_query(AutoRepeat.choosing_dates, F.data.startswith("calendar_next:"))
async def next_month(callback: types.CallbackQuery, state: FSMContext):
    _, year, month = callback.data.split(":")
    year, month = int(year), int(month) + 1
    if month == 13:
        month = 1
        year += 1

    await state.update_data(year=year, month=month)
    await callback.message.edit_reply_markup(reply_markup=build_calendar(year, month))
    await callback.answer()


# ============================================================
#                ВЫБОР ДАТЫ
# ============================================================


@router.callback_query(AutoRepeat.choosing_dates, F.data.startswith("calendar_pick:"))
async def pick_date(callback: types.CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":")[1]

    data = await state.get_data()
    dates = data.get("repeat_dates", set())

    if date_str in dates:
        dates.remove(date_str)
    else:
        dates.add(date_str)

    await state.update_data(repeat_dates=dates)
    await callback.answer(f"Выбрано дат: {len(dates)}")


# ============================================================
#                   КНОПКА ДАЛЕЕ
# ============================================================


@router.callback_query(AutoRepeat.choosing_dates, F.data == "calendar_confirm")
async def confirm_dates(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("repeat_dates"):
        await callback.answer("Выбери хотя бы одну дату ❗", show_alert=True)
        return

    await state.set_state(AutoRepeat.choosing_time)
    await callback.message.answer(
        "⏰ <b>Теперь введи время публикации</b>\n\n"
        "Примеры:\n"
        "• <code>12:00</code>\n"
        "• <code>12 00, 18 00</code>\n"
        "• <code>30m</code>\n"
        "• <code>1h 30m</code>",
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#            HELPERS (генерация будущих дат)
# ============================================================


def _parse_date_str(d: str):
    # d: "YYYY-MM-DD"
    return datetime.strptime(d, "%Y-%m-%d").date()


def _future_datetimes(repeat_dates: list[str], repeat_time: dict) -> list[datetime]:
    """
    Генерим ТОЛЬКО будущие datetime (tz-aware, LA).
    Это убирает 'Run time was missed' на 100%.
    """
    now = datetime.now(LA)
    out: list[datetime] = []

    if repeat_time["type"] == "fixed":
        for d in repeat_dates:
            day = _parse_date_str(d)

            # если дата уже в прошлом — пропускаем
            if day < now.date():
                continue

            for t in repeat_time["times"]:
                h, m = map(int, t.split(":"))
                dt = LA.localize(datetime.combine(day, time(h, m)))

                # только будущее
                if dt > now:
                    out.append(dt)

        return sorted(out)

    # interval/step mode
    step = timedelta(minutes=repeat_time["step_minutes"])

    for d in repeat_dates:
        day = _parse_date_str(d)

        # если дата уже в прошлом — пропускаем
        if day < now.date():
            continue

        day_start = LA.localize(datetime.combine(day, time(0, 0)))
        day_end = LA.localize(datetime.combine(day, time(23, 59)))

        # если это сегодня — стартуем не с полуночи, а с "сейчас"
        current = day_start
        if day == now.date():
            current = max(current, now)

            # чтобы не шлёпать "впритык", можно чуть округлить вверх на минуту
            # (по желанию — можно убрать)
            current = current.replace(second=0, microsecond=0) + timedelta(minutes=1)

        while current <= day_end:
            out.append(current)
            current += step

    return sorted(out)


# ============================================================
#              ВВОД ВРЕМЕНИ
# ============================================================


@router.message(AutoRepeat.choosing_time)
async def process_repeat_time(message: types.Message, state: FSMContext):
    try:
        repeat_time = parse_repeat_time(message.text)
    except ValueError as e:
        await message.answer(f"⚠️ {e}")
        return

    await state.update_data(repeat_time=repeat_time)
    await state.set_state(AutoRepeat.confirm)

    data = await state.get_data()
    repeat_dates = sorted(list(data["repeat_dates"]))

    # считаем именно будущие публикации
    datetimes = _future_datetimes(repeat_dates, repeat_time)

    if repeat_time["type"] == "fixed":
        time_text = ", ".join(repeat_time["times"])
    else:
        time_text = f"каждые {repeat_time['step_minutes']} мин"

    await message.answer(
        "📅 <b>Автоповтор будет создан</b>\n\n"
        f"🗓 Дат выбрано: {len(repeat_dates)}\n"
        f"⏰ Время: {time_text}\n"
        f"📦 Будущих публикаций: <b>{len(datetimes)}</b>\n\n"
        "Подтвердить?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Подтвердить", callback_data="auto_repeat_confirm"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отменить", callback_data="auto_repeat_cancel"
                    ),
                ]
            ]
        ),
        parse_mode="HTML",
    )


# ============================================================
#               ОТМЕНА
# ============================================================


@router.callback_query(F.data == "auto_repeat_cancel")
async def cancel_auto_repeat(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Автоповтор отменён")
    await callback.answer()


# ============================================================
#               ПОДТВЕРЖДЕНИЕ
# ============================================================


@router.callback_query(F.data == "auto_repeat_confirm")
async def confirm_auto_repeat(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    base_post_id = data.get("post_id")
    if not base_post_id:
        await callback.answer("Ошибка: post_id не найден", show_alert=True)
        return

    repeat_dates = sorted(list(data["repeat_dates"]))
    repeat_time = data["repeat_time"]

    # ✅ генерим только будущие datetime
    datetimes = _future_datetimes(repeat_dates, repeat_time)

    if not datetimes:
        await state.clear()
        await callback.message.edit_text(
            "⚠️ <b>Нет будущих публикаций</b>\n\n"
            "Ты выбрал даты/время, которые уже прошли.\n"
            "Попробуй выбрать будущие даты или другое время.",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    created = 0
    for dt in datetimes:
        new_post_id = await create_scheduled_post(base_post_id, dt)
        schedule_post(callback.bot, new_post_id, dt)
        created += 1

    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>Автоповтор создан</b>\n\n"
        f"📦 Запланировано публикаций: <b>{created}</b>",
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#               РЕГИСТРАЦИЯ
# ============================================================


def register_auto_repeat_handlers(dp):
    dp.include_router(router)
