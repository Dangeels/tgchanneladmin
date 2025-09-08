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
    posts = await breq.list_broadcasts()
    if not posts:
        await message.answer('Активных или сохранённых рассылок нет')
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


# /broadcast_manual <interval_minutes> <start:HH:MM_DD-MM-YYYY|now> <end:HH:MM_DD-MM-YYYY> <full|limited> [HH:MM-HH:MM]
@router1.message(Command('broadcast_manual'))
async def broadcast_manual(message: Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    try:
        parts = message.text.split()
        if len(parts) < 5:
            raise ValueError
        _, interval_s, start_s, end_s, mode, *rest = parts
        interval = int(interval_s)
        if interval <= 0 or interval > 60*24:
            await message.answer('Интервал минут должен быть >0 и <=1440')
            return
        tz = pytz.timezone('Europe/Moscow')
        now = datetime.now(tz)
        if start_s.lower() == 'now':
            start_dt = now + timedelta(minutes=1)
        else:
            start_dt = datetime.strptime(start_s, '%H:%M_%d-%m-%Y')
            if start_dt.tzinfo is None:
                start_dt = tz.localize(start_dt)
        end_dt = datetime.strptime(end_s, '%H:%M_%d-%m-%Y')
        if end_dt.tzinfo is None:
            end_dt = tz.localize(end_dt)
        if end_dt <= start_dt:
            await message.answer('end <= start')
            return
        if mode not in ('full','limited'):
            await message.answer('mode должен быть full или limited')
            return
        win_start = win_end = None
        if rest:
            try:
                t1,t2 = rest[0].split('-')
                h1,m1 = map(int,t1.split(':'))
                h2,m2 = map(int,t2.split(':'))
                win_start = h1*60+m1
                win_end = h2*60+m2
            except Exception:
                await message.answer('Окно формата HH:MM-HH:MM')
                return
        await state.update_data(
            manual_interval=interval,
            manual_start=start_dt,
            manual_end=end_dt,
            manual_mode=mode,
            manual_win_start=win_start,
            manual_win_end=win_end
        )
        await state.set_state(AdminBroadcast.waiting_content)
        await message.answer('Отправьте контент (текст или фото) для ручной рассылки.')
    except Exception:
        await message.answer('Формат: /broadcast_manual <interval_minutes> <start HH:MM_DD-MM-YYYY|now> <end HH:MM_DD-MM-YYYY> <full|limited> [HH:MM-HH:MM]')


@router1.message(AdminBroadcast.waiting_content)
async def broadcast_manual_content(message: Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    ad = await is_admin(message.from_user.username)
    if not ad[0]:
        return
    data = await state.get_data()
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
    # NEW: валидация длины аналогично обычной публикации
    max_len = 1024 if file_ids else 4096
    if len(text or '') > max_len:
        await message.answer(f'Слишком длинный текст. Лимит: {max_len} символов. Сейчас: {len(text)}. Отправьте заново.')
        return
    try:
        free_chat = int(os.getenv('FREE_CHAT_ID','0'))
        start_dt = data['manual_start']
        end_dt = data['manual_end']
        interval = data['manual_interval']
        mode = data['manual_mode']
        ws = data.get('manual_win_start')
        we = data.get('manual_win_end')
        # сохраняем без tz
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
        await message.answer('Ручная рассылка создана')
    except Exception as e:
        await message.answer(f'Ошибка создания: {e}')
    await state.clear()
