import os
import pytz
from datetime import datetime, timedelta
from sqlalchemy import select, update, delete, func
from app.database.models import async_session, PendingPost, ScheduledPost, LastMessage, PendingCounter


def get_current_date():
    msk_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(msk_tz)
    date_str = now.strftime("%Y-%m-%d")
    return date_str


async def get_pending_count(chat_id):
    async with async_session() as session:
        count = await session.scalar(select(PendingCounter).where(PendingCounter.chat_id == chat_id, PendingCounter.date == get_current_date()))
        if not count:
            return 0
        return count.messages_count


async def set_or_update_pending_count(chat_id):
    async with async_session() as session:
        async with session.begin():
            # Проверяем существование с lock (with_for_update)
            existing = await session.scalar(
                select(PendingCounter)
                .where(PendingCounter.chat_id == chat_id,
                       PendingCounter.date == get_current_date())
                .with_for_update()
            )
            if existing:
                existing.messages_count += 1
                session.add(existing)
            else:
                session.add(PendingCounter(chat_id=chat_id, messages_count=1, date=get_current_date()))
        await session.commit()


async def get_last_message_time():
    async with async_session() as session:
        messages = await session.scalars(select(LastMessage))
        res = [[msg.id, msg.time] for msg in messages]
        await session.commit()
        return None if not res else max(res)[1]


async def add_last_message_time(time):
    async with async_session() as session:
        session.add(LastMessage(time=time))
        await session.commit()


async def delete_last_messages():
    async with async_session() as session:
        await session.delete(LastMessage)
        await session.commit()


async def add_or_update_pending_post(content_type: str, text: str, photo_file_ids: list[str], media_group_id: int = 0):
    post = PendingPost(
        content_type=content_type,
        text=text,
        photo_file_ids=photo_file_ids,
        media_group_id=media_group_id if media_group_id else 0
    )

    async with async_session() as session:
        async with session.begin():
            # Проверяем существование с lock (with_for_update)
            existing = await session.scalar(
                select(PendingPost)
                .where(PendingPost.media_group_id == post.media_group_id,
                       PendingPost.media_group_id != 0)
                .with_for_update()
            )
            if existing:
                # Обновляем существующий: добавляем новые file_ids
                existing.photo_file_ids.extend(photo_file_ids)
                existing.text = text or existing.text  # Сохраняем caption, если новый
                session.add(existing)
            else:
                session.add(post)
        await session.commit()


async def get_pending_posts():
    async with async_session() as session:
        posts = await session.scalars(select(PendingPost))
        return posts.all()


async def delete_pending_post(post_id: int):
    async with async_session() as session:
        post = await session.get(PendingPost, post_id)
        if post:
            await session.delete(post)
            await session.commit()
            return True


async def add_scheduled_post(content_type: str, text: str, photo_file_ids: list[str], scheduled_time: datetime,
                             pin_duration_minutes: int, media_group_id: int = 0):
    post = ScheduledPost(
        content_type=content_type,
        text=text,
        photo_file_ids=photo_file_ids,
        scheduled_time=scheduled_time,
        pin_duration_minutes=pin_duration_minutes,
        media_group_id=media_group_id if media_group_id else 0
    )

    async with async_session() as session:
        async with session.begin():
            # Проверяем существование (upsert)
            existing = await session.scalar(
                select(ScheduledPost)
                .where(ScheduledPost.media_group_id == post.media_group_id,
                       ScheduledPost.media_group_id != 0)
                .with_for_update()  # Lock для concurrency
            )
            if existing:
                # Обновляем: добавляем file_ids, сохраняем text
                existing.photo_file_ids.extend(photo_file_ids)
                existing.text = text or existing.text
                existing.scheduled_time = scheduled_time
                existing.pin_duration_minutes = pin_duration_minutes
                existing.is_published = False
                existing.message_id = 0
                session.add(existing)
            else:
                session.add(post)
        await session.commit()


async def set_is_published_true(id: int, message_id: int):
    async with async_session() as session:
        await session.scalar(update(ScheduledPost)
                             .where(ScheduledPost.id == id)
                             .values(is_published=True, message_id=message_id))
        await session.commit()


async def set_is_published_false(id: int):
    async with async_session() as session:
        await session.scalar(update(ScheduledPost)
                             .where(ScheduledPost.id == id)
                             .values(is_published=False, message_id=0))
        await session.commit()


async def get_scheduled_posts():
    async with async_session() as session:
        posts = await session.scalars(select(ScheduledPost))
        return posts.all()


async def delete_scheduled_post(post_id: int):
    async with async_session() as session:
        post = await session.get(ScheduledPost, post_id)
        if post:
            await session.delete(post)
            await session.commit()
            return True
