from sqlalchemy import BigInteger, String, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine


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
    is_published: Mapped[dict] = mapped_column(JSON, default=dict)
    message_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    unpin_time = mapped_column(JSON, default=dict)
    delete_time = mapped_column(JSON, default=dict)
    chat_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class PostIsPinned(Base):  # Changed: Renamed from PostIsPinned for clarity; adapted for per-chat
    __tablename__ = 'is_pinned'
    chat_id: Mapped[int] = mapped_column(primary_key=True)  # Changed: Added chat_id as part of composite PK
    message_id: Mapped[int] = mapped_column(primary_key=True)  # Changed: Renamed from post_id; part of composite PK
    pinned: Mapped[bool] = mapped_column(default=False)


class Admin(Base):
    __tablename__ = 'admins'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(40))
    permission: Mapped[int] = mapped_column()


async def async_main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
