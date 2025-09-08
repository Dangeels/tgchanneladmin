import os
from datetime import datetime
from sqlalchemy import select
from app.database.models import async_session, PendingPost, ScheduledPost, LastMessage, PostIsPinned, BroadcastPost, BroadcastConfig


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
        chat_id=chat_id or int(os.getenv('MAIN_CHAT_ID', 0))
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
        return False


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
        chat_id=chat_id or int(os.getenv('MAIN_CHAT_ID', 0))
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
        return False


async def add_broadcast_post(
    content_type: str,
    text: str | None,
    photo_file_ids: list[str] | None,
    media_group_id: int,
    next_run_time: datetime,
    end_time: datetime,
    interval_minutes: int,
    chat_id: int,
    mode: str = 'full',
    active_start_min: int | None = None,
    active_end_min: int | None = None
):
    if not photo_file_ids:
        photo_file_ids = []
    if mode not in ('full', 'limited'):
        mode = 'full'
    # Если окно не передано — пробуем взять глобальное
    if mode == 'limited':
        if active_start_min is None or active_end_min is None:
            cfg = await get_broadcast_config()
            if cfg and cfg.enabled:
                active_start_min = cfg.active_start_min
                active_end_min = cfg.active_end_min
            else:
                # если глобальная конфигурация выключена — fallback в full
                mode = 'full'
    post = BroadcastPost(
        content_type=content_type,
        text=text,
        photo_file_ids=photo_file_ids.copy(),
        media_group_id=media_group_id or 0,
        next_run_time=next_run_time,
        end_time=end_time,
        interval_minutes=interval_minutes,
        chat_id=chat_id,
        is_active=True,
        mode=mode,
        active_start_min=active_start_min if active_start_min is not None else 9*60,
        active_end_min=active_end_min if active_end_min is not None else 23*60
    )
    async with async_session() as session:
        async with session.begin():
            session.add(post)
        await session.commit()
    return post


async def get_active_broadcast_posts():
    async with async_session() as session:
        posts = await session.scalars(select(BroadcastPost).where(BroadcastPost.is_active == True))
        return posts.all()


async def update_broadcast_run(post_id: int, next_run_time: datetime | None, last_run_time: datetime, deactivate: bool = False):
    async with async_session() as session:
        async with session.begin():
            bp = await session.get(BroadcastPost, post_id, with_for_update=True)
            if not bp:
                return False
            bp.last_run_time = last_run_time
            if deactivate:
                bp.is_active = False
            else:
                bp.next_run_time = next_run_time
            session.add(bp)
        await session.commit()
    return True


async def stop_broadcast(post_id: int):
    async with async_session() as session:
        async with session.begin():
            bp = await session.get(BroadcastPost, post_id, with_for_update=True)
            if not bp:
                return False
            bp.is_active = False
            session.add(bp)
        await session.commit()
    return True


async def set_broadcast_mode(post_id: int, mode: str):
    if mode not in ('full', 'limited'):
        return False
    async with async_session() as session:
        async with session.begin():
            bp = await session.get(BroadcastPost, post_id, with_for_update=True)
            if not bp:
                return False
            bp.mode = mode
            session.add(bp)
        await session.commit()
    return True


async def update_broadcast_window(post_id: int, start_min: int, end_min: int):
    async with async_session() as session:
        async with session.begin():
            bp = await session.get(BroadcastPost, post_id, with_for_update=True)
            if not bp:
                return False
            bp.active_start_min = start_min
            bp.active_end_min = end_min
            session.add(bp)
        await session.commit()
    return True


async def get_broadcast(post_id: int):
    async with async_session() as session:
        return await session.get(BroadcastPost, post_id)


async def list_broadcasts(active_only: bool = False):
    async with async_session() as session:
        if active_only:
            posts = await session.scalars(select(BroadcastPost).where(BroadcastPost.is_active == True))
        else:
            posts = await session.scalars(select(BroadcastPost))
        return posts.all()


async def get_broadcast_config():
    async with async_session() as session:
        cfg = await session.scalar(select(BroadcastConfig).limit(1))
        return cfg


async def upsert_broadcast_config(enabled: bool, start_min: int | None = None, end_min: int | None = None):
    async with async_session() as session:
        async with session.begin():
            cfg = await session.scalar(select(BroadcastConfig).limit(1).with_for_update())
            if not cfg:
                cfg = BroadcastConfig(
                    enabled=enabled,
                    active_start_min=start_min if start_min is not None else 9*60,
                    active_end_min=end_min if end_min is not None else 23*60
                )
                session.add(cfg)
            else:
                cfg.enabled = enabled
                if start_min is not None:
                    cfg.active_start_min = start_min
                if end_min is not None:
                    cfg.active_end_min = end_min
                session.add(cfg)
        await session.commit()
    return True
