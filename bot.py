import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db,
    create_order,
    get_user_orders,
    get_pending_orders,
    set_order_status,
)
from settings import (
    USD_TO_KGS,
    STARS_BUY_RATE_USD,
    STARS_SELL_RATE_USD,
    PREMIUM_PRICES_USD,
    MIN_STARS,
    SUPPORT_USERNAME,
)


dp = Dispatcher()


# =========================
# STATES
# =========================

class StarAmountState(StatesGroup):
    waiting_buy_amount = State()
    waiting_sell_amount = State()


class PremiumState(StatesGroup):
    waiting_friend_username = State()


class SellState(StatesGroup):
    waiting_qr = State()


# =========================
# HELPERS
# =========================

def usd_to_kgs(amount: float) -> float:
    return round(amount * USD_TO_KGS, 2)


def main_menu():
    kb = InlineKeyboardBuilder()

    kb.button(text="⭐️ Купить Stars", callback_data="buy_stars")
    kb.button(text="💰 Продать Stars", callback_data="sell_stars")
    kb.button(text="💎 Premium", callback_data="premium")
    kb.button(text="📦 Мои заказы", callback_data="orders")
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="💬 Поддержка", callback_data="support")

    kb.adjust(2, 2, 2)

    return kb.as_markup()


def back_button():
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад", callback_data="back_main")
    return kb.as_markup()


def stars_amount_keyboard(prefix: str):
    kb = InlineKeyboardBuilder()

    kb.button(text="100 ⭐️", callback_data=f"{prefix}_100")
    kb.button(text="500 ⭐️", callback_data=f"{prefix}_500")
    kb.button(text="1000 ⭐️", callback_data=f"{prefix}_1000")
    kb.button(text="2000 ⭐️", callback_data=f"{prefix}_2000")
    kb.button(
        text="✏️ Другое количество",
        callback_data=f"{prefix}_custom"
    )
    kb.button(text="◀️ Назад", callback_data="back_main")

    kb.adjust(2, 2, 1, 1)

    return kb.as_markup()


def admin_order_keyboard(order_id: int):
    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ Подтвердить",
        callback_data=f"admin_done_{order_id}"
    )

    kb.button(
        text="❌ Отклонить",
        callback_data=f"admin_reject_{order_id}"
    )

    kb.adjust(1, 1)

    return kb.as_markup()


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    if message.from_user.username:
        greeting = (
            f"👋 Добро пожаловать, "
            f"@{message.from_user.username}!"
        )
    else:
        greeting = (
            f"👋 Добро пожаловать, "
            f"{message.from_user.full_name}!"
        )

    text = (
        f"{greeting}\n\n"
        "У нас Вы можете приобрести Telegram Stars, "
        "Telegram Premium.\n\n"
        "Выберите нужное действие:"
    )

    await message.answer(
        text,
        reply_markup=main_menu()
    )


# =========================
# BACK
# =========================

@dp.callback_query(F.data == "back_main")
async def back_main(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    if callback.from_user.username:
        greeting = (
            f"👋 Добро пожаловать, "
            f"@{callback.from_user.username}!"
        )
    else:
        greeting = (
            f"👋 Добро пожаловать, "
            f"{callback.from_user.full_name}!"
        )

    text = (
        f"{greeting}\n\n"
        "У нас Вы можете приобрести Telegram Stars, "
        "Telegram Premium.\n\n"
        "Выберите нужное действие:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu()
    )

    await callback.answer()


# ============================================================
# BUY STARS
# ============================================================

@dp.callback_query(F.data == "buy_stars")
async def buy_stars(callback: CallbackQuery):
    price_100_usd = STARS_BUY_RATE_USD
    price_100_kgs = usd_to_kgs(price_100_usd)

    text = (
        "⭐️ Купить Stars\n\n"
        f"Курс: 100 ⭐️ = {price_100_usd:.2f}$ "
        f"({price_100_kgs:.2f} сом)\n\n"
        f"Минимальная покупка — {MIN_STARS} ⭐️\n\n"
        "Выберите количество:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=stars_amount_keyboard("buy")
    )

    await callback.answer()


@dp.callback_query(F.data == "buy_custom")
async def buy_custom(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.set_state(
        StarAmountState.waiting_buy_amount
    )

    await callback.message.edit_text(
        f"✏️ Введите количество Stars.\n\n"
        f"Минимум: {MIN_STARS} ⭐️",
        reply_markup=back_button()
    )

    await callback.answer()


@dp.message(StarAmountState.waiting_buy_amount)
async def buy_custom_amount(
    message: Message,
    state: FSMContext
):
    try:
        amount = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer(
            "❌ Введите количество только цифрами.\n\n"
            "Например: 350"
        )
        return

    if amount < MIN_STARS:
        await message.answer(
            f"❌ Минимальная покупка — {MIN_STARS} ⭐️."
        )
        return

    if not message.from_user.username:
        await state.clear()

        await message.answer(
            "⚠️ Для покупки Stars необходимо установить "
            "username в Telegram.\n\n"
            "После установки username снова нажмите "
            "«Купить Stars».",
            reply_markup=main_menu()
        )
        return

    await state.clear()
    await create_buy_order(message, amount)


@dp.callback_query(F.data.startswith("buy_"))
async def buy_fixed(callback: CallbackQuery):
    value = callback.data.replace("buy_", "")

    if value == "custom":
        return

    try:
        amount = int(value)
    except ValueError:
        return

    if amount < MIN_STARS:
        await callback.answer(
            "Минимум 100 Stars",
            show_alert=True
        )
        return

    if not callback.from_user.username:
        await callback.message.edit_text(
            "⚠️ Для покупки Stars необходимо установить "
            "username в Telegram.\n\n"
            "После установки username снова нажмите "
            "«Купить Stars».",
            reply_markup=back_button()
        )
        await callback.answer()
        return

    await create_buy_order(
        callback.message,
        amount
    )

    await callback.answer()


async def create_buy_order(
    message: Message,
    amount: int
):
    price_usd = (
        amount / 100
    ) * STARS_BUY_RATE_USD

    price_kgs = usd_to_kgs(price_usd)

    username = (
        message.from_user.username
        if message.from_user.username
        else "без username"
    )

    order_id = await create_order(
        telegram_id=message.from_user.id,
        username=username,
        order_type="BUY_STARS",
        amount=str(amount),
        price=price_usd,
    )

    text = (
        f"⭐️ Покупка {amount} Stars\n\n"
        f"💵 Сумма: {price_usd:.2f}$\n"
        f"🇰🇬 Сумма: {price_kgs:.2f} сом\n\n"
        "⚠️ ВАЖНО:\n"
        "Оплатить надо полную сумму !!\n"
        "Возврата денег не подлежит, будьте внимательны.\n\n"
        f"📦 Заказ №{order_id}\n\n"
        "💳 Этап оплаты\n"
        "Реквизиты для оплаты будут добавлены позже.\n\n"
        "После оплаты нажмите кнопку ниже."
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ Я оплатил",
        callback_data=f"paid_{order_id}"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(1, 1)

    await message.answer(
        text,
        reply_markup=kb.as_markup()
    )

    await notify_admin_new_order(
        message.bot,
        order_id,
        message.from_user.id,
        username,
        "⭐️ Покупка Stars",
        f"{amount} Stars",
        price_usd,
        price_kgs,
    )


# ============================================================
# SELL STARS
# ============================================================

@dp.callback_query(F.data == "sell_stars")
async def sell_stars(callback: CallbackQuery):
    price_100_usd = STARS_SELL_RATE_USD
    price_100_kgs = usd_to_kgs(price_100_usd)

    text = (
        "💰 Продать Stars\n\n"
        f"Курс: 100 ⭐️ = {price_100_usd:.2f}$ "
        f"({price_100_kgs:.2f} сом)\n\n"
        f"Минимальная продажа — {MIN_STARS} ⭐️\n\n"
        "⚠️ Перед продажей обязательно подготовьте "
        "скриншот, где видно, откуда были куплены Stars.\n\n"
        "Выберите количество:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=stars_amount_keyboard("sell")
    )

    await callback.answer()


@dp.callback_query(F.data == "sell_custom")
async def sell_custom(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.set_state(
        StarAmountState.waiting_sell_amount
    )

    await callback.message.edit_text(
        f"✏️ Введите количество Stars для продажи.\n\n"
        f"Минимум: {MIN_STARS} ⭐️",
        reply_markup=back_button()
    )

    await callback.answer()


@dp.message(StarAmountState.waiting_sell_amount)
async def sell_custom_amount(
    message: Message,
    state: FSMContext
):
    try:
        amount = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer(
            "❌ Введите количество только цифрами.\n\n"
            "Например: 350"
        )
        return

    if amount < MIN_STARS:
        await message.answer(
            f"❌ Минимальная продажа — {MIN_STARS} ⭐️."
        )
        return

    await state.clear()

    await ask_sell_bank(
        message,
        amount
    )


@dp.callback_query(F.data.startswith("sell_"))
async def sell_fixed(callback: CallbackQuery):
    value = callback.data.replace("sell_", "")

    if value == "custom":
        return

    try:
        amount = int(value)
    except ValueError:
        return

    if amount < MIN_STARS:
        await callback.answer(
            "Минимум 100 Stars",
            show_alert=True
        )
        return

    await ask_sell_bank(
        callback.message,
        amount
    )

    await callback.answer()


async def ask_sell_bank(
    message: Message,
    amount: int
):
    price_usd = (
        amount / 100
    ) * STARS_SELL_RATE_USD

    price_kgs = usd_to_kgs(price_usd)

    kb = InlineKeyboardBuilder()

    kb.button(
        text="🏦 MBank",
        callback_data=f"sellbank_mbank_{amount}"
    )

    kb.button(
        text="🏦 Optima 24",
        callback_data=f"sellbank_optima_{amount}"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(2, 1)

    text = (
        f"💰 Продажа {amount} Stars\n\n"
        f"💵 Вы получите: {price_usd:.2f}$\n"
        f"🇰🇬 Вы получите: {price_kgs:.2f} сом\n\n"
        "🏦 Выберите банк для получения выплаты.\n\n"
        "После выбора банка отправляйте только QR-код."
    )

    await message.answer(
        text,
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data.startswith("sellbank_"))
async def sell_bank(
    callback: CallbackQuery,
    state: FSMContext
):
    parts = callback.data.split("_")

    if len(parts) != 3:
        await callback.answer(
            "Ошибка.",
            show_alert=True
        )
        return

    bank = parts[1]

    try:
        amount = int(parts[2])
    except ValueError:
        await callback.answer(
            "Ошибка количества.",
            show_alert=True
        )
        return

    bank_name = (
        "MBank"
        if bank == "mbank"
        else "Optima 24"
    )

    await state.update_data(
        sell_amount=amount,
        sell_bank=bank_name
    )

    await state.set_state(
        SellState.waiting_qr
    )

    await callback.message.edit_text(
        f"🏦 Банк: {bank_name}\n\n"
        f"⭐️ Количество: {amount} Stars\n\n"
        "📲 Теперь отправьте только QR-код "
        "для получения выплаты.\n\n"
        "❗️Нужен именно QR-код."
    )

    await callback.answer()


@dp.message(
    SellState.waiting_qr,
    F.photo
)
async def receive_sell_qr(
    message: Message,
    state: FSMContext
):
    data = await state.get_data()

    amount = data.get("sell_amount")
    bank = data.get("sell_bank")

    if not amount or not bank:
        await state.clear()

        await message.answer(
            "❌ Данные заявки потеряны.\n"
            "Начните продажу заново.",
            reply_markup=main_menu()
        )
        return

    price_usd = (
        amount / 100
    ) * STARS_SELL_RATE_USD

    price_kgs = usd_to_kgs(price_usd)

    username = (
        message.from_user.username
        if message.from_user.username
        else "без username"
    )

    order_id = await create_order(
        telegram_id=message.from_user.id,
        username=username,
        order_type="SELL_STARS",
        amount=str(amount),
        price=price_usd,
    )

    photo_id = message.photo[-1].file_id

    await state.clear()

    await message.answer(
        f"✅ Заявка оформлена!\n\n"
        f"📦 Заказ №{order_id}\n"
        f"⭐️ Stars: {amount}\n"
        f"🏦 Банк: {bank}\n"
        f"💰 Выплата: {price_kgs:.2f} сом\n\n"
        "Заявка отправлена на проверку.\n"
        "После подтверждения деньги будут отправлены "
        "в течение 24 часов.",
        reply_markup=main_menu()
    )

    await notify_admin_sell_order(
        message.bot,
        order_id,
        message.from_user.id,
        username,
        amount,
        bank,
        price_usd,
        price_kgs,
        photo_id,
    )


@dp.message(SellState.waiting_qr)
async def sell_qr_only(message: Message):
    await message.answer(
        "❌ Отправьте QR-код фотографией."
    )


# ============================================================
# PREMIUM
# ============================================================

@dp.callback_query(F.data == "premium")
async def premium(callback: CallbackQuery):
    text = (
        "💎 Telegram Premium\n\n"
        f"3 месяца — {PREMIUM_PRICES_USD['3']:.2f}$ "
        f"({usd_to_kgs(PREMIUM_PRICES_USD['3']):.2f} сом)\n"
        f"6 месяцев — {PREMIUM_PRICES_USD['6']:.2f}$ "
        f"({usd_to_kgs(PREMIUM_PRICES_USD['6']):.2f} сом)\n"
        f"12 месяцев — {PREMIUM_PRICES_USD['12']:.2f}$ "
        f"({usd_to_kgs(PREMIUM_PRICES_USD['12']):.2f} сом)\n\n"
        "Для кого хотите приобрести Premium?"
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="👤 Себе",
        callback_data="premium_self"
    )

    kb.button(
        text="👥 Для друга",
        callback_data="premium_friend"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(2, 1)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data == "premium_self")
async def premium_self(callback: CallbackQuery):
    await show_premium_durations(
        callback.message,
        "self"
    )

    await callback.answer()


@dp.callback_query(F.data == "premium_friend")
async def premium_friend(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.set_state(
        PremiumState.waiting_friend_username
    )

    await callback.message.edit_text(
        "👥 Введите username получателя Premium.\n\n"
        "Например:\n"
        "@username",
        reply_markup=back_button()
    )

    await callback.answer()


@dp.message(PremiumState.waiting_friend_username)
async def premium_friend_username(
    message: Message,
    state: FSMContext
):
    username = message.text.strip()

    if not username.startswith("@"):
        username = "@" + username

    if len(username) < 2:
        await message.answer(
            "❌ Укажите корректный username."
        )
        return

    await state.clear()

    await show_premium_durations(
        message,
        "friend",
        username
    )


async def show_premium_durations(
    message: Message,
    purchase_for: str,
    recipient_username: str = None
):
    kb = InlineKeyboardBuilder()

    kb.button(
        text="3 месяца",
        callback_data=f"premium_3_{purchase_for}"
    )

    kb.button(
        text="6 месяцев",
        callback_data=f"premium_6_{purchase_for}"
    )

    kb.button(
        text="12 месяцев",
        callback_data=f"premium_12_{purchase_for}"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(1, 1, 1, 1)

    text = "💎 Выберите срок Premium:\n\n"

    if recipient_username:
        text += (
            f"👤 Получатель: "
            f"{recipient_username}\n\n"
        )

    text += (
        f"3 месяца — {PREMIUM_PRICES_USD['3']:.2f}$ "
        f"({usd_to_kgs(PREMIUM_PRICES_USD['3']):.2f} сом)\n"
        f"6 месяцев — {PREMIUM_PRICES_USD['6']:.2f}$ "
        f"({usd_to_kgs(PREMIUM_PRICES_USD['6']):.2f} сом)\n"
        f"12 месяцев — {PREMIUM_PRICES_USD['12']:.2f}$ "
        f"({usd_to_kgs(PREMIUM_PRICES_USD['12']):.2f} сом)"
    )

    await message.answer(
        text,
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data.startswith("premium_"))
async def premium_duration(
    callback: CallbackQuery
):
    parts = callback.data.split("_")

    if len(parts) != 3:
        return

    months = parts[1]
    purchase_for = parts[2]

    if months not in PREMIUM_PRICES_USD:
        return

    price_usd = PREMIUM_PRICES_USD[months]
    price_kgs = usd_to_kgs(price_usd)

    recipient = (
        "себе"
        if purchase_for == "self"
        else "для друга"
    )

    username = (
        callback.from_user.username
        if callback.from_user.username
        else "без username"
    )

    order_id = await create_order(
        telegram_id=callback.from_user.id,
        username=username,
        order_type="PREMIUM",
        amount=f"{months} месяцев ({recipient})",
        price=price_usd,
    )

    text = (
        "💎 Telegram Premium\n\n"
        f"⏱️ Срок: {months} месяцев\n"
        f"👤 Покупка: {recipient}\n"
        f"💵 Сумма: {price_usd:.2f}$\n"
        f"🇰🇬 Сумма: {price_kgs:.2f} сом\n\n"
        "⚠️ ВАЖНО:\n"
        "Оплатить надо полную сумму !!\n"
        "Возврата денег не подлежит, будьте внимательны.\n\n"
        f"📦 Заказ №{order_id}\n\n"
        "💳 Этап оплаты\n"
        "Реквизиты для оплаты будут добавлены позже.\n\n"
        "После оплаты нажмите кнопку ниже."
    )

    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ Я оплатил",
        callback_data=f"paid_{order_id}"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(1, 1)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await notify_admin_new_order(
        callback.bot,
        order_id,
        callback.from_user.id,
        username,
        "💎 Telegram Premium",
        f"{months} месяцев ({recipient})",
        price_usd,
        price_kgs,
    )

    await callback.answer()


# ============================================================
# PAID
# ============================================================

@dp.callback_query(F.data.startswith("paid_"))
async def paid_order(callback: CallbackQuery):
    try:
        order_id = int(
            callback.data.replace("paid_", "")
        )
    except ValueError:
        await callback.answer(
            "Ошибка заказа.",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        f"⏳ Оплата по заказу №{order_id} "
        "отправлена на проверку.\n\n"
        "Ожидайте подтверждения администратора.",
        reply_markup=main_menu()
    )

    await callback.answer(
        "Оплата отправлена."
    )

    if ADMIN_ID:
        try:
            await callback.bot.send_message(
                ADMIN_ID,
                "💳 ПОЛЬЗОВАТЕЛЬ НАЖАЛ «Я ОПЛАТИЛ»\n\n"
                f"📦 Заказ №{order_id}\n"
                f"👤 {get_user_display(callback)}\n"
                f"🆔 ID: {callback.from_user.id}",
                reply_markup=admin_order_keyboard(order_id)
            )
        except Exception:
            pass


def get_user_display(callback: CallbackQuery):
    if callback.from_user.username:
        return f"@{callback.from_user.username}"

    return callback.from_user.full_name


# ============================================================
# ORDERS
# ============================================================

@dp.callback_query(F.data == "orders")
async def orders(callback: CallbackQuery):
    rows = await get_user_orders(
        callback.from_user.id
    )

    if not rows:
        await callback.message.edit_text(
            "📦 У вас пока нет заказов.",
            reply_markup=back_button()
        )

        await callback.answer()
        return

    text = "📦 Мои заказы\n\n"

    for row in rows[:20]:
        (
            order_id,
            order_type,
            amount,
            price,
            status,
            created_at
        ) = row

        if order_type == "BUY_STARS":
            icon = "⭐️"
            name = "Покупка Stars"
        elif order_type == "SELL_STARS":
            icon = "💰"
            name = "Продажа Stars"
        elif order_type == "PREMIUM":
            icon = "💎"
            name = "Premium"
        else:
            icon = "📦"
            name = order_type

        status_text = {
            "WAITING_PAYMENT": "⏳ Ожидает оплаты",
            "PROCESSING": "🔄 В обработке",
            "COMPLETED": "✅ Выполнен",
            "REJECTED": "❌ Отклонён",
        }.get(status, status)

        text += (
            f"{icon} Заказ №{order_id}\n"
            f"Тип: {name}\n"
            f"Количество: {amount}\n"
            f"Сумма: {price:.2f}$\n"
            f"Статус: {status_text}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_button()
    )

    await callback.answer()


# ============================================================
# PROFILE
# ============================================================

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    rows = await get_user_orders(
        callback.from_user.id
    )

    if callback.from_user.username:
        username = f"@{callback.from_user.username}"
    else:
        username = "Не установлен"

    text = (
        "👤 Профиль\n\n"
        f"Username: {username}\n"
        f"Telegram ID: {callback.from_user.id}\n"
        f"Заказов: {len(rows)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_button()
    )

    await callback.answer()


# ============================================================
# SUPPORT
# ============================================================

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    username = SUPPORT_USERNAME.replace("@", "")

    kb = InlineKeyboardBuilder()

    kb.button(
        text="💬 Написать в поддержку",
        url=f"https://t.me/{username}"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(1, 1)

    await callback.message.edit_text(
        "💬 Поддержка\n\n"
        f"По всем вопросам обращайтесь к @{username}.",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


# ============================================================
# ADMIN NOTIFICATIONS
# ============================================================

async def notify_admin_new_order(
    bot: Bot,
    order_id: int,
    telegram_id: int,
    username: str,
    order_name: str,
    amount: str,
    price_usd: float,
    price_kgs: float,
):
    if not ADMIN_ID:
        return

    text = (
        "🆕 НОВЫЙ ЗАКАЗ\n\n"
        f"📦 Заказ №{order_id}\n"
        f"📌 {order_name}\n"
        f"📊 {amount}\n"
        f"💵 {price_usd:.2f}$\n"
        f"🇰🇬 {price_kgs:.2f} сом\n\n"
        f"👤 Username: {username}\n"
        f"🆔 Telegram ID: {telegram_id}\n"
        "📌 Статус: ожидание оплаты"
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            text,
            reply_markup=admin_order_keyboard(order_id)
        )
    except Exception:
        pass


async def notify_admin_sell_order(
    bot: Bot,
    order_id: int,
    telegram_id: int,
    username: str,
    amount: int,
    bank: str,
    price_usd: float,
    price_kgs: float,
    photo_id: str,
):
    if not ADMIN_ID:
        return

    text = (
        "💰 НОВАЯ ЗАЯВКА НА ПРОДАЖУ STARS\n\n"
        f"📦 Заказ №{order_id}\n"
        f"⭐️ Stars: {amount}\n"
        f"🏦 Банк: {bank}\n"
        f"💵 Выплата: {price_usd:.2f}$\n"
        f"🇰🇬 Выплата: {price_kgs:.2f} сом\n\n"
        f"👤 Username: {username}\n"
        f"🆔 Telegram ID: {telegram_id}\n\n"
        "📲 QR-код пользователя:"
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            text,
            reply_markup=admin_order_keyboard(order_id)
        )

        await bot.send_photo(
            ADMIN_ID,
            photo=photo_id,
            caption=f"📦 QR-код к заказу №{order_id}"
        )

    except Exception:
        pass


# ============================================================
# ADMIN CONFIRM
# ============================================================

@dp.callback_query(F.data.startswith("admin_done_"))
async def admin_done(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "❌ Нет доступа.",
            show_alert=True
        )
        return

    try:
        order_id = int(
            callback.data.replace("admin_done_", "")
        )
    except ValueError:
        await callback.answer(
            "Ошибка заказа.",
            show_alert=True
        )
        return

    # Сначала получаем pending-заказ,
    # чтобы сохранить Telegram ID пользователя.
    pending_orders = await get_pending_orders()

    target_order = None

    for row in pending_orders:
        if row[0] == order_id:
            target_order = row
            break

    if not target_order:
        await callback.answer(
            "Заказ уже обработан или не найден.",
            show_alert=True
        )
        return

    (
        _order_id,
        telegram_id,
        username,
        order_type,
        amount,
        price,
        status,
        created_at
    ) = target_order

    await set_order_status(
        order_id,
        "COMPLETED"
    )

    await callback.message.edit_text(
        callback.message.text
        + "\n\n✅ Заказ отмечен как выполненный."
    )

    # Сообщение пользователю зависит от типа заказа.
    if order_type == "BUY_STARS":
        user_text = (
            "✅ Заказ оформлен!\n\n"
            f"📦 Заказ №{order_id}\n"
            "⭐️ Stars поступят в течение 24 часов."
        )

    elif order_type == "PREMIUM":
        user_text = (
            "✅ Заказ оформлен!\n\n"
            f"📦 Заказ №{order_id}\n"
            "💎 Premium поступит в течение 24 часов."
        )

    elif order_type == "SELL_STARS":
        user_text = (
            "✅ Заявка оформлена!\n\n"
            f"📦 Заказ №{order_id}\n"
            "💰 Деньги поступят в течение 24 часов."
        )

    else:
        user_text = (
            "✅ Заказ оформлен!\n\n"
            f"📦 Заказ №{order_id}\n"
            "Заказ будет обработан в течение 24 часов."
        )

    try:
        await callback.bot.send_message(
            telegram_id,
            user_text,
            reply_markup=main_menu()
        )
    except Exception:
        pass

    await callback.answer(
        "Заказ подтверждён."
    )


# ============================================================
# ADMIN REJECT
# ============================================================

@dp.callback_query(F.data.startswith("admin_reject_"))
async def admin_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "❌ Нет доступа.",
            show_alert=True
        )
        return

    try:
        order_id = int(
            callback.data.replace("admin_reject_", "")
        )
    except ValueError:
        await callback.answer(
            "Ошибка заказа.",
            show_alert=True
        )
        return

    pending_orders = await get_pending_orders()

    target_order = None

    for row in pending_orders:
        if row[0] == order_id:
            target_order = row
            break

    if not target_order:
        await callback.answer(
            "Заказ уже обработан или не найден.",
            show_alert=True
        )
        return

    telegram_id = target_order[1]

    await set_order_status(
        order_id,
        "REJECTED"
    )

    await callback.message.edit_text(
        callback.message.text
        + "\n\n❌ Заказ отклонён."
    )

    try:
        await callback.bot.send_message(
            telegram_id,
            f"❌ Заказ №{order_id} отклонён.\n\n"
            "Если у вас есть вопросы, обратитесь "
            "в поддержку.",
            reply_markup=main_menu()
        )
    except Exception:
        pass

    await callback.answer(
        "Заказ отклонён."
    )


# ============================================================
# ADMIN PANEL
# ============================================================

@dp.message(F.text == "/admin")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(
            "❌ У вас нет доступа."
        )
        return

    rows = await get_pending_orders()

    if not rows:
        await message.answer(
            "🛠 Админ-панель\n\n"
            "Ожидающих заказов нет."
        )
        return

    await message.answer(
        f"🛠 Админ-панель\n\n"
        f"Ожидающих заказов: {len(rows)}"
    )

    for row in rows:
        (
            order_id,
            telegram_id,
            username,
            order_type,
            amount,
            price,
            status,
            created_at
        ) = row

        if order_type == "BUY_STARS":
            title = "⭐️ Покупка Stars"
        elif order_type == "SELL_STARS":
            title = "💰 Продажа Stars"
        elif order_type == "PREMIUM":
            title = "💎 Premium"
        else:
            title = order_type

        text = (
            f"📦 Заказ №{order_id}\n\n"
            f"📌 {title}\n"
            f"📊 {amount}\n"
            f"💵 {price:.2f}$\n\n"
            f"👤 {username}\n"
            f"🆔 {telegram_id}\n"
            f"⏳ {status}"
        )

        await message.answer(
            text,
            reply_markup=admin_order_keyboard(order_id)
        )


# ============================================================
# MAIN
# ============================================================

async def main():
    await init_db()

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не установлен в Railway Variables"
        )

    bot = Bot(
        token=BOT_TOKEN
    )

    print("Starzo запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
