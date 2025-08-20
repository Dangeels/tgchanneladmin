import asyncio
import os
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InputMediaPhoto
import app.database.requests as req
from datetime import datetime, timedelta
from app.handlers.admin_handlers import is_admin
from app.utils.scheduler import update_unpin_or_delete_task
import pytz

router = Router()


@router.message(Command("help"))
async def help_command(message: Message):
    x = await is_admin(message.from_user.username)
    if message.chat.type != 'private' or not x[0]:
        return
    help_text = """
Помощь по боту для администрирования Telegram-канала
Этот бот помогает управлять постами в канале: добавлять в очередь, планировать публикации и т.д. Доступны только для администраторов.
Доступные команды:
- /pending: Добавить пост в очередь на публикацию.
- /schedule: Добавить пост и опубликовать сразу/запланировать публикацию на определённое время (в формате HH:MM DD-MM-YYYY, часовой пояс Москвы).
- /pin_post [post_id] [chat_id] date[HH:MM DD-MM-YYYY]: Закрепить уже опубликованный пост или добавить закрепление для запланированного поста, где дата - время открепления поста, если его не указывать, пост будет закреплён навсегда
- /all_pending_posts: Показать все посты в очереди на публикацию
- /all_scheduled_posts: Показать все посты с определённым временем публикации
- /delete_pending_post [id]: Удалить определённый пост из очереди по id поста
- /delete_scheduled_post [id]: Удалить из базы данных определённый пост с назначенным временем публикации по id поста, если пост уже опубликован, он также будет удалён

- /all_admins - получить список всех администраторов 
- /set_admin @username - добавить нового администратора
- /delete_admin @username - удалить администратора

- /help: Показать эту справку.
    """

    await message.answer(help_text)


@router.message(Command('all_pending_posts'))
async def all_pending_posts(message: Message):
    x = await is_admin(message.from_user.username)
    if not x[0] or message.chat.type != 'private':
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
    if not x[0] or message.chat.type != 'private':
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
    if not x[0] or message.chat.type != 'private':
        return
    posts = await req.get_scheduled_posts()
    for post in posts:
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
        text = f'id поста: {post.id}.\n'
        published = {True: f'Пост уже опубликован в  чатах: {post.chat_ids}\n',
                     False: f'Запланированное время публикации поста: {post.scheduled_time}\n'}
        unpin = {True: f'Пост будет откреплён: {post.unpin_time}\n', False: 'Пост не будет закреплён\n'}
        text+=published[all(i for i in post.is_published.values())]+unpin[post.unpin_time is not None]+f'Пост будет удалён: {post.delete_time}'
        await message.answer(text=text)


async def delete_scheduled_post(message: Message, bot: Bot):
    x = await is_admin(message.from_user.username)
    if not x[0] or message.chat.type != 'private':
        return
    try:
        post_id = int(message.text.split()[1])
        post = await req.get_scheduled_post(post_id)
        for chat_id in post.chat_ids:
            if post.is_published.get(str(chat_id), False):
                await bot.delete_messages(chat_id, post.message_ids)
        a = await req.delete_scheduled_post(post_id)
        if a:
            await message.answer('Пост успешно удалён')
    except Exception as e:
        await message.answer(f'Укажите корректный id поста {e}')


async def pin_post(message: Message, bot: Bot, scheduler):
    x = await is_admin(message.from_user.username)
    if not x[0] or message.chat.type != 'private':
        return
    try:
        m_text = message.text.split()
        chat_id = int(m_text[2])
        post = await req.get_scheduled_post(int(m_text[1]))
        if len(message.text.split()) >= 4:
            unpin = ' '.join(m_text[3:])
        else:
            unpin = '12:00 31-12-2200'
        unpin = datetime.strptime(unpin, '%H:%M %d-%m-%Y').isoformat()
        await req.add_or_update_scheduled_post(content_type=post.content_type, unpin_time={str(chat_id): unpin},
                                               post_id=post.id, is_published=post.is_published)
        if post.is_published.get(str(chat_id), False):
            await update_unpin_or_delete_task(bot, chat_id, scheduler)
    except Exception:
        await message.answer('Не удалось закрепить пост')


class PendingState(StatesGroup):
    content = State()


@router.message(Command('pending'))
async def store_pending_post(message: Message, state: FSMContext):
    x = await is_admin(message.from_user.username)
    if x[0] and message.chat.type == 'private':
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
        await req.add_or_update_pending_post(content_type, text, file_ids, int(media_group_id))
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
    chat_selection = State()  # Added: New state for selecting multiple chat IDs
    time = State()
    unpin_time = State()
    delete_time = State()


@router.message(Command("schedule"))
async def start_schedule(message: Message, state: FSMContext):
    x = await is_admin(message.from_user.username)
    if x[0] and message.chat.type == 'private':  # Ensures admin-only and private chat restriction
        await message.answer("Отправьте контент поста (текст и фото, при наличии).")
        await state.set_state(ScheduleState.content)
    else:
        await message.answer("Доступ запрещен.")  # Added: Explicit denial for non-admins or non-private chats


@router.message(ScheduleState.content)
async def get_content(message: Message, state: FSMContext, album: list[Message] | None = None):
    if album:
        # Обработка медиа-группы (albums handled via middleware, as per Aiogram docs)
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

    # Changed: Now prompt for chat selection after content, before time
    await message.answer(
        f"Введите chat_id для публикации, если их несколько, введите через их через запятую.\n"
        f"Текущие id чатов:\n"
        f"Фриланс и Удалёнка | Бесплатное Размещение: {os.getenv('FREE_CHAT_ID')}\n"
        f"Фриланс, вакансии, удалёнка: {os.getenv('MAIN_CHAT_ID')}\n"
        f"Удалёнка и вакансии | Премиум: {os.getenv('PREMIUM_CHANNEL_ID')}"
    )
    await state.set_state(ScheduleState.chat_selection)


# Added: New handler for chat selection state
@router.message(ScheduleState.chat_selection)
async def get_chat_selection(message: Message, state: FSMContext):
    try:
        # Parse comma-separated chat IDs into a list of integers
        chat_ids = [int(cid.strip()) for cid in message.text.split(',')]
        if not chat_ids:
            raise ValueError("No valid chat IDs provided.")
        await state.update_data(chat_ids=chat_ids)
        await message.answer(
            "Отправьте время публикации в формате HH:MM DD-MM-YYYY. Время публикации считается в часовом поясе Москвы."
            "\nОтправьте /now, если пост нужно опубликовать сейчас"
        )
        await state.set_state(ScheduleState.time)
    except ValueError:
        await message.reply("Неверный формат chat_id. Введите числа через запятую.")


@router.message(ScheduleState.time)
async def get_time(message: Message, state: FSMContext):
    try:
        if message.text == '/now':
            scheduled_time_moscow = datetime.now() + timedelta(minutes=1, seconds=30)
        else:
            scheduled_time_moscow = datetime.strptime(message.text, "%H:%M %d-%m-%Y")
        if scheduled_time_moscow < datetime.now():
            await message.reply("Время публикации должно быть корректным")
            return
        await state.update_data(scheduled_time_moscow=scheduled_time_moscow)
        await message.answer(
            "Отправьте дату и время, до которых нужно закрепить пост\n/stop если пост не нужно закреплять\n/forever "
            "если пост нужно закрепить навсегда"
        )
        await state.set_state(ScheduleState.unpin_time)
    except ValueError:
        await message.reply("Неверный формат времени. Используйте HH:MM DD-MM-YYYY.")


@router.message(ScheduleState.unpin_time)
async def get_unpin_time(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_ids = data.get('chat_ids', [])  # Retrieve chat_ids from state
    try:
        if message.text.lower() == '/forever':
            unpin_time_moscow = datetime.strptime("12:00 31-12-2200", "%H:%M %d-%m-%Y")
            unpin_dict = {cid: unpin_time_moscow for cid in chat_ids}  # Adapted: Dict per chat for new DB schema
        elif message.text.lower() == '/stop':
            unpin_dict = {}  # Adapted: Empty dict means no unpin (per scheduler logic)
        else:
            unpin_time_moscow = datetime.strptime(message.text, "%H:%M %d-%m-%Y")
            if unpin_time_moscow <= data['scheduled_time_moscow']:
                await message.reply("Время открепления должно быть позже времени публикации.")
                return
            unpin_dict = {cid: unpin_time_moscow for cid in chat_ids}  # Adapted: Uniform dict for all chats

        await state.update_data(unpin_time=unpin_dict)  # Changed: Store as dict instead of single value
        await message.answer(
            "Отправьте дату и время удаления поста\n/forever если пост нужно опубликовать навсегда"
        )
        await state.set_state(ScheduleState.delete_time)
    except ValueError:
        await message.reply("Неверный формат времени. Используйте HH:MM DD-MM-YYYY или /stop.")


@router.message(ScheduleState.delete_time)
async def get_delete_time(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_ids = data.get('chat_ids', [])
    try:
        if message.text.lower() == '/forever':
            delete_time = datetime.strptime("12:00 31-12-2200", "%H:%M %d-%m-%Y")
        else:
            delete_time = datetime.strptime(message.text, "%H:%M %d-%m-%Y")
            if delete_time <= data['scheduled_time_moscow']:
                await message.reply("Время удаления поста должно быть позже времени публикации.")
                return

        unpin_time = {str(cid): data['unpin_time'].isoformat() for cid in chat_ids}
        delete_dict = {str(cid): delete_time.isoformat() for cid in chat_ids}
        is_published = {str(cid): False for cid in chat_ids}  # Initialize with string keys
        await req.add_or_update_scheduled_post(
            content_type=data['content_type'],
            text=data['text'],
            photo_file_ids=data['photo_file_ids'],
            scheduled_time=data['scheduled_time_moscow'],
            media_group_id=data['media_group_id'],
            unpin_time=unpin_time,
            delete_time=delete_dict,
            chat_ids=chat_ids,
            is_published=is_published
        )
        await message.answer("Пост успешно запланирован.")
    except ValueError:
        await message.reply("Неверный формат времени. Используйте HH:MM DD-MM-YYYY или /forever.")
    except Exception as e:
        await message.reply(f"Ошибка при планировании поста. {e}")
    await state.clear()
