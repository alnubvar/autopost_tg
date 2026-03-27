from aiogram import F, Router, types
from aiogram.enums import ChatType

from utils.access import ACCESS_DENIED_TEXT, is_admin

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


def register_user_handlers(dp):
    dp.include_router(router)


@router.message(F.text)
async def echo(message: types.Message):
    if is_admin(message.from_user.id):
        return
    await message.answer(ACCESS_DENIED_TEXT)


@router.callback_query()
async def deny_callback(callback: types.CallbackQuery):
    if is_admin(callback.from_user.id):
        return
    await callback.answer(ACCESS_DENIED_TEXT, show_alert=True)
