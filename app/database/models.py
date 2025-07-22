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


class PendingCounter(Base):
    __tablename__ = 'pending_counter'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column()
    messages_count: Mapped[int] = mapped_column()
    date: Mapped[str] = mapped_column()


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
    delete_time = mapped_column(DateTime)
    pin_duration_minutes: Mapped[int] = mapped_column()
    is_published: Mapped[bool] = mapped_column()
    message_id: Mapped[int] = mapped_column()
    media_group_id: Mapped[int] = mapped_column()


class Admin(Base):
    __tablename__ = 'admins'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(40))
    permission: Mapped[int] = mapped_column()


async def async_main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
