import os
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InputMediaPhoto
import app.database.requests as req
from datetime import datetime, timedelta
from app.handlers.admin_handlers import is_admin
from app.utils.scheduler import update_unpin_or_delete_task


router = Router()


@router.message(Command("help"))
async def help_command(message: Message):
    x = await is_admin(message.from_user.username)
    if message.chat.type != 'private' or not x[0]:
        return
    help_text = (
"""
Помощь (админ)
Основные пользовательские функции теперь доступны через /menu (там же пункт Рассылка).

Команды управления постами:
/pending – добавить пост в очередь.
/schedule – запланировать публикацию.
/all_pending_posts – показать очередь.
/all_scheduled_posts – показать запланированные.
/delete_pending_post <id> – удалить из очереди.
/delete_scheduled_post <id> – удалить запланированный (и из чата, если уже опубликован).
/pin_post <id> [HH:MM DD-MM-YYYY] – (пере)закрепить; если время не указано – навсегда (до 31-12-2200).
/chats – показать текущие chat_id из .env.

Администраторы:
/all_admins – список админов.
/set_admin @username – добавить админа.
/delete_admin @username – удалить админа (при достаточных правах).

Рассылки (broadcast) – повторная публикация поста по интервалу в бесплатный чат:
/broadcast_list – список рассылок (ID, статус, режим, окно, next, end).
/broadcast_stop <id> – остановить кампанию.
/broadcast_mode <id> <full|limited> – сменить режим.
/broadcast_window <id> HH:MM-HH:MM – локальное дневное окно кампании (автоматически ставит limited).
/broadcast_global_window HH:MM-HH:MM – включить/обновить глобальное окно для всех limited без локального.
/broadcast_global_off – отключить глобальное окно (limited без локального работает как full).
/broadcast_manual <interval_minutes> <start HH:MM_DD-MM-YYYY|now> <end HH:MM_DD-MM-YYYY> <full|limited> [HH:MM-HH:MM]
  Пример: /broadcast_manual 120 now 23:00_10-09-2025 limited 09:00-23:00

Режимы:
 full – публикация 24/7.
 limited – только внутри окна (локального или глобального). Если оба отключены – работает как full.

Окна (ночной режим):
- Локальное (per campaign) через /broadcast_window.
- Глобальное через /broadcast_global_window.
- Если limited и нет активного окна – будет выбран full.


Эта справка предназначена только для админов. Для обычных пользователей /menu.
"""
    )
    await message.answer(help_text)


@router.message(Command('chats'))
async def show_chats(message: Message):
    x = await is_admin(message.from_user.username)
    if message.chat.type != 'private' or not x[0]:
        return
    admin_chat_id = os.getenv('ADMIN_CHAT_ID')
    channel_id = os.getenv('CHANNEL_ID')  # Премиум-канал
    free_chat_id = os.getenv('FREE_CHAT_ID')
    main_chat_id = os.getenv('MAIN_CHAT_ID')
    notification_chat = os.getenv('NOTIFICATION_CHAT', admin_chat_id)
    txt = (
        f"ADMIN_CHAT_ID: {admin_chat_id}\n"
        f"CHANNEL_ID (премиум): {channel_id}\n"
        f"FREE_CHAT_ID: {free_chat_id}\n"
        f"MAIN_CHAT_ID: {main_chat_id}\n"
        f"NOTIFICATION_CHAT: {notification_chat}"
    )
    await message.answer(txt)


@router.message(Command('all_pending_posts'))
async def all_pending_posts(message: Message):
    x = await is_admin(message.from_user.username)
    if not x[0] or message.chat.type != 'private':
        return
    posts = await req.get_pending_posts()
    for post in posts:
        await message.answer(text=f'id поста: {post.id}\nchat_id: {getattr(post, "chat_id", None)}')
        if post.photo_file_ids:
            if len(post.photo_file_ids) == 1:
                await message.answer_photo(post.photo_file_ids[0], caption=(post.text or ''))
            else:
                media = [InputMediaPhoto(media=file_id) for file_id in post.photo_file_ids]
                if post.text:
                    media[0].caption = post.text  # Caption только для первого
                await message.answer_media_group(media=media)
        else:
            await message.answer(text=(post.text or ''))


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
                await message.answer_photo(post.photo_file_ids[0], caption=(post.text or ''))
            else:
                media = [InputMediaPhoto(media=file_id) for file_id in post.photo_file_ids]
                if post.text:
                    media[0].caption = post.text  # Caption только для первого
                await message.answer_media_group(media=media)
        else:
            await message.answer(text=(post.text or ''))
        text = f'id поста: {post.id}.\nchat_id: {getattr(post, "chat_id", None)}\n'
        published = {True: 'Пост уже опубликован\n', False: f'Запланированное время публикации поста: {post.scheduled_time}\n'}
        unpin = {True: f'Пост будет откреплён: {post.unpin_time}\n', False: 'Пост не будет закреплён\n'}
        text+=published[post.is_published]+unpin[post.unpin_time is not None]+f'Пост будет удалён: {post.delete_time}'
        await message.answer(text=text)


async def delete_scheduled_post(message: Message, bot: Bot, chat_id):
    x = await is_admin(message.from_user.username)
    if not x[0] or message.chat.type != 'private':
        return
    try:
        post_id = int(message.text.split()[1])
        post = await req.get_scheduled_post(post_id)
        target_chat = getattr(post, 'chat_id', None) or chat_id
        if post.is_published:
            await bot.delete_messages(target_chat, post.message_ids)
        a = await req.delete_scheduled_post(post_id)
        if a:
            await message.answer('Пост успешно удалён')
    except Exception as e:
        await message.answer(f'Укажите корректный id поста {e}')


async def pin_post(message: Message, bot: Bot, chat_id, scheduler):
    x = await is_admin(message.from_user.username)
    if not x[0] or message.chat.type != 'private':
        return
    try:
        m_text = message.text.split()
        post = await req.get_scheduled_post(int(m_text[1]))
        target_chat = getattr(post, 'chat_id', None) or chat_id
        if len(message.text.split()) >= 3:
            unpin = ' '.join(m_text[2:])
        else:
            unpin = '12:00 31-12-2200'
        unpin = datetime.strptime(unpin, '%H:%M %d-%m-%Y')
        await req.add_or_update_scheduled_post(content_type=post.content_type, unpin_time=unpin, post_id=post.id,
                                               is_published=post.is_published)
        if post.is_published:
            await update_unpin_or_delete_task(bot, target_chat, scheduler)
        await message.answer('Настройки закрепа обновлены')
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
        # Валидация длины текста
        max_len = 1024 if file_ids else 4096
        if len(text or '') > max_len:
            await message.answer(
                f"Слишком длинный текст. Для постов с медиа — до 1024 символов, без медиа — до 4096 символов. "
                f"Сейчас: {len(text or '')} символов. Отправьте контент заново."
            )
            return
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

        # Валидация длины текста
        max_len = 1024 if file_ids else 4096
        if len(text or '') > max_len:
            await message.answer(
                f"Слишком длинный текст. Для постов с медиа — до 1024 символов, без медиа — до 4096 символов. "
                f"Сейчас: {len(text or '')} символов. Отправьте контент заново."
            )
            return

        await req.add_or_update_pending_post(content_type, text, file_ids, media_group_id)

    await message.answer("Пост получен и сохранён.")
    await state.clear()


class ScheduleState(StatesGroup):
    content = State()
    time = State()
    unpin_time = State()
    delete_time = State()


@router.message(Command("schedule"))
async def start_schedule(message: Message, state: FSMContext):
    x = await is_admin(message.from_user.username)
    if x[0] and message.chat.type == 'private':
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
        # Валидация длины текста
        max_len = 1024 if file_ids else 4096
        if len(text or '') > max_len:
            await message.answer(
                f"Слишком длинный текст. Для постов с медиа — до 1024 символов, без медиа — до 4096 символов. "
                f"Сейчас: {len(text or '')} символов. Отправьте контент заново."
            )
            return
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

        # Валидация длины текста
        max_len = 1024 if file_ids else 4096
        if len(text or '') > max_len:
            await message.answer(
                f"Слишком длинный текст. Для постов с медиа — до 1024 символов, без медиа — до 4096 символов. "
                f"Сейчас: {len(text or '')} символов. Отправьте контент заново."
            )
            return

        await state.update_data(
            content_type=content_type,
            text=text,
            photo_file_ids=file_ids,
            media_group_id=media_group_id
        )

    await message.answer(
        "Отправьте время публикации в формате HH:MM DD-MM-YYYY. Время публикации считается в часовом поясе Москвы."
        "\nОтправьте /now, если пост нужно опубликовать сейчас")
    await state.set_state(ScheduleState.time)


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
            "если пост нужно закрепить навсегда")
        await state.set_state(ScheduleState.unpin_time)
    except ValueError:
        await message.reply("Неверный формат времени. Используйте HH:MM DD-MM-YYYY.")


@router.message(ScheduleState.unpin_time)
async def get_unpin_time(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        if message.text.lower() == '/forever':
            unpin_time_moscow = "12:00 31-12-2200"
            unpin_time_moscow = datetime.strptime(unpin_time_moscow, "%H:%M %d-%m-%Y")
        elif message.text.lower() == '/stop':
            unpin_time_moscow = None
        else:
            unpin_time_moscow = datetime.strptime(message.text, "%H:%M %d-%m-%Y")
            if unpin_time_moscow <= data['scheduled_time_moscow']:
                await message.reply("Время открепления должно быть позже времени публикации.")
                return
        await state.update_data(unpin_time=unpin_time_moscow)
        await message.answer(
            "Отправьте дату и время удаления поста пост\n/forever если пост нужно опубликовать навсегда")
        await state.set_state(ScheduleState.delete_time)
    except ValueError:
        await message.reply("Неверный формат времени. Используйте HH:MM DD-MM-YYYY или /stop.")


@router.message(ScheduleState.delete_time)
async def get_delete_time(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        if message.text.lower() == '/forever':
            delete_time = "12:00 31-12-2200"
            delete_time = datetime.strptime(delete_time, "%H:%M %d-%m-%Y")
        else:
            delete_time = datetime.strptime(message.text, "%H:%M %d-%m-%Y")
            if delete_time <= data['scheduled_time_moscow']:
                await message.reply("Время удаления поста должно быть позже времени публикации.")
                return

        await req.add_or_update_scheduled_post(
            data['content_type'],
            data['text'],
            data['photo_file_ids'],
            data['scheduled_time_moscow'],
            data['media_group_id'],
            unpin_time=data['unpin_time'],
            delete_time=delete_time
        )
        await message.answer("Пост успешно запланирован.")
    except ValueError:
        await message.reply("Неверный формат времени. Используйте HH:MM DD-MM-YYYY или /stop.")
    await state.clear()
