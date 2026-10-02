import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN
from database import init_db, create_order, get_user_orders
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
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================

def usd_to_kgs(amount: float) -> float:
    return round(amount * USD_TO_KGS, 2)


def get_user_nickname(message: Message) -> str:
    if message.from_user.username:
        return f"@{message.from_user.username}"
    return message.from_user.full_name


def main_menu():
    kb = InlineKeyboardBuilder()

    kb.button(text="⭐️ Купить Stars", callback_data="buy_stars")
    kb.button(text="💰 Продать Stars", callback_data="sell_stars")
    kb.button(text="💎 Premium", callback_data="premium")

    kb.button(text="📦 Мои заказы", callback_data="orders")
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="💬 Поддержка", callback_data="support")

    kb.adjust(2, 1, 2, 1)

    return kb.as_markup()


def back_button():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="back_main")
    return kb.as_markup()


# =========================
# START
# =========================

@dp.message(CommandStart())
async def start_handler(message: Message):
    nickname = get_user_nickname(message)

    text = (
        f"👋 Добро пожаловать, {nickname}!\n\n"
        "У нас Вы можете приобрести Telegram Stars, Telegram Premium.\n\n"
        "Выберите нужный раздел:"
    )

    await message.answer(
        text,
        reply_markup=main_menu()
    )


# =========================
# КУПИТЬ STARS
# =========================

@dp.callback_query(F.data == "buy_stars")
async def buy_stars_handler(callback: CallbackQuery):
    buy_price = usd_to_kgs(STARS_BUY_RATE_USD)

    text = (
        "⭐️ Покупка Telegram Stars\n\n"
        "Текущий курс:\n"
        f"100 ⭐️ — {STARS_BUY_RATE_USD:.2f}$ / {buy_price:.2f} сом\n\n"
        f"Минимальная покупка — {MIN_STARS} ⭐️\n\n"
        "Выберите количество:"
    )

    kb = InlineKeyboardBuilder()

    kb.button(text="100 ⭐️", callback_data="buy_100")
    kb.button(text="500 ⭐️", callback_data="buy_500")
    kb.button(text="1000 ⭐️", callback_data="buy_1000")
    kb.button(text="2000 ⭐️", callback_data="buy_2000")
    kb.button(text="⬅️ Назад", callback_data="back_main")

    kb.adjust(2, 2, 1)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await callback.answer()


async def create_buy_order(callback: CallbackQuery, stars: int):
    username = callback.from_user.username

    if not username:
        await callback.message.edit_text(
            "⚠️ Для покупки Stars необходимо установить Telegram username.\n\n"
            "Пример: @username\n\n"
            "После установки username нажмите /start.",
            reply_markup=back_button()
        )
        return

    price_usd = STARS_BUY_RATE_USD * stars / 100
    price_kgs = usd_to_kgs(price_usd)

    order_id = await create_order(
        telegram_id=callback.from_user.id,
        username=username,
        order_type="BUY_STARS",
        amount=f"{stars} Stars",
        price=price_usd
    )

    text = (
        "⭐️ Заказ на покупку Stars\n\n"
        f"Количество: {stars} ⭐️\n"
        f"Стоимость: {price_usd:.2f}$ / {price_kgs:.2f} сом\n\n"
        "💳 Способ оплаты: Optima 24\n\n"
        "⚠️ Оплатить необходимо полную сумму.\n"
        "⚠️ После оплаты возврат денежных средств не производится.\n\n"
        f"Номер заказа: #{order_id}\n\n"
        "Реквизиты для оплаты будут предоставлены следующим этапом."
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_button()
    )


@dp.callback_query(F.data.startswith("buy_"))
async def buy_amount_handler(callback: CallbackQuery):
    try:
        stars = int(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка")
        return

    await create_buy_order(callback, stars)
    await callback.answer()


# =========================
# ПРОДАТЬ STARS
# =========================

@dp.callback_query(F.data == "sell_stars")
async def sell_stars_handler(callback: CallbackQuery):
    sell_price = usd_to_kgs(STARS_SELL_RATE_USD)

    text = (
        "💰 Продажа Telegram Stars\n\n"
        "Текущий курс:\n"
        f"100 ⭐️ — {STARS_SELL_RATE_USD:.2f}$ / {sell_price:.2f} сом\n\n"
        f"Минимальная продажа — {MIN_STARS} ⭐️\n\n"
        "⚠️ Перед продажей необходимо предоставить скриншот, "
        "где видно источник покупки Stars.\n\n"
        "Выберите количество:"
    )

    kb = InlineKeyboardBuilder()

    kb.button(text="100 ⭐️", callback_data="sell_100")
    kb.button(text="500 ⭐️", callback_data="sell_500")
    kb.button(text="1000 ⭐️", callback_data="sell_1000")
    kb.button(text="2000 ⭐️", callback_data="sell_2000")
    kb.button(text="⬅️ Назад", callback_data="back_main")

    kb.adjust(2, 2, 1)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("sell_"))
async def sell_amount_handler(callback: CallbackQuery):
    try:
        stars = int(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка")
        return

    username = callback.from_user.username

    if not username:
        await callback.message.edit_text(
            "⚠️ Для продажи Stars необходимо установить Telegram username.\n\n"
            "После установки username нажмите /start.",
            reply_markup=back_button()
        )
        await callback.answer()
        return

    price_usd = STARS_SELL_RATE_USD * stars / 100
    price_kgs = usd_to_kgs(price_usd)

    text = (
        "💰 Продажа Stars\n\n"
        f"Количество: {stars} ⭐️\n"
        f"Вы получите: {price_usd:.2f}$ / {price_kgs:.2f} сом\n\n"
        "Выберите банк для получения выплаты:"
    )

    kb = InlineKeyboardBuilder()

    kb.button(text="🏦 MBank", callback_data=f"sell_mbank_{stars}")
    kb.button(text="🏦 Optima 24", callback_data=f"sell_optima_{stars}")
    kb.button(text="⬅️ Назад", callback_data="sell_stars")

    kb.adjust(2, 1)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("sell_mbank_"))
async def sell_mbank_handler(callback: CallbackQuery):
    stars = int(callback.data.split("_")[2])

    await callback.message.edit_text(
        f"🏦 MBank\n\n"
        f"Количество: {stars} ⭐️\n\n"
        "Для получения выплаты отправьте **только QR-код MBank**.\n\n"
        "Не отправляйте номер карты или другие данные.",
        reply_markup=back_button()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("sell_optima_"))
async def sell_optima_handler(callback: CallbackQuery):
    stars = int(callback.data.split("_")[2])

    await callback.message.edit_text(
        f"🏦 Optima 24\n\n"
        f"Количество: {stars} ⭐️\n\n"
        "Для получения выплаты отправьте **только QR-код Optima 24**.\n\n"
        "Не отправляйте номер карты или другие данные.",
        reply_markup=back_button()
    )

    await callback.answer()


# =========================
# PREMIUM
# =========================

@dp.callback_query(F.data == "premium")
async def premium_handler(callback: CallbackQuery):
    p3 = usd_to_kgs(PREMIUM_PRICES_USD["3"])
    p6 = usd_to_kgs(PREMIUM_PRICES_USD["6"])
    p12 = usd_to_kgs(PREMIUM_PRICES_USD["12"])

    text = (
        "💎 Telegram Premium\n\n"
        f"3 месяца — {PREMIUM_PRICES_USD['3']:.2f}$ / {p3:.2f} сом\n"
        f"6 месяцев — {PREMIUM_PRICES_USD['6']:.2f}$ / {p6:.2f} сом\n"
        f"12 месяцев — {PREMIUM_PRICES_USD['12']:.2f}$ / {p12:.2f} сом\n\n"
        "Для кого хотите приобрести Premium?"
    )

    kb = InlineKeyboardBuilder()

    kb.button(text="👤 Себе", callback_data="premium_self")
    kb.button(text="👥 Для друга", callback_data="premium_friend")
    kb.button(text="⬅️ Назад", callback_data="back_main")

    kb.adjust(2, 1)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data.in_(["premium_self", "premium_friend"]))
async def premium_recipient_handler(callback: CallbackQuery):
    mode = "self" if callback.data == "premium_self" else "friend"

    kb = InlineKeyboardBuilder()

    kb.button(text="3 месяца", callback_data=f"prem_{mode}_3")
    kb.button(text="6 месяцев", callback_data=f"prem_{mode}_6")
    kb.button(text="12 месяцев", callback_data=f"prem_{mode}_12")
    kb.button(text="⬅️ Назад", callback_data="premium")

    kb.adjust(1)

    await callback.message.edit_text(
        "💎 Выберите срок Premium:",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("prem_"))
async def premium_duration_handler(callback: CallbackQuery):
    parts = callback.data.split("_")

    if len(parts) != 3:
        await callback.answer("Ошибка")
        return

    mode = parts[1]
    months = parts[2]

    price_usd = PREMIUM_PRICES_USD[months]
    price_kgs = usd_to_kgs(price_usd)

    if mode == "friend":
        recipient_text = (
            "\n\n👥 После выбора оплаты потребуется username получателя."
        )
    else:
        recipient_text = ""

    text = (
        "💎 Заказ Telegram Premium\n\n"
        f"Срок: {months} месяцев\n"
        f"Стоимость: {price_usd:.2f}$ / {price_kgs:.2f} сом\n"
        f"{recipient_text}\n"
        "⚠️ Оплатить необходимо полную сумму.\n"
        "⚠️ Возврат денежных средств не производится.\n\n"
        "Способ оплаты будет добавлен следующим этапом."
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_button()
    )

    await callback.answer()


# =========================
# МОИ ЗАКАЗЫ
# =========================

@dp.callback_query(F.data == "orders")
async def orders_handler(callback: CallbackQuery):
    orders = await get_user_orders(callback.from_user.id)

    if not orders:
        text = (
            "📦 Мои заказы\n\n"
            "У вас пока нет заказов."
        )
    else:
        lines = ["📦 Мои заказы\n"]

        for order in orders:
            order_id, order_type, amount, price, status, created_at = order

            if order_type == "BUY_STARS":
                title = "⭐️ Покупка Stars"
            elif order_type == "SELL_STARS":
                title = "💰 Продажа Stars"
            else:
                title = "💎 Premium"

            lines.append(
                f"#{order_id} — {title}\n"
                f"{amount} — {price:.2f}$\n"
                f"Статус: {status}\n"
            )

        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=back_button()
    )

    await callback.answer()


# =========================
# ПРОФИЛЬ
# =========================

@dp.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    username = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else "Не установлен"
    )

    orders = await get_user_orders(callback.from_user.id)

    text = (
        "👤 Профиль\n\n"
        f"Username: {username}\n"
        f"Telegram ID: {callback.from_user.id}\n"
        f"Количество заказов: {len(orders)}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_button()
    )

    await callback.answer()


# =========================
# ПОДДЕРЖКА
# =========================

@dp.callback_query(F.data == "support")
async def support_handler(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()

    kb.button(
        text="💬 Написать в поддержку",
        url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"
    )
    kb.button(text="⬅️ Назад", callback_data="back_main")

    kb.adjust(1)

    await callback.message.edit_text(
        "💬 Поддержка\n\n"
        "Если у вас возникли вопросы по заказу, "
        "обратитесь в поддержку.",
        reply_markup=kb.as_markup()
    )

    await callback.answer()


# =========================
# НАЗАД
# =========================

@dp.callback_query(F.data == "back_main")
async def back_main_handler(callback: CallbackQuery):
    nickname = get_user_nickname(callback.message)

    await callback.message.edit_text(
        f"👋 Добро пожаловать, {nickname}!\n\n"
        "У нас Вы можете приобрести Telegram Stars, Telegram Premium.\n\n"
        "Выберите нужный раздел:",
        reply_markup=main_menu()
    )

    await callback.answer()


# =========================
# ЗАПУСК
# =========================

async def main():
    await init_db()

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не установлен")

    bot = Bot(token=BOT_TOKEN)

    print("Starzo запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
