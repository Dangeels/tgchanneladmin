from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from app.database import admin_crud as req

router1 = Router()


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