from aiogram.filters import BaseFilter

from config import ADMIN_IDS


ACCESS_DENIED_TEXT = "У вас нет доступа к этому боту."


def is_admin(user_id: int | None) -> bool:
    return bool(user_id) and user_id in ADMIN_IDS


class AdminOnlyFilter(BaseFilter):
    async def __call__(self, event) -> bool:
        from_user = getattr(event, "from_user", None)
        if not from_user:
            return False
        return is_admin(from_user.id)
