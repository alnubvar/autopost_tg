from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_post_buttons_kb(buttons: list[dict]) -> InlineKeyboardMarkup:
    """
    buttons = [
        {"row": 0, "text": "Написать", "url": "https://t.me/username"},
        {"row": 0, "text": "Сайт", "url": "https://site.com"},
        {"row": 1, "text": "Канал", "url": "https://t.me/channel"},
    ]
    """
    builder = InlineKeyboardBuilder()

    rows: dict[int, list[InlineKeyboardButton]] = {}

    for btn in buttons:
        row = btn["row"]

        button = InlineKeyboardButton(
            text=btn["text"],
            url=btn["url"],
        )

        rows.setdefault(row, []).append(button)

    # добавляем строки
    for row_buttons in rows.values():
        builder.row(*row_buttons)

    return builder.as_markup()
