import os
from typing import Dict, List
import uuid
import dotenv
from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


dotenv.load_dotenv()
# Загружаем ID чатов из окружения
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', '0'))
NOTIFICATION_CHAT = int(os.getenv('NOTIFICATION_CHAT', str(ADMIN_CHAT_ID)))

# Быстрые ссылки на наши площадки
LINKS = {
    'main': 'https://t.me/FreelanceSET',
    'premium': 'https://t.me/VakansiiPREMIUM',
    'free': 'https://t.me/freelanceFREEchat',
    'reviews': 'https://t.me/PUSHfeedback',
}

ADMIN_CONTACT_URL = 'https://t.me/push_admin_Evgen'

# Утилита: добавить кнопку «Связаться с админом» в самый низ клавиатуры
def add_contact_button(builder: InlineKeyboardBuilder) -> InlineKeyboardBuilder:
    builder.row(InlineKeyboardButton(text='Связаться с админом', url=ADMIN_CONTACT_URL))
    return builder

# Global storage for pending orders
pending_orders: Dict[str, Dict] = {}

# Define FSM states for the purchase process
class Purchase(StatesGroup):
    waiting_check = State()  # Waiting for payment check photo
    waiting_post = State()   # Waiting for the post text

# Новый FSM для админа при отклонении
class AdminReject(StatesGroup):
    waiting_reason = State()

# Define FSM states for the broadcast process
class Broadcast(StatesGroup):
    waiting_start_time = State()
    waiting_post = State()
    waiting_check = State()

BROADCAST_INTERVALS = {
    '15m': 15,
    '30m': 30,
    '1h': 60,
    '2h': 120,
    '3h': 180
}

# Добавили 3 недели
BROADCAST_DURATIONS = {
    '1w': 7*24*60,
    '2w': 14*24*60,
    '3w': 21*24*60,
    '1m': 30*24*60,
    '2m': 60*24*60,
    '3m': 90*24*60
}

# Русские подписи
INTERVAL_LABELS = {
    '15m': 'Раз в 15 минут',
    '30m': 'Раз в 30 минут',
    '1h': 'Раз в 1 час',
    '2h': 'Раз в 2 часа',
    '3h': 'Раз в 3 часа',
}

DURATION_LABELS = {
    '1w': '1 неделя (7 дней)',
    '2w': '2 недели (14 дней)',
    '3w': '3 недели (21 день)',
    '1m': '1 месяц (30 дней)',
    '2m': '2 месяца (60 дней)',
    '3m': '3 месяца (90 дней)',
}

# Прайс-лист: базовые цены для дневного режима (09:00–23:00)
BROADCAST_PRICE_MAP: Dict[str, Dict[str, int]] = {
    '15m': {
        '1w': 1250, '2w': 1950, '3w': 2650, '1m': 3200, '2m': 4100, '3m': 5000
    },
    '30m': {
        '1w': 750, '2w': 1250, '3w': 1800, '1m': 2200, '2m': 3100, '3m': 4000
    },
    '1h': {
        '1w': 500, '2w': 900, '3w': 1250, '1m': 1600, '2m': 2800, '3m': 3500
    },
    '2h': {
        '1w': 450, '2w': 750, '3w': 900, '1m': 1200, '2m': 1950, '3m': 2850
    },
    '3h': {
        '1w': 350, '2w': 600, '3w': 750, '1m': 1000, '2m': 1750, '3m': 2500
    }
}

# Хелперы для цены и количества сообщений
WINDOW_START_MIN = 9*60   # 09:00
WINDOW_END_MIN = 23*60    # 23:00

def get_broadcast_price(interval_code: str | None, duration_code: str | None, mode: str | None) -> int | None:
    if not interval_code or not duration_code or not mode:
        return None
    base = BROADCAST_PRICE_MAP.get(interval_code, {}).get(duration_code)
    if base is None:
        return None
    if mode == 'full':
        return int(base * 1.5)
    return base

def get_duration_days(duration_code: str) -> int:
    return {
        '1w': 7, '2w': 14, '3w': 21, '1m': 30, '2m': 60, '3m': 90
    }.get(duration_code, 0)

def count_per_day(interval_minutes: int, mode: str | None) -> int:
    if mode == 'limited':
        window = WINDOW_END_MIN - WINDOW_START_MIN
        # Количество слотов в [09:00,23:00) с шагом interval: 9:00, 9:00+M, ... < 23:00
        return ((window - 1) // interval_minutes) + 1
    if mode == 'full':
        # Полный режим 24/7
        return ((24*60 - 1) // interval_minutes) + 1
    return 0

def total_messages(interval_code: str | None, duration_code: str | None, mode: str | None) -> int | None:
    if not interval_code or not duration_code or not mode:
        return None
    interval = BROADCAST_INTERVALS.get(interval_code)
    if not interval:
        return None
    days = get_duration_days(duration_code)
    if not days:
        return None
    return count_per_day(interval, mode) * days

# Define CallbackData factory for menu navigation
class MenuCallback(CallbackData, prefix="menu"):
    level: str  # e.g., 'main', 'sub', 'extra', 'subextra', 'toggle', 'buy', 'cancel'
    user_type: str = ""  # 'employer' or 'freelancer'
    option: str = ""     # '1', '2', etc.
    suboption: str = ""  # For extra options like 'pin', 'boost'
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

# Base prices (новый прайс)
BASE_PRICES = {
    "employer": {
        "1": 0,          # Бесплатный чат — только закреп (без размещения)
        "2": 1600,       # Платный чат
        "3": 2400,       # Канал (премиум)
        "4": 2700,       # Пакет Стандарт
        "5": 3200,       # Пакет Стандарт + Закреп
        "6": 10000       # Пакет Премиум (оставлен как ранее)
    },
    "freelancer": {
        "1": 0,          # Бесплатный чат — только закреп (без размещения)
        "2": 1200,       # Платный чат
        "3": 1500,       # Канал (премиум)
        "4": 1950,       # Пакет Стандарт
        "5": 2450,       # Пакет Стандарт + Закреп
        "6": 5000        # Пакет Премиум (оставлен как ранее)
    }
}

# Descriptions с расширенным пояснением и ссылками
DESCRIPTIONS = {
    "employer": {
        "1": (
            "📌 Бесплатный чат — только закреп\n"
            "• Публикация бесплатная, покупается только закреп в бесплатном чате.\n"
            "• Закреп удерживает ваш пост вверху чата выбранный срок.\n"
            f"• Ссылка на чат: {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "2": (
            "📑 Стандарт (Платный чат) — 1600₽\n"
            "• Размещение навсегда.\n"
            "• Без закрепа по умолчанию. Можно добавить: Закреп.\n"
            f"• Ссылка на чат: {LINKS['main']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "3": (
            "📢 Канал (Премиум) — 2400₽\n"
            "• Размещение навсегда.\n"
            "• Без закрепа по умолчанию. Можно добавить: Закреп.\n"
            f"• Ссылка на премиум-канал: {LINKS['premium']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "4": (
            "📦 Пакет Стандарт — 2700₽ (вместо 4750₽)\n"
            "• Основной чат (без закрепа).\n"
            "• Премиум-канал (без закрепа).\n"
            "• Закреп в бесплатном чате на 1 месяц.\n"
            f"• Ссылки: \nосновной {LINKS['main']}\nпремиум {LINKS['premium']}\nбесплатный {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "5": (
            "📦 Пакет Стандарт + Закреп — 3200₽ (вместо 6000₽)\n"
            "• Основной чат — с закрепом на 1 месяц.\n"
            "• Премиум-канал — с закрепом на 1 месяц.\n"
            "• Бесплатный чат — закреп на 1 месяц.\n"
            f"• Ссылки: \nосновной {LINKS['main']}\nпремиум {LINKS['premium']}\nбесплатный {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "6": (
            "⭐ Пакет Премиум\n"
            "• Основной чат — закреп навсегда.\n"
            "• Премиум-канал — закреп навсегда.\n"
            "• Бесплатный чат — закреп навсегда.\n"
            f"• Ссылки: \nосновной {LINKS['main']}\nпремиум {LINKS['premium']}\nбесплатный {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        )
    },
    "freelancer": {
        "1": (
            "📌 Бесплатный чат — только закреп\n"
            "• Публикация бесплатная, покупается только закреп в бесплатном чате.\n"
            "• Закреп удерживает ваш пост вверху чата выбранный срок.\n"
            f"• Ссылка на чат: {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "2": (
            "📄 Стандарт (Платный чат) — 1200₽\n"
            "• Размещение навсегда.\n"
            "• Без закрепа по умолчанию. Можно добавить: Закреп.\n"
            f"• Ссылка на чат: {LINKS['main']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "3": (
            "📢 Канал (Премиум) — 1500₽\n"
            "• Размещение навсегда.\n"
            "• Без закрепа по умолчанию. Можно добавить: Закреп.\n"
            f"• Ссылка на премиум-канал: {LINKS['premium']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "4": (
            "📦 Пакет Стандарт — 1950₽ (вместо 3450₽)\n"
            "• Основной чат (без закрепа).\n"
            "• Премиум-канал (без закрепа).\n"
            "• Закреп в бесплатном чате на 1 месяц.\n"
            f"• Ссылки: \nосновной {LINKS['main']}\nпремиум {LINKS['premium']}\nбесплатный {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "5": (
            "📦 Пакет Стандарт + Закреп — 2450₽ (вместо 4550₽)\n"
            "• Основной чат — с закрепом на 1 месяц.\n"
            "• Премиум-канал — с закрепом на 1 месяц.\n"
            "• Бесплатный чат — закреп на 1 месяц.\n"
            f"• Ссылки: \nосновной {LINKS['main']}\nпремиум {LINKS['premium']}\nбесплатный {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        ),
        "6": (
            "⭐ Пакет Премиум\n"
            "• Основной чат — закреп навсегда.\n"
            "• Премиум-канал — закреп навсегда.\n"
            "• Бесплатный чат — закреп навсегда.\n"
            f"• Ссылки: \nосновной {LINKS['main']}\nпремиум {LINKS['premium']}\nбесплатный {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}"
        )
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
        "2": ["pin", "boost"],
        "3": ["pin"],
        "4": [],
        "5": [],
        "6": []
    }
}

# Prices dict for variants (новый прайс)
PRICES_DICT = {
    "pin_free_chat": {
        "1_week": {"text": "1 неделя", "price": 450},
        "2_weeks": {"text": "2 недели", "price": 500},
        "3_weeks": {"text": "3 недели", "price": 650},
        "1_month": {"text": "1 месяц", "price": 750},
        "2_months": {"text": "2 месяца", "price": 850},
        "3_months": {"text": "3 месяца", "price": 1000},
        "6_months": {"text": "6 месяцев", "price": 1750},
        "forever": {"text": "НАВСЕГДА", "price": 2200},
    },
    "pin_employer_chat": {
        "2_weeks": {"text": "2 недели", "price": 400},
        "1_month": {"text": "1 месяц", "price": 550},
        "3_months": {"text": "3 месяца", "price": 1000},
        "forever": {"text": "НАВСЕГДА", "price": 5000},
    },
    "pin_freelancer_chat": {
        "1_month": {"text": "1 месяц", "price": 550},
        "3_months": {"text": "3 месяца", "price": 1000},
        "forever": {"text": "НАВСЕГДА", "price": 5000},
    },
    "pin_channel_employer": {
        "2_weeks": {"text": "2 недели", "price": 550},
        "1_month": {"text": "1 месяц", "price": 700},
        "3_months": {"text": "3 месяца", "price": 1500},
        "forever": {"text": "НАВСЕГДА", "price": 10000},
    },
    "pin_channel_freelancer": {
        "2_weeks": {"text": "2 недели", "price": 350},
        "1_month": {"text": "1 месяц", "price": 550},
        "3_months": {"text": "3 месяца", "price": 750},
        "forever": {"text": "НАВСЕГДА", "price": 5000},
    },
    "boost": {
        "1": {"text": "1 поднятие", "price": 450},
        "2": {"text": "2 поднятия", "price": 650},
        "3": {"text": "3 поднятия", "price": 700},
        "4": {"text": "4 поднятия", "price": 850},
        "5": {"text": "5 поднятий", "price": 900},
    },
}

SUBOPTION_EMOJIS = {
    "pin": "📌",
    "boost": "⬆️",
}

def get_suboption_key(suboption: str, user_type: str, option: str) -> str:
    if suboption == "pin":
        if option == "1":
            return "pin_free_chat"
        elif option == "2":
            return "pin_employer_chat" if user_type == "employer" else "pin_freelancer_chat"
        elif option == "3":
            return "pin_channel_employer" if user_type == "employer" else "pin_channel_freelancer"
    elif suboption == "boost":
        return "boost"
    return ""

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
    builder = add_contact_button(builder)
    return text, builder.as_markup()

# Function to build subextra text and keyboard (variants for a suboption)
async def build_subextra_text_and_keyboard(state: FSMContext, user_type: str, option: str, suboption: str) -> tuple[str, InlineKeyboardMarkup | None]:
    data = await state.get_data()
    selected = data.get("selected_suboptions", {})
    key = get_suboption_key(suboption, user_type, option)
    if not key:
        return "Ошибка", None
    variants = PRICES_DICT[key]
    sel_var = selected.get(suboption)
    text = f"📌{SUBOPTION_NAMES[suboption]}:"
    if suboption == 'boost':
        text += "\n\nПоднятие — это повторная публикация вашего поста с закрепом на 2 часа. Вы можете выбрать, сколько раз поднять пост."

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
    builder = add_contact_button(builder)
    return text, builder.as_markup()

# Handler for /start
@menu_router.message(Command("start"))
async def command_start(message: Message):
    if message.chat.type != 'private':
        return
    text = (
        "Привет! Здесь можно быстро и удобно разместить вакансию или резюме\n\n"
        "Чтобы начать, откройте главное меню командой /menu"
    )
    kb = InlineKeyboardBuilder()
    kb = add_contact_button(kb)
    await message.answer(text, reply_markup=kb.as_markup())

# Handler for /menu - shows initial menu with employer/freelancer choices
@menu_router.message(Command("menu"))
async def command_menu(message: Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    await state.clear()
    intro = (
        "Добро пожаловать! Ниже — быстрые ссылки на наши площадки:\n"
        f"• Основной чат: {LINKS['main']}\n"
        f"• Премиум-канал: {LINKS['premium']}\n"
        f"• Бесплатный чат: {LINKS['free']}\n"
        f"• Чат с отзывами: {LINKS['reviews']}\n\n"
        "Выберите тип услуги."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Обычная публикация", callback_data=MenuCallback(level="root_pub").pack())
    builder.button(text="Рассылка", callback_data=MenuCallback(level="broadcast").pack())
    builder.adjust(1)
    builder = add_contact_button(builder)
    await message.answer(intro, reply_markup=builder.as_markup())

# Main callback query handler
@menu_router.callback_query(MenuCallback.filter())
async def process_menu_callback(query: CallbackQuery, callback_data: MenuCallback, state: FSMContext, bot: Bot):
    rus_names = {'freelancer': 'Фрилансера', 'employer': 'Работодателя'}
    level = callback_data.level
    user_type = callback_data.user_type
    option = callback_data.option
    suboption = callback_data.suboption
    variant = callback_data.variant
    action = callback_data.action

    await query.answer()  # Acknowledge the callback

    if level == "sub":
        await state.clear()
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
        builder.adjust(2)
        builder = add_contact_button(builder)
        header = (
            f"Меню для {rus_names[user_type]}:\n\n"
            "— Выберите площадку или пакет размещения ниже.\n"
            "— Важно: указывайте верный статус (Фрилансер/Работодатель) — объявление проходит модерацию и при неверном выборе может быть отклонено."
        )
        await query.message.edit_text(header, reply_markup=builder.as_markup())

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
        # Send new message with cancel (без кнопки контакта на этапе оплаты)
        cancel_builder = InlineKeyboardBuilder()
        cancel_builder.button(text="Отмена", callback_data=MenuCallback(level="cancel").pack())
        final_price_text = (f"Итоговая цена: {total}₽.\nОтправьте фотографию чека оплаты на сумму {total}₽.\n\n"
                            f"Реквизиты для оплаты:\n"
                            f"Сбербанк:\n"
                            f"Даниил Дмитриевич М.\n"
                            f"2202206250331753\n"
                            f"Можно по номеру:\n"
                            f"89164253032")
        sent_msg = await bot.send_message(query.from_user.id, text=final_price_text, reply_markup=cancel_builder.as_markup())
        await state.update_data(waiting_msg_id=sent_msg.message_id)

    elif level == "main":
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="Обычная публикация", callback_data=MenuCallback(level="root_pub").pack())
        builder.button(text="Рассылка", callback_data=MenuCallback(level="broadcast").pack())
        builder.adjust(1)
        builder = add_contact_button(builder)
        intro = (
            "Добро пожаловать! Ниже — быстрые ссылки на наши площадки:\n"
            f"• Основной чат: {LINKS['main']}\n"
            f"• Премиум-канал: {LINKS['premium']}\n"
            f"• Бесплатный чат: {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}\n\n"
            "Выберите тип услуги."
        )
        await query.message.edit_text(text=intro, reply_markup=builder.as_markup())

    elif level == "cancel":
        data = await state.get_data()
        waiting_msg_id = data.get("waiting_msg_id")
        if waiting_msg_id:
            await bot.edit_message_text(chat_id=query.from_user.id, message_id=waiting_msg_id, text="Покупка отменена.", reply_markup=None)
        await state.clear()
        # Возврат в начальное меню
        builder = InlineKeyboardBuilder()
        builder.button(text="Обычная публикация", callback_data=MenuCallback(level="root_pub").pack())
        builder.button(text="Рассылка", callback_data=MenuCallback(level="broadcast").pack())
        builder.adjust(1)
        builder = add_contact_button(builder)
        intro = (
            "Добро пожаловать! Ниже — быстрые ссылки на наши площадки:\n"
            f"• Основной чат: {LINKS['main']}\n"
            f"• Премиум-канал: {LINKS['premium']}\n"
            f"• Бесплатный чат: {LINKS['free']}\n"
            f"• Чат с отзывами: {LINKS['reviews']}\n\n"
            "Выберите тип услуги."
        )
        await bot.send_message(query.from_user.id, text=intro, reply_markup=builder.as_markup())

    elif level == "root_pub":
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="А) Для работодателей", callback_data=MenuCallback(level="sub", user_type="employer").pack())
        builder.button(text="Б) Для фрилансеров", callback_data=MenuCallback(level="sub", user_type="freelancer").pack())
        builder.button(text="Назад", callback_data=MenuCallback(level="main").pack())
        builder.adjust(1)
        builder = add_contact_button(builder)
        try:
            await query.message.edit_text("Выберите категорию:", reply_markup=builder.as_markup())
        except Exception:
            await bot.send_message(query.from_user.id, "Выберите категорию:", reply_markup=builder.as_markup())
        return
    elif level == "broadcast":
        # Корневое меню рассылки: режим, интервал, длительность, продолжить
        data = await state.get_data()
        sel_mode = data.get('broadcast_mode')  # БЕЗ значения по умолчанию — требуется явный выбор
        sel_interval = data.get('broadcast_interval_code')
        sel_duration = data.get('broadcast_duration_code')
        # Русские подписи выбранных значений
        sel_interval_text = INTERVAL_LABELS.get(sel_interval, 'не выбран') if sel_interval else 'не выбран'
        sel_duration_text = DURATION_LABELS.get(sel_duration, 'не выбрана') if sel_duration else 'не выбрана'
        # Динамика: цена и кол-во сообщений — считаем только при выбранном режиме
        price = get_broadcast_price(sel_interval, sel_duration, sel_mode)
        total_msgs = total_messages(sel_interval, sel_duration, sel_mode)
        price_line = f"Цена: {price}₽" if price is not None else "Цена: —"
        count_line = f"Всего сообщений: {total_msgs}" if total_msgs is not None else "Всего сообщений: —"
        mode_line = (
            "Дневной 09:00–23:00" if sel_mode == 'limited' else ("Круглосуточно 24/7 (+50% к цене)" if sel_mode == 'full' else "не выбран")
        )
        txt = [
            'Настройка рассылки в бесплатный чат:',
            f"Режим: {mode_line}",
            f"Интервал: {sel_interval_text}",
            f"Длительность: {sel_duration_text}",
            price_line,
            count_line,
            '',
            'Как это работает: пост публикуется по выбранному интервалу в бесплатный чат в течение указанного срока.',
            'По умолчанию — дневной режим 09:00–23:00 (ночью публикации не идут). Можно включить 24/7 (+50% к цене).'
        ]
        builder = InlineKeyboardBuilder()
        builder.button(text=f"Режим", callback_data=MenuCallback(level="broadcast_mode_menu").pack())
        builder.button(text=f"Интервал", callback_data=MenuCallback(level="broadcast_interval_menu").pack())
        builder.button(text=f"Длительность", callback_data=MenuCallback(level="broadcast_duration_menu").pack())
        if sel_mode and sel_interval and sel_duration:
            builder.button(text="Продолжить", callback_data=MenuCallback(level="broadcast_start").pack())
        builder.button(text="Назад", callback_data=MenuCallback(level="main").pack())
        builder.adjust(2,1,1)
        # Удалены разделители-пустышки перед кнопкой контакта
        builder = add_contact_button(builder)
        try:
            await query.message.edit_text('\n'.join(txt), reply_markup=builder.as_markup())
        except Exception:
            await bot.send_message(query.from_user.id, '\n'.join(txt), reply_markup=builder.as_markup())
        return
    elif level == "broadcast_mode_menu":
        builder = InlineKeyboardBuilder()
        builder.button(text="Дневной режим 09:00–23:00", callback_data=MenuCallback(level="broadcast_mode", option="limited").pack())
        builder.button(text="Круглосуточно 24/7 (+50% к цене)", callback_data=MenuCallback(level="broadcast_mode", option="full").pack())
        builder.button(text="Назад", callback_data=MenuCallback(level="broadcast").pack())
        builder.adjust(1)
        builder = add_contact_button(builder)
        await query.message.edit_text("Выберите режим рассылки:", reply_markup=builder.as_markup())
        return
    elif level == "broadcast_mode":
        mode = callback_data.option
        if mode not in ("full","limited"):
            await query.answer("Неверный режим", show_alert=True); return
        await state.update_data(broadcast_mode=mode)
        await query.answer("Режим выбран")
        # Возврат к корню рассылки
        await process_menu_callback(query, MenuCallback(level="broadcast", user_type='', option='', suboption='', variant='', action=''), state, bot)
        return
    elif level == "broadcast_interval_menu":
        data = await state.get_data()
        sel_duration = data.get('broadcast_duration_code')
        sel_mode = data.get('broadcast_mode')  # без дефолта, чтобы не подсвечивать цену до выбора режима
        builder = InlineKeyboardBuilder()
        for code, mins in BROADCAST_INTERVALS.items():
            label = INTERVAL_LABELS.get(code, code)
            if sel_duration and sel_mode:
                p = get_broadcast_price(code, sel_duration, sel_mode)
                if p is not None:
                    label = f"{label} — {p}₽"
            builder.button(text=label, callback_data=MenuCallback(level="broadcast_interval", option=code).pack())
        builder.button(text="Назад", callback_data=MenuCallback(level="broadcast").pack())
        builder.adjust(1)
        builder = add_contact_button(builder)
        await query.message.edit_text("Выберите интервал:", reply_markup=builder.as_markup())
        return
    elif level == "broadcast_interval":
        interval_code = callback_data.option
        if interval_code not in BROADCAST_INTERVALS:
            await query.answer("Неверный интервал", show_alert=True)
            return
        await state.update_data(broadcast_interval_code=interval_code, broadcast_interval=BROADCAST_INTERVALS[interval_code])
        await query.answer("Интервал выбран")
        await process_menu_callback(query, MenuCallback(level="broadcast", user_type='', option='', suboption='', variant='', action=''), state, bot)
        return
    elif level == "broadcast_duration_menu":
        data = await state.get_data()
        sel_interval = data.get('broadcast_interval_code')
        sel_mode = data.get('broadcast_mode')  # без дефолта
        builder = InlineKeyboardBuilder()
        for code, minutes in BROADCAST_DURATIONS.items():
            label = DURATION_LABELS.get(code, code)
            if sel_interval and sel_mode:
                p = get_broadcast_price(sel_interval, code, sel_mode)
                if p is not None:
                    label = f"{label} — {p}₽"
            builder.button(text=label, callback_data=MenuCallback(level="broadcast_duration", option=code).pack())
        builder.button(text="Назад", callback_data=MenuCallback(level="broadcast").pack())
        builder.adjust(1)
        builder = add_contact_button(builder)
        await query.message.edit_text("Выберите длительность:", reply_markup=builder.as_markup())
        return
    elif level == "broadcast_duration":
        dur_code = callback_data.option
        if dur_code not in BROADCAST_DURATIONS:
            await query.answer("Неверная длительность", show_alert=True)
            return
        await state.update_data(broadcast_duration_code=dur_code, broadcast_duration=BROADCAST_DURATIONS[dur_code])
        await query.answer("Длительность выбрана")
        await process_menu_callback(query, MenuCallback(level="broadcast", user_type='', option='', suboption='', variant='', action=''), state, bot)
        return
    elif level == "broadcast_start":
        data = await state.get_data()
        if not (data.get('broadcast_mode') and data.get('broadcast_interval') and data.get('broadcast_duration')):
            await query.answer("Заполните сначала режим, интервал и длительность", show_alert=True)
            return
        await state.set_state(Broadcast.waiting_start_time)
        await query.message.edit_text("Если хотите настроить начало рассылки на определённое время, отправьте время старта в формате HH:MM DD-MM-YYYY\nОтправьте /now, если хотите, чтобы рассылка началась сразу.")
        return
    elif level == "noop":
        # Пустышка — ничего не делаем
        await query.answer()
        return
@menu_router.message(Broadcast.waiting_check, F.photo)
async def broadcast_get_check(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id
    order_id = str(uuid.uuid4())
    # Рассчитываем цену и количество сообщений для модераторов
    price = get_broadcast_price(data.get('broadcast_interval_code'), data.get('broadcast_duration_code'), data.get('broadcast_mode'))
    msgs = total_messages(data.get('broadcast_interval_code'), data.get('broadcast_duration_code'), data.get('broadcast_mode'))
    pending_orders[order_id] = {
        'order_type': 'broadcast',
        'user_id': message.from_user.id,
        'user_username': message.from_user.username,
        'mode': data.get('broadcast_mode','limited'),
        'interval_minutes': data['broadcast_interval'],
        'interval_code': data['broadcast_interval_code'],
        'duration_code': data['broadcast_duration_code'],
        'start_time': data['broadcast_start'],
        'end_time': data['broadcast_end'],  # историческое имя
        'broadcast_end': data['broadcast_end'],  # добавлено для совместимости с обработчиком подтверждения
        'content_type': data['broadcast_content_type'],
        'text': data['broadcast_text'],
        'file_ids': data['broadcast_file_ids'],
        'media_group_id': data['broadcast_media_group_id'],
        'check_photo': photo_id,
        'price': price,
        'messages_total': msgs,
    }
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data=AdminCallback(action="confirm", order_id=order_id).pack())
    builder.button(text="Отклонить", callback_data=AdminCallback(action="reject", order_id=order_id).pack())
    builder.adjust(2)
    # Читаемые подписи
    interval_h = INTERVAL_LABELS.get(data['broadcast_interval_code'], data['broadcast_interval_code'])
    duration_h = DURATION_LABELS.get(data['broadcast_duration_code'], data['broadcast_duration_code'])
    mode_h = "Дневной 09:00–23:00" if (data.get('broadcast_mode') or 'limited') == 'limited' else "24/7"
    caption = (f"Новый заказ (рассылка) #{order_id[:8]}\n"
               f"Пользователь: @{message.from_user.username} ({message.from_user.id})\n"
               f"Режим: {mode_h}\n"
               f"Интервал: {interval_h} ({data['broadcast_interval']} мин)\n"
               f"Длительность: {duration_h}\n"
               f"Старт: {data['broadcast_start']}\n"
               f"Окончание: {data['broadcast_end']}\n"
               f"Цена: {price if price is not None else '—'}₽\n"
               f"Сообщений: {msgs if msgs is not None else '—'}\n")
    if data['broadcast_file_ids']:
        media = [InputMediaPhoto(media=fid, caption=data['broadcast_text'] if i == 0 else None) for i, fid in enumerate(data['broadcast_file_ids'])]
        await bot.send_media_group(ADMIN_CHAT_ID, media)
    else:
        await bot.send_message(ADMIN_CHAT_ID, data['broadcast_text'] or '(без текста)')
    await bot.send_photo(ADMIN_CHAT_ID, photo=photo_id, caption=caption, reply_markup=builder.as_markup())
    await message.answer("Заказ на рассылку отправлен на модерацию.")
    await state.clear()

@menu_router.message(Broadcast.waiting_check)
async def broadcast_need_photo(message: Message):
    # Добавляем кнопку отмены и без контакта, как и в обычной публикации
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.button(text="Отмена", callback_data=MenuCallback(level="cancel").pack())
    await message.answer("Пришлите фотографию чека.", reply_markup=cancel_builder.as_markup())

# Модификация admin callback для обработки рассылки
@menu_router.callback_query(AdminCallback.filter())
async def process_admin_callback(query: CallbackQuery, callback_data: AdminCallback, state: FSMContext, bot: Bot):
    from datetime import datetime, timedelta
    import os
    import pytz
    from app.database import requests as req

    order_id = callback_data.order_id
    action = callback_data.action
    if order_id in pending_orders and pending_orders[order_id].get('order_type') == 'broadcast' and action == 'confirm':
        from app.database import requests as req
        from datetime import datetime
        data = pending_orders.pop(order_id)
        free_chat = int(os.getenv('FREE_CHAT_ID', '0'))
        await req.add_broadcast_post(
            content_type=data['content_type'],
            text=data['text'],
            photo_file_ids=data['file_ids'],
            media_group_id=data['media_group_id'],
            next_run_time=data['start_time'],
            end_time=data['broadcast_end'],
            interval_minutes=data['interval_minutes'],
            chat_id=free_chat,
            mode=data.get('mode','full')
        )
        try:
            await query.message.edit_caption(caption=(query.message.caption + "\n\nСтатус: Подтверждено"), reply_markup=None)
        except Exception:
            pass
        await bot.send_message(data['user_id'], "Ваша рассылка подтверждена и запланирована.")
        await query.answer()
        return
    if action == 'reject':
        await state.update_data(order_id_to_reject=order_id)
        # Убираем инлайн-клавиатуру у сообщения с заказом
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            await bot.edit_message_reply_markup(chat_id=query.message.chat.id, message_id=query.message.message_id, reply_markup=None)
        await query.message.answer("Введите причину отклонения заказа:")
        await state.set_state(AdminReject.waiting_reason)
        await query.answer()
        return

    def parse_pin_variant_to_delta(var: str) -> timedelta | None:
        mapping = {
            '1_week': timedelta(weeks=1),
            '2_weeks': timedelta(weeks=2),
            '3_weeks': timedelta(weeks=3),
            '1_month': timedelta(days=30),
            '2_months': timedelta(days=60),
            '3_months': timedelta(days=90),
            '6_months': timedelta(days=180),
            'forever': None,
        }
        return mapping.get(var)

    def forever_dt(tz) -> datetime:
        return tz.localize(datetime.strptime("12:00 31-12-2200", "%H:%M %d-%m-%Y"))

    def compute_targets(user_type: str, option: str) -> List[int | str] | List[List[int | str]]:
        # Для пакетов возвращаем список чатов, для обычных — один
        free_chat = int(os.getenv('FREE_CHAT_ID', '0'))
        main_chat = int(os.getenv('MAIN_CHAT_ID', '0'))
        channel = int(os.getenv('CHANNEL_ID', '0'))  # теперь это премиум-канал
        if option == '1':
            return [free_chat]
        if option == '2':
            return [main_chat]
        if option == '3':
            return [channel]
        if option in ('4', '5', '6'):
            return [main_chat, channel, free_chat]
        return [channel]

    def get_boost_count(selected: dict) -> int:
        try:
            var = selected.get('boost')
            return int(var) if var and var.isdigit() else 0
        except Exception:
            return 0

    await query.answer()

    if order_id in pending_orders:
        order = pending_orders.pop(order_id)
        user_id = order['user_id']
        status = "Обработано"
        if action == "confirm":
            # Сохраняем пост(ы) в БД как ScheduledPost по целевым чатам
            tz = pytz.timezone("Europe/Moscow")
            now = datetime.now(tz)
            scheduled_time = now + timedelta(seconds=90)
            selected = order.get('selected_suboptions', {})
            user_type = order['user_type']
            option = order['option']
            pin_variant = selected.get('pin')
            pin_delta = parse_pin_variant_to_delta(pin_variant) if pin_variant else None
            boost_count = get_boost_count(selected)

            # Время удаления: все размещения теперь навсегда
            delete_time_base = forever_dt(tz)

            targets = compute_targets(user_type, option)
            for chat_id in targets:
                # unpin_time по правилам для основной публикации:
                if option == '4':
                    # Пакет 4: закреп только в бесплатном чате на 1 месяц
                    if chat_id == int(os.getenv('FREE_CHAT_ID', '0')):
                        unpin_time = now + timedelta(days=30)
                    else:
                        unpin_time = None
                elif option == '5':
                    # Пакет 5: закреп 1 месяц во всех входящих чатиках
                    unpin_time = now + timedelta(days=30)
                elif option == '6':
                    # Пакет 6: закреп навсегда
                    unpin_time = forever_dt(tz)
                else:
                    # Обычные: если выбрана опция pin — берём её, forever -> 2200; иначе без закрепа
                    if pin_delta is not None:
                        unpin_time = now + pin_delta
                    elif pin_variant == 'forever':
                        unpin_time = forever_dt(tz)
                    else:
                        unpin_time = None

                # delete_time по правилам
                delete_time = delete_time_base

                # Основная публикация
                await req.add_or_update_scheduled_post(
                    content_type=order['content_type'],
                    text=order['text'],
                    photo_file_ids=order['file_ids'],
                    scheduled_time=scheduled_time.replace(tzinfo=None),  # в БД без tz
                    media_group_id=order['media_group_id'] or 0,
                    unpin_time=unpin_time.replace(tzinfo=None) if unpin_time else None,
                    delete_time=delete_time.replace(tzinfo=None) if delete_time else None,
                    chat_id=int(chat_id)
                )

                # Поднятия: дублируем пост boost_count раз, каждые +2 часа, с закрепом на 2 часа
                for i in range(1, boost_count + 1):
                    st = (now + timedelta(hours=2 * i)).replace(tzinfo=None)
                    unpin_boost = (now + timedelta(hours=2 * i + 2)).replace(tzinfo=None)
                    await req.add_or_update_scheduled_post(
                        content_type=order['content_type'],
                        text=order['text'],
                        photo_file_ids=order['file_ids'],
                        scheduled_time=st,
                        media_group_id=order['media_group_id'] or 0,
                        unpin_time=unpin_boost,
                        delete_time=delete_time.replace(tzinfo=None) if delete_time else None,
                        chat_id=int(chat_id)
                    )

            # Уведомление пользователю с кнопкой контакта
            kb = InlineKeyboardBuilder(); kb = add_contact_button(kb)
            await bot.send_message(user_id, "Ваш заказ подтверждён! Посты запланированы к публикации.", reply_markup=kb.as_markup())
            status = "Подтверждено"

        await query.message.edit_caption(caption=query.message.caption + f"\n\nСтатус: {status}", reply_markup=None)
    else:
        await query.answer("Заказ не найден или уже обработан.")

# Новый обработчик для получения причины отклонения от админа
@menu_router.message(AdminReject.waiting_reason)
async def process_rejection_reason(message: Message, state: FSMContext, bot: Bot):
    reason = message.text
    data = await state.get_data()
    order_id = data.get('order_id_to_reject')

    if order_id in pending_orders:
        order = pending_orders.pop(order_id)
        user_id = order['user_id']

        # Отправляем пользователю сообщение с причиной
        kb = InlineKeyboardBuilder(); kb = add_contact_button(kb)
        await bot.send_message(
            user_id,
            f"Ваш заказ был отклонён.\n\n<b>Причина:</b> {reason}",
            reply_markup=kb.as_markup(),
            parse_mode=ParseMode.HTML
        )

        # Обновляем сообщение в админском чате
        # (Предполагается, что админ отвечает на сообщение с заказом, но это сложно отследить без reply)
        # Проще просто уведомить админа, что причина отправлена
        await message.answer(f"Причина отклонения для заказа #{order_id[:8]} отправлена пользователю.")

    await state.clear()


# Fallback for wrong input in states
@menu_router.message(Purchase.waiting_check)
async def invalid_check(message: Message):
    kb = InlineKeyboardBuilder(); kb = add_contact_button(kb)
    await message.answer("Пожалуйста, отправьте фотографию чека.", reply_markup=kb.as_markup())

@menu_router.message(Purchase.waiting_post)
async def invalid_post(message: Message):
    kb = InlineKeyboardBuilder(); kb = add_contact_button(kb)
    await message.answer("Пожалуйста, отправьте текст или фото.", reply_markup=kb.as_markup())

@menu_router.message(Broadcast.waiting_start_time)
async def broadcast_waiting_start_time(message: Message, state: FSMContext):
    from datetime import datetime, timedelta
    try:
        txt = message.text.strip()
        if txt.lower() == '/now':
            start = datetime.now() + timedelta(minutes=1)
        else:
            start = datetime.strptime(txt, "%H:%M %d-%m-%Y")
            if start < datetime.now():
                await message.reply("Время в прошлом. Укажите корректное.")
                return
        data = await state.get_data()
        duration_minutes = data['broadcast_duration']
        end_time = start + timedelta(minutes=duration_minutes)
        await state.update_data(broadcast_start=start, broadcast_end=end_time)
        await state.set_state(Broadcast.waiting_post)
        await message.answer("Теперь отправьте контент поста (текст или фото). Он будет публиковаться по расписанию.")
    except Exception:
        await message.reply("Неверный формат. Используйте HH:MM DD-MM-YYYY или /now")

@menu_router.message(Broadcast.waiting_post)
async def broadcast_waiting_post(message: Message, state: FSMContext, album: List[Message] | None = None):
    # Поддержка альбома через middleware
    if album:
        content_type = 'photo'
        file_ids = [msg.photo[-1].file_id for msg in album if msg.photo]
        text = next((msg.caption for msg in album if msg.caption), '')
        media_group_id = album[0].media_group_id if album and album[0].media_group_id else 0
    else:
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

    # Валидация длины
    max_len = 1024 if file_ids else 4096
    if len(text or '') > max_len:
        await message.reply(f"Слишком длинный текст. Лимит: {max_len} символов. Сейчас: {len(text or '')}.")
        return

    # Сохраняем контент рассылки и просим чек с суммой
    await state.update_data(
        broadcast_content_type=content_type,
        broadcast_text=text,
        broadcast_file_ids=file_ids,
        broadcast_media_group_id=media_group_id
    )
    await state.set_state(Broadcast.waiting_check)

    data = await state.get_data()
    price = get_broadcast_price(
        data.get('broadcast_interval_code'),
        data.get('broadcast_duration_code'),
        data.get('broadcast_mode')
    )
    # Добавляем кнопку Отмена и сохраняем id сообщения для последующего редактирования
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.button(text="Отмена", callback_data=MenuCallback(level="cancel").pack())
    if price is not None:
        sent = await message.answer(f"Отправьте фотографию чека оплаты на сумму {price}₽.\n\n"
                            f"Реквизиты для оплаты:\n"
                            f"Сбербанк:\n"
                            f"Даниил Дмитриевич М.\n"
                            f"2202206250331753\n"
                            f"Можно по номеру:\n"
                            f"89164253032", reply_markup=cancel_builder.as_markup())
    else:
        sent = await message.answer("Отправьте фотографию чека оплаты рассылки.", reply_markup=cancel_builder.as_markup())
    await state.update_data(waiting_msg_id=sent.message_id)
