import os
import pytz
from datetime import datetime, timedelta
from sqlalchemy import select, update, delete, func
from app.database.models import async_session, PendingPost, ScheduledPost, LastMessage, PostIsPinned
import logging
from sqlalchemy.orm.attributes import flag_modified

# Configure logging
logging.basicConfig(level=logging.INFO, filename='bot.log', format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def get_pin_info(chat_id: int, message_id: int):  # Changed: Added chat_id param
    async with async_session() as session:
        existing = await session.scalar(
            select(PostIsPinned).where(  # Changed: Use MessagePinned; query by both chat_id and message_id
                PostIsPinned.chat_id == chat_id,
                PostIsPinned.message_id == message_id
            )
        )
        return existing.pinned if existing else False


async def set_pin_info(chat_id: int, message_id: int, pinned: bool):
    async with async_session() as session:
        async with session.begin():
            existing = await session.scalar(
                select(PostIsPinned).where(  # Changed: Query by both
                    PostIsPinned.chat_id == chat_id,
                    PostIsPinned.message_id == message_id
                ).with_for_update()
            )
            if existing:
                existing.pinned = pinned
                session.add(existing)
            else:
                session.add(PostIsPinned(chat_id=chat_id, message_id=message_id, pinned=pinned))
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


async def add_or_update_scheduled_post(
        content_type: str,
        text: str | None = None,
        photo_file_ids: list[str] | None = None,
        scheduled_time: datetime | None = None,
        media_group_id: int = 0,
        is_published: dict | None = None,
        message_ids: dict | None = None,
        unpin_time: dict | None = None,
        delete_time: dict | None = None,
        chat_ids: list[int] | None = None,
        post_id: int = 0
):
    if message_ids is None:
        message_ids = {}
    if not photo_file_ids:
        photo_file_ids = []
    if unpin_time is None:
        unpin_time = {}
    if delete_time is None:
        delete_time = {}
    if not chat_ids:
        chat_ids = []
    if is_published is None:
        is_published = {}
    # Ensure all dictionary keys are strings
    is_published = {str(k): v for k, v in is_published.items()}
    message_ids = {str(k): v for k, v in message_ids.items()}
    unpin_time = {str(k): v for k, v in unpin_time.items()}
    delete_time = {str(k): v for k, v in delete_time.items()}

    logger.info(
        f"Input to add_or_update_scheduled_post: post_id={post_id}, is_published={is_published}, message_ids={message_ids}")

    post = ScheduledPost(
        content_type=content_type,
        text=text,
        photo_file_ids=photo_file_ids.copy(),
        scheduled_time=scheduled_time,
        media_group_id=media_group_id or 0,
        is_published=is_published.copy(),
        message_ids=message_ids.copy(),
        unpin_time=unpin_time.copy(),
        delete_time=delete_time.copy(),
        chat_ids=chat_ids.copy(),
    )

    async with async_session() as session:
        async with session.begin():
            try:
                existing = await session.scalar(
                    select(ScheduledPost)
                    .where(ScheduledPost.id == post_id)
                    .with_for_update()
                )
                if existing:
                    # Merge photo_file_ids
                    updated_ids = existing.photo_file_ids or []
                    if photo_file_ids:
                        for pid in photo_file_ids:
                            if pid not in updated_ids:
                                updated_ids.append(pid)
                    existing.photo_file_ids = updated_ids or existing.photo_file_ids

                    # Update scalar fields
                    existing.content_type = content_type or existing.content_type
                    existing.text = text or existing.text
                    existing.scheduled_time = scheduled_time or existing.scheduled_time
                    existing.chat_ids = chat_ids.copy() or existing.chat_ids
                    existing.media_group_id = media_group_id or existing.media_group_id

                    # Merge dictionary fields
                    existing_is_published = existing.is_published or {}
                    existing_is_published.update(is_published)
                    existing.is_published = existing_is_published
                    flag_modified(existing, "is_published")  # Mark JSON field as modified
                    logger.info(f"Updated post {post_id}: is_published={existing.is_published}")

                    existing_message_ids = existing.message_ids or {}
                    existing_message_ids.update(message_ids)
                    existing.message_ids = existing_message_ids
                    flag_modified(existing, "message_ids")  # Mark JSON field as modified
                    logger.info(f"Updated post {post_id}: message_ids={existing.message_ids}")

                    existing_unpin_time = existing.unpin_time or {}
                    existing_unpin_time.update(unpin_time)
                    existing.unpin_time = existing_unpin_time
                    flag_modified(existing, "unpin_time")

                    existing_delete_time = existing.delete_time or {}
                    existing_delete_time.update(delete_time)
                    existing.delete_time = existing_delete_time
                    flag_modified(existing, "delete_time")

                    session.add(existing)
                else:
                    session.add(post)
                    logger.info(f"Added new post: is_published={post.is_published}, message_ids={post.message_ids}")

                await session.commit()
                logger.info(f"Successfully committed post {post_id or post.id}")

                # Verify database state
                verification = await session.scalar(
                    select(ScheduledPost).where(ScheduledPost.id == (post_id or post.id))
                )
                logger.info(
                    f"Post {post_id or post.id} after commit: is_published={verification.is_published}, message_ids={verification.message_ids}")
            except Exception as e:
                logger.error(f"Failed to update post {post_id}: {e}")
                await session.rollback()
                raise


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
