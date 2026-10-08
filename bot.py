import asyncio
import logging
from decimal import Decimal, InvalidOperation

import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from config import (
    BOT_TOKEN,
    CRYPTO_PAY_TOKEN,
    SUPPORT_USERNAME,
    ADMIN_ID,
)

from settings import (
    USD_TO_KGS,
    STARS_BUY_RATE_USD,
    MIN_STARS,
    PREMIUM_PRICES_USD,
    SHOP_NAME,
    PAYMENT_CURRENCY,
)

from database import (
    init_db,
    create_order,
    set_crypto_invoice,
    get_order,
    get_user_orders,
    get_waiting_payment_orders,
    get_pending_admin_orders,
    set_order_status,
)


logging.basicConfig(level=logging.INFO)


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не указан")

if not CRYPTO_PAY_TOKEN:
    raise RuntimeError("CRYPTO_PAY_TOKEN не указан")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID не указан")


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    ),
)

dp = Dispatcher()


# =========================================================
# STATES
# =========================================================

class BuyStarsState(StatesGroup):
    waiting_amount = State()


class PremiumState(StatesGroup):
    waiting_friend_username = State()


# =========================================================
# HELPERS
# =========================================================

def usd_to_kgs(amount: float) -> float:
    return round(amount * USD_TO_KGS, 2)


def format_usd(amount: float) -> str:
    return f"{amount:.2f}$"


def format_kgs(amount: float) -> str:
    return f"{usd_to_kgs(amount):.2f} сом"


def username_text(message: Message) -> str:
    if message.from_user.username:
        return f"@{message.from_user.username}"

    return message.from_user.full_name or "Пользователь"


def normalize_username(value: str) -> str:
    value = value.strip()

    if not value:
        return ""

    if not value.startswith("@"):
        value = "@" + value

    return value


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⭐️ Купить Stars"),
                KeyboardButton(text="💰 Продать Stars"),
            ],
            [
                KeyboardButton(text="💎 Premium"),
                KeyboardButton(text="📦 Мои заказы"),
            ],
            [
                KeyboardButton(text="👤 Профиль"),
                KeyboardButton(text="💬 Поддержка"),
            ],
        ],
        resize_keyboard=True,
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main",
                )
            ]
        ]
    )


def buy_stars_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="100 ⭐️",
                    callback_data="buy_100",
                ),
                InlineKeyboardButton(
                    text="500 ⭐️",
                    callback_data="buy_500",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="1000 ⭐️",
                    callback_data="buy_1000",
                ),
                InlineKeyboardButton(
                    text="2000 ⭐️",
                    callback_data="buy_2000",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Другое количество",
                    callback_data="buy_custom",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main",
                )
            ],
        ]
    )


def premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="3 месяца — $12.99",
                    callback_data="premium_3",
                )
            ],
            [
                InlineKeyboardButton(
                    text="6 месяцев — $17.99",
                    callback_data="premium_6",
                )
            ],
            [
                InlineKeyboardButton(
                    text="12 месяцев — $30.00",
                    callback_data="premium_12",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="back_main",
                )
            ],
        ]
    )


def premium_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Себе",
                    callback_data="premium_self",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Другому пользователю",
                    callback_data="premium_friend",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="premium_back",
                )
            ],
        ]
    )


def payment_keyboard(order_id: int, invoice_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Оплатить через Crypto Bot",
                    url=invoice_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Проверить оплату",
                    callback_data=f"check_payment:{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ В магазин",
                    callback_data="back_main",
                )
            ],
        ]
    )


def admin_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выполнено",
                    callback_data=f"admin_complete:{order_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"admin_reject:{order_id}",
                ),
            ]
        ]
    )


# =========================================================
# CRYPTO PAY API
# =========================================================

CRYPTO_API_URL = "https://pay.crypt.bot/api"


async def crypto_api(
    method: str,
    data: dict | None = None,
):
    headers = {
        "Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN,
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.post(
            f"{CRYPTO_API_URL}/{method}",
            headers=headers,
            json=data or {},
        ) as response:

            result = await response.json()

            if not result.get("ok"):
                raise RuntimeError(
                    result.get("error", "Crypto Pay API error")
                )

            return result.get("result")


async def create_crypto_invoice(
    amount_usd: float,
    description: str,
):
    result = await crypto_api(
        "createInvoice",
        {
            "currency_type": "fiat",
            "fiat": "USD",
            "amount": f"{amount_usd:.2f}",
            "description": description,
            "paid_btn_name": "callback",
            "paid_btn_url": "https://t.me/",
        },
    )

    return {
        "id": str(result["invoice_id"]),
        "url": result["bot_invoice_url"],
    }


async def get_crypto_invoice(invoice_id: str):
    result = await crypto_api(
        "getInvoices",
        {
            "invoice_ids": invoice_id,
        },
    )

    items = result.get("items", [])

    if not items:
        return None

    return items[0]


# =========================================================
# TEXTS
# =========================================================

def welcome_text(message: Message) -> str:
    if message.from_user.username:
        name = f"@{message.from_user.username}"
    else:
        name = message.from_user.first_name or "Пользователь"

    return (
        f"👋 <b>Добро пожаловать, {name}!</b>\n\n"
        "У нас Вы можете приобрести "
        "<b>Telegram Stars</b>, "
        "<b>Telegram Premium</b>.\n\n"
        "Выберите нужное действие ниже."
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await message.answer(
        welcome_text(message),
        reply_markup=main_menu(),
    )


# =========================================================
# BUY STARS
# =========================================================

@dp.message(F.text == "⭐️ Купить Stars")
async def buy_stars(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    if not message.from_user.username:
        await message.answer(
            "⚠️ <b>Для покупки Stars нужен Telegram username.</b>\n\n"
            "Установите username в настройках Telegram и "
            "после этого снова нажмите «⭐️ Купить Stars».",
            reply_markup=main_menu(),
        )
        return

    await message.answer(
        "⭐️ <b>Покупка Telegram Stars</b>\n\n"
        f"Цена: <b>100 Stars = {format_usd(STARS_BUY_RATE_USD)}</b>\n"
        f"Это примерно <b>{format_kgs(STARS_BUY_RATE_USD)}</b>.\n\n"
        f"Минимальная покупка — <b>{MIN_STARS} Stars</b>.\n\n"
        "Выберите количество:",
        reply_markup=buy_stars_keyboard(),
    )


async def process_buy_stars(
    message: Message,
    stars: int,
):
    if stars < MIN_STARS:
        await message.answer(
            f"⚠️ Минимальная покупка — {MIN_STARS} Stars."
        )
        return

    price = (stars / 100) * STARS_BUY_RATE_USD

    username = username_text(message)

    order_id = await create_order(
        telegram_id=message.from_user.id,
        username=username,
        order_type="STARS",
        amount=str(stars),
        price=price,
    )

    try:
        invoice = await create_crypto_invoice(
            amount_usd=price,
            description=f"Starzo — покупка {stars} Telegram Stars",
        )

    except Exception as e:
        logging.exception(e)

        await set_order_status(
            order_id,
            "PAYMENT_ERROR",
        )

        await message.answer(
            "❌ Не удалось создать счёт Crypto Bot.\n\n"
            "Попробуйте ещё раз позже."
        )
        return

    await set_crypto_invoice(
        order_id=order_id,
        invoice_id=invoice["id"],
        invoice_url=invoice["url"],
    )

    await message.answer(
        "⭐️ <b>Заказ создан</b>\n\n"
        f"Заказ №<b>{order_id}</b>\n"
        f"Количество: <b>{stars} Stars</b>\n"
        f"Стоимость: <b>{format_usd(price)}</b>\n"
        f"К оплате: <b>{format_kgs(price)}</b>\n\n"
        "Нажмите кнопку ниже и оплатите через Crypto Bot.\n\n"
        "После оплаты нажмите «🔄 Проверить оплату».",
        reply_markup=payment_keyboard(
            order_id,
            invoice["url"],
        ),
    )


@dp.callback_query(F.data.startswith("buy_"))
async def buy_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    action = callback.data

    await callback.answer()

    if action == "buy_custom":
        await state.set_state(
            BuyStarsState.waiting_amount
        )

        await callback.message.edit_text(
            "✏️ <b>Введите количество Stars</b>\n\n"
            f"Минимум: <b>{MIN_STARS}</b> Stars.\n"
            "Количество должно быть целым числом."
        )
        return

    try:
        stars = int(
            action.replace("buy_", "")
        )
    except ValueError:
        return

    await process_buy_stars(
        callback.message,
        stars,
    )


@dp.message(BuyStarsState.waiting_amount)
async def custom_stars_amount(
    message: Message,
    state: FSMContext,
):
    try:
        stars = int(
            message.text.strip()
        )
    except (ValueError, AttributeError):
        await message.answer(
            "❌ Введите количество Stars числом.\n\n"
            "Например: <b>300</b>"
        )
        return

    if stars < MIN_STARS:
        await message.answer(
            f"❌ Минимальная покупка — {MIN_STARS} Stars."
        )
        return

    await state.clear()

    await process_buy_stars(
        message,
        stars,
    )


# =========================================================
# PREMIUM
# =========================================================

@dp.message(F.text == "💎 Premium")
async def premium(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await message.answer(
        "💎 <b>Telegram Premium</b>\n\n"
        "Выберите срок подписки:",
        reply_markup=premium_keyboard(),
    )


@dp.callback_query(F.data.startswith("premium_"))
async def premium_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    action = callback.data

    if action == "premium_back":
        await callback.message.edit_text(
            "💎 <b>Telegram Premium</b>\n\n"
            "Выберите срок подписки:",
            reply_markup=premium_keyboard(),
        )
        return

    if action == "premium_self":
        await state.clear()

        await callback.message.edit_text(
            "👤 <b>Premium для себя</b>\n\n"
            "Сначала выберите срок подписки:",
            reply_markup=premium_keyboard(),
        )
        return

    if action == "premium_friend":
        await state.set_state(
            PremiumState.waiting_friend_username
        )

        await callback.message.edit_text(
            "👥 <b>Premium для другого пользователя</b>\n\n"
            "Введите Telegram username получателя.\n\n"
            "Например:\n"
            "<code>@username</code>"
        )
        return

    months = action.replace(
        "premium_",
        "",
    )

    if months not in PREMIUM_PRICES_USD:
        return

    price = PREMIUM_PRICES_USD[months]

    await state.update_data(
        premium_months=months,
        premium_price=price,
        premium_target="self",
    )

    await callback.message.edit_text(
        f"💎 <b>Premium на {months} месяцев</b>\n\n"
        f"Цена: <b>{format_usd(price)}</b>\n"
        f"В сомах: <b>{format_kgs(price)}</b>\n\n"
        "Для кого оформить?",
        reply_markup=premium_target_keyboard(),
    )


@dp.message(PremiumState.waiting_friend_username)
async def premium_friend_username(
    message: Message,
    state: FSMContext,
):
    target = normalize_username(
        message.text or ""
    )

    if len(target) < 2:
        await message.answer(
            "❌ Неверный username.\n\n"
            "Введите, например: <code>@username</code>"
        )
        return

    data = await state.get_data()

    months = data.get("premium_months")
    price = data.get("premium_price")

    if not months or not price:
        await state.clear()

        await message.answer(
            "❌ Сессия заказа устарела.\n"
            "Начните покупку Premium заново.",
            reply_markup=main_menu(),
        )
        return

    order_id = await create_order(
        telegram_id=message.from_user.id,
        username=target,
        order_type=f"PREMIUM_{months}",
        amount=target,
        price=float(price),
    )

    try:
        invoice = await create_crypto_invoice(
            amount_usd=float(price),
            description=(
                f"Starzo — Telegram Premium "
                f"{months} мес. для {target}"
            ),
        )

    except Exception as e:
        logging.exception(e)

        await set_order_status(
            order_id,
            "PAYMENT_ERROR",
        )

        await state.clear()

        await message.answer(
            "❌ Не удалось создать счёт Crypto Bot.",
            reply_markup=main_menu(),
        )
        return

    await set_crypto_invoice(
        order_id,
        invoice["id"],
        invoice["url"],
    )

    await state.clear()

    await message.answer(
        "💎 <b>Заказ Premium создан</b>\n\n"
        f"Заказ №<b>{order_id}</b>\n"
        f"Срок: <b>{months} месяцев</b>\n"
        f"Получатель: <b>{target}</b>\n"
        f"Стоимость: <b>{format_usd(float(price))}</b>\n"
        f"К оплате: <b>{format_kgs(float(price))}</b>\n\n"
        "Оплатите через Crypto Bot.\n"
        "После оплаты нажмите «🔄 Проверить оплату».",
        reply_markup=payment_keyboard(
            order_id,
            invoice["url"],
        ),
    )


# =========================================================
# SELL STARS
# =========================================================

@dp.message(F.text == "💰 Продать Stars")
async def sell_stars(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await message.answer(
        "🚧 <b>Продажа Stars в разработке, вернитесь позже.</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Вернуться в магазин",
                        callback_data="back_main",
                    )
                ]
            ]
        ),
    )


# =========================================================
# MY ORDERS
# =========================================================

@dp.message(F.text == "📦 Мои заказы")
async def my_orders(
    message: Message,
):
    orders = await get_user_orders(
        message.from_user.id
    )

    if not orders:
        await message.answer(
            "📦 <b>Мои заказы</b>\n\n"
            "У вас пока нет заказов.",
            reply_markup=main_menu(),
        )
        return

    text = "📦 <b>Мои заказы</b>\n\n"

    for order in orders[:20]:
        (
            order_id,
            order_type,
            amount,
            price,
            status,
            created_at,
        ) = order

        if order_type == "STARS":
            product = f"{amount} Stars"

        elif order_type.startswith("PREMIUM_"):
            months = order_type.replace(
                "PREMIUM_",
                "",
            )
            product = (
                f"Premium на {months} месяцев"
            )

        else:
            product = order_type

        status_text = {
            "WAITING_PAYMENT": "⏳ Ожидает оплаты",
            "PROCESSING": "🔄 В обработке",
            "COMPLETED": "✅ Выполнен",
            "REJECTED": "❌ Отклонён",
            "PAYMENT_ERROR": "⚠️ Ошибка оплаты",
        }.get(
            status,
            status,
        )

        text += (
            f"🧾 <b>Заказ №{order_id}</b>\n"
            f"Товар: {product}\n"
            f"Сумма: {format_usd(price)} "
            f"({format_kgs(price)})\n"
            f"Статус: {status_text}\n"
            f"Дата: {created_at}\n\n"
        )

    await message.answer(
        text,
        reply_markup=main_menu(),
    )


# =========================================================
# PROFILE
# =========================================================

@dp.message(F.text == "👤 Профиль")
async def profile(
    message: Message,
):
    orders = await get_user_orders(
        message.from_user.id
    )

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "не установлен"
    )

    await message.answer(
        "👤 <b>Профиль</b>\n\n"
        f"Имя: <b>{message.from_user.full_name}</b>\n"
        f"Username: <b>{username}</b>\n"
        f"Telegram ID: <code>{message.from_user.id}</code>\n\n"
        f"📦 Всего заказов: <b>{len(orders)}</b>",
        reply_markup=main_menu(),
    )


# =========================================================
# SUPPORT
# =========================================================

@dp.message(F.text == "💬 Поддержка")
async def support(
    message: Message,
):
    if SUPPORT_USERNAME:
        username = SUPPORT_USERNAME

        if not username.startswith("@"):
            username = "@" + username

        await message.answer(
            "💬 <b>Поддержка</b>\n\n"
            "Если у вас возникли вопросы по заказу, "
            "обратитесь в поддержку:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💬 Написать в поддержку",
                            url=f"https://t.me/{username.lstrip('@')}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ В магазин",
                            callback_data="back_main",
                        )
                    ],
                ]
            ),
        )
    else:
        await message.answer(
            "💬 <b>Поддержка</b>\n\n"
            "Поддержка пока не настроена.",
            reply_markup=main_menu(),
        )


# =========================================================
# CHECK PAYMENT
# =========================================================

@dp.callback_query(
    F.data.startswith("check_payment:")
)
async def check_payment(
    callback: CallbackQuery,
):
    await callback.answer()

    try:
        order_id = int(
            callback.data.split(":")[1]
        )
    except (ValueError, IndexError):
        await callback.message.answer(
            "❌ Ошибка заказа."
        )
        return

    order = await get_order(order_id)

    if not order:
        await callback.message.answer(
            "❌ Заказ не найден."
        )
        return

    (
        db_order_id,
        telegram_id,
        username,
        order_type,
        amount,
        price,
        status,
        invoice_id,
        invoice_url,
        created_at,
    ) = order

    if telegram_id != callback.from_user.id:
        await callback.message.answer(
            "❌ Этот заказ вам не принадлежит."
        )
        return

    if status == "PROCESSING":
        await callback.message.answer(
            "✅ Оплата уже подтверждена.\n\n"
            "Заказ находится в обработке."
        )
        return

    if status == "COMPLETED":
        await callback.message.answer(
            "✅ Этот заказ уже выполнен."
        )
        return

    if status == "REJECTED":
        await callback.message.answer(
            "❌ Этот заказ был отклонён."
        )
        return

    if not invoice_id:
        await callback.message.answer(
            "❌ Счёт оплаты не найден."
        )
        return

    try:
        invoice = await get_crypto_invoice(
            invoice_id
        )

    except Exception:
        await callback.message.answer(
            "⚠️ Не удалось проверить оплату.\n"
            "Попробуйте ещё раз через несколько секунд."
        )
        return

    if not invoice:
        await callback.message.answer(
            "⚠️ Счёт не найден в Crypto Bot."
        )
        return

    invoice_status = invoice.get(
        "status"
    )

    if invoice_status != "paid":
        await callback.message.answer(
            "⏳ <b>Оплата пока не найдена.</b>\n\n"
            "Если вы уже оплатили счёт, "
            "подождите немного и нажмите "
            "«🔄 Проверить оплату» ещё раз."
        )
        return

    await set_order_status(
        order_id,
        "PROCESSING",
    )

    if order_type == "STARS":
        product_text = f"{amount} Stars"
        user_text = (
            "Заказ оформлен! "
            "Stars поступят в течение 24 часов."
        )

    elif order_type.startswith("PREMIUM_"):
        months = order_type.replace(
            "PREMIUM_",
            "",
        )

        product_text = (
            f"Telegram Premium — {months} месяцев"
        )

        user_text = (
            "Заказ оформлен! "
            "Telegram Premium будет активирован "
            "в течение 24 часов."
        )

    else:
        product_text = order_type
        user_text = (
            "Заказ оформлен! "
            "Заказ будет обработан в течение 24 часов."
        )

    await callback.message.answer(
        f"✅ <b>{user_text}</b>\n\n"
        f"Заказ №<b>{order_id}</b>"
    )

    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                "💰 <b>Новая оплаченная заявка!</b>\n\n"
                f"Заказ №<b>{order_id}</b>\n"
                f"Пользователь: <b>{username}</b>\n"
                f"Telegram ID: <code>{telegram_id}</code>\n"
                f"Товар: <b>{product_text}</b>\n"
                f"Сумма: <b>{format_usd(price)}</b>\n"
                f"В сомах: <b>{format_kgs(price)}</b>\n\n"
                "Оплата через Crypto Bot подтверждена.",
                reply_markup=admin_order_keyboard(
                    order_id
                ),
            )
        except Exception as e:
            logging.exception(e)


# =========================================================
# AUTOMATIC PAYMENT CHECKER
# =========================================================

async def payment_checker():
    while True:
        try:
            orders = await get_waiting_payment_orders()

            for order in orders:
                (
                    order_id,
                    telegram_id,
                    username,
                    order_type,
                    amount,
                    price,
                    status,
                    invoice_id,
                    invoice_url,
                    created_at,
                ) = order

                try:
                    invoice = await get_crypto_invoice(
                        invoice_id
                    )

                except Exception as e:
                    logging.warning(
                        "Payment check error for order %s: %s",
                        order_id,
                        e,
                    )
                    continue

                if not invoice:
                    continue

                if invoice.get("status") != "paid":
                    continue

                await set_order_status(
                    order_id,
                    "PROCESSING",
                )

                if order_type == "STARS":
                    product_text = (
                        f"{amount} Stars"
                    )

                    user_text = (
                        "Заказ оформлен! "
                        "Stars поступят в течение 24 часов."
                    )

                elif order_type.startswith("PREMIUM_"):
                    months = order_type.replace(
                        "PREMIUM_",
                        "",
                    )

                    product_text = (
                        f"Telegram Premium — "
                        f"{months} месяцев"
                    )

                    user_text = (
                        "Заказ оформлен! "
                        "Telegram Premium будет активирован "
                        "в течение 24 часов."
                    )

                else:
                    product_text = order_type

                    user_text = (
                        "Заказ оформлен! "
                        "Заказ будет обработан "
                        "в течение 24 часов."
                    )

                try:
                    await bot.send_message(
                        telegram_id,
                        f"✅ <b>{user_text}</b>\n\n"
                        f"Заказ №<b>{order_id}</b>",
                    )
                except Exception as e:
                    logging.warning(
                        "Cannot notify user %s: %s",
                        telegram_id,
                        e,
                    )

                if ADMIN_ID:
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            "💰 <b>Новая оплаченная заявка!</b>\n\n"
                            f"Заказ №<b>{order_id}</b>\n"
                            f"Пользователь: <b>{username}</b>\n"
                            f"Telegram ID: <code>{telegram_id}</code>\n"
                            f"Товар: <b>{product_text}</b>\n"
                            f"Сумма: <b>{format_usd(price)}</b>\n"
                            f"В сомах: <b>{format_kgs(price)}</b>\n\n"
                            "Оплата через Crypto Bot подтверждена.",
                            reply_markup=admin_order_keyboard(
                                order_id
                            ),
                        )

                    except Exception as e:
                        logging.warning(
                            "Cannot notify admin: %s",
                            e,
                        )

        except Exception as e:
            logging.exception(
                "Payment checker error: %s",
                e,
            )

        await asyncio.sleep(30)


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_panel(
    message: Message,
):
    if message.from_user.id != ADMIN_ID:
        return

    orders = await get_pending_admin_orders()

    if not orders:
        await message.answer(
            "🛠 <b>Админ-панель</b>\n\n"
            "Нет заказов, ожидающих обработки."
        )
        return

    await message.answer(
        f"🛠 <b>Админ-панель</b>\n\n"
        f"Ожидают обработки: <b>{len(orders)}</b>"
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
            invoice_id,
            invoice_url,
            created_at,
        ) = order

        if order_type == "STARS":
            product = f"{amount} Stars"

        elif order_type.startswith("PREMIUM_"):
            months = order_type.replace(
                "PREMIUM_",
                "",
            )
            product = (
                f"Premium {months} месяцев"
            )

        else:
            product = order_type

        await message.answer(
            "📦 <b>Заказ</b>\n\n"
            f"№ <b>{order_id}</b>\n"
            f"Пользователь: <b>{username}</b>\n"
            f"ID: <code>{telegram_id}</code>\n"
            f"Товар: <b>{product}</b>\n"
            f"Сумма: <b>{format_usd(price)}</b>\n"
            f"Сом: <b>{format_kgs(price)}</b>\n"
            f"Статус: <b>{status}</b>",
            reply_markup=admin_order_keyboard(
                order_id
            ),
        )


@dp.callback_query(
    F.data.startswith("admin_complete:")
)
async def admin_complete(
    callback: CallbackQuery,
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа",
            show_alert=True,
        )
        return

    await callback.answer()

    try:
        order_id = int(
            callback.data.split(":")[1]
        )
    except (ValueError, IndexError):
        return

    order = await get_order(order_id)

    if not order:
        await callback.message.answer(
            "❌ Заказ не найден."
        )
        return

    (
        db_order_id,
        telegram_id,
        username,
        order_type,
        amount,
        price,
        status,
        invoice_id,
        invoice_url,
        created_at,
    ) = order

    if status != "PROCESSING":
        await callback.message.answer(
            "⚠️ Этот заказ нельзя завершить.\n"
            f"Текущий статус: {status}"
        )
        return

    await set_order_status(
        order_id,
        "COMPLETED",
    )

    try:
        await bot.send_message(
            telegram_id,
            f"✅ <b>Заказ №{order_id} выполнен!</b>\n\n"
            "Спасибо за покупку в Starzo.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🛍 Вернуться в магазин",
                            callback_data="back_main",
                        )
                    ]
                ]
            ),
        )
    except Exception as e:
        logging.warning(
            "User notification failed: %s",
            e,
        )

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.message.answer(
        f"✅ Заказ №<b>{order_id}</b> отмечен как выполненный."
    )


@dp.callback_query(
    F.data.startswith("admin_reject:")
)
async def admin_reject(
    callback: CallbackQuery,
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа",
            show_alert=True,
        )
        return

    await callback.answer()

    try:
        order_id = int(
            callback.data.split(":")[1]
        )
    except (ValueError, IndexError):
        return

    order = await get_order(order_id)

    if not order:
        await callback.message.answer(
            "❌ Заказ не найден."
        )
        return

    (
        db_order_id,
        telegram_id,
        username,
        order_type,
        amount,
        price,
        status,
        invoice_id,
        invoice_url,
        created_at,
    ) = order

    if status != "PROCESSING":
        await callback.message.answer(
            "⚠️ Этот заказ уже обработан."
        )
        return

    await set_order_status(
        order_id,
        "REJECTED",
    )

    try:
        await bot.send_message(
            telegram_id,
            f"❌ <b>Заказ №{order_id} отклонён.</b>\n\n"
            "Если вы считаете, что произошла ошибка, "
            "обратитесь в поддержку.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💬 Поддержка",
                            callback_data="support_inline",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🛍 В магазин",
                            callback_data="back_main",
                        )
                    ],
                ]
            ),
        )
    except Exception as e:
        logging.warning(
            "User notification failed: %s",
            e,
        )

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.message.answer(
        f"❌ Заказ №<b>{order_id}</b> отклонён."
    )


# =========================================================
# BACK BUTTONS
# =========================================================

@dp.callback_query(F.data == "back_main")
async def back_main(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()

    await state.clear()

    await callback.message.answer(
        "🛍 <b>Магазин Starzo</b>\n\n"
        "Выберите нужное действие:",
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data == "support_inline")
async def support_inline(
    callback: CallbackQuery,
):
    await callback.answer()

    if SUPPORT_USERNAME:
        username = SUPPORT_USERNAME.lstrip("@")

        await callback.message.answer(
            "💬 <b>Поддержка</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💬 Написать в поддержку",
                            url=f"https://t.me/{username}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⬅️ В магазин",
                            callback_data="back_main",
                        )
                    ],
                ]
            ),
        )
    else:
        await callback.message.answer(
            "Поддержка пока не настроена.",
            reply_markup=main_menu(),
        )


# =========================================================
# UNKNOWN COMMANDS / ERRORS
# =========================================================

@dp.message(Command("menu"))
async def menu_command(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await message.answer(
        "🛍 <b>Магазин Starzo</b>",
        reply_markup=main_menu(),
    )


# =========================================================
# STARTUP
# =========================================================

async def main():
    await init_db()

    payment_task = asyncio.create_task(
        payment_checker()
    )

    try:
        logging.info("Starzo bot started")

        await dp.start_polling(
            bot
        )

    finally:
        payment_task.cancel()

        try:
            await payment_task
        except asyncio.CancelledError:
            pass

        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
