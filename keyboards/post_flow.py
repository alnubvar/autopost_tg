from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_editor_kb(
    has_text: bool,
    has_media: bool,
    has_buttons: bool,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✅' if has_text else '✏️'} Изменить текст",
                    callback_data="draft_edit:text",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✅' if has_media else '🖼'} Добавить / изменить медиа",
                    callback_data="draft_edit:media",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{'✅' if has_buttons else '🔘'} Добавить кнопку",
                    callback_data="draft_edit:buttons",
                )
            ],
            [
                InlineKeyboardButton(text="⬅ Назад к чатам", callback_data="draft_back:chats"),
                InlineKeyboardButton(text="Далее ➡", callback_data="draft_next:actions"),
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="draft_cancel"),
            ],
        ]
    )


def build_action_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Опубликовать сейчас",
                    callback_data="draft_action:publish_now",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🕒 Запланировать один раз",
                    callback_data="draft_action:schedule_once",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔁 Автоповтор / зацикленность",
                    callback_data="draft_action:auto_repeat",
                )
            ],
            [
                InlineKeyboardButton(text="⬅ Назад", callback_data="draft_action:back"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="draft_cancel"),
            ],
        ]
    )


def build_repeat_mode_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📅 Конкретные даты",
                    callback_data="repeat_mode:dates",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📆 Дни недели",
                    callback_data="repeat_mode:weekdays",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗓 Дни месяца",
                    callback_data="repeat_mode:month_days",
                )
            ],
            [
                InlineKeyboardButton(text="⬅ Назад", callback_data="repeat_mode:back"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="draft_cancel"),
            ],
        ]
    )


def build_weekdays_kb(selected: set[int]) -> InlineKeyboardMarkup:
    labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if index in selected else ''}{label}",
                callback_data=f"repeat_weekday:{index}",
            )
            for index, label in enumerate(labels[:4])
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if index in selected else ''}{label}",
                callback_data=f"repeat_weekday:{index}",
            )
            for index, label in enumerate(labels[4:], start=4)
        ],
        [
            InlineKeyboardButton(text="⬅ Назад", callback_data="repeat_select:back"),
            InlineKeyboardButton(text="Далее ➡", callback_data="repeat_select:confirm"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_month_days_kb(selected: set[int]) -> InlineKeyboardMarkup:
    inline_keyboard = []
    row = []

    for day in range(1, 32):
        row.append(
            InlineKeyboardButton(
                text=f"{'✅ ' if day in selected else ''}{day}",
                callback_data=f"repeat_month_day:{day}",
            )
        )
        if len(row) == 7:
            inline_keyboard.append(row)
            row = []

    if row:
        inline_keyboard.append(row)

    inline_keyboard.append(
        [
            InlineKeyboardButton(text="⬅ Назад", callback_data="repeat_select:back"),
            InlineKeyboardButton(text="Далее ➡", callback_data="repeat_select:confirm"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def build_repeat_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data="repeat_confirm:yes",
                ),
                InlineKeyboardButton(
                    text="⬅ Назад",
                    callback_data="repeat_confirm:back",
                ),
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="draft_cancel"),
            ],
        ]
    )


def build_manage_recurrence_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗓 Изменить расписание",
                    callback_data=f"edit_schedule:{post_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏹ Остановить автоповтор",
                    callback_data=f"stop_repeat:{post_id}",
                )
            ],
        ]
    )
