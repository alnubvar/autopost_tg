from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def build_chat_select_kb(chats: list[dict], selected: set[str]) -> InlineKeyboardMarkup:
    kb = []

    for chat in chats:
        chat_id = chat["id"]
        title = chat["title"] or chat_id
        is_selected = chat_id in selected

        prefix = "☑️" if is_selected else "⬜"
        kb.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix} {title}", callback_data=f"toggle_chat:{chat_id}"
                )
            ]
        )

    kb.append(
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_chats"),
            InlineKeyboardButton(
                text="☑️ Выбрать все", callback_data="select_all_chats"
            ),
        ]
    )

    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="draft_cancel")])

    return InlineKeyboardMarkup(inline_keyboard=kb)
