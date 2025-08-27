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
    # Приветственный текст с ссылками
    intro = (
        "Добро пожаловать! Ниже — быстрые ссылки на наши площадки:\n"
        f"• Основной чат: {LINKS['main']}\n"
        f"• Премиум-канал: {LINKS['premium']}\n"
        f"• Бесплатный чат: {LINKS['free']}\n"
        f"• Чат с отзывами: {LINKS['reviews']}\n\n"
        "Выберите категорию.\n"
        "Важно: указывайте верный статус (Фрилансер/Работодатель) — объявления проходят модерацию и при неверном выборе могут быть отклонены."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="А) Для работодателей", callback_data=MenuCallback(level="sub", user_type="employer").pack())
    builder.button(text="Б) Для фрилансеров", callback_data=MenuCallback(level="sub", user_type="freelancer").pack())
    builder.adjust(1)  # One button per row
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
        builder.button(text="А) Для работодателей", callback_data=MenuCallback(level="sub", user_type="employer").pack())
        builder.button(text="Б) Для фрилансеров", callback_data=MenuCallback(level="sub", user_type="freelancer").pack())
        builder.adjust(1)
        builder = add_contact_button(builder)
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
        # остаёмся без кнопок на этапе оплаты
        await bot.edit_message_text(chat_id=message.chat.id, message_id=waiting_msg_id, text="Чек получен.", reply_markup=None)

    user_type = data.get('user_type')
    hashtag = '#ищу' if user_type == 'employer' else '#помогу'

    # Следующий шаг (отправка поста) — показываем кнопку контакта и правила по хэштегам
    kb = InlineKeyboardBuilder()
    kb = add_contact_button(kb)
    post_rules_text = (
        "Теперь отправьте пост, который хотите опубликовать.\n\n"
        "<b>Важно:</b>\n"
        f"• Ваш пост должен содержать обязательный хэштег: <code>{'#ищу' if user_type == 'employer' else '#помогу'}</code>\n"
        "• Правило сети по хэштегам: для фрилансера обязателен <code>#помогу</code>, для работодателя — <code>#ищу</code>.\n"
        "• Кроме обязательного хэштега <code>#ищу</code> или <code>#помогу</code> укажите уточняющие хэштеги. "
        "К примеру, <code>#smm</code> или <code>#менеджер</code>.\n"
        "• Не забудьте указать свой контакт или форму в объявлении.\n"
        "• Убедитесь, что хэштег присутствует и написан правильно."
    )
    await bot.send_message(message.chat.id, post_rules_text, reply_markup=kb.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(Purchase.waiting_post)

# Handler for post content
@menu_router.message(Purchase.waiting_post)
async def process_post_content(message: Message, state: FSMContext, bot: Bot, album: List[Message] | None = None):
    data = await state.get_data()
    user_type = data.get('user_type')
    required_hashtag = '#ищу' if user_type == 'employer' else '#помогу'

    if album:
        # Обработка медиа-группы (альбома)
        content_type = 'photo'
        file_ids = [msg.photo[-1].file_id for msg in album if msg.photo]
        text = next((msg.caption for msg in album if msg.caption), '')  # Caption от первого с текстом
        media_group_id = 0  # используем 0, чтобы не сохранять строковый идентификатор
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
            kb = InlineKeyboardBuilder(); kb = add_contact_button(kb)
            await message.answer("Пожалуйста, отправьте текст или фото.", reply_markup=kb.as_markup())
            return

    # Проверка хэштега (регистронезависимо)
    if required_hashtag.lower() not in (text or '').lower():
        kb = InlineKeyboardBuilder(); kb = add_contact_button(kb)
        await message.reply(
            f"Ошибка: в вашем посте отсутствует обязательный хэштег <code>{required_hashtag}</code>. "
            f"Пожалуйста, исправьте и отправьте пост заново.",
            reply_markup=kb.as_markup(),
            parse_mode=ParseMode.HTML
        )
        return

    await state.update_data(content_type=content_type, text=text, file_ids=file_ids, media_group_id=media_group_id)

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
    suboptions_str = ', '.join([f"{SUBOPTION_NAMES.get(k, k)}: {PRICES_DICT[get_suboption_key(k, data['user_type'], data['option'])][v]['text']}" for k, v in data['selected_suboptions'].items()]) if data['selected_suboptions'] else 'Нет'

    # If post has photos, send them to admin first
    if file_ids:
        media = [InputMediaPhoto(media=file_id, caption=text if i == 0 else None, parse_mode=ParseMode.HTML) for i, file_id in enumerate(file_ids)]
        await bot.send_media_group(ADMIN_CHAT_ID, media)
        post_str = "Пост: опубликован выше"
    else:
        await bot.send_message(ADMIN_CHAT_ID, text)
        post_str = f"Пост: опубликован выше"

    # Build admin keyboard
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить", callback_data=AdminCallback(action="confirm", order_id=order_id).pack())
    builder.button(text="Отклонить", callback_data=AdminCallback(action="reject", order_id=order_id).pack())
    builder.adjust(2)

    # Send check photo with caption and buttons to admin
    caption = (
        f"Новый заказ #{order_id[:8]}\n"
        f"От пользователя: @{message.from_user.username} (ID: {message.from_user.id})\n"
        f"Тип: {data['user_type'].capitalize()}\n"
        f"Опция: {DESCRIPTIONS[data['user_type']][data['option']].splitlines()[0]}\n"
        f"Дополнительные опции: {suboptions_str}\n"
        f"Сумма: {data['total']}₽\n"
        f"{post_str}"
    )
    await bot.send_photo(ADMIN_CHAT_ID, photo=data['check_photo'], caption=caption, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

    # Пользователю — ответ с кнопкой контакта
    kb = InlineKeyboardBuilder(); kb = add_contact_button(kb)
    await message.answer("Пост получен и отправлен на модерацию. Спасибо!", reply_markup=kb.as_markup())
    await state.clear()

# Admin callback handler
@menu_router.callback_query(AdminCallback.filter())
async def process_admin_callback(query: CallbackQuery, callback_data: AdminCallback, state: FSMContext, bot: Bot):
    from datetime import datetime, timedelta
    import os
    import pytz
    from app.database import requests as req

    order_id = callback_data.order_id
    action = callback_data.action

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
