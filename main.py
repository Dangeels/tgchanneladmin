import os
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command, CommandStart
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import app.handlers as handlers
from app.handlers.admin_handlers import router1
from app.handlers.handlers import router
from app.database.models import async_main
from dotenv import load_dotenv

from app.middlewares.album import AlbumMiddleware
from app.utils.scheduler import scheduler_task, pending_task


load_dotenv()

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()
dp.message.middleware(AlbumMiddleware())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        'Если хотите предложить свой пост для публикации, пишите администрации канала @push_admin_Evgen')


async def on_startup(dispatcher):
    scheduler.add_job(scheduler_task, "interval", minutes=1, args=[bot, os.getenv('CHANNEL_ID'), scheduler])
    scheduler.add_job(pending_task, "interval", minutes=1, args=[bot, os.getenv('CHANNEL_ID')])
    scheduler.start()
    print("Планировщик запущен")


async def on_shutdown(dispatcher):
    """Остановка планировщика."""
    scheduler.shutdown()
    print("Планировщик остановлен")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.include_routers(router, router1)
    await async_main()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
