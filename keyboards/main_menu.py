from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def admin_menu():
    kb = [
        [KeyboardButton(text="📝 Добавить пост")],
        [KeyboardButton(text="📋 Мои запланированные")],
        [KeyboardButton(text="➕ Добавить чат")],
        [KeyboardButton(text="🗂 Управление чатами")],
        # [KeyboardButton(text="🗑 Удалить пост")],
        # [KeyboardButton(text="⚙️ Настройки")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
