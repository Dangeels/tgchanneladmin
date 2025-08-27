import os
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command, CommandStart
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import app.handlers as handlers
from app.handlers.menu import menu_router
from app.handlers.admin_handlers import router1
from app.handlers.handlers import router, pin_post, delete_scheduled_post
from app.database.models import async_main
from dotenv import load_dotenv
from app.middlewares.album import AlbumMiddleware
from app.utils.scheduler import scheduler_task, pending_task, handle_missed_tasks
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

load_dotenv()


bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()
dp.message.middleware(AlbumMiddleware())
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


# @dp.message(CommandStart())
# async def start(message: Message):  # потом надо текст придумать
#     await message.answer(
#         '/menu'
#     )


@dp.message(Command('pin_post'))  # /pin_post [id] date[HH:MM DD-MM-YYYY]
async def command_pin_post(message: Message):
    await pin_post(message, bot, os.getenv('CHANNEL_ID'), scheduler)


@dp.message(Command('delete_scheduled_post'))
async def command_delete_post(message: Message):
    await delete_scheduled_post(message, bot, os.getenv('CHANNEL_ID'))


async def on_startup(dispatcher):
    scheduler.add_job(scheduler_task, "interval", minutes=1, args=[bot, os.getenv('CHANNEL_ID'), scheduler],
                      id='scheduler_task', replace_existing=True)
    scheduler.add_job(pending_task, "interval", minutes=1, args=[bot, os.getenv('CHANNEL_ID')],
                      id='pending_task', replace_existing=True)
    scheduler.start()
    print("Планировщик запущен")


async def on_shutdown(dispatcher):
    """Остановка планировщика."""
    scheduler.shutdown()
    print("Планировщик остановлен")


async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    dp.include_routers(router, router1, menu_router)
    await handle_missed_tasks(bot, os.getenv('CHANNEL_ID'), scheduler)
    await async_main()
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
