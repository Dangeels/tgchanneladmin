# app/utils/scheduler.py
import logging
import asyncio
import os
from datetime import datetime, timedelta
import random
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputMediaPhoto
from app.database.requests import get_pending_posts, delete_pending_post, get_scheduled_posts, delete_scheduled_post
import app.database.requests as req
import pytz
from app.database.models import ScheduledPost, PendingPost
from apscheduler.triggers.date import DateTrigger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def handle_missed_tasks(bot: Bot, scheduler):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)
    scheduled_posts = await get_scheduled_posts()  # Ваша функция для получения постов
    for post in scheduled_posts:
        # Changed: Check if published in any chat before processing
        if not post.is_published:
            continue
        # Безопасная локализация (используйте вашу функцию make_aware)
        # Проверка и выполнение missed unpin
        for chat_id in post.chat_ids:
            if not post.is_published.get(str(chat_id), False):
                continue
            unpin_time = make_aware(post.unpin_time.get(str(chat_id)), msk_tz) if post.unpin_time.get(
                str(chat_id)) else None
            delete_time = make_aware(post.delete_time.get(str(chat_id)), msk_tz) if post.delete_time.get(
                str(chat_id)) else None

            if unpin_time and now >= unpin_time:
                msgs = post.message_ids.get(str(chat_id), [])
                if msgs:
                    # Changed: Pass chat_id and msgs[0] to get_pin_info
                    if await req.get_pin_info(chat_id, msgs[0]):
                        try:
                            await unpin_after_duration(bot, chat_id, post)  # Выполняем открепление
                            await notification_admins(bot, os.getenv('NOTIFICATION_CHAT'), post, 'unpin')  # Уведомление
                            logger.info(f"Performed missed unpin for post {post.id}")
                        except Exception as e:
                            logger.error(f"Error performing missed unpin for post {post.id}: {e}")

            if delete_time and now >= delete_time:
                try:
                    await delete_post(bot, post.id)  # Удаление сообщений
                    await notification_admins(bot, os.getenv('NOTIFICATION_CHAT'), post, 'delete')  # Уведомление
                    logger.info(f"Performed missed delete for post {post.id}")
                except Exception as e:
                    logger.error(f"Error performing missed delete for post {post.id}: {e}")

            # Если время не прошло, добавляем в scheduler как обычно
            if (unpin_time and now < unpin_time) or (delete_time and now < delete_time):
                await update_unpin_or_delete_task(bot, chat_id, scheduler)  # Ваша функция для добавления jobs


def make_aware(dt: str | datetime, tz: pytz.timezone) -> datetime:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)  # Changed: Deserialize ISO string
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)


async def post_content(bot: Bot, chat_id: int, post: ScheduledPost | PendingPost, notification: bool = False):
    if post.content_type == 'text':
        msg = await bot.send_message(chat_id, str(post.text))
    elif post.content_type == 'photo' and post.photo_file_ids:
        if len(post.photo_file_ids) == 1:
            msg = await bot.send_photo(chat_id, post.photo_file_ids[0], caption=str(post.text))
        else:
            media = [InputMediaPhoto(media=file_id) for file_id in post.photo_file_ids]
            if post.text:
                media[0].caption = post.text  # Caption только для первого
            msg = await bot.send_media_group(chat_id, media)
    else:
        raise ValueError("Неверный тип контента")
    if not notification:
        m = [msg] if type(msg) is not list else msg
        if chat_id == os.getenv('MAIN_CHAT_ID'):
            await req.add_last_message_time(datetime.now())
        is_published = post.is_published
        is_published[str(chat_id)] = True
        if isinstance(post, ScheduledPost):
            await req.add_or_update_scheduled_post(
                post.content_type,
                is_published=is_published,
                message_ids={chat_id: [s.message_id for s in m]},
                post_id=post.id
            )
        return m


async def unpin_after_duration(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.unpin_chat_message(chat_id, message_id=message_id)
        await req.set_pin_info(chat_id, message_id, False)
    except Exception as e:
        print(f"Не удалось открепить сообщение {message_id} в чате {chat_id}: {e}")


async def delete_post(bot: Bot, post_id: int):
    post = await req.get_scheduled_post(post_id)  # Assume you have a function to get by id
    for chat_id in post.chat_ids:
        msgs = post.message_ids.get(chat_id, [])
        if msgs:
            await bot.delete_messages(chat_id, msgs)
    await delete_scheduled_post(post_id)


async def notification_admins(bot: Bot, chat_id: int | str, post: ScheduledPost, notification: str):
    await post_content(bot, chat_id, post, notification=True)
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)
    text = f'id поста: {post.id}\nChats: {", ".join(map(str, post.chat_ids))}\n'
    dct = {}
    unpin_info = ''
    for c in post.chat_ids:
        ut = post.unpin_time.get(c)
        if ut:
            ut = make_aware(ut, msk_tz)
            if (ut-now).days <= 3:
                unpin_info += f'Chat {c}: Пост будет откреплён через 3 дня: {ut}\n'
            if now >= ut:
                unpin_info += f'Chat {c}: Пост {post.id} был откреплён\n'
    if unpin_info:
        dct['unpin'] = unpin_info + 'Изменить время открепления можно командой /pin_post, подробнее указано в /help'
    delete_info = ''
    for c in post.chat_ids:
        dt = post.delete_time.get(c)
        if dt:
            dt = make_aware(dt, msk_tz)
            if (dt - now).days <= 3:
                delete_info += f'Chat {c}: Пост будет удалён через 3 дня: {dt}\n'
            if now >= dt:
                delete_info += f'Chat {c}: Пост был удалён\n'
    if delete_info:
        dct['delete'] = delete_info + 'После удаления из чата он также будет удалён из базы данных'
    text += dct.get(notification, '')
    await bot.send_message(chat_id, text=text)


async def scheduler_task(bot: Bot, scheduler):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)

    # Проверка запланированных постов
    scheduled_posts = await get_scheduled_posts()
    for post in scheduled_posts:
        post.scheduled_time = make_aware(post.scheduled_time, msk_tz)
        if post.scheduled_time > now:
            continue
        for chat in post.chat_ids:
            if post.is_published.get(str(chat), False):
                continue
            await post_content(bot, chat, post)
            await asyncio.sleep(5)
            await update_unpin_or_delete_task(bot, chat, scheduler)


async def update_unpin_or_delete_task(bot: Bot, channel_id: int | str, scheduler):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)
    # Проверка запланированных постов
    scheduled_posts = await get_scheduled_posts()
    for post in scheduled_posts:
        if not post.is_published.get(str(channel_id), False):  # str() as JSON keys may be strings
            continue
        msg = post.message_ids[str(channel_id)]
        if not msg:
            continue

        unpin_time = make_aware(post.unpin_time.get(channel_id), msk_tz) if post.unpin_time.get(channel_id) else None
        delete_time = make_aware(post.delete_time.get(channel_id), msk_tz) if post.delete_time.get(channel_id) else None

        first_msg_id = int(msg[0])
        is_pinned = await req.get_pin_info(channel_id, first_msg_id)
        # 1) Пин разрешён ТОЛЬКО если время открепления ещё не наступило
        if unpin_time and now < unpin_time and not is_pinned:
            try:
                print('sth')
                logger.info(f"Закрепление сообщения {first_msg_id} в чате {channel_id}")
                await bot.pin_chat_message(channel_id, first_msg_id, disable_notification=True)
                await req.set_pin_info(channel_id, first_msg_id, True)
                logger.info(f"Успешно закреплено сообщение {first_msg_id} в чате {channel_id}")
            except TelegramBadRequest as e:
                logger.error(f"Не удалось закрепить сообщение {first_msg_id} в чате {channel_id}: {e}")
                if "not enough rights" in str(e).lower():
                    logger.error(f"Боту не хватает прав для закрепления в чате {channel_id}")
                raise
            except Exception as e:
                logger.error(f"Ошибка при закреплении сообщения {first_msg_id} в чате {channel_id}: {e}")
                raise

        if unpin_time and now < unpin_time:
            try:
                scheduler.add_job(
                    notification_admins,
                    trigger=DateTrigger(run_date=unpin_time-timedelta(days=3)),
                    args=[bot, os.getenv('NOTIFICATION_CHAT'), post, 'unpin'],
                    id=f'notify_unpin_3_{post.id}_{channel_id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    unpin_after_duration,
                    trigger=DateTrigger(run_date=unpin_time),
                    args=[bot, channel_id, msg[0]],
                    id=f'unpin_{post.id}_{channel_id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    notification_admins,
                    trigger=DateTrigger(run_date=unpin_time),
                    args=[bot, os.getenv('NOTIFICATION_CHAT'), post, 'unpin'],
                    id=f'notify_unpin_{post.id}_{channel_id}',
                    replace_existing=True
                )
            except Exception as e:
                print(f"Не удалось закрепить сообщение: {e}")
        if delete_time and now < delete_time:
            try:
                scheduler.add_job(
                    notification_admins,
                    trigger=DateTrigger(run_date=delete_time - timedelta(days=3)),
                    args=[bot, os.getenv('NOTIFICATION_CHAT'), post, 'delete'],
                    id=f'notify_3_delete_{post.id}_{channel_id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    delete_post,
                    trigger=DateTrigger(run_date=delete_time),
                    args=[bot, post.id],
                    id=f'delete_{post.id}_{channel_id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    notification_admins,
                    trigger=DateTrigger(run_date=delete_time),
                    args=[bot, os.getenv('NOTIFICATION_CHAT'), post, 'delete'],
                    id=f'notify_delete_{post.id}_{channel_id}',
                    replace_existing=True
                )
            except Exception as e:
                print(f'Не удалось запланировать удаление: {e}')


async def pending_task(bot: Bot, channel_id: int):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)

    last_message_time = await req.get_last_message_time()
    if last_message_time:
        last_message_time = make_aware(last_message_time, msk_tz)
    # Проверка низкой активности
    if 11 <= now.hour < 23:
        if last_message_time is None or (now - last_message_time) > timedelta(hours=2):
            delay = random.randint(60, 3600)  # Задержка 1–60 минут
            await asyncio.sleep(delay)
        last_message_time = await req.get_last_message_time()
        if last_message_time:
            last_message_time = make_aware(last_message_time, msk_tz)
        if last_message_time is None or (now - last_message_time) > timedelta(hours=2):
            pending_posts = await get_pending_posts()
            if pending_posts:
                post = random.choice(pending_posts)
                await post_content(bot, channel_id, post)
                await delete_pending_post(post.id)
