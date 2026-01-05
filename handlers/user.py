from aiogram import Router, types, F

router = Router()

ADMIN_ID = [580759300, 8120213148, 7773812278]  # тот же ID, что и в admin.py


def register_user_handlers(dp):
    dp.include_router(router)


@router.message(F.text)
async def echo(message: types.Message):
    # не мешаем админу работать с ботом
    if message.from_user.id == ADMIN_ID:
        return

    await message.answer(f"Ты написал: {message.text}")
