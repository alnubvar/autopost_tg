from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def _type_icon(t: str) -> str:
    mapping = {
        "text": "📝",
        "photo": "🖼",
        "video": "🎬",
        "document": "📎",
        "voice": "🎙",
        "audio": "🎵",
        "animation": "🎞",
        "video_note": "📹",
        "media_group": "🖼🖼",
    }
    return mapping.get(t, "❓")


def build_posts_list_kb(posts, page: int, page_size: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for post in posts:
        t = post["type"]
        icon = _type_icon(t)
        time_str = post.get("next_run_at") or post["publish_time"]
        repeat_prefix = "🔁 " if post.get("is_recurring") else ""
        text = f"{repeat_prefix}{icon} #{post['id']} • {time_str}"

        builder.button(
            text=text,
            callback_data=f"post_open:{post['id']}:{page}",
        )

    # Пагинация
    if page > 1:
        builder.button(text="⬅️ Назад", callback_data=f"posts_page:{page-1}")
    if len(posts) == page_size:
        builder.button(text="➡️ Далее", callback_data=f"posts_page:{page+1}")

    builder.adjust(1)
    return builder.as_markup()
