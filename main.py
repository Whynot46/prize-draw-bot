import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import router
from bot.config import Config
from bot.db import init_db
from bot.logger import logger
from bot.scheduler import setup_scheduler, restore_scheduled_giveaways


async def main():
    try:
        # Инициализация бота и диспетчера
        bot = Bot(token=Config.BOT_TOKEN)
        dp = Dispatcher(bot=bot, storage=MemoryStorage())

        # Инициализация базы данных
        await init_db()
        logger.info("Database initialized successfully.")

        # Инициализация планировщика задач
        await setup_scheduler(bot)
        await restore_scheduled_giveaways(bot)
        logger.info("Scheduler started successfully.")

        # Подключение роутера
        dp.include_router(router)
        logger.info("Router included successfully.")

        # Запуск бота
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted. Starting polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    except Exception as error:
        logger.error(f"Bot error: {error}", exc_info=True)
        raise  # Повторно выбрасываем исключение для завершения работы

    finally:
        # Корректное завершение работы
        logger.info("Shutting down the bot...")
        if hasattr(dp, '_polling') and dp._polling:
            await dp.stop_polling()
            logger.info("Polling stopped successfully.")
        await bot.session.close()
        logger.info("Bot session closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as error:
        logger.error(f"Unexpected error: {error}", exc_info=True)
