from aiogram import Router


router = Router()


def register_auto_repeat_handlers(dp):
    dp.include_router(router)
