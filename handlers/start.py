from aiogram import Router, types
from aiogram.enums import ChatType
from aiogram.filters import Command

from keyboards.main_menu import admin_menu
from utils.access import ACCESS_DENIED_TEXT, is_admin

router = Router()


def register_start_handlers(dp):
    dp.include_router(router)


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "Приветствую! 😊\nВыбери действие:", reply_markup=admin_menu()
        )
    elif message.chat.type == ChatType.PRIVATE:
        await message.answer(ACCESS_DENIED_TEXT)
