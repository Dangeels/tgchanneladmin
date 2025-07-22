# utils/scheduler.py
import asyncio
from datetime import datetime, timedelta
import random
from aiogram import Bot
from aiogram.types import InputMediaPhoto
from apscheduler.triggers.date import DateTrigger

from app.database.requests import get_pending_posts, delete_pending_post, get_scheduled_posts, delete_scheduled_post
import app.database.requests as req
import pytz
from app.database.models import ScheduledPost, PendingPost


async def post_content(bot: Bot, chat_id: int, post: ScheduledPost | PendingPost):
    if post.content_type == 'text':
        msg = await bot.send_message(chat_id, post.text)
    elif post.content_type == 'photo' and post.photo_file_ids:
        if len(post.photo_file_ids) == 1:
            msg = await bot.send_photo(chat_id, post.photo_file_ids[0], caption=post.text)
        else:
            media = [InputMediaPhoto(media=file_id) for file_id in post.photo_file_ids]
            if post.text:
                media[0].caption = post.text  # Caption только для первого
            msg = await bot.send_media_group(chat_id, media)
    else:
        raise ValueError("Неверный тип контента")
    await req.add_last_message_time(datetime.now())
    return [msg] if type(msg)!=list else msg


async def unpin_after_duration(bot: Bot, chat_id: int, message_id: int, duration_seconds: int):
    await asyncio.sleep(duration_seconds)
    try:
        await bot.unpin_chat_message(chat_id, message_id=message_id)
    except Exception as e:
        print(f"Не удалось открепить сообщение {message_id} в чате {chat_id}: {e}")


async def scheduler_task(bot: Bot, channel_id: int, scheduler):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now()

    # Проверка запланированных постов
    scheduled_posts = await get_scheduled_posts()
    for post in scheduled_posts:
        scheduler.add_job(
            post_content,
            trigger=DateTrigger(run_date=post.scheduled_time),
            args=[bot, channel_id, post]
        )
        msg = await post_content(bot, channel_id, post)
        if post.pin_duration_minutes > 0:
            try:
                await bot.pin_chat_message(channel_id, msg[0].message_id, disable_notification=True)
                unpin_time = datetime.now(tz=msk_tz) + timedelta(minutes=post.pin_duration_minutes)

                scheduler.add_job(
                    unpin_after_duration,
                    trigger=DateTrigger(run_date=unpin_time),
                    args=[bot, channel_id, msg[0].message_id],
                )
            except Exception as e:
                print(f"Не удалось закрепить сообщение: {e}")
        await delete_scheduled_post(post.id)


async def reset_delay():
    last_message_time = await req.get_last_message_time()
    now = datetime.now()
    return last_message_time is None or (now - last_message_time) > timedelta(seconds=2)


async def pending_task(bot: Bot, channel_id: int):
    now = datetime.now()
    count = await req.get_pending_count(channel_id)
    # Проверка низкой активности
    if 0 <= now.hour < 24:
        if_delay = await reset_delay()
        if if_delay and count <= 5:
            delay = random.randint(6, 36)  # Задержка 1–60 минут
            await asyncio.sleep(delay)
            if_delay = await reset_delay()
            if not if_delay:
                return
            pending_posts = await get_pending_posts()
            if pending_posts:
                await req.set_or_update_pending_count()
                post = random.choice(pending_posts)
                await post_content(bot, channel_id, post)
                await delete_pending_post(post.id)

