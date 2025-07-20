from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable
import asyncio


class AlbumMiddleware(BaseMiddleware):
    album_data: dict = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        if not event.media_group_id:
            return await handler(event, data)

        try:
            self.album_data[event.media_group_id].append(event)
            return  # Не вызываем хендлер для отдельных сообщений в группе
        except KeyError:
            self.album_data[event.media_group_id] = [event]
            await asyncio.sleep(0.01)  # Маленькая задержка для сбора всей группы

        await asyncio.sleep(2)  # Ждём 2 секунды на сбор всей группы
        data["album"] = self.album_data.pop(event.media_group_id)
        return await handler(event, data)