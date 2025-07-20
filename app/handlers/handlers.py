import asyncio
import os
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InputMediaPhoto
import app.database.requests as req
from datetime import datetime, timedelta
from app.handlers.admin_handlers import is_admin
import pytz

router = Router()


@router.message(Command("help"))
async def help_command(message: Message):
    help_text = """
Помощь по боту для администрирования Telegram-канала
Этот бот помогает управлять постами в канале: добавлять в очередь, планировать публикации и т.д. Доступны только для администраторов.
Доступные команды:
- /pending: Добавить пост в очередь на публикацию.
- /schedule: Добавить пост и запланировать публикацию на определённое время (в формате HH:MM DD-MM-YYYY, часовой пояс Москвы).
- /all_pending_posts: Показать все посты в очереди на публикацию
- /all_scheduled_posts: Показать все посты с определённым временем публикации
- /delete_pending_post id: Удалить определённый пост из очереди по id поста
- /delete_scheduled_post id: Удалить определённый пост с назначенным временем публикации по id поста

- /all_admins - получить список всех администраторов 
- /set_admin @username - добавить нового администратора
- /delete_admin @username - удалить администратора

- /help: Показать эту справку.
    """

    await message.answer(help_text)


@router.message(Command('all_pending_posts'))
async def all_pending_posts(message: Message):
    x = await is_admin(message.from_user.username)
    if not x[0]:
        return
    posts = await req.get_pending_posts()
    for post in posts:
        await message.answer(text=f'id поста: {post.id}')
        if post.photo_file_ids:
            if len(post.photo_file_ids) == 1:
                await message.answer_photo(post.photo_file_ids[0], caption=post.text)
            else:
                media = [InputMediaPhoto(media=file_id) for file_id in post.photo_file_ids]
                if post.text:
                    media[0].caption = post.text  # Caption только для первого
                await message.answer_media_group(media=media)
        else:
            await message.answer(text=post.text)


@router.message(Command('delete_pending_post'))
async def delete_pending_post(message: Message):
    x = await is_admin(message.from_user.username)
    if not x[0]:
        return
    try:
        post_id = int(message.text.split()[1])
        await req.delete_pending_post(post_id)
        await message.answer('Пост успешно удалён')
    except Exception:
        await message.answer('Укажите корректный id поста')


@router.message(Command('all_scheduled_posts'))
async def all_scheduled_posts(message: Message):
    x = await is_admin(message.from_user.username)
    if not x[0]:
        return
    posts = await req.get_scheduled_posts()
    for post in posts:
        await message.answer(text=f'id поста: {post.id}.\n'
                                  f'Запланированное время публикации поста: {post.scheduled_time}\n'
                                  f'Продолжительность нахождения поста в закреплённых в минутах: {post.pin_duration_minutes}')
        if post.photo_file_ids:
            if len(post.photo_file_ids) == 1:
                await message.answer_photo(post.photo_file_ids[0], caption=post.text)
            else:
                media = [InputMediaPhoto(media=file_id) for file_id in post.photo_file_ids]
                if post.text:
                    media[0].caption = post.text  # Caption только для первого
                await message.answer_media_group(media=media)
        else:
            await message.answer(text=post.text)


@router.message(Command('delete_scheduled_post'))
async def delete_scheduled_post(message: Message):
    x = await is_admin(message.from_user.username)
    if not x[0]:
        return
    try:
        post_id = int(message.text.split()[1])
        await req.delete_scheduled_post(post_id)
        await message.answer('Пост успешно удалён')
    except Exception:
        await message.answer('Укажите корректный id поста')


class PendingState(StatesGroup):
    content = State()


@router.message(Command('pending'))
async def store_pending_post(message: Message, state: FSMContext):
    x = await is_admin(message.from_user.username)
    if x[0]:
        await message.answer("Отправьте контент поста (текст и фото, при наличии).")
        await state.set_state(PendingState.content)


@router.message(PendingState.content)
async def second_store_pending_post(message: Message, state: FSMContext, album: list[Message] | None = None):
    if album:
        # Обработка медиа-группы (альбома)
        content_type = 'photo'
        file_ids = [msg.photo[-1].file_id for msg in album if msg.photo]
        text = next((msg.caption for msg in album if msg.caption), '')  # Caption от первого с текстом
        media_group_id = album[0].media_group_id
        await req.add_or_update_pending_post(content_type, text, file_ids, media_group_id)
    else:
        # Одиночное сообщение
        media_group_id = message.media_group_id or 0
        if message.text:
            content_type = 'text'
            text = message.text
            file_ids = []
        elif message.photo:
            content_type = 'photo'
            text = message.caption or ''
            file_ids = [message.photo[-1].file_id]
        else:
            await message.answer("Пожалуйста, отправьте текст или фото.")
            return

        await req.add_or_update_pending_post(content_type, text, file_ids, media_group_id)

    await message.answer("Пост получен и сохранён.")
    await state.clear()


class ScheduleState(StatesGroup):
    content = State()
    time = State()
    unpin_time = State()


@router.message(Command("schedule"))
async def start_schedule(message: Message, state: FSMContext):
    x = await is_admin(message.from_user.username)
    if x[0]:
        await message.answer("Отправьте контент поста (текст и фото, при наличии).")
        await state.set_state(ScheduleState.content)


@router.message(ScheduleState.content)
async def get_content(message: Message, state: FSMContext, album: list[Message] | None = None):
    if album:
        # Обработка медиа-группы
        content_type = 'photo'
        file_ids = [msg.photo[-1].file_id for msg in album if msg.photo]
        text = next((msg.caption for msg in album if msg.caption), '')  # Caption от первого с текстом
        media_group_id = album[0].media_group_id
        await state.update_data(
            content_type=content_type,
            text=text,
            photo_file_ids=file_ids,
            media_group_id=media_group_id
        )
    else:
        # Одиночное сообщение
        media_group_id = message.media_group_id or 0
        if message.text:
            content_type = 'text'
            text = message.text
            file_ids = []
        elif message.photo:
            content_type = 'photo'
            text = message.caption or ''
            file_ids = [message.photo[-1].file_id]
        else:
            await message.answer("Пожалуйста, отправьте текст или фото.")
            return

        await state.update_data(
            content_type=content_type,
            text=text,
            photo_file_ids=file_ids,
            media_group_id=media_group_id
        )

    await message.answer(
        "Отправьте время публикации в формате HH:MM DD-MM-YYYY. Время публикации считается в часовом поясе Москвы.")
    await state.set_state(ScheduleState.time)


@router.message(ScheduleState.time)
async def get_time(message: Message, state: FSMContext):
    try:
        scheduled_time_moscow = datetime.strptime(message.text, "%H:%M %d-%m-%Y")
        if scheduled_time_moscow < datetime.now():
            await message.reply("Время публикации должно быть корректным")
            return
        await state.update_data(scheduled_time_moscow=scheduled_time_moscow)
        await message.answer(
            "Отправьте дату и время, до которых нужно закрепить пост\n/stop если пост не нужно закреплять")
        await state.set_state(ScheduleState.unpin_time)
    except ValueError:
        await message.reply("Неверный формат времени. Используйте HH:MM DD-MM-YYYY.")


@router.message(ScheduleState.unpin_time)
async def get_unpin_time(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        if message.text.lower() == '/stop':
            unpin_time_moscow = 0
        else:
            unpin_time_moscow = datetime.strptime(message.text, "%H:%M %d-%m-%Y")
            if unpin_time_moscow <= data['scheduled_time_moscow']:
                await message.reply("Время открепления должно быть позже времени публикации.")
                return
            unpin_time_moscow -= data['scheduled_time_moscow']
            unpin_time_moscow = unpin_time_moscow.days*24*60*60+unpin_time_moscow.seconds
        await req.add_scheduled_post(
            data['content_type'],
            data['text'],
            data['photo_file_ids'],
            data['scheduled_time_moscow'],
            unpin_time_moscow,
            data['media_group_id']
        )
        await message.answer("Пост успешно запланирован.")
    except ValueError:
        await message.reply("Неверный формат времени. Используйте HH:MM DD-MM-YYYY или /stop.")
    await state.clear()
