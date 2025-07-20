import os
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command, CommandStart
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import app.handlers as handlers
from app.handlers.handlers import router
from app.database.models import async_main
from dotenv import load_dotenv

from app.middlewares.album import AlbumMiddleware
from app.utils.scheduler import scheduler_task


load_dotenv()

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()
dp.message.middleware(AlbumMiddleware())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


@dp.message(CommandStart())
async def start(message: Message):
    await bot.send_message('-1002883928771', message.text)


arr = []
@dp.message(Command('pin_message'))
async def pin(message: Message):
    await message.pin(disable_notification=True)
    arr.append(message.message_id)


@dp.message(Command('unpin_message'))
async def unpin(message: Message):
    await bot.unpin_chat_message(message.chat.id,None,arr[-1])


async def on_startup(dispatcher):
    scheduler.add_job(scheduler_task, "interval", seconds=15, args=[bot, os.getenv('CHANNEL_ID')])
    scheduler.start()
    print("Планировщик запущен")


async def on_shutdown(dispatcher):
    """Остановка планировщика."""
    scheduler.shutdown()
    print("Планировщик остановлен")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.include_router(router)
    await async_main()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())