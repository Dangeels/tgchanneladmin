from sqlalchemy import BigInteger, String, DateTime, JSON, Integer, Boolean
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
    # Новое: целевой чат для публикации
    chat_id: Mapped[int] = mapped_column(BigInteger, default=0)


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
    # Новое: целевой чат для публикации
    chat_id: Mapped[int] = mapped_column(BigInteger, default=0)


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


class BroadcastPost(Base):
    __tablename__ = 'broadcast_posts'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_type: Mapped[str] = mapped_column()
    text: Mapped[str | None] = mapped_column()
    photo_file_ids = mapped_column(JSON, default=list)
    media_group_id: Mapped[int] = mapped_column(default=0)
    next_run_time = mapped_column(DateTime)
    end_time = mapped_column(DateTime)
    interval_minutes: Mapped[int] = mapped_column(Integer)
    chat_id: Mapped[int] = mapped_column(BigInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_time = mapped_column(DateTime, default=None, nullable=True)
    # NEW: режим (full | limited)
    mode: Mapped[str] = mapped_column(String(16), default='full')
    # NEW: окно активности (минуты от полуночи локального времени), используется если mode == 'limited'
    active_start_min: Mapped[int] = mapped_column(Integer, default=9*60)  # 09:00
    active_end_min: Mapped[int] = mapped_column(Integer, default=23*60)    # 23:00


class BroadcastConfig(Base):
    __tablename__ = 'broadcast_config'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active_start_min: Mapped[int] = mapped_column(Integer, default=9*60)
    active_end_min: Mapped[int] = mapped_column(Integer, default=23*60)


async def async_main():
    async with engine.begin() as conn:
        # Создаём таблицы, если их нет
        await conn.run_sync(Base.metadata.create_all)
        # Простейшая "миграция" для добавления chat_id, если столбца ещё нет
        try:
            for table in ('pending_posts', 'scheduled_posts'):
                res = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
                cols = [row[1] for row in res.fetchall()]  # 1-й индекс = имя колонки
                if 'chat_id' not in cols:
                    await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN chat_id BIGINT DEFAULT 0")
        except Exception:
            # Игнорируем, если БД не SQLite или столбец уже есть
            pass
        try:
            # Дополнительная проверка наличия таблицы broadcast_posts
            res = await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='broadcast_posts'")
            exists = res.fetchone()
            if not exists:
                await conn.run_sync(Base.metadata.create_all)
        except Exception:
            pass
        try:
            # Миграция для новых колонок BroadcastPost
            res = await conn.exec_driver_sql("PRAGMA table_info(broadcast_posts)")
            cols = [row[1] for row in res.fetchall()]
            alter_map = {
                'mode': "ALTER TABLE broadcast_posts ADD COLUMN mode VARCHAR(16) DEFAULT 'full'",
                'active_start_min': "ALTER TABLE broadcast_posts ADD COLUMN active_start_min INTEGER DEFAULT 540",
                'active_end_min': "ALTER TABLE broadcast_posts ADD COLUMN active_end_min INTEGER DEFAULT 1380",
            }
            for col, sql in alter_map.items():
                if col not in cols:
                    try:
                        await conn.exec_driver_sql(sql)
                    except Exception:
                        pass
            # Создание таблицы broadcast_config если нет
            res2 = await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='broadcast_config'")
            if not res2.fetchone():
                await conn.run_sync(Base.metadata.create_all)
        except Exception:
            pass
