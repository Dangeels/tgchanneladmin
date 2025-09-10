from aiogram import Router
from aiogram.types import Message, InputMediaPhoto
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from app.database import admin_crud as req
from app.database import requests as breq
import os
from datetime import datetime, timedelta
import pytz

router1 = Router()


class AdminBroadcast(StatesGroup):
    waiting_interval = State()
    waiting_start = State()
    waiting_end = State()
    waiting_mode = State()
    waiting_window = State()
    waiting_content = State()


async def is_admin(username):
    x = await req.is_admin(username)
    return x


@router1.message(Command('all_admins'))
async def all_admins(message: Message):
    if message.chat.type != 'private':
        return
    a = await is_admin(message.from_user.username)
    if a[0]:
        admins = await req.all_admins()
        await message.answer('Список администраторов\n'+'\n'.join(admins[0]))


@router1.message(Command('delete_admin'))  # формат сообщения /delete_admin @user
async def delete_admin(message: Message):
    if message.chat.type != 'private':
        return
    try:
        username = message.text.split()[1].strip('@')
        ad = await is_admin(message.from_user.username)
        ad2 = await is_admin(username)
        if username==message.from_user.username:
            await message.answer('Вы не можете удалить себя из списка администраторов')
            return
        if ad[0] and ad[2] and ad2[0]:
            dct = {True: 'Пользователь успешно удалён из списка администраторов',
                   False: 'Ошибка доступа: вы не можете удалить этого пользователя'}
            c = await req.delete_admin(message.from_user, username)
            await message.answer(f'{dct[c]}')
        else:
            await message.answer('Пользователь не найден в списке администраторов')
    except Exception:
        await message.answer('Ошибка в формате сообщения')


@router1.message(Command('set_admin'))  # сообщение формата /set_admin @username
async def set_admin(message: Message):
    if message.chat.type != 'private':
        return
    try:
        ad = await is_admin(message.from_user.username)
        if ad[0] and ad[2]:
            username = message.text.split()[1].strip('@')
            await req.set_admin(username)
            await message.answer(f'@{username} успешно добавлен в список администраторов')
    except Exception:
        await message.answer(f'Ошибка в формате сообщения')


@router1.message(Command('broadcast_list'))
async def broadcast_list(message: Message):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    posts = await breq.list_broadcasts(active_only=True)
    if not posts:
        await message.answer('Активных рассылок нет')
        return
    lines = []
    for p in posts[:60]:
        mode = getattr(p, 'mode', 'full')
        window = ''
        if mode == 'limited':
            window = f" [{p.active_start_min//60:02d}:{p.active_start_min%60:02d}-{p.active_end_min//60:02d}:{p.active_end_min%60:02d}]"
        lines.append(f"ID {p.id} | {'ON' if p.is_active else 'OFF'} | {mode}{window} | int {p.interval_minutes}м | next {p.next_run_time} | end {p.end_time}")
    await message.answer('Рассылки (summary):\n' + '\n'.join(lines))
    # Дополнительно отправляем контент для наглядности
    for p in posts[:30]:  # ограничим детализированную выдачу до 30
        header = f"Broadcast ID {p.id} | interval {p.interval_minutes}м | mode {p.mode}"
        if p.content_type == 'text':
            txt = p.text or ''
            if len(txt) > 3500:
                txt_show = txt[:3500] + '...'
            else:
                txt_show = txt
            await message.answer(f"{header}\n---\n{txt_show}" if txt_show else f"{header}\n(пустой текст)")
        elif p.content_type == 'photo' and p.photo_file_ids:
            caption_full = (p.text or '')
            if len(caption_full) > 900:
                caption = caption_full[:900] + '...'
            else:
                caption = caption_full
            if len(p.photo_file_ids) == 1:
                try:
                    await message.answer_photo(p.photo_file_ids[0], caption=f"{header}\n---\n{caption}" if caption else header)
                except Exception:
                    await message.answer(f"{header}\n(не удалось отправить фото)")
            else:
                media = []
                for i, fid in enumerate(p.photo_file_ids[:10]):  # лимит 10
                    if i == 0:
                        media.append(InputMediaPhoto(media=fid, caption=f"{header}\n---\n{caption}" if caption else header))
                    else:
                        media.append(InputMediaPhoto(media=fid))
                try:
                    await message.answer_media_group(media)
                except Exception:
                    await message.answer(f"{header}\n(не удалось отправить медиагруппу)")
        else:
            await message.answer(f"{header}\n(неподдерживаемый или пустой контент)")


@router1.message(Command('broadcast_show'))
async def broadcast_show(message: Message):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    try:
        _, sid = message.text.split(maxsplit=1)
        bid = int(sid)
    except Exception:
        await message.answer('Формат: /broadcast_show <id>')
        return
    bp = await breq.get_broadcast(bid)
    if not bp:
        await message.answer('Не найдена')
        return
    header = (f"Broadcast ID {bp.id}\nStatus: {'ON' if bp.is_active else 'OFF'}\n"
              f"Mode: {bp.mode} | Interval: {bp.interval_minutes}м\n"
              f"Next: {bp.next_run_time}\nEnd: {bp.end_time}")
    if bp.mode == 'limited':
        header += f"\nWindow: {bp.active_start_min//60:02d}:{bp.active_start_min%60:02d}-{bp.active_end_min//60:02d}:{bp.active_end_min%60:02d}"
    if bp.content_type == 'text':
        txt = bp.text or '(пусто)'
        if len(txt) > 4000:
            txt = txt[:4000] + '...'
        await message.answer(header + '\n---\n' + txt)
    elif bp.content_type == 'photo' and bp.photo_file_ids:
        caption = bp.text or ''
        if len(caption) > 900:
            caption = caption[:900] + '...'
        if len(bp.photo_file_ids) == 1:
            try:
                await message.answer_photo(bp.photo_file_ids[0], caption=header + ('\n---\n' + caption if caption else ''))
            except Exception:
                await message.answer(header + '\n(не удалось отправить фото)')
        else:
            media = []
            for i, fid in enumerate(bp.photo_file_ids[:10]):
                if i == 0:
                    media.append(InputMediaPhoto(media=fid, caption=header + ('\n---\n' + caption if caption else '')))
                else:
                    media.append(InputMediaPhoto(media=fid))
            try:
                await message.answer_media_group(media)
            except Exception:
                await message.answer(header + '\n(не удалось отправить медиагруппу)')
    else:
        await message.answer(header + '\n(контент отсутствует или не поддерживается)')


@router1.message(Command('broadcast_stop'))
async def broadcast_stop(message: Message):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    try:
        bid = int(message.text.split()[1])
        ok = await breq.stop_broadcast(bid)
        await message.answer('Остановлено' if ok else 'Не найдено')
    except Exception:
        await message.answer('Формат: /broadcast_stop <id>')


@router1.message(Command('broadcast_mode'))
async def broadcast_mode(message: Message):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    try:
        _, bid, mode = message.text.split(maxsplit=2)
        bid = int(bid)
        if mode not in ('full', 'limited'):
            await message.answer("Режим должен быть full или limited")
            return
        ok = await breq.set_broadcast_mode(bid, mode)
        await message.answer('Изменено' if ok else 'Не найдено')
    except Exception:
        await message.answer('Формат: /broadcast_mode <id> <full|limited>')


@router1.message(Command('broadcast_window'))
async def broadcast_window(message: Message):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    try:
        # /broadcast_window <id> HH:MM-HH:MM
        _, bid, rng = message.text.split(maxsplit=2)
        bid = int(bid)
        t1, t2 = rng.split('-')
        def to_min(s):
            h, m = s.split(':'); return int(h)*60+int(m)
        m1 = to_min(t1); m2 = to_min(t2)
        if not (0 <= m1 < 1440 and 0 <= m2 < 1440):
            raise ValueError
        ok = await breq.update_broadcast_window(bid, m1, m2)
        if ok:
            await breq.set_broadcast_mode(bid, 'limited')
        await message.answer('Окно обновлено' if ok else 'Не найдено')
    except Exception:
        await message.answer('Формат: /broadcast_window <id> HH:MM-HH:MM')


@router1.message(Command('broadcast_global_window'))
async def broadcast_global_window(message: Message):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    try:
        # /broadcast_global_window HH:MM-HH:MM
        _, rng = message.text.split(maxsplit=1)
        t1, t2 = rng.split('-')
        def to_min(s):
            h, m = s.split(':'); return int(h)*60+int(m)
        m1 = to_min(t1); m2 = to_min(t2)
        if not (0 <= m1 < 1440 and 0 <= m2 < 1440):
            raise ValueError
        await breq.upsert_broadcast_config(True, m1, m2)
        await message.answer(f'Глобальное окно включено {t1}-{t2}')
    except Exception:
        await message.answer('Формат: /broadcast_global_window HH:MM-HH:MM')


@router1.message(Command('broadcast_global_off'))
async def broadcast_global_off(message: Message):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    await breq.upsert_broadcast_config(False)
    await message.answer('Глобальное окно отключено (кампании limited будут работать как full если локальное окно не задано).')


# Новый пошаговый мастер для /broadcast
@router1.message(Command('broadcast'))
async def broadcast_start(message: Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    await state.clear()
    await state.set_state(AdminBroadcast.waiting_interval)
    await message.answer('Интервал в минутах (>0 и <=1440). Пример: 120')


@router1.message(AdminBroadcast.waiting_interval)
async def broadcast_get_interval(message: Message, state: FSMContext):
    try:
        interval = int(message.text.strip())
        if interval <= 0 or interval > 1440:
            await message.answer('Интервал минут должен быть >0 и <=1440. Введите снова.')
            return
        await state.update_data(bc_interval=interval)
        await state.set_state(AdminBroadcast.waiting_start)
        await message.answer('Время старта: HH:MM_DD-MM-YYYY или now')
    except Exception:
        await message.answer('Введите число минут. Пример: 180')


@router1.message(AdminBroadcast.waiting_start)
async def broadcast_get_start(message: Message, state: FSMContext):
    tz = pytz.timezone('Europe/Moscow')
    txt = (message.text or '').strip()
    try:
        if txt.lower() in ('now', '/now'):
            start_dt = datetime.now(tz) + timedelta(minutes=1)
        else:
            start_dt = datetime.strptime(txt, '%H:%M_%d-%m-%Y')
            if start_dt.tzinfo is None:
                start_dt = tz.localize(start_dt)
        await state.update_data(bc_start=start_dt)
        await state.set_state(AdminBroadcast.waiting_end)
        await message.answer('Время окончания: HH:MM_DD-MM-YYYY')
    except Exception:
        await message.answer('Формат времени: HH:MM_DD-MM-YYYY или now')


@router1.message(AdminBroadcast.waiting_end)
async def broadcast_get_end(message: Message, state: FSMContext):
    tz = pytz.timezone('Europe/Moscow')
    try:
        end_dt = datetime.strptime(message.text.strip(), '%H:%M_%d-%m-%Y')
        if end_dt.tzinfo is None:
            end_dt = tz.localize(end_dt)
        data = await state.get_data()
        start_dt = data.get('bc_start')
        if not start_dt or end_dt <= start_dt:
            await message.answer('end <= start. Укажите корректное время окончания.')
            return
        await state.update_data(bc_end=end_dt)
        await state.set_state(AdminBroadcast.waiting_mode)
        await message.answer('Режим: full (24/7) или limited (окно). Введите full или limited')
    except Exception:
        await message.answer('Формат времени: HH:MM_DD-MM-YYYY')


@router1.message(AdminBroadcast.waiting_mode)
async def broadcast_get_mode(message: Message, state: FSMContext):
    mode = (message.text or '').strip().lower()
    if mode not in ('full', 'limited'):
        await message.answer('Введите full или limited')
        return
    await state.update_data(bc_mode=mode)
    if mode == 'limited':
        await state.set_state(AdminBroadcast.waiting_window)
        await message.answer('Окно активности HH:MM-HH:MM или /skip для стандартного 09:00-23:00')
    else:
        await state.set_state(AdminBroadcast.waiting_content)
        await message.answer('Отправьте контент (текст или фото) для рассылки')


@router1.message(AdminBroadcast.waiting_window)
async def broadcast_get_window(message: Message, state: FSMContext):
    txt = (message.text or '').strip().lower()
    if txt in ('/skip', 'skip'):
        ws, we = 9*60, 23*60
    else:
        try:
            t1, t2 = txt.split('-')
            h1, m1 = map(int, t1.split(':'))
            h2, m2 = map(int, t2.split(':'))
            ws, we = h1*60+m1, h2*60+m2
            if not (0 <= ws < 1440 and 0 <= we < 1440):
                raise ValueError
        except Exception:
            await message.answer('Формат окна: HH:MM-HH:MM или /skip')
            return
    await state.update_data(bc_win_start=ws, bc_win_end=we)
    await state.set_state(AdminBroadcast.waiting_content)
    await message.answer('Отправьте контент (текст или фото) для рассылки')


@router1.message(AdminBroadcast.waiting_content)
async def broadcast_flow_content(message: Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    data = await state.get_data()
    # Контент
    content_type = None
    text = ''
    file_ids = []
    media_group_id = 0
    if message.text:
        content_type = 'text'
        text = message.text
    elif message.photo:
        content_type = 'photo'
        text = message.caption or ''
        file_ids = [message.photo[-1].file_id]
    else:
        await message.answer('Нужен текст или фото')
        return
    # Валидация длины как в обычной публикации
    max_len = 1024 if file_ids else 4096
    if len(text or '') > max_len:
        await message.answer(f'Слишком длинный текст. Лимит: {max_len} символов. Сейчас: {len(text)}. Отправьте заново.')
        return
    try:
        free_chat = int(os.getenv('FREE_CHAT_ID','0'))
        start_dt = data['bc_start']
        end_dt = data['bc_end']
        interval = data['bc_interval']
        mode = data['bc_mode']
        ws = data.get('bc_win_start') if mode == 'limited' else None
        we = data.get('bc_win_end') if mode == 'limited' else None
        await breq.add_broadcast_post(
            content_type=content_type,
            text=text,
            photo_file_ids=file_ids,
            media_group_id=media_group_id,
            next_run_time=start_dt.replace(tzinfo=None),
            end_time=end_dt.replace(tzinfo=None),
            interval_minutes=interval,
            chat_id=free_chat,
            mode=mode,
            active_start_min=ws,
            active_end_min=we
        )
        await message.answer('Рассылка создана')
    except Exception as e:
        await message.answer(f'Ошибка создания: {e}')
    await state.clear()


# Алиас: старая команда уведомляет об изменении
@router1.message(Command('broadcast_manual'))
async def broadcast_manual_deprecated(message: Message):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    await message.answer('Команда устарела. Используйте /broadcast для пошагового создания рассылки.')
