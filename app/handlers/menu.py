import asyncio
import logging
import sys
from os import getenv
from typing import Any, Awaitable, Callable, Dict, List
import uuid
import os

from aiogram import F, Router, Bot
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timedelta
import pytz
from app.database.requests import add_or_update_scheduled_post
from dotenv import load_dotenv

# Replace with your admin chat ID
ADMIN_CHAT_ID = -1002890391749  # Example, replace with actual chat ID

load_dotenv()

FREE_CHAT_ID = (os.getenv('FREE_CHAT_ID'))
MAIN_CHAT_ID = (os.getenv('MAIN_CHAT_ID'))
PREMIUM_CHANNEL_ID = (os.getenv('PREMIUM_CHANNEL_ID'))


# Global storage for pending orders
pending_orders: Dict[str, Dict] = {}

# Define FSM states for the purchase process
class Purchase(StatesGroup):
    waiting_check = State()  # Waiting for payment check photo
    waiting_post = State()   # Waiting for the post text

# Define CallbackData factory for menu navigation
class MenuCallback(CallbackData, prefix="menu"):
    level: str  # e.g., 'main', 'sub', 'extra', 'subextra', 'toggle', 'buy', 'cancel'
    user_type: str = ""  # 'employer' or 'freelancer'
    option: str = ""     # '1', '2', etc.
    suboption: str = ""  # For extra options like 'pin', 'boost', 'extend'
    variant: str = ""    # For variants like '1_month', 'forever'
    action: str = ""     # 'add' or 'remove' for toggle

# Define CallbackData for admin actions
class AdminCallback(CallbackData, prefix="admin"):
    action: str  # 'confirm' or 'reject'
    order_id: str

menu_router = Router()

# Suboption names
SUBOPTION_NAMES = {
    "pin": "Закреп",
    "boost": "Поднятие",
    "extend": "Продление"
}

# Emoji for main options
OPTION_EMOJIS = {
    "1": "📌",
    "2": "📑",
    "3": "📢",
    "4": "📦",
    "5": "📦",
    "6": "⭐"
}

# Base prices
BASE_PRICES = {
    "employer": {
        "1": 0,
        "2": 1200,
        "3": 2400,
        "4": 2500,
        "5": 2900,
        "6": 10000
    },
    "freelancer": {
        "1": 0,
        "2": 900,
        "4": 2500,
        "5": 2900,
        "6": 5000
    }
}

# Descriptions
DESCRIPTIONS = {
    "employer": {
        "1": "для работодателей\nЦена Закрепа в бесплатном чате:",
        "2": "📑Стандарт - 1200 рублей:\n- Размещение НАВСЕГДА\n- Без закрепа",
        "3": "Прайс канала:\n📑Стандарт - 2400 рублей:\n- Размещение НАВСЕГДА\n- Без закрепа",
        "4": "ПАКЕТ СТАНДАРТ - 2500₽ (вместо 4100₽)\n- Основной чат (без закрепа)\n- Премиум канал (без закрепа)\n- Закреп в бесплатном чате - на 1 месяц",
        "5": "ПАКЕТ СТАНДАРТ + ЗАКРЕП - 2900₽ (вместо 5600₽)\n- Основной чат (с закрепом на 1 мес)\n- Премиум канал (с закрепом на 1 мес)\n- Закреп в бесплатном чате - на 1 месяц",
        "6": "🔹 ПАКЕТ ПРЕМИУМ\n📍 Основной чат — закреп навсегда\n📍 Премиум канал — закреп навсегда\n📍 Бесплатный чат — закреп навсегда\n• 🧑‍💼 Работодатели: 10000₽ (вместо 20600₽)"
    },
    "freelancer": {
        "1": "👨‍💻ДЛЯ ФРИЛАНСЕРОВ И СПЕЦИАЛИСТОВ (для тех, кто ищет работу/клиентов):\nЦена Закрепа в бесплатном чате:",
        "2": "📄Стандарт - 900₽:\n- Размещение на месяц\n- Без закрепа\n- Объявление остаётся в чате до удаления по истечении срока",
        "4": "ПАКЕТ СТАНДАРТ - 2500₽ (вместо 4100₽)\n- Основной чат (без закрепа)\n- Премиум канал (без закрепа)\n- Закреп в бесплатном чате - на 1 месяц",
        "5": "ПАКЕТ СТАНДАРТ + ЗАКРЕП - 2900₽ (вместо 5600₽)\n- Основной чат (с закрепом на 1 мес)\n- Премиум канал (с закрепом на 1 мес)\n- Закреп в бесплатном чате - на 1 месяц",
        "6": "🔹 ПАКЕТ ПРЕМИУМ\n📍 Основной чат — закреп навсегда\n📍 Премиум канал — закреп навсегда\n📍 Бесплатный чат — закреп навсегда\n• 🧑‍💻 Фрилансеры: 5000₽ (вместо 15000₽)"
    }
}

# Suboptions available
SUBOPTIONS_AVAILABLE = {
    "employer": {
        "1": ["pin"],
        "2": ["pin", "boost"],
        "3": ["pin"],
        "4": [],
        "5": [],
        "6": []
    },
    "freelancer": {
        "1": ["pin"],
        "2": ["pin", "boost", "extend"],
        "4": [],
        "5": [],
        "6": []
    }
}

# Prices dict for variants
PRICES_DICT = {
    "pin_free_chat": {
        "1_week": {"text": "1 неделя", "price": 350},
        "2_weeks": {"text": "2 недели", "price": 400},
        "3_weeks": {"text": "3 недели", "price": 450},
        "1_month": {"text": "1 месяц", "price": 550},
        "2_months": {"text": "2 месяца", "price": 750},
        "3_months": {"text": "3 месяца", "price": 900},
        "6_months": {"text": "6 месяцев", "price": 1500},
        "forever": {"text": "НАВСЕГДА", "price": 2000},
    },
    "pin_employer_chat": {
        "2_weeks": {"text": "2 недели", "price": 300},
        "1_month": {"text": "1 месяц", "price": 450},
        "3_months": {"text": "3 месяца", "price": 900},
        "forever": {"text": "НАВСЕГДА", "price": 5000},
    },
    "pin_freelancer_chat": {
        "1_month": {"text": "1 месяц", "price": 450},
        "3_months": {"text": "3 месяца", "price": 1000},
        "forever": {"text": "НАВСЕГДА", "price": 5000},
    },
    "pin_channel": {
        "2_weeks": {"text": "2 недели", "price": 450},
        "1_month": {"text": "1 месяц", "price": 600},
        "3_months": {"text": "3 месяца", "price": 1200},
        "forever": {"text": "НАВСЕГДА", "price": 10000},
    },
    "boost": {
        "1": {"text": "1 поднятие", "price": 250},
        "2": {"text": "2 поднятия", "price": 350},
        "3": {"text": "3 поднятия", "price": 400},
        "4": {"text": "4 поднятия", "price": 450},
        "5": {"text": "5 поднятий", "price": 500},
    },
    "extend_freelancer": {
        "1_month": {"text": "1 месяц", "price": 300},
        "3_months": {"text": "3 месяца", "price": 600},
        "forever": {"text": "НАВСЕГДА", "price": 5000},
    }
}

SUBOPTION_EMOJIS = {
    "pin": "📌",
    "boost": "⬆️",
    "extend": "📎"
}

def get_suboption_key(suboption: str, user_type: str, option: str) -> str:
    if suboption == "pin":
        if option == "1":
            return "pin_free_chat"
        elif option == "2":
            return "pin_employer_chat" if user_type == "employer" else "pin_freelancer_chat"
        elif option == "3":
            return "pin_channel"
    elif suboption == "boost":
        return "boost"
    elif suboption == "extend":
        return "extend_freelancer"
    return ""

def parse_period(text: str) -> timedelta | None:
    if text == "НАВСЕГДА":
        return None
    parts = text.split()
    if len(parts) < 2:
        return None
    try:
        num = int(parts[0])
    except ValueError:
        return None
    unit = parts[1].lower()
    if 'недел' in unit:
        return timedelta(weeks=num)
    elif 'месяц' in unit:
        return timedelta(days=30 * num)  # approximation
    elif 'поднят' in unit:
        return None
    return None

def get_chat_ids(user_type: str, option: str, selected: dict) -> list[int]:
    if option == "1":
        return [FREE_CHAT_ID]
    elif option == "2":
        return [MAIN_CHAT_ID]
    elif option == "3":
        return [PREMIUM_CHANNEL_ID]
    elif option in ["4", "5", "6"]:
        return [MAIN_CHAT_ID, PREMIUM_CHANNEL_ID, FREE_CHAT_ID]
    return []


def get_times(user_type: str, option: str, selected: dict) -> tuple[datetime, dict[int, str | None], dict[int, str | None]]:
    tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(tz)
    scheduled_time = now
    unpin_times = {}
    delete_times = {}
    chat_ids = get_chat_ids(user_type, option, selected)
    forever_date = datetime.strptime("12:00 31-12-2200", "%H:%M %d-%m-%Y").replace(tzinfo=tz)
    forever_date_str = forever_date.isoformat()  # Changed: Serialize to ISO string

    for chat_id in chat_ids:
        unpin_times[chat_id] = forever_date_str  # Default to forever if pinned
        delete_times[chat_id] = forever_date_str  # Default to forever

    # Base delete_time per chat
    if user_type == 'freelancer':
        if option in ['2', '4', '5']:
            for chat_id in chat_ids:
                delete_times[chat_id] = (now + timedelta(days=30)).isoformat()  # Changed: Serialize
        elif option == '6':
            for chat_id in chat_ids:
                delete_times[chat_id] = forever_date_str
    elif user_type == 'employer':
        for chat_id in chat_ids:
            delete_times[chat_id] = forever_date_str

    # Extend for delete_time
    if 'extend' in selected:
        var = selected['extend']
        key = get_suboption_key('extend', user_type, option)
        period_text = PRICES_DICT[key][var]['text']
        additional = parse_period(period_text)
        if additional is None:
            for chat_id in chat_ids:
                delete_times[chat_id] = forever_date_str
        else:
            for chat_id in chat_ids:
                if delete_times[chat_id] != forever_date_str:
                    delete_time_dt = datetime.fromisoformat(delete_times[chat_id])  # Changed: Deserialize
                    delete_times[chat_id] = (delete_time_dt + additional).isoformat()  # Changed: Re-serialize

    # Pin for unpin_time per chat
    if 'pin' in selected:
        var = selected['pin']
        key = get_suboption_key('pin', user_type, option)
        period_text = PRICES_DICT[key][var]['text']
        period = parse_period(period_text)
        if period:
            unpin_time = (now + period).isoformat()  # Changed: Serialize
        else:
            unpin_time = forever_date_str
        for chat_id in chat_ids:
            unpin_times[chat_id] = unpin_time
    else:
        for chat_id in chat_ids:
            unpin_times[chat_id] = None  # No pin

    # Special for packages
    if option == '4':
        for chat_id in chat_ids:
            if chat_id == FREE_CHAT_ID:
                unpin_times[chat_id] = (now + timedelta(days=30)).isoformat()  # Changed: Serialize
            else:
                unpin_times[chat_id] = None
    elif option == '5':
        for chat_id in chat_ids:
            unpin_times[chat_id] = (now + timedelta(days=30)).isoformat()  # Changed: Serialize
    elif option == '6':
        for chat_id in chat_ids:
            unpin_times[chat_id] = forever_date_str

    return scheduled_time, unpin_times, delete_times


# Function to build extra text and keyboard (category buttons)
async def build_extra_text_and_keyboard(state: FSMContext, user_type: str, option: str) -> tuple[str, InlineKeyboardMarkup]:
    data = await state.get_data()
    selected = data.get("selected_suboptions", {})
    available = SUBOPTIONS_AVAILABLE.get(user_type, {}).get(option, [])
    base_price = BASE_PRICES[user_type][option]
    desc = DESCRIPTIONS[user_type][option]
    text = desc
    builder = InlineKeyboardBuilder()
    sub_total = 0
    selected_text = ""

    if available:
        text += "\n\nДополнительные опции:"
        for subopt in available:
            sel_var = selected.get(subopt)
            if sel_var:
                key = get_suboption_key(subopt, user_type, option)
                var_info = PRICES_DICT[key][sel_var]
                price = var_info["price"]
                sub_total += price
                selected_text += f"\n- {SUBOPTION_EMOJIS[subopt]} {SUBOPTION_NAMES[subopt]} {var_info['text']} ({price}₽)"
            btext = f"{SUBOPTION_EMOJIS[subopt]} {SUBOPTION_NAMES[subopt]}"
            if sel_var:
                btext += f" (выбрано: {PRICES_DICT[get_suboption_key(subopt, user_type, option)][sel_var]['text']})"
            builder.button(text=btext, callback_data=MenuCallback(level="subextra", user_type=user_type, option=option, suboption=subopt).pack())

    total = base_price + sub_total
    if selected_text:
        text += "\n\nВыбранные опции:" + selected_text
    text += f"\n\nИтоговая цена: {total}₽"

    # Add Buy and Back
    builder.button(text="Купить", callback_data=MenuCallback(level="buy", user_type=user_type, option=option).pack())
    builder.button(text="Назад", callback_data=MenuCallback(level="sub", user_type=user_type).pack())
    builder.adjust(2)  # Adjust to 2 per row for better layout
    return text, builder.as_markup()


# Function to build subextra keyboard (variants for a suboption)
async def build_subextra_text_and_keyboard(state: FSMContext, user_type: str, option: str, suboption: str) -> tuple[str, InlineKeyboardMarkup|None]:
    data = await state.get_data()
    selected = data.get("selected_suboptions", {})
    key = get_suboption_key(suboption, user_type, option)
    if not key:
        return "Ошибка", None
    variants = PRICES_DICT[key]
    sel_var = selected.get(suboption)
    text = f"📌{SUBOPTION_NAMES[suboption]}:"
    builder = InlineKeyboardBuilder()
    for var, info in variants.items():
        if sel_var == var:
            btext = f"Удалить опцию {info['text']}"
            act = "remove"
        else:
            btext = f"{info['text']} - {info['price']} рублей"
            act = "add"
        builder.button(text=btext, callback_data=MenuCallback(level="toggle", user_type=user_type, option=option, suboption=suboption, variant=var, action=act).pack())
    builder.button(text="Назад", callback_data=MenuCallback(level="extra", user_type=user_type, option=option).pack())
    builder.adjust(2)
    return text, builder.as_markup()

# Handler for /start
@menu_router.message(Command("start"))
async def command_start(message: Message):
    await message.answer("Welcome! Use /menu to open the main menu.")

# Handler for /menu - shows initial menu with employer/freelancer choices
@menu_router.message(Command("menu"))
async def command_menu(message: Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="А) Для работодателей", callback_data=MenuCallback(level="sub", user_type="employer").pack())
    builder.button(text="Б) Для фрилансеров", callback_data=MenuCallback(level="sub", user_type="freelancer").pack())
    builder.adjust(1)  # One button per row
    await message.answer("Выберите категорию:", reply_markup=builder.as_markup())


# Main callback query handler
@menu_router.callback_query(MenuCallback.filter())
async def process_menu_callback(query: CallbackQuery, callback_data: MenuCallback, state: FSMContext, bot: Bot):
    level = callback_data.level
    user_type = callback_data.user_type
    option = callback_data.option
    suboption = callback_data.suboption
    variant = callback_data.variant
    action = callback_data.action

    await query.answer()  # Acknowledge the callback

    if level == "sub":
        await state.clear()
        # Show sub-menu with options 1-6, only available ones
        builder = InlineKeyboardBuilder()
        options = [
            ("Бесплатный чат (только закреп)", "1"),
            ("Платный чат", "2"),
            ("Канал", "3"),
            ("Пакет Стандарт", "4"),
            ("Пакет Стандарт+Закреп", "5"),
            ("Пакет Премиум", "6")
        ]
        for text, opt in options:
            if opt in BASE_PRICES.get(user_type, {}):
                builder.button(text=f"{OPTION_EMOJIS[opt]} {text}", callback_data=MenuCallback(level="extra", user_type=user_type, option=opt).pack())
        builder.button(text="Назад", callback_data=MenuCallback(level="main").pack())
        builder.adjust(2)  # Two buttons per row
        await query.message.edit_text(f"Меню для {user_type.capitalize()}:", reply_markup=builder.as_markup())

    elif level == "extra":
        data = await state.get_data()
        current_option = data.get('option')
        if current_option != option:
            selected = {}
        else:
            selected = data.get('selected_suboptions', {})
        await state.update_data(user_type=user_type, option=option, selected_suboptions=selected)
        text, markup = await build_extra_text_and_keyboard(state, user_type, option)
        await query.message.edit_text(text, reply_markup=markup)

    elif level == "subextra":
        text, markup = await build_subextra_text_and_keyboard(state, user_type, option, suboption)
        await query.message.edit_text(text, reply_markup=markup)

    elif level == "toggle":
        data = await state.get_data()
        selected = data.get("selected_suboptions", {})
        subopt_name = SUBOPTION_NAMES.get(suboption, suboption)
        key = get_suboption_key(suboption, user_type, option)
        var_info = PRICES_DICT[key].get(variant, {})
        var_text = var_info.get("text", variant)
        if action == "add":
            selected[suboption] = variant
            await query.answer(f"К заказу добавлена опция {subopt_name} {var_text}")
        elif action == "remove":
            if suboption in selected:
                del selected[suboption]
            await query.answer(f"Опция {subopt_name} удалена из заказа")
        await state.update_data(selected_suboptions=selected)
        # Return to subextra view after toggle
        text, markup = await build_subextra_text_and_keyboard(state, user_type, option, suboption)
        await query.message.edit_text(text, reply_markup=markup)

    elif level == "buy":
        data = await state.get_data()
        selected = data.get("selected_suboptions", {})
        base_price = BASE_PRICES[user_type][option]
        sub_total = 0
        for subopt, var in selected.items():
            key = get_suboption_key(subopt, user_type, option)
            sub_total += PRICES_DICT[key][var]["price"]
        total = base_price + sub_total
        await state.update_data(total=total, selected_suboptions=selected)
        await state.set_state(Purchase.waiting_check)
        # Remove buttons from previous message
        await bot.edit_message_reply_markup(chat_id=query.from_user.id, message_id=query.message.message_id, reply_markup=None)
        # Send new message with cancel
        cancel_builder = InlineKeyboardBuilder()
        cancel_builder.button(text="Отмена", callback_data=MenuCallback(level="cancel").pack())
        sent_msg = await bot.send_message(query.from_user.id, f"Итоговая цена: {total}₽.\nОтправьте фотографию чека оплаты на сумму {total}₽.", reply_markup=cancel_builder.as_markup())
        await state.update_data(waiting_msg_id=sent_msg.message_id)

    elif level == "main":
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="А) Для работодателей", callback_data=MenuCallback(level="sub", user_type="employer").pack())
        builder.button(text="Б) Для фрилансеров", callback_data=MenuCallback(level="sub", user_type="freelancer").pack())
        builder.adjust(1)
        await query.message.edit_text("Выберите категорию:", reply_markup=builder.as_markup())

    elif level == "cancel":
        data = await state.get_data()
        waiting_msg_id = data.get("waiting_msg_id")
        if waiting_msg_id:
            await bot.edit_message_text(chat_id=query.from_user.id, message_id=waiting_msg_id, text="Покупка отменена.", reply_markup=None)
        await state.clear()

# Handler for payment check photo
@menu_router.message(Purchase.waiting_check, F.photo)
async def process_check_photo(message: Message, state: FSMContext, bot: Bot):
    photo_id = message.photo[-1].file_id  # Get the highest resolution photo
    await state.update_data(check_photo=photo_id)
    data = await state.get_data()
    waiting_msg_id = data.get('waiting_msg_id')
    if waiting_msg_id:
        await bot.edit_message_text(chat_id=message.chat.id, message_id=waiting_msg_id, text="Чек получен.", reply_markup=None)
    await bot.send_message(message.chat.id, "Теперь отправьте пост, который хотите опубликовать.")
    await state.set_state(Purchase.waiting_post)

# Handler for post content
@menu_router.message(Purchase.waiting_post)
async def process_post_content(message: Message, state: FSMContext, bot: Bot, album: List[Message] | None = None):
    if album:
        # Обработка медиа-группы (альбома)
        content_type = 'photo'
        file_ids = [msg.photo[-1].file_id for msg in album if msg.photo]
        text = next((msg.caption for msg in album if msg.caption), '')  # Caption от первого с текстом
        media_group_id = album[0].media_group_id if album else None
    else:
        # Одиночное сообщение
        media_group_id = message.media_group_id
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

    await state.update_data(content_type=content_type, text=text, file_ids=file_ids, media_group_id=media_group_id)

    data = await state.get_data()

    # Generate unique order ID
    order_id = str(uuid.uuid4())

    # Store order data
    pending_orders[order_id] = {
        'user_id': message.from_user.id,
        'user_username': message.from_user.username,
        'user_type': data['user_type'],
        'option': data['option'],
        'selected_suboptions': data['selected_suboptions'],
        'total': data['total'],
        'check_photo': data['check_photo'],
        'content_type': content_type,
        'text': text,
        'file_ids': file_ids,
        'media_group_id': media_group_id
    }

    # Format suboptions string
    suboptions_str = ', '.join(
        [f"{SUBOPTION_NAMES.get(k, k)}: {PRICES_DICT[get_suboption_key(k, data['user_type'], data['option'])][v]['text']}" for k, v in data['selected_suboptions'].items()]) if data['selected_suboptions'] else 'Нет'

    # If post has photos, send them to admin first
    if file_ids:
        media = [InputMediaPhoto(media=file_id, caption=text if i == 0 else None, parse_mode=ParseMode.HTML) for i, file_id in enumerate(file_ids)]
        await bot.send_media_group(ADMIN_CHAT_ID, media)
        post_str = "Пост: фото отправлены выше"
    else:
        post_str = f"Пост: {text}"

    # Format caption for check photo
    caption = (
        f"Новый заказ #{order_id[:8]}\n"
        f"От пользователя: @{message.from_user.username} (ID: {message.from_user.id})\n"
        f"Тип: {data['user_type'].capitalize()}\n"
        f"Опция: {DESCRIPTIONS[data['user_type']][data['option']].splitlines()[0]}\n"
        f"Дополнительные опции: {suboptions_str}\n"
        f"Сумма: {data['total']}₽\n"
        f"{post_str}"
    )

    # Build admin keyboard
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data=AdminCallback(action="confirm", order_id=order_id).pack())
    builder.button(text="Отклонить", callback_data=AdminCallback(action="reject", order_id=order_id).pack())
    builder.adjust(2)

    # Send check photo with caption and buttons to admin
    await bot.send_photo(
        ADMIN_CHAT_ID, photo=data['check_photo'],
        caption=caption,
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )

    await message.answer("Пост получен и отправлен на модерацию. Спасибо!")
    await state.clear()


# Admin callback handler
@menu_router.callback_query(AdminCallback.filter())
async def process_admin_callback(query: CallbackQuery, callback_data: AdminCallback, bot: Bot):
    action = callback_data.action
    order_id = callback_data.order_id

    await query.answer()

    if order_id in pending_orders:
        order = pending_orders.pop(order_id)
        user_id = order['user_id']
        if action == "confirm":
            tz = pytz.timezone('Europe/Moscow')
            now = datetime.now(tz)
            scheduled_time, unpin_times, delete_times = get_times(
                order['user_type'], order['option'], order['selected_suboptions']
            )
            chat_ids = get_chat_ids(order['user_type'], order['option'], order['selected_suboptions'])
            await add_or_update_scheduled_post(
                content_type=order['content_type'],
                text=order['text'],
                photo_file_ids=order['file_ids'] or [],
                scheduled_time=scheduled_time,
                media_group_id=order['media_group_id'] or 0,
                is_published={str(chat_id): False for chat_id in chat_ids},
                message_ids={str(chat_id): [] for chat_id in chat_ids},
                unpin_time=unpin_times,
                delete_time=delete_times,
                chat_ids=chat_ids,
                post_id=0
            )
            await bot.send_message(user_id, "Ваш заказ подтверждён!")
            status = "Подтверждено"
        else:
            await bot.send_message(user_id, "Ваш заказ отклонён.")
            status = "Отклонено"
        await query.message.edit_caption(caption=query.message.caption + f"\n\nСтатус: {status}", reply_markup=None)
        print(status)
    else:
        await query.answer("Заказ не найден.")


# Fallback for wrong input in states
@menu_router.message(Purchase.waiting_check)
async def invalid_check(message: Message):
    await message.answer("Пожалуйста, отправьте фотографию чека.")


@menu_router.message(Purchase.waiting_post)
async def invalid_post(message: Message):
    await message.answer("Пожалуйста, отправьте текст или фото.")
