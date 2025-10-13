# utils/scheduler.py
import logging
import asyncio
import os
from datetime import datetime, timedelta
import random
from aiogram import Bot
from aiogram.types import InputMediaPhoto
from aiogram.exceptions import TelegramBadRequest  # NEW
from app.database.requests import get_pending_posts, delete_pending_post, get_scheduled_posts, delete_scheduled_post
import app.database.requests as req
import pytz
from app.database.models import ScheduledPost, PendingPost
from apscheduler.triggers.date import DateTrigger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def handle_missed_tasks(bot: Bot, channel_id: int | str, scheduler):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)
    scheduled_posts = await get_scheduled_posts()  # Ваша функция для получения постов
    for post in scheduled_posts:
        if not post.is_published:
            continue
        # Безопасная локализация (используйте вашу функцию make_aware)
        unpin_time = make_aware(post.unpin_time, msk_tz) if post.unpin_time else None
        delete_time = make_aware(post.delete_time, msk_tz) if post.delete_time else None
        msg = post.message_ids
        is_pinned = await req.get_pin_info(post.message_ids[0]) if post.message_ids else False
        target_chat = post.chat_id or channel_id
        # Проверка и выполнение missed unpin
        if unpin_time and now >= unpin_time and is_pinned:  # Предполагаем поле is_unpinned в модели
            try:
                await unpin_after_duration(bot, target_chat, msg[0])  # Выполняем открепление
                #await notification_admins(bot, os.getenv('NOTIFICATION_CHAT'), post, 'unpin')  # Уведомление
                logger.info(f"Performed missed unpin for post {post.id}")
            except Exception as e:
                logger.error(f"Error performing missed unpin for post {post.id}: {e}")
        # Проверка и выполнение missed delete
        if delete_time and now >= delete_time:  # Предполагаем поле is_deleted
            try:
                await bot.delete_messages(target_chat, msg)  # Удаление сообщений
                await delete_scheduled_post(post.id)  # Удаление из БД
                await notification_admins(bot, os.getenv('NOTIFICATION_CHAT'), post, 'delete')  # Уведомление
                logger.info(f"Performed missed delete for post {post.id}")
            except Exception as e:
                logger.error(f"Error performing missed delete for post {post.id}: {e}")
        # Если время не прошло, добавляем в scheduler как обычно
        if (unpin_time and now < unpin_time) or (delete_time and now < delete_time):
            await update_unpin_or_delete_task(bot, channel_id, scheduler)  # Ваша функция для добавления jobs


def make_aware(dt: datetime, tz) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return tz.localize(dt)
    else:
        return dt.astimezone(tz)


async def post_content(bot: Bot, chat_id: int, post, notification: bool = False):
    # Если это уведомление — всегда шлём в указанный chat_id, иначе используем chat_id поста
    target_chat = chat_id if notification else (getattr(post, 'chat_id', None) or chat_id)
    text = str(getattr(post, 'text', '') or '')
    entities = getattr(post, 'entities', None) or []  # НОВОЕ: используем сохранённые entities
    # NEW: Проверка лимитов до отправки; если нарушены — не публикуем
    try:
        if post.content_type == 'text':
            if len(text) > 4096:
                logger.warning(f"Skip publish: text too long ({len(text)} > 4096). post_id={getattr(post, 'id', None)}")
                # уведомление админам (если это не служебное уведомление)
                notif_chat = os.getenv('NOTIFICATION_CHAT') or os.getenv('ADMIN_CHAT_ID')
                if notif_chat and not notification:
                    await bot.send_message(int(notif_chat), f"Пост id={getattr(post, 'id', None)} не опубликован: превышен лимит 4096 символов.")
                return
            msg = await bot.send_message(target_chat, text, entities=entities or None)

        elif post.content_type == 'photo' and post.photo_file_ids:
            if len(text) > 1024:
                logger.warning(f"Skip publish: caption too long ({len(text)} > 1024). post_id={getattr(post, 'id', None)}")
                notif_chat = os.getenv('NOTIFICATION_CHAT') or os.getenv('ADMIN_CHAT_ID')
                if notif_chat and not notification:
                    await bot.send_message(int(notif_chat), f"Пост id={getattr(post, 'id', None)} не опубликован: превышен лимит 1024 символов для подписи.")
                return
            if len(post.photo_file_ids) == 1:
                msg = await bot.send_photo(target_chat, post.photo_file_ids[0], caption=text or None, caption_entities=entities or None)
            else:
                media = [InputMediaPhoto(media=file_id) for file_id in post.photo_file_ids]
                if text:
                    media[0].caption = text  # Caption только для первого
                    media[0].caption_entities = entities or None
                msg = await bot.send_media_group(target_chat, media)
        else:
            raise ValueError("Неверный тип контента")

    except TelegramBadRequest as e:
        logger.error(f"TelegramBadRequest while posting content (post id={getattr(post, 'id', None)}): {e}")
        try:
            notif_chat = os.getenv('NOTIFICATION_CHAT') or os.getenv('ADMIN_CHAT_ID')
            if notif_chat and not notification:
                await bot.send_message(int(notif_chat), f"Не удалось опубликовать пост id={getattr(post, 'id', None)}: {e}")
        except Exception as e2:
            logger.error(f"Failed to notify about bad request: {e2}")
        return
    except Exception as e:
        logger.exception(f"Unexpected error while posting content (post id={getattr(post, 'id', None)}): {e}")
        return

    if not notification:
        m = [msg] if type(msg) is not list else msg
        if getattr(post, 'chat_id', None) == int(os.getenv('MAIN_CHAT_ID')):
            await req.add_last_message_time(datetime.now())
        if isinstance(post, ScheduledPost):
            await req.add_or_update_scheduled_post(
                post.content_type,
                is_published=True,
                message_ids=[s.message_id for s in m],
                post_id=post.id
            )
        return m


async def unpin_after_duration(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.unpin_chat_message(chat_id, message_id=message_id)
        await req.set_pin_info(message_id, False)
    except Exception as e:
        print(f"Не удалось открепить сообщение {message_id} в чате {chat_id}: {e}")


async def notification_admins(bot: Bot, chat_id: int | str, post: ScheduledPost, notification: str):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)
    text = f'id поста: {post.id}\n'
    dct = {}
    if post.unpin_time:
        post.unpin_time = make_aware(post.unpin_time, msk_tz)
        if now >= post.unpin_time:
            dct['unpin'] = f'Пост {post.id} был откреплён'
        elif (post.unpin_time - now).days <= 3:
            dct['unpin'] = (f'Пост будет откреплён через 3 дня или менее: {post.unpin_time}\n'
                            f'Изменить время открепления можно командой /pin_post, как её использовать указано в /help')

    if post.delete_time:
        post.delete_time = make_aware(post.delete_time, msk_tz)
        if now >= post.delete_time:
            dct['delete'] = f'Пост был удалён'
        elif (post.delete_time - now).days <= 3:
            dct['delete'] = (f'Пост будет удалён через 3 дня или менее: {post.delete_time}\n'
                             f'После удаления из чата он также будет удалён из базы данных')

    # Проверяем, есть ли соответствующее уведомление в словаре
    if notification in dct:
        await post_content(bot, chat_id, post, notification=True)
        text += dct[notification]
        await bot.send_message(chat_id, text=text)


async def scheduler_task(bot: Bot, channel_id: int, scheduler):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)

    # Проверка запланированных постов
    scheduled_posts = await get_scheduled_posts()
    for post in scheduled_posts:
        post.scheduled_time = make_aware(post.scheduled_time, msk_tz)
        if post.scheduled_time > now or post.is_published:
            continue
        await post_content(bot, post.chat_id or channel_id, post)
        await asyncio.sleep(5)
        await update_unpin_or_delete_task(bot, channel_id, scheduler)


async def update_unpin_or_delete_task(bot: Bot, channel_id: int | str, scheduler):
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)
    # Проверка запланированных постов
    scheduled_posts = await get_scheduled_posts()
    for post in scheduled_posts:
        if not post.is_published:
            continue
        msg = post.message_ids
        if not msg:
            continue

        unpin_time = make_aware(post.unpin_time, msk_tz) if post.unpin_time else None
        delete_time = make_aware(post.delete_time, msk_tz) if post.delete_time else None

        first_msg_id = msg[0]
        is_pinned = await req.get_pin_info(first_msg_id)
        target_chat = post.chat_id or channel_id
        # 1) Пин разрешён ТОЛЬКО если время открепления ещё не наступило
        if unpin_time and now < unpin_time and not is_pinned:
            try:
                await bot.pin_chat_message(target_chat, first_msg_id, disable_notification=True)
                await req.set_pin_info(first_msg_id, True)  # фиксируем только после успеха
            except Exception as e:
                logger.error(f"Не удалось закрепить сообщение {first_msg_id}: {e}")

        if unpin_time and now < unpin_time:
            try:
                scheduler.add_job(
                    notification_admins,
                    trigger=DateTrigger(run_date=post.unpin_time-timedelta(days=2, hours=23)),
                    args=[bot, os.getenv('NOTIFICATION_CHAT'), post, 'unpin'],
                    id=f'notify_unpin_3_{post.id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    unpin_after_duration,
                    trigger=DateTrigger(run_date=post.unpin_time),
                    args=[bot, target_chat, msg[0]],
                    id=f'unpin_{post.id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    notification_admins,
                    trigger=DateTrigger(run_date=post.unpin_time),
                    args=[bot, os.getenv('NOTIFICATION_CHAT'), post, 'unpin'],
                    id=f'notify_unpin_{post.id}',
                    replace_existing=True
                )
            except Exception as e:
                print(f"Не удалось закрепить сообщение: {e}")
        if delete_time and now < delete_time:
            try:
                scheduler.add_job(
                    notification_admins,
                    trigger=DateTrigger(run_date=post.delete_time - timedelta(days=2, hours=23)),
                    args=[bot, os.getenv('NOTIFICATION_CHAT'), post, 'delete'],
                    id=f'notify_3_delete_{post.id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    bot.delete_messages,
                    trigger=DateTrigger(run_date=post.delete_time),
                    args=[target_chat, msg],
                    id=f'delete_{post.id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    delete_scheduled_post,
                    trigger=DateTrigger(run_date=post.delete_time),
                    args=[post.id],
                    id=f'delete_from_db_{post.id}',
                    replace_existing=True
                )
                scheduler.add_job(
                    notification_admins,
                    trigger=DateTrigger(run_date=post.delete_time),
                    args=[bot, os.getenv('NOTIFICATION_CHAT'), post, 'delete'],
                    id=f'notify_delete_{post.id}',
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
            delay = random.randint(6, 36)  # Задержка 1–60 минут
            await asyncio.sleep(delay)
        last_message_time = await req.get_last_message_time()
        last_message_time = make_aware(last_message_time, msk_tz)
        if last_message_time is None or (now - last_message_time) > timedelta(hours=2):
            pending_posts = await get_pending_posts()
            if pending_posts:
                post = random.choice(pending_posts)
                await post_content(bot, getattr(post, 'chat_id', None) or channel_id, post)
                await delete_pending_post(post.id)


async def broadcast_task(bot: Bot, scheduler):
    """Рассылка broadcast-постов без «догоняющей» публикации:
    - За один проход публикуется максимум одно сообщение на кампанию.
    - Если режим limited и сейчас вне окна — переносим next_run_time на ближайшее начало окна (без публикации).
    - После публикации переносим next_run_time в будущее (с учётом окна).
    """
    from app.database.requests import get_active_broadcast_posts, update_broadcast_run, get_broadcast_config
    try:
        msk_tz = pytz.timezone("Europe/Moscow")
        now = datetime.now(msk_tz)
        cfg = await get_broadcast_config()
        broadcasts = await get_active_broadcast_posts()

        for bp in broadcasts:
            # Helpers
            def aware(dt):
                if dt is None:
                    return None
                return msk_tz.localize(dt) if dt.tzinfo is None else dt.astimezone(msk_tz)

            def in_window(dt: datetime, mode: str, start_min: int, end_min: int) -> bool:
                if mode != 'limited':
                    return True
                mins = dt.hour * 60 + dt.minute
                if start_min <= end_min:
                    return start_min <= mins < end_min
                # окно через полночь
                return mins >= start_min or mins < end_min

            def next_window_start_from(ref: datetime, mode: str, start_min: int, end_min: int) -> datetime:
                if mode != 'limited':
                    return ref
                day_start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
                start_today = day_start + timedelta(minutes=start_min)
                end_today = day_start + timedelta(minutes=end_min)
                if ref < start_today:
                    return start_today
                if ref >= end_today:
                    return start_today + timedelta(days=1)
                return ref  # внутри окна

            next_run = aware(bp.next_run_time)
            end_time = aware(bp.end_time)
            if not next_run or not end_time:
                continue

            # Деактивируем, если кампания завершилась
            if now > end_time:
                await update_broadcast_run(
                    bp.id,
                    next_run_time=None,
                    last_run_time=(aware(bp.last_run_time) or now).replace(tzinfo=None),
                    deactivate=True
                )
                continue

            # Параметры режима/окна
            mode = getattr(bp, 'mode', 'full') or 'full'
            start_min = getattr(bp, 'active_start_min', 9 * 60)
            end_min = getattr(bp, 'active_end_min', 23 * 60)
            if mode == 'limited' and cfg and not cfg.enabled:
                mode = 'full'

            interval = timedelta(minutes=bp.interval_minutes)

            # Если пора публиковать (или мы «опоздали»), решаем, публиковать ли сейчас
            if next_run <= now:
                # В limited вне окна — перенос на ближайшее окно, публикации нет
                if not in_window(now, mode, start_min, end_min):
                    new_next = next_window_start_from(now, mode, start_min, end_min)
                    if new_next > end_time:
                        await update_broadcast_run(
                            bp.id, None, last_run_time=(aware(bp.last_run_time) or now).replace(tzinfo=None), deactivate=True
                        )
                    else:
                        await update_broadcast_run(
                            bp.id, new_next.replace(tzinfo=None), last_run_time=(aware(bp.last_run_time) or now).replace(tzinfo=None)
                        )
                    continue

                # Публикуем ОДИН раз
                class _Tmp:
                    pass
                tmp = _Tmp()
                tmp.content_type = bp.content_type
                tmp.text = bp.text
                tmp.photo_file_ids = bp.photo_file_ids or []
                tmp.chat_id = bp.chat_id
                tmp.id = f"broadcast:{bp.id}"
                tmp.entities = getattr(bp, 'entities', [])  # НОВОЕ: передаём entities

                try:
                    await post_content(bot, bp.chat_id, tmp)
                except Exception as e:
                    logger.error(f"Ошибка публикации broadcast {bp.id}: {e}")
                    # Перенесём попытку на следующий интервал, чтобы не спамить
                    new_next = next_window_start_from(now + interval, mode, start_min, end_min)
                    if new_next > end_time:
                        await update_broadcast_run(bp.id, None, last_run_time=now.replace(tzinfo=None), deactivate=True)
                    else:
                        await update_broadcast_run(bp.id, new_next.replace(tzinfo=None), last_run_time=now.replace(tzinfo=None))
                    continue

                # Обновляем next_run_time в будущее
                new_next = now + interval
                if not in_window(new_next, mode, start_min, end_min):
                    new_next = next_window_start_from(new_next, mode, start_min, end_min)

                if new_next > end_time:
                    await update_broadcast_run(bp.id, None, last_run_time=now.replace(tzinfo=None), deactivate=True)
                else:
                    await update_broadcast_run(bp.id, new_next.replace(tzinfo=None), last_run_time=now.replace(tzinfo=None))

            else:
                # Ещё не время. Если limited и next вне окна — аккуратно подтянем к ближайшему окну в будущем.
                if not in_window(next_run, mode, start_min, end_min):
                    aligned = next_window_start_from(next_run, mode, start_min, end_min)
                    if aligned != next_run:
                        if aligned > end_time:
                            await update_broadcast_run(
                                bp.id, None, last_run_time=(aware(bp.last_run_time) or now).replace(tzinfo=None), deactivate=True
                            )
                        else:
                            await update_broadcast_run(
                                bp.id, aligned.replace(tzinfo=None), last_run_time=(aware(bp.last_run_time) or now).replace(tzinfo=None)
                            )
                # иначе просто ждём
    except Exception as e:
        logger.exception(f"broadcast_task fatal error: {e}")
