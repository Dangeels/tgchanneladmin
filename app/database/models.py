from sqlalchemy import BigInteger, String, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
import os

engine = create_async_engine(url='sqlite+aiosqlite:///db.sqlite3', echo=False)
async_session = async_sessionmaker(engine)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class LastMessage(Base):
    __tablename__ = 'last_message'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    time = mapped_column(DateTime)


class PendingPost(Base):
    __tablename__ = 'pending_posts'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_type: Mapped[str] = mapped_column()
    text: Mapped[str] = mapped_column()
    photo_file_ids = mapped_column(JSON, default=list)
    media_group_id: Mapped[int] = mapped_column()


class ScheduledPost(Base):
    __tablename__ = 'scheduled_posts'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_type: Mapped[str] = mapped_column()
    text: Mapped[str | None] = mapped_column()
    photo_file_ids = mapped_column(JSON, default=list)
    scheduled_time = mapped_column(DateTime)
    media_group_id: Mapped[int] = mapped_column()
    is_published: Mapped[bool] = mapped_column(default=False)
    message_ids: Mapped[list] = mapped_column(JSON, default=list)
    unpin_time = mapped_column(DateTime, default=None, nullable=True)
    delete_time = mapped_column(DateTime, default=None, nullable=True)


class PostIsPinned(Base):
    __tablename__ = 'is_pinned'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column()
    pinned: Mapped[bool] = mapped_column(default=False)


class Admin(Base):
    __tablename__ = 'admins'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(40))
    permission: Mapped[int] = mapped_column()


async def async_main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
