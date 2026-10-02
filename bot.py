import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, ADMIN_ID, SUPPORT_USERNAME
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
)

dp = Dispatcher()


# =========================================================
# STATES
# =========================================================

class BuyStarsState(StatesGroup):
    waiting_amount = State()


class SellStarsState(StatesGroup):
    waiting_amount = State()
    waiting_purchase_screenshot = State()
    waiting_bank = State()
    waiting_qr = State()


class PremiumState(StatesGroup):
    waiting_friend_username = State()


# =========================================================
# HELPERS
# =========================================================

def usd_to_kgs(amount: float) -> float:
    return amount * USD_TO_KGS


def format_user(user) -> str:
    if user.username:
        return f"@{user.username}"
    return "без username"


def greeting_text(user) -> str:
    if user.username:
        return (
            f"👋 Добро пожаловать, @{user.username}!\n\n"
            "У нас Вы можете приобрести Telegram Stars и Telegram Premium.\n\n"
            "Выберите действие:"
        )

    return (
        "👋 Добро пожаловать!\n\n"
        "У нас Вы можете приобрести Telegram Stars и Telegram Premium.\n\n"
        "Выберите действие:"
    )


def main_menu():
    kb = InlineKeyboardBuilder()

    kb.button(text="⭐️ Купить Stars", callback_data="buy_stars")
    kb.button(text="💰 Продать Stars", callback_data="sell_stars")
    kb.button(text="💎 Premium", callback_data="premium")
    kb.button(text="📦 Мои заказы", callback_data="orders")
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="💬 Поддержка", callback_data="support")

    kb.adjust(1)

    return kb.as_markup()


def back_button():
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад", callback_data="back_main")
    return kb.as_markup()


def return_shop_button():
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🛍 Вернуться в магазин",
        callback_data="back_shop"
    )
    return kb.as_markup()


def payment_keyboard(order_id: int):
    kb = InlineKeyboardBuilder()

    kb.button(
        text="✅ Я оплатил",
        callback_data=f"paid_{order_id}"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(1)

    return kb.as_markup()


def stars_amount_keyboard(prefix: str):
    kb = InlineKeyboardBuilder()

    kb.button(text="⭐️ 100 Stars", callback_data=f"{prefix}_100")
    kb.button(text="⭐️ 500 Stars", callback_data=f"{prefix}_500")
    kb.button(text="⭐️ 1000 Stars", callback_data=f"{prefix}_1000")
    kb.button(text="⭐️ 2000 Stars", callback_data=f"{prefix}_2000")
    kb.button(text="✏️ Другое количество", callback_data=f"{prefix}_custom")
    kb.button(text="◀️ Назад", callback_data="back_main")

    kb.adjust(2, 2, 1, 1)

    return kb.as_markup()


def bank_keyboard():
    kb = InlineKeyboardBuilder()

    kb.button(
        text="🏦 MBank",
        callback_data="sell_bank_mbank"
    )

    kb.button(
        text="🏦 Optima 24",
        callback_data="sell_bank_optima"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(2, 1)

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

    kb.adjust(2)

    return kb.as_markup()


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        greeting_text(message.from_user),
        reply_markup=main_menu()
    )


# =========================================================
# BACK TO SHOP
# =========================================================

@dp.callback_query(F.data == "back_shop")
async def back_shop_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    await callback.message.edit_text(
        greeting_text(callback.from_user),
        reply_markup=main_menu()
    )

    await callback.answer()


@dp.callback_query(F.data == "back_main")
async def back_main_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    await callback.message.edit_text(
        greeting_text(callback.from_user),
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================================================
# BUY STARS
# =========================================================

@dp.callback_query(F.data == "buy_stars")
async def buy_stars_start(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    if not callback.from_user.username:
        await callback.message.edit_text(
            "❌ Для покупки Stars необходимо установить "
            "username в Telegram.\n\n"
            "Установите username и снова откройте магазин.",
            reply_markup=back_button()
        )
        await callback.answer()
        return

    buy_kgs = usd_to_kgs(STARS_BUY_RATE_USD)

    await callback.message.edit_text(
        "⭐️ Покупка Stars\n\n"
        f"Курс: 100 ⭐️ = ${STARS_BUY_RATE_USD:.2f}\n"
        f"100 ⭐️ = {buy_kgs:.2f} сом\n\n"
        f"Минимальная покупка — {MIN_STARS} ⭐️\n\n"
        "Выберите количество:",
        reply_markup=stars_amount_keyboard("buy_amount")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("buy_amount_"))
async def buy_amount_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    value = callback.data.replace("buy_amount_", "")

    if value == "custom":
        await state.set_state(BuyStarsState.waiting_amount)

        await callback.message.edit_text(
            f"✏️ Введите количество Stars.\n\n"
            f"Минимум: {MIN_STARS} ⭐️",
            reply_markup=back_button()
        )

        await callback.answer()
        return

    try:
        amount = int(value)
    except ValueError:
        await callback.answer("Ошибка количества", show_alert=True)
        return

    await create_buy_order(callback.message, callback.from_user, amount)


@dp.message(BuyStarsState.waiting_amount)
async def buy_custom_amount(
    message: Message,
    state: FSMContext
):
    try:
        amount = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer(
            "❌ Введите количество Stars числом.",
            reply_markup=back_button()
        )
        return

    if amount < MIN_STARS:
        await message.answer(
            f"❌ Минимальная покупка — {MIN_STARS} ⭐️.",
            reply_markup=back_button()
        )
        return

    await state.clear()

    await create_buy_order(
        message,
        message.from_user,
        amount
    )


async def create_buy_order(
    message: Message,
    user,
    amount: int
):
    if not user.username:
        await message.answer(
            "❌ Для покупки Stars необходимо установить "
            "username в Telegram.",
            reply_markup=back_button()
        )
        return

    price_usd = (amount / 100) * STARS_BUY_RATE_USD
    price_kgs = usd_to_kgs(price_usd)

    order_id = await create_order(
        telegram_id=user.id,
        username=user.username,
        order_type="BUY_STARS",
        amount=str(amount),
        price=price_usd
    )

    await message.answer(
        "💳 Этап оплаты\n\n"
        f"📦 Заказ №{order_id}\n"
        f"⭐️ Stars: {amount}\n"
        f"💵 К оплате: ${price_usd:.2f}\n"
        f"🇰🇬 К оплате: {price_kgs:.2f} сом\n\n"
        "Реквизиты для оплаты будут добавлены позже.\n\n"
        "После оплаты нажмите кнопку «Я оплатил».\n\n"
        "⚠️ Оплачивать необходимо полную сумму.\n"
        "⚠️ Возврат денежных средств не производится. "
        "Будьте внимательны.",
        reply_markup=payment_keyboard(order_id)
    )

    await notify_admin_new_order(
        order_id=order_id,
        user=user,
        order_type="⭐️ Покупка Stars",
        amount=f"{amount} ⭐️",
        price_usd=price_usd,
        price_kgs=price_kgs
    )


# =========================================================
# SELL STARS
# =========================================================

@dp.callback_query(F.data == "sell_stars")
async def sell_stars_start(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    sell_kgs = usd_to_kgs(STARS_SELL_RATE_USD)

    await callback.message.edit_text(
        "💰 Продажа Stars\n\n"
        f"Курс: 100 ⭐️ = ${STARS_SELL_RATE_USD:.2f}\n"
        f"100 ⭐️ = {sell_kgs:.2f} сом\n\n"
        f"Минимум — {MIN_STARS} ⭐️\n\n"
        "⚠️ Перед продажей необходимо отправить "
        "скриншот, где видно, откуда были куплены Stars.\n\n"
        "Покупки через Fragment принимаются.\n"
        "Stars, купленные напрямую через Telegram, "
        "могут иметь повышенный риск возврата.",
        reply_markup=stars_amount_keyboard("sell_amount")
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("sell_amount_"))
async def sell_amount_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    value = callback.data.replace("sell_amount_", "")

    if value == "custom":
        await state.set_state(SellStarsState.waiting_amount)

        await callback.message.edit_text(
            f"✏️ Введите количество Stars для продажи.\n\n"
            f"Минимум: {MIN_STARS} ⭐️",
            reply_markup=back_button()
        )

        await callback.answer()
        return

    try:
        amount = int(value)
    except ValueError:
        await callback.answer("Ошибка количества", show_alert=True)
        return

    await state.update_data(amount=amount)
    await state.set_state(
        SellStarsState.waiting_purchase_screenshot
    )

    await callback.message.edit_text(
        "📸 Отправьте скриншот покупки Stars.\n\n"
        "На скриншоте должно быть видно, где были приобретены Stars.\n\n"
        "Отправьте именно фотографию.",
        reply_markup=back_button()
    )

    await callback.answer()


@dp.message(SellStarsState.waiting_amount)
async def sell_custom_amount(
    message: Message,
    state: FSMContext
):
    try:
        amount = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer(
            "❌ Введите количество Stars числом.",
            reply_markup=back_button()
        )
        return

    if amount < MIN_STARS:
        await message.answer(
            f"❌ Минимальная продажа — {MIN_STARS} ⭐️.",
            reply_markup=back_button()
        )
        return

    await state.update_data(amount=amount)
    await state.set_state(
        SellStarsState.waiting_purchase_screenshot
    )

    await message.answer(
        "📸 Теперь отправьте скриншот покупки Stars.\n\n"
        "На нём должно быть видно, где были приобретены Stars.\n\n"
        "Отправьте именно фотографию.",
        reply_markup=back_button()
    )


@dp.message(SellStarsState.waiting_purchase_screenshot)
async def sell_purchase_screenshot(
    message: Message,
    state: FSMContext
):
    if not message.photo:
        await message.answer(
            "❌ Отправьте скриншот именно фотографией."
        )
        return

    photo_id = message.photo[-1].file_id

    await state.update_data(
        purchase_screenshot=photo_id
    )

    await state.set_state(
        SellStarsState.waiting_bank
    )

    await message.answer(
        "🏦 Выберите банк для получения выплаты:\n\n"
        "После выбора банка вам нужно будет отправить "
        "только QR-код.",
        reply_markup=bank_keyboard()
    )


@dp.callback_query(
    F.data.in_(
        {"sell_bank_mbank", "sell_bank_optima"}
    )
)
async def sell_bank_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    data = await state.get_data()

    amount = data.get("amount")
    screenshot = data.get("purchase_screenshot")

    if not amount or not screenshot:
        await state.clear()

        await callback.message.edit_text(
            "❌ Сессия продажи устарела.\n\n"
            "Начните продажу Stars заново.",
            reply_markup=main_menu()
        )

        await callback.answer()
        return

    if callback.data == "sell_bank_mbank":
        bank = "MBank"
    else:
        bank = "Optima 24"

    await state.update_data(bank=bank)
    await state.set_state(SellStarsState.waiting_qr)

    await callback.message.edit_text(
        f"🏦 Вы выбрали: {bank}\n\n"
        "📲 Теперь отправьте только QR-код "
        "для получения выплаты.\n\n"
        "⚠️ Не отправляйте номер карты, пароль, "
        "код из SMS или другие данные.\n\n"
        "Нужен только QR-код фотографией.",
        reply_markup=back_button()
    )

    await callback.answer()


@dp.message(SellStarsState.waiting_qr)
async def sell_qr_handler(
    message: Message,
    state: FSMContext
):
    if not message.photo:
        await message.answer(
            "❌ Отправьте QR-код именно фотографией.\n\n"
            "Нужен только QR-код."
        )
        return

    data = await state.get_data()

    amount = data.get("amount")
    bank = data.get("bank")
    purchase_screenshot = data.get("purchase_screenshot")

    if not amount or not bank or not purchase_screenshot:
        await state.clear()

        await message.answer(
            "❌ Не удалось восстановить данные заявки.\n\n"
            "Начните продажу Stars заново.",
            reply_markup=main_menu()
        )
        return

    qr_photo = message.photo[-1].file_id

    price_usd = (amount / 100) * STARS_SELL_RATE_USD
    price_kgs = usd_to_kgs(price_usd)

    order_id = await create_order(
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        order_type="SELL_STARS",
        amount=f"{amount}|{bank}",
        price=price_usd
    )

    await state.clear()

    await message.answer(
        "✅ Заявка оформлена!\n\n"
        f"📦 Заказ №{order_id}\n"
        f"⭐️ Stars: {amount}\n"
        f"🏦 Банк: {bank}\n"
        f"💰 Выплата: {price_kgs:.2f} сом\n\n"
        "Заявка отправлена на проверку.\n"
        "После подтверждения деньги будут отправлены "
        "в течение 24 часов.",
        reply_markup=return_shop_button()
    )

    await notify_admin_sell_order(
        order_id=order_id,
        user=message.from_user,
        amount=amount,
        bank=bank,
        price_usd=price_usd,
        price_kgs=price_kgs,
        purchase_screenshot=purchase_screenshot,
        qr_photo=qr_photo
    )


# =========================================================
# PREMIUM
# =========================================================

@dp.callback_query(F.data == "premium")
async def premium_start(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    if not callback.from_user.username:
        await callback.message.edit_text(
            "❌ Для покупки Premium необходимо установить "
            "username в Telegram.",
            reply_markup=back_button()
        )
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()

    kb.button(
        text="👤 Для себя",
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
        "💎 Telegram Premium\n\n"
        "Для кого хотите приобрести Premium?",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data == "premium_self")
async def premium_self(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()
    await state.update_data(recipient="self")

    await show_premium_periods(
        callback.message
    )

    await callback.answer()


@dp.callback_query(F.data == "premium_friend")
async def premium_friend(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()
    await state.update_data(recipient="friend")

    await state.set_state(
        PremiumState.waiting_friend_username
    )

    await callback.message.edit_text(
        "👥 Покупка Premium для друга\n\n"
        "Введите username получателя.\n\n"
        "Например: @username",
        reply_markup=back_button()
    )

    await callback.answer()


@dp.message(PremiumState.waiting_friend_username)
async def premium_friend_username(
    message: Message,
    state: FSMContext
):
    username = message.text.strip()

    if username.startswith("@"):
        username = username[1:]

    if not username:
        await message.answer(
            "❌ Введите корректный username.",
            reply_markup=back_button()
        )
        return

    if " " in username:
        await message.answer(
            "❌ Username должен быть без пробелов.",
            reply_markup=back_button()
        )
        return

    await state.update_data(
        friend_username=username
    )

    await state.clear()

    await state.update_data(
        recipient="friend",
        friend_username=username
    )

    await show_premium_periods(message)


async def show_premium_periods(message: Message):
    kb = InlineKeyboardBuilder()

    price_3 = PREMIUM_PRICES_USD["3"]
    price_6 = PREMIUM_PRICES_USD["6"]
    price_12 = PREMIUM_PRICES_USD["12"]

    kb.button(
        text=f"3 месяца — {usd_to_kgs(price_3):.2f} сом",
        callback_data="premium_3"
    )

    kb.button(
        text=f"6 месяцев — {usd_to_kgs(price_6):.2f} сом",
        callback_data="premium_6"
    )

    kb.button(
        text=f"12 месяцев — {usd_to_kgs(price_12):.2f} сом",
        callback_data="premium_12"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(1)

    await message.edit_text(
        "💎 Выберите срок Premium:\n\n"
        f"3 месяца — ${price_3:.2f} / "
        f"{usd_to_kgs(price_3):.2f} сом\n"
        f"6 месяцев — ${price_6:.2f} / "
        f"{usd_to_kgs(price_6):.2f} сом\n"
        f"12 месяцев — ${price_12:.2f} / "
        f"{usd_to_kgs(price_12):.2f} сом",
        reply_markup=kb.as_markup()
    )


@dp.callback_query(F.data.startswith("premium_"))
async def premium_period(
    callback: CallbackQuery,
    state: FSMContext
):
    period = callback.data.replace("premium_", "")

    if period not in PREMIUM_PRICES_USD:
        await callback.answer(
            "Ошибка срока",
            show_alert=True
        )
        return

    price_usd = PREMIUM_PRICES_USD[period]
    price_kgs = usd_to_kgs(price_usd)

    data = await state.get_data()

    recipient = data.get("recipient", "self")
    friend_username = data.get("friend_username")

    if recipient == "friend" and not friend_username:
        await state.clear()

        await callback.message.edit_text(
            "❌ Не указан username получателя.\n\n"
            "Начните покупку Premium заново.",
            reply_markup=main_menu()
        )

        await callback.answer()
        return

    if recipient == "friend":
        recipient_text = f"👥 Получатель: @{friend_username}"
        amount_text = f"{period} месяцев | @{friend_username}"
    else:
        recipient_text = "👤 Получатель: вы"
        amount_text = f"{period} месяцев | себе"

    order_id = await create_order(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username or "",
        order_type="PREMIUM",
        amount=amount_text,
        price=price_usd
    )

    await state.clear()

    await callback.message.edit_text(
        "💳 Этап оплаты\n\n"
        f"📦 Заказ №{order_id}\n"
        f"💎 Premium: {period} месяцев\n"
        f"{recipient_text}\n"
        f"💵 К оплате: ${price_usd:.2f}\n"
        f"🇰🇬 К оплате: {price_kgs:.2f} сом\n\n"
        "Реквизиты для оплаты будут добавлены позже.\n\n"
        "После оплаты нажмите кнопку «Я оплатил».\n\n"
        "⚠️ Оплачивать необходимо полную сумму.\n"
        "⚠️ Возврат денежных средств не производится. "
        "Будьте внимательны.",
        reply_markup=payment_keyboard(order_id)
    )

    await notify_admin_new_order(
        order_id=order_id,
        user=callback.from_user,
        order_type="💎 Premium",
        amount=f"{period} месяцев",
        price_usd=price_usd,
        price_kgs=price_kgs
    )

    await callback.answer()


# =========================================================
# PAID BUTTON
# =========================================================

@dp.callback_query(F.data.startswith("paid_"))
async def paid_order(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    try:
        order_id = int(
            callback.data.replace("paid_", "")
        )
    except ValueError:
        await callback.answer(
            "Ошибка заказа",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        f"⏳ Оплата по заказу №{order_id} "
        "отправлена на проверку.\n\n"
        "Ожидайте подтверждения администратора.",
        reply_markup=back_button()
    )

    await notify_admin_paid(
        order_id,
        callback.from_user
    )

    await callback.answer(
        "Оплата отправлена на проверку."
    )


# =========================================================
# ORDERS
# =========================================================

@dp.callback_query(F.data == "orders")
async def orders_handler(
    callback: CallbackQuery
):
    orders = await get_user_orders(
        callback.from_user.id
    )

    if not orders:
        await callback.message.edit_text(
            "📦 Мои заказы\n\n"
            "У вас пока нет заказов.",
            reply_markup=back_button()
        )

        await callback.answer()
        return

    status_names = {
        "WAITING_PAYMENT": "⏳ Ожидает оплаты",
        "PROCESSING": "🔄 В обработке",
        "COMPLETED": "✅ Выполнен",
        "REJECTED": "❌ Отклонён",
    }

    lines = ["📦 Мои заказы\n"]

    for order in orders[:20]:
        (
            order_id,
            order_type,
            amount,
            price,
            status,
            created_at
        ) = order

        status_text = status_names.get(
            status,
            status
        )

        lines.append(
            f"📦 Заказ №{order_id}\n"
            f"📌 {order_type}\n"
            f"📊 {amount}\n"
            f"💵 ${price:.2f}\n"
            f"📍 {status_text}\n"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_button()
    )

    await callback.answer()


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(F.data == "profile")
async def profile_handler(
    callback: CallbackQuery
):
    orders = await get_user_orders(
        callback.from_user.id
    )

    username = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else "Не установлен"
    )

    await callback.message.edit_text(
        "👤 Профиль\n\n"
        f"Username: {username}\n"
        f"Telegram ID: {callback.from_user.id}\n"
        f"📦 Заказов: {len(orders)}",
        reply_markup=back_button()
    )

    await callback.answer()


# =========================================================
# SUPPORT
# =========================================================

@dp.callback_query(F.data == "support")
async def support_handler(
    callback: CallbackQuery
):
    username = SUPPORT_USERNAME.lstrip("@")

    kb = InlineKeyboardBuilder()

    kb.button(
        text="💬 Написать в поддержку",
        url=f"https://t.me/{username}"
    )

    kb.button(
        text="◀️ Назад",
        callback_data="back_main"
    )

    kb.adjust(1)

    await callback.message.edit_text(
        "💬 Поддержка\n\n"
        "Если у вас возникли вопросы по заказу, "
        "оплате или продаже Stars — обратитесь "
        "в поддержку.",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


# =========================================================
# ADMIN — NEW ORDER
# =========================================================

async def notify_admin_new_order(
    order_id: int,
    user,
    order_type: str,
    amount: str,
    price_usd: float,
    price_kgs: float
):
    if not ADMIN_ID:
        return

    text = (
        "🆕 НОВЫЙ ЗАКАЗ\n\n"
        f"📦 Заказ №{order_id}\n"
        f"📌 Тип: {order_type}\n"
        f"📊 Количество: {amount}\n"
        f"💵 USD: ${price_usd:.2f}\n"
        f"🇰🇬 KGS: {price_kgs:.2f} сом\n"
        f"👤 Username: {format_user(user)}\n"
        f"🆔 Telegram ID: {user.id}\n\n"
        "📌 Статус: ожидает оплаты"
    )

    try:
        bot = dp.workflow_data.get("bot")

        if bot is None:
            return

        await bot.send_message(
            ADMIN_ID,
            text
        )

    except Exception as e:
        print(
            f"ADMIN NEW ORDER ERROR: {e}"
        )


# =========================================================
# ADMIN — USER PAID
# =========================================================

async def notify_admin_paid(
    order_id: int,
    user
):
    if not ADMIN_ID:
        return

    try:
        bot = dp.workflow_data.get("bot")

        if bot is None:
            return

        await bot.send_message(
            ADMIN_ID,
            "💳 ПОЛЬЗОВАТЕЛЬ НАЖАЛ «Я ОПЛАТИЛ»\n\n"
            f"📦 Заказ №{order_id}\n"
            f"👤 Username: {format_user(user)}\n"
            f"🆔 Telegram ID: {user.id}\n\n"
            "Проверьте оплату и выберите действие:",
            reply_markup=admin_order_keyboard(order_id)
        )

    except Exception as e:
        print(
            f"ADMIN PAID ERROR: {e}"
        )


# =========================================================
# ADMIN — SELL ORDER
# =========================================================

async def notify_admin_sell_order(
    order_id: int,
    user,
    amount: int,
    bank: str,
    price_usd: float,
    price_kgs: float,
    purchase_screenshot: str,
    qr_photo: str
):
    if not ADMIN_ID:
        return

    try:
        bot = dp.workflow_data.get("bot")

        if bot is None:
            return

        text = (
            "💰 НОВАЯ ЗАЯВКА НА ПРОДАЖУ STARS\n\n"
            f"📦 Заказ №{order_id}\n"
            f"⭐️ Stars: {amount}\n"
            f"🏦 Банк: {bank}\n"
            f"💵 Выплата: ${price_usd:.2f}\n"
            f"🇰🇬 Выплата: {price_kgs:.2f} сом\n"
            f"👤 Username: {format_user(user)}\n"
            f"🆔 Telegram ID: {user.id}\n\n"
            "📸 Ниже будут скриншот покупки и QR-код."
        )

        await bot.send_message(
            ADMIN_ID,
            text
        )

        await bot.send_photo(
            ADMIN_ID,
            purchase_screenshot,
            caption=f"📸 Скриншот покупки — заказ №{order_id}"
        )

        await bot.send_photo(
            ADMIN_ID,
            qr_photo,
            caption=(
                f"📲 QR для выплаты — заказ №{order_id}"
            ),
            reply_markup=admin_order_keyboard(order_id)
        )

    except Exception as e:
        print(
            f"ADMIN SELL ERROR: {e}"
        )


# =========================================================
# ADMIN PANEL
# =========================================================

@dp.message(Command("admin"))
async def admin_panel(
    message: Message
):
    if message.from_user.id != ADMIN_ID:
        await message.answer(
            "❌ Доступ запрещён."
        )
        return

    orders = await get_pending_orders()

    if not orders:
        await message.answer(
            "🛠 Админ-панель\n\n"
            "Нет ожидающих заказов."
        )
        return

    await message.answer(
        f"🛠 Админ-панель\n\n"
        f"Ожидающих заказов: {len(orders)}"
    )

    for order in orders:
        (
            order_id,
            telegram_id,
            username,
            order_type,
            amount,
            price,
            status,
            created_at
        ) = order

        price_kgs = usd_to_kgs(price)

        text = (
            "📦 ОЖИДАЕТ ПРОВЕРКИ\n\n"
            f"Заказ №{order_id}\n"
            f"Тип: {order_type}\n"
            f"Количество: {amount}\n"
            f"USD: ${price:.2f}\n"
            f"KGS: {price_kgs:.2f} сом\n"
            f"Username: @{username if username else 'без username'}\n"
            f"Telegram ID: {telegram_id}\n"
            f"Статус: {status}"
        )

        await message.answer(
            text,
            reply_markup=admin_order_keyboard(order_id)
        )


# =========================================================
# ADMIN — CONFIRM
# =========================================================

@dp.callback_query(F.data.startswith("admin_done_"))
async def admin_done(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "❌ Доступ запрещён.",
            show_alert=True
        )
        return

    try:
        order_id = int(
            callback.data.replace(
                "admin_done_",
                ""
            )
        )
    except ValueError:
        await callback.answer(
            "Ошибка заказа.",
            show_alert=True
        )
        return

    pending_orders = await get_pending_orders()

    order = None

    for item in pending_orders:
        if item[0] == order_id:
            order = item
            break

    if order is None:
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
    ) = order

    await set_order_status(
        order_id,
        "COMPLETED"
    )

    await callback.message.edit_text(
        "✅ Заказ отмечен как выполненный.\n\n"
        f"📦 Заказ №{order_id}"
    )

    bot = dp.workflow_data.get("bot")

    if bot is not None:
        if order_type == "BUY_STARS":
            user_text = (
                "✅ Заказ выполнен!\n\n"
                f"📦 Заказ №{order_id}\n"
                f"⭐️ Stars: {amount}\n\n"
                "Stars поступят в течение 24 часов."
            )

        elif order_type == "PREMIUM":
            user_text = (
                "✅ Заказ выполнен!\n\n"
                f"📦 Заказ №{order_id}\n"
                f"💎 Premium: {amount}\n\n"
                "Premium поступит в течение 24 часов."
            )

        elif order_type == "SELL_STARS":
            user_text = (
                "✅ Заявка выполнена!\n\n"
                f"📦 Заказ №{order_id}\n\n"
                "💰 Деньги поступят в течение 24 часов."
            )

        else:
            user_text = (
                "✅ Заказ выполнен!\n\n"
                f"📦 Заказ №{order_id}"
            )

        try:
            await bot.send_message(
                telegram_id,
                user_text,
                reply_markup=return_shop_button()
            )
        except Exception as e:
            print(
                f"USER CONFIRM MESSAGE ERROR: {e}"
            )

    await callback.answer(
        "Заказ подтверждён."
    )


# =========================================================
# ADMIN — REJECT
# =========================================================

@dp.callback_query(F.data.startswith("admin_reject_"))
async def admin_reject(
    callback: CallbackQuery
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "❌ Доступ запрещён.",
            show_alert=True
        )
        return

    try:
        order_id = int(
            callback.data.replace(
                "admin_reject_",
                ""
            )
        )
    except ValueError:
        await callback.answer(
            "Ошибка заказа.",
            show_alert=True
        )
        return

    pending_orders = await get_pending_orders()

    order = None

    for item in pending_orders:
        if item[0] == order_id:
            order = item
            break

    if order is None:
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
    ) = order

    await set_order_status(
        order_id,
        "REJECTED"
    )

    await callback.message.edit_text(
        "❌ Заказ отклонён.\n\n"
        f"📦 Заказ №{order_id}"
    )

    bot = dp.workflow_data.get("bot")

    if bot is not None:
        try:
            await bot.send_message(
                telegram_id,
                "❌ Заказ отклонён.\n\n"
                f"📦 Заказ №{order_id}\n\n"
                "Если вы считаете, что произошла ошибка, "
                "обратитесь в поддержку.",
                reply_markup=return_shop_button()
            )
        except Exception as e:
            print(
                f"USER REJECT MESSAGE ERROR: {e}"
            )

    await callback.answer(
        "Заказ отклонён."
    )


# =========================================================
# MAIN
# =========================================================

async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не найден в переменных окружения."
        )

    if not ADMIN_ID:
        raise RuntimeError(
            "ADMIN_ID не найден или равен 0."
        )

    bot = Bot(token=BOT_TOKEN)

    dp.workflow_data["bot"] = bot

    await init_db()

    print("Bot started")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
