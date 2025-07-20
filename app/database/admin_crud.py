from sqlalchemy import select, delete
from app.database.models import async_session, Admin


async def is_admin(username):
    async with async_session() as session:
        username = username.strip('@')
        admin = await session.scalar(select(Admin).where(Admin.username == username))
        if admin:
            us = admin.username
            cre = admin.permission
            await session.commit()
            return True, us, cre
        else:
            await session.commit()
            return False, None, 0


async def delete_admin(from_user, username):
    async with async_session() as session:
        username = username.strip('@')
        admin1 = await session.scalar(select(Admin).where(Admin.username == from_user.username))
        admin2 = await session.scalar(select(Admin).where(Admin.username == username))
        if admin1.permission > admin2.permission:
            await session.execute(delete(Admin).where(Admin.username == username))
            await session.commit()
            return True
        await session.commit()
        return False


async def all_admins():
    async with async_session() as session:
        res = []
        nicknames = []
        admin = await session.scalars(select(Admin))
        for a in admin:
            nicknames.append(a.username)
            res.append(f'@{a.username}')
        return res, nicknames


async def set_admin(username1, permission=0):
    async with async_session() as session:
        admin = await session.scalar(select(Admin).where(Admin.username == username1))
        if not admin:
            session.add(Admin(username=username1, permission=permission))
            await session.commit()