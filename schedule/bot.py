import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession

from config import BOT_TOKEN
from handlers import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fa-bot")

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN пуст. Укажи токен в config.py")

    session = AiohttpSession(timeout=30)
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session
    )

    # сбрасываем webhook и старые апдейты
    await bot.delete_webhook(drop_pending_updates=True)

    # самопроверка — выведем имя бота
    me = await bot.get_me()
    print(f"BOT USERNAME: @{me.username}  ID: {me.id}")

    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

