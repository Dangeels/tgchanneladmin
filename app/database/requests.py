import os
import pytz
from datetime import datetime, timedelta
from sqlalchemy import select, update, delete, func
from app.database.models import async_session, PendingPost, ScheduledPost, LastMessage, PostIsPinned


async def get_pin_info(post_id: int):
    async with async_session() as session:
        existing = await session.scalar(select(PostIsPinned).where(PostIsPinned.post_id == post_id))
        return existing.pinned if existing else False


async def set_pin_info(post_id: int, pinned: bool):
    async with async_session() as session:
        async with session.begin():
            existing = await session.scalar(select(PostIsPinned).where(PostIsPinned.post_id == post_id).with_for_update())
            if existing:
                existing.pinned = pinned
                session.add(existing)
            else:
                session.add(PostIsPinned(post_id=post_id, pinned=pinned))
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


async def add_or_update_pending_post(content_type: str, text: str, photo_file_ids: list[str], media_group_id: int = 0, chat_id: int | None = None):
    post = PendingPost(
        content_type=content_type,
        text=text,
        photo_file_ids=photo_file_ids,
        media_group_id=media_group_id if media_group_id else 0,
        chat_id=chat_id or int(os.getenv('CHANNEL_ID', 0))
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
                if chat_id:
                    existing.chat_id = chat_id
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


async def add_or_update_scheduled_post(
    content_type: str,
    text: str | None = None,
    photo_file_ids: list[str] | None = None,
    scheduled_time: datetime | None = None,
    media_group_id: int = 0,
    is_published: bool = False,
    message_ids: list | None = None,
    unpin_time: datetime | None = None,
    delete_time: datetime | None = None,
    post_id: int = 0,
    chat_id: int | None = None
):
    if message_ids is None:
        message_ids = []
    if not photo_file_ids:
        photo_file_ids = []
    post = ScheduledPost(
        content_type=content_type,
        text=text,
        photo_file_ids=photo_file_ids.copy(),  # копируем список во избежание мутации аргумента
        scheduled_time=scheduled_time,
        media_group_id=media_group_id or 0,
        is_published=is_published,
        message_ids=message_ids.copy(),
        unpin_time=unpin_time,
        delete_time=delete_time,
        chat_id=chat_id or int(os.getenv('CHANNEL_ID', 0))
    )

    async with async_session() as session:
        async with session.begin():
            existing = await session.scalar(
                select(ScheduledPost)
                .where(
                    ScheduledPost.id == post_id
                )
                .with_for_update()
            )
            if existing:
                # Обновляем список photo_file_ids, добавляя новые уникальные элементы
                updated_ids = existing.photo_file_ids or []
                if photo_file_ids:
                    for pid in photo_file_ids:
                        if pid not in updated_ids:
                            updated_ids.append(pid)
                existing.photo_file_ids = updated_ids or existing.photo_file_ids

                # Обновляем другие поля, если переданы значения

                existing.text = text or existing.text
                existing.scheduled_time = scheduled_time or existing.scheduled_time
                existing.is_published = is_published
                existing.message_ids = message_ids.copy() or existing.message_ids
                existing.unpin_time = unpin_time or existing.unpin_time
                existing.delete_time = delete_time or existing.delete_time
                existing.chat_id = chat_id or existing.chat_id

                session.add(existing)
            else:
                session.add(post)

        await session.commit()


async def get_scheduled_post(post_id: int):
    async with async_session() as session:
        post = await session.scalar(select(ScheduledPost).where(ScheduledPost.id == post_id))
        return post


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
