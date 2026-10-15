import asyncio
import logging
from html import escape

import aiohttp
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

from config import BOT_TOKEN, CRYPTO_PAY_TOKEN, SUPPORT_USERNAME, ADMIN_ID
from settings import USD_TO_KGS, STARS_BUY_RATE_USD, MIN_STARS, PREMIUM_PRICES_USD
from database import (init_db, create_order, set_crypto_invoice, get_order, get_user_orders,
                      get_waiting_payment_orders, get_pending_admin_orders, set_order_status,
                      register_user, get_all_user_ids)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("starzo")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не указан")
if not CRYPTO_PAY_TOKEN:
    log.warning("CRYPTO_PAY_TOKEN не указан: оплата Crypto Bot будет недоступна, но бот сможет запуститься для остальных функций.")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID не указан")
ADMIN_ID = int(ADMIN_ID)
USD_TO_KGS = float(USD_TO_KGS)
STARS_BUY_RATE_USD = float(STARS_BUY_RATE_USD)  # цена берётся из settings.py
MIN_STARS = int(MIN_STARS)
PREMIUM_PRICES_USD = {"3": 14.00, "6": 21.99, "12": 33.00}

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
SUBSCRIPTION_CHANNEL = "@vukoul"
SUBSCRIPTION_URL = "https://t.me/vukoul"

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)
        # Keep the broadcast audience up to date. The users table is additive;
        # existing orders and their history are not modified.
        try:
            await register_user(user.id, user.username, user.first_name)
        except Exception:
            log.exception("Не удалось сохранить пользователя для рассылки")
        if user.id == ADMIN_ID:
            return await handler(event, data)
        # The check button must be allowed through so it can re-check membership.
        if isinstance(event, CallbackQuery) and event.data == "check_subscription":
            return await handler(event, data)
        try:
            member = await bot.get_chat_member(chat_id=SUBSCRIPTION_CHANNEL, user_id=user.id)
            subscribed = member.status in ("member", "administrator", "creator") or (member.status == "restricted" and getattr(member, "is_member", False))
        except Exception:
            log.exception("Не удалось проверить подписку на %s", SUBSCRIPTION_CHANNEL)
            subscribed = False
        if subscribed:
            return await handler(event, data)
        markup = subscription_keyboard()
        notice = ("🔒 <b>Чтобы пользоваться Starzo, подпишитесь на канал</b> "
                  f'<a href="{SUBSCRIPTION_URL}">@vukoul</a>, затем нажмите «Проверить подписку».\n\n'
                  "Если проверка не проходит, убедитесь, что бот добавлен администратором канала.")
        try:
            if isinstance(event, Message):
                await event.answer(notice, reply_markup=markup)
            elif isinstance(event, CallbackQuery):
                await event.answer("Сначала подпишитесь на @vukoul", show_alert=True)
                if event.message:
                    await event.message.answer(notice, reply_markup=markup)
        except Exception:
            log.exception("Не удалось показать запрос подписки")
        return None

dp.message.outer_middleware(SubscriptionMiddleware())
dp.callback_query.outer_middleware(SubscriptionMiddleware())
CRYPTO_API_URL = "https://pay.crypt.bot/api"
OPTIMA_ACCOUNT = "1090934711416531"
OPTIMA_RECIPIENT = "Аким У."

# We only track the last regular screen. Payment links and receipt messages are not deleted.
last_screen: dict[int, tuple[int, int]] = {}

class BuyStarsState(StatesGroup):
    waiting_amount = State()
    waiting_gift_username = State()
class PremiumState(StatesGroup):
    waiting_friend_username = State()
class OptimaReceiptState(StatesGroup):
    waiting_receipt = State()
class RejectState(StatesGroup):
    waiting_reason = State()
class BroadcastState(StatesGroup):
    waiting_message = State()


def usd_to_kgs(amount):
    return round(float(amount) * USD_TO_KGS, 2)
def format_usd(amount):
    return f"${float(amount):.2f}"
def format_kgs(amount):
    return f"{usd_to_kgs(amount):.2f} сом"
def username_text(user):
    return f"@{user.username}" if user.username else f"ID {user.id}"
def esc(value):
    return escape(str(value or ""))
def normalize_username(value):
    value = (value or "").strip()
    if value.startswith("@"):
        value = value[1:]
    if not 5 <= len(value) <= 32 or not value[0].isalpha():
        return ""
    if not all(c.isascii() and (c.isalnum() or c == "_") for c in value):
        return ""
    return "@" + value


def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=SUBSCRIPTION_URL)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")],
    ])


def stars_target_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Купить себе", callback_data="stars_target:self")],
        [InlineKeyboardButton(text="🎁 Подарить другу", callback_data="stars_target:gift")],
        [InlineKeyboardButton(text="⬅️ В магазин", callback_data="back_main")],
    ])


def stars_gift_quantity_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="100 ⭐️", callback_data="buy_100"), InlineKeyboardButton(text="500 ⭐️", callback_data="buy_500")],
        [InlineKeyboardButton(text="1000 ⭐️", callback_data="buy_1000"), InlineKeyboardButton(text="2000 ⭐️", callback_data="buy_2000")],
        [InlineKeyboardButton(text="✏️ Другое количество", callback_data="buy_custom")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="stars_back_target")],
    ])


def stars_order_base(order_type):
    return str(order_type or "").split(":", 1)[0]


def stars_order_recipient(order_type):
    parts = str(order_type or "").split(":", 1)
    return parts[1] if len(parts) == 2 else None


def stars_product(order_type, amount):
    base = stars_order_base(order_type)
    gift_recipient = stars_order_recipient(order_type)
    is_optima = base.endswith("_OPTIMA")
    if base.startswith("STARS_GIFT"):
        product = f"{amount} Stars в подарок для {gift_recipient or 'получателя'}"
    else:
        product = f"{amount} Stars"
    if is_optima:
        product += " — Optima 24"
    return product


def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⭐️ Купить Stars"), KeyboardButton(text="💰 Продать Stars")],
        [KeyboardButton(text="💎 Premium"), KeyboardButton(text="📦 Мои заказы")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="💬 Поддержка")],
    ], resize_keyboard=True)

def inline_back(data="back_main", label="⬅️ В магазин"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=data)]])
def buy_stars_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="100 ⭐️", callback_data="buy_100"), InlineKeyboardButton(text="500 ⭐️", callback_data="buy_500")],
        [InlineKeyboardButton(text="1000 ⭐️", callback_data="buy_1000"), InlineKeyboardButton(text="2000 ⭐️", callback_data="buy_2000")],
        [InlineKeyboardButton(text="✏️ Другое количество", callback_data="buy_custom")],
        [InlineKeyboardButton(text="⬅️ В магазин", callback_data="back_main")],
    ])
def stars_payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Crypto Bot", callback_data="stars_pay_crypto")],
        [InlineKeyboardButton(text="🏦 Optima 24", callback_data="stars_pay_optima")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="stars_back_amount")],
    ])
def premium_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"3 месяца — {format_usd(PREMIUM_PRICES_USD.get('3', 14.00))}", callback_data="premium_months:3")],
        [InlineKeyboardButton(text=f"6 месяцев — {format_usd(PREMIUM_PRICES_USD.get('6', 21.99))}", callback_data="premium_months:6")],
        [InlineKeyboardButton(text=f"12 месяцев — {format_usd(PREMIUM_PRICES_USD.get('12', 33.00))}", callback_data="premium_months:12")],
        [InlineKeyboardButton(text="⬅️ В магазин", callback_data="back_main")],
    ])
def premium_target_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Себе", callback_data="premium_target:self")],
        [InlineKeyboardButton(text="👥 Другому пользователю", callback_data="premium_target:friend")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="premium_back_months")],
    ])
def premium_payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Crypto Bot", callback_data="premium_pay:crypto")],
        [InlineKeyboardButton(text="🏦 Optima 24", callback_data="premium_pay:optima")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="premium_back_target")],
    ])
def crypto_payment_keyboard(order_id, url):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить через Crypto Bot", url=url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_payment:{order_id}")],
        [InlineKeyboardButton(text="⬅️ В магазин", callback_data="back_main")],
    ])
def optima_paid_keyboard(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"optima_paid:{order_id}")],
        [InlineKeyboardButton(text="⬅️ В магазин", callback_data="back_main")],
    ])
def admin_order_keyboard(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[[ 
        InlineKeyboardButton(text="✅ Выполнено", callback_data=f"admin_complete:{order_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_reject:{order_id}"),
    ]])

async def clean_screen(user_id):
    old = last_screen.pop(user_id, None)
    if old:
        try:
            await bot.delete_message(old[0], old[1])
        except Exception:
            pass
async def send_screen(message: Message, text: str, markup=None):
    await clean_screen(message.from_user.id)
    sent = await message.answer(text, reply_markup=markup)
    last_screen[message.from_user.id] = (sent.chat.id, sent.message_id)
    return sent
async def edit_or_answer(callback: CallbackQuery, text: str, markup=None):
    try:
        await callback.message.edit_text(text, reply_markup=markup)
        last_screen[callback.from_user.id] = (callback.message.chat.id, callback.message.message_id)
    except Exception:
        sent = await callback.message.answer(text, reply_markup=markup)
        last_screen[callback.from_user.id] = (sent.chat.id, sent.message_id)

async def crypto_api(method, data=None):
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN, "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{CRYPTO_API_URL}/{method}", headers=headers, json=data or {}) as response:
            result = await response.json()
            if response.status >= 400 or not result.get("ok"):
                raise RuntimeError(str(result.get("error") or result))
            return result.get("result")
async def create_crypto_invoice(amount, description):
    result = await crypto_api("createInvoice", {"currency_type": "fiat", "fiat": "USD", "amount": f"{float(amount):.2f}", "description": description})
    return {"id": str(result["invoice_id"]), "url": result["bot_invoice_url"]}
async def get_crypto_invoice(invoice_id):
    result = await crypto_api("getInvoices", {"invoice_ids": str(invoice_id)})
    items = result.get("items", [])
    return items[0] if items else None
async def attach_invoice(order_id, price, description):
    invoice = await create_crypto_invoice(price, description)
    await set_crypto_invoice(order_id, invoice["id"], invoice["url"])
    return invoice


def welcome_text(message):
    name = f"@{message.from_user.username}" if message.from_user.username else (message.from_user.first_name or "Пользователь")
    return f"👋 <b>Добро пожаловать, {esc(name)}!</b>\n\nУ нас Вы можете приобрести <b>Telegram Stars</b> и <b>Telegram Premium</b>.\n\nВыберите нужное действие ниже."
def optima_text(order_id, product, price):
    return ("🏦 <b>Оплата через Optima 24</b>\n\n"
        f"Заказ №<b>{order_id}</b>\nТовар: <b>{esc(product)}</b>\n"
        f"К оплате: <b>{format_usd(price)}</b>\nСумма: <b>{format_kgs(price)}</b>\n\n"
        "Переведите указанную сумму по реквизитам:\n\n"
        f"🏦 Номер счёта: <code>{OPTIMA_ACCOUNT}</code>\n👤 Получатель: <b>{esc(OPTIMA_RECIPIENT)}</b>\n\n"
        "После оплаты нажмите «✅ Я оплатил» и отправьте фото/скриншот чека.\n"
        "⚠️ Не отправляйте пароль, SMS-код или полные данные карты.")

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery, state: FSMContext):
    try:
        member = await bot.get_chat_member(chat_id=SUBSCRIPTION_CHANNEL, user_id=callback.from_user.id)
        subscribed = member.status in ("member", "administrator", "creator") or (member.status == "restricted" and getattr(member, "is_member", False))
    except Exception:
        log.exception("Проверка подписки не удалась")
        await callback.answer("Не удалось проверить подписку. Попробуйте позже.", show_alert=True)
        return
    if not subscribed:
        await callback.answer("Вы ещё не подписались на @vukoul", show_alert=True)
        return
    await callback.answer("Подписка подтверждена!")
    await state.clear()
    try:
        await callback.message.edit_text("✅ <b>Подписка подтверждена!</b>\n\nДобро пожаловать в Starzo. Выберите действие в меню ниже.")
    except Exception:
        pass
    await callback.message.answer("🛍 <b>Магазин Starzo</b>", reply_markup=main_menu())

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await send_screen(message, welcome_text(message), main_menu())

@dp.message(Command("menu"))
async def menu_cmd(message: Message, state: FSMContext):
    await state.clear()
    await send_screen(message, "🛍 <b>Магазин Starzo</b>\n\nВыберите нужное действие:", main_menu())

@dp.message(F.text == "⭐️ Купить Stars")
async def buy_stars(message: Message, state: FSMContext):
    await state.clear()
    if not message.from_user.username:
        await send_screen(message, "❌ <b>Покупка Stars недоступна без Telegram username.</b>\n\nУстановите username в настройках Telegram и попробуйте снова.", main_menu())
        return
    await send_screen(message, "⭐️ <b>Покупка Telegram Stars</b>\n\n"
        f"Цена: <b>100 Stars = {format_usd(STARS_BUY_RATE_USD)}</b>\nЭто примерно <b>{format_kgs(STARS_BUY_RATE_USD)}</b>.\n"
        f"Минимальная покупка — <b>{MIN_STARS} Stars</b>.\n\nКому покупаем Stars?", stars_target_keyboard())

@dp.callback_query(F.data == "stars_target:self")
async def stars_target_self(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not callback.from_user.username:
        await state.clear()
        await callback.message.answer("❌ Для покупки Stars необходимо установить Telegram username.", reply_markup=main_menu())
        return
    await state.update_data(stars_recipient=f"@{callback.from_user.username}", stars_gift=False)
    await edit_or_answer(callback, "⭐️ <b>Выберите количество Stars для себя:</b>", buy_stars_keyboard())

@dp.callback_query(F.data == "stars_target:gift")
async def stars_target_gift(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not callback.from_user.username:
        await state.clear()
        await callback.message.answer("❌ Для покупки Stars необходимо установить собственный Telegram username.", reply_markup=main_menu())
        return
    await state.set_state(BuyStarsState.waiting_gift_username)
    await edit_or_answer(callback, "🎁 <b>Подарить Stars другу</b>\n\nВведите username получателя, например <code>@username</code>.", inline_back("stars_back_target", "⬅️ Назад"))

@dp.message(BuyStarsState.waiting_gift_username)
async def stars_gift_username(message: Message, state: FSMContext):
    target = normalize_username(message.text or "")
    if not target:
        await message.answer("❌ Неверный username. Введите @username (5–32 символа, латинские буквы, цифры или _).")
        return
    if not message.from_user.username:
        await state.clear()
        await message.answer("❌ Для покупки Stars необходимо установить собственный Telegram username.", reply_markup=main_menu())
        return
    await state.update_data(stars_recipient=target, stars_gift=True)
    await state.set_state(None)
    await message.answer(f"🎁 <b>Stars для {esc(target)}</b>\n\nВыберите количество:", reply_markup=buy_stars_keyboard())

@dp.callback_query(F.data == "stars_back_target")
async def stars_back_target(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(None)
    await edit_or_answer(callback, "⭐️ <b>Кому покупаем Stars?</b>", stars_target_keyboard())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not callback.from_user.username:
        await state.clear()
        await callback.message.answer("❌ Для покупки Stars необходимо установить Telegram username.", reply_markup=main_menu())
        return
    if callback.data == "buy_custom":
        await state.set_state(BuyStarsState.waiting_amount)
        await edit_or_answer(callback, f"✏️ <b>Введите количество Stars</b>\n\nМинимум: <b>{MIN_STARS}</b>. Введите целое число.", inline_back())
        return
    try:
        stars = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        return
    if stars < MIN_STARS:
        await callback.message.answer(f"❌ Минимальная покупка — {MIN_STARS} Stars.")
        return
    await state.update_data(stars=stars)
    price = stars / 100 * STARS_BUY_RATE_USD
    await edit_or_answer(callback, f"⭐️ <b>{stars} Stars</b>\n\nСтоимость: <b>{format_usd(price)}</b>\nВ сомах: <b>{format_kgs(price)}</b>\n\nВыберите способ оплаты:", stars_payment_keyboard())

@dp.message(BuyStarsState.waiting_amount)
async def custom_stars(message: Message, state: FSMContext):
    try:
        stars = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Введите количество Stars целым числом, например 300.")
        return
    if stars < MIN_STARS:
        await message.answer(f"❌ Минимальная покупка — {MIN_STARS} Stars.")
        return
    if not message.from_user.username:
        await state.clear()
        await message.answer("❌ Для покупки Stars необходимо установить Telegram username.", reply_markup=main_menu())
        return
    await state.update_data(stars=stars)
    await state.set_state(None)
    price = stars / 100 * STARS_BUY_RATE_USD
    await message.answer(f"⭐️ <b>{stars} Stars</b>\n\nСтоимость: <b>{format_usd(price)}</b>\nВ сомах: <b>{format_kgs(price)}</b>\n\nВыберите способ оплаты:", reply_markup=stars_payment_keyboard())

@dp.callback_query(F.data == "stars_back_amount")
async def stars_back(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(None)
    await edit_or_answer(callback, "⭐️ <b>Выберите количество Stars:</b>", buy_stars_keyboard())

async def create_stars_order(callback, state, method):
    buyer = callback.from_user
    if not buyer.username:
        await state.clear()
        await callback.message.answer("❌ Для покупки Stars необходимо установить Telegram username.", reply_markup=main_menu())
        return
    data = await state.get_data()
    stars = data.get("stars")
    if not stars:
        await state.clear()
        await callback.message.answer("❌ Сессия устарела. Начните покупку Stars заново.", reply_markup=main_menu())
        return
    price = int(stars) / 100 * STARS_BUY_RATE_USD
    recipient = data.get("stars_recipient") or f"@{buyer.username}"
    is_gift = bool(data.get("stars_gift"))
    base_type = "STARS_GIFT" if is_gift else "STARS"
    if method != "Crypto Bot":
        base_type += "_OPTIMA"
    order_type = base_type + (f":{recipient}" if is_gift else "")
    order_id = await create_order(buyer.id, username_text(buyer), order_type, str(stars), price)
    if method == "Crypto Bot":
        try:
            invoice = await attach_invoice(order_id, price, f"Starzo — покупка {stars} Telegram Stars для {recipient}")
        except Exception:
            log.exception("Crypto invoice creation failed")
            await set_order_status(order_id, "PAYMENT_ERROR")
            await state.clear()
            await callback.message.answer("❌ Не удалось создать счёт Crypto Bot. Попробуйте позже.", reply_markup=main_menu())
            return
        gift_line = f"\nПолучатель: <b>{esc(recipient)}</b>" if is_gift else ""
        await callback.message.answer("⭐️ <b>Заказ создан</b>\n\n"
            f"Заказ №<b>{order_id}</b>\nКоличество: <b>{stars} Stars</b>{gift_line}\nСтоимость: <b>{format_usd(price)}</b>\nВ сомах: <b>{format_kgs(price)}</b>\n\n"
            "Оплатите счёт и нажмите «🔄 Проверить оплату». Чек Crypto Bot не требуется.", reply_markup=crypto_payment_keyboard(order_id, invoice["url"]))
    else:
        product = f"{stars} Stars для {recipient}" if is_gift else f"{stars} Stars"
        await callback.message.answer(optima_text(order_id, product, price), reply_markup=optima_paid_keyboard(order_id))
    await state.clear()

@dp.callback_query(F.data == "stars_pay_crypto")
async def stars_crypto(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await create_stars_order(callback, state, "Crypto Bot")

@dp.callback_query(F.data == "stars_pay_optima")
async def stars_optima(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await create_stars_order(callback, state, "Optima 24")

@dp.message(F.text == "💎 Premium")
async def premium(message: Message, state: FSMContext):
    await state.clear()
    if not message.from_user.username:
        await send_screen(message, "❌ <b>Покупка Premium недоступна без Telegram username.</b>\n\nУстановите username в настройках Telegram и попробуйте снова.", main_menu())
        return
    await send_screen(message, "💎 <b>Telegram Premium</b>\n\nВыберите срок подписки:", premium_keyboard())

@dp.callback_query(F.data.startswith("premium_months:"))
async def premium_months(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not callback.from_user.username:
        await state.clear()
        await callback.message.answer("❌ Для покупки Premium необходимо установить Telegram username.", reply_markup=main_menu())
        return
    months = callback.data.split(":", 1)[1]
    if months not in PREMIUM_PRICES_USD:
        await callback.message.answer("❌ Этот срок Premium не настроен в settings.py.")
        return
    price = PREMIUM_PRICES_USD[months]
    await state.update_data(premium_months=months, premium_price=price, premium_target=None)
    await edit_or_answer(callback, f"💎 <b>Premium на {months} месяцев</b>\n\nЦена: <b>{format_usd(price)}</b>\nВ сомах: <b>{format_kgs(price)}</b>\n\nДля кого оформить?", premium_target_keyboard())

@dp.callback_query(F.data == "premium_target:self")
async def premium_self(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not callback.from_user.username:
        await state.clear()
        await callback.message.answer("❌ Для покупки Premium необходимо установить Telegram username.", reply_markup=main_menu())
        return
    data = await state.get_data()
    months, price = data.get("premium_months"), data.get("premium_price")
    if not months or price is None:
        await state.clear()
        await callback.message.answer("❌ Сессия устарела. Начните покупку Premium заново.", reply_markup=main_menu())
        return
    target = f"@{callback.from_user.username}"
    await state.update_data(premium_target=target)
    await edit_or_answer(callback, f"💎 <b>Premium на {months} месяцев</b>\n\nПолучатель: <b>{esc(target)}</b>\nСтоимость: <b>{format_usd(price)}</b>\nВ сомах: <b>{format_kgs(price)}</b>\n\nВыберите способ оплаты:", premium_payment_keyboard())

@dp.callback_query(F.data == "premium_target:friend")
async def premium_friend(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not callback.from_user.username:
        await state.clear()
        await callback.message.answer("❌ Для покупки Premium необходимо установить собственный Telegram username.", reply_markup=main_menu())
        return
    data = await state.get_data()
    if not data.get("premium_months"):
        await state.clear()
        await callback.message.answer("❌ Сначала выберите срок Premium.", reply_markup=main_menu())
        return
    await state.set_state(PremiumState.waiting_friend_username)
    await edit_or_answer(callback, "👥 <b>Premium для другого пользователя</b>\n\nВведите username получателя, например <code>@username</code>.", inline_back("premium_back_months", "⬅️ Назад"))

@dp.message(PremiumState.waiting_friend_username)
async def premium_friend_username(message: Message, state: FSMContext):
    if not message.from_user.username:
        await state.clear()
        await message.answer("❌ Для покупки Premium необходимо установить собственный Telegram username.", reply_markup=main_menu())
        return
    target = normalize_username(message.text or "")
    if not target:
        await message.answer("❌ Неверный username. Введите @username (5–32 символа, латинские буквы, цифры или _).")
        return
    data = await state.get_data()
    months, price = data.get("premium_months"), data.get("premium_price")
    if not months or price is None:
        await state.clear()
        await message.answer("❌ Сессия устарела. Начните покупку Premium заново.", reply_markup=main_menu())
        return
    await state.update_data(premium_target=target)
    await state.set_state(None)
    await message.answer(f"💎 <b>Premium на {months} месяцев</b>\n\nПолучатель: <b>{esc(target)}</b>\nСтоимость: <b>{format_usd(price)}</b>\nВ сомах: <b>{format_kgs(price)}</b>\n\nВыберите способ оплаты:", reply_markup=premium_payment_keyboard())

@dp.callback_query(F.data == "premium_back_months")
async def premium_back_months(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(None)
    await edit_or_answer(callback, "💎 <b>Telegram Premium</b>\n\nВыберите срок подписки:", premium_keyboard())

@dp.callback_query(F.data == "premium_back_target")
async def premium_back_target(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    months, price = data.get("premium_months"), data.get("premium_price")
    if not months or price is None:
        await state.clear()
        await edit_or_answer(callback, "❌ Сессия устарела. Начните покупку Premium заново.", main_menu())
        return
    target = data.get("premium_target")
    if not target:
        await edit_or_answer(callback, f"💎 <b>Premium на {months} месяцев</b>\n\nДля кого оформить?", premium_target_keyboard())
    else:
        await edit_or_answer(callback, f"💎 <b>Premium на {months} месяцев</b>\n\nПолучатель: <b>{esc(target)}</b>\nСтоимость: <b>{format_usd(price)}</b>\nВ сомах: <b>{format_kgs(price)}</b>\n\nВыберите способ оплаты:", premium_payment_keyboard())

async def create_premium_order(callback, state, method):
    buyer = callback.from_user
    if not buyer.username:
        await state.clear()
        await callback.message.answer("❌ Для покупки Premium необходимо установить Telegram username.", reply_markup=main_menu())
        return
    data = await state.get_data()
    months, price, target = data.get("premium_months"), data.get("premium_price"), data.get("premium_target")
    if not months or price is None or not target:
        await state.clear()
        await callback.message.answer("❌ Сессия заказа устарела. Начните покупку Premium заново.", reply_markup=main_menu())
        return
    order_type = f"PREMIUM_{months}" + ("_OPTIMA" if method == "Optima 24" else "")
    order_id = await create_order(buyer.id, username_text(buyer), order_type, target, float(price))
    product = f"Telegram Premium — {months} месяцев для {target}"
    if method == "Crypto Bot":
        try:
            invoice = await attach_invoice(order_id, price, f"Starzo — Premium {months} мес. для {target}")
        except Exception:
            log.exception("Crypto invoice creation failed")
            await set_order_status(order_id, "PAYMENT_ERROR")
            await state.clear()
            await callback.message.answer("❌ Не удалось создать счёт Crypto Bot. Попробуйте позже.", reply_markup=main_menu())
            return
        await callback.message.answer("💎 <b>Заказ Premium создан</b>\n\n"
            f"Заказ №<b>{order_id}</b>\nСрок: <b>{months} месяцев</b>\nПолучатель: <b>{esc(target)}</b>\n"
            f"Стоимость: <b>{format_usd(price)}</b>\nВ сомах: <b>{format_kgs(price)}</b>\n\nОплатите счёт и нажмите «🔄 Проверить оплату». Чек Crypto Bot не требуется.",
            reply_markup=crypto_payment_keyboard(order_id, invoice["url"]))
    else:
        await callback.message.answer(optima_text(order_id, product, price), reply_markup=optima_paid_keyboard(order_id))
    await state.clear()

@dp.callback_query(F.data == "premium_pay:crypto")
async def premium_crypto(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await create_premium_order(callback, state, "Crypto Bot")

@dp.callback_query(F.data == "premium_pay:optima")
async def premium_optima(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await create_premium_order(callback, state, "Optima 24")

@dp.callback_query(F.data.startswith("optima_paid:"))
async def optima_paid(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        order_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.message.answer("❌ Ошибка заказа.")
        return
    order = await get_order(order_id)
    if not order:
        await callback.message.answer("❌ Заказ не найден.")
        return
    _, telegram_id, username, order_type, amount, price, status, invoice_id, invoice_url, created_at = order
    if telegram_id != callback.from_user.id:
        await callback.message.answer("❌ Этот заказ вам не принадлежит.")
        return
    if status != "WAITING_PAYMENT":
        await callback.message.answer("⚠️ Этот заказ уже обрабатывается.")
        return
    await state.set_state(OptimaReceiptState.waiting_receipt)
    await state.update_data(optima_order_id=order_id)
    await callback.message.answer("🧾 <b>Отправьте чек</b>\n\nПришлите фото или скриншот подтверждения оплаты через Optima 24.\nБез чека заказ не будет принят.")

@dp.message(OptimaReceiptState.waiting_receipt)
async def optima_receipt(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("⚠️ Нужен именно чек: отправьте фото или скриншот чека Optima 24.")
        return
    data = await state.get_data()
    order_id = data.get("optima_order_id")
    order = await get_order(order_id) if order_id else None
    if not order:
        await state.clear()
        await message.answer("❌ Заказ не найден. Начните заново.", reply_markup=main_menu())
        return
    _, telegram_id, username, order_type, amount, price, status, invoice_id, invoice_url, created_at = order
    if telegram_id != message.from_user.id or status != "WAITING_PAYMENT":
        await state.clear()
        await message.answer("⚠️ Этот заказ не принадлежит вам или уже обрабатывается.", reply_markup=main_menu())
        return
    await set_order_status(order_id, "PROCESSING")
    if stars_order_base(order_type).startswith("STARS"):
        product = stars_product(order_type, amount)
    elif order_type.startswith("PREMIUM_"):
        months = order_type.removeprefix("PREMIUM_").removesuffix("_OPTIMA")
        product = f"Telegram Premium — {months} месяцев; получатель {amount}"
    else:
        product = order_type
    await message.answer(f"✅ <b>Чек получен!</b>\n\nЗаказ №<b>{order_id}</b> отправлен на проверку.\nПосле подтверждения заказ будет выполнен в течение 24 часов.", reply_markup=main_menu())
    try:
        await bot.send_message(ADMIN_ID, "🏦 <b>Новая оплата через Optima 24!</b>\n\n"
            f"Заказ №<b>{order_id}</b>\nПокупатель: <b>{esc(username)}</b>\nTelegram ID: <code>{telegram_id}</code>\n"
            f"Товар: <b>{esc(product)}</b>\nСумма: <b>{format_usd(price)} ({format_kgs(price)})</b>\n\nЧек прикреплён следующим сообщением.", reply_markup=admin_order_keyboard(order_id))
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"🧾 Чек заказа №{order_id}\nПокупатель: {esc(username)}\nТовар: {esc(product)}\nСумма: {format_usd(price)} ({format_kgs(price)})")
    except Exception:
        log.exception("Не удалось отправить чек админу")
    await state.clear()

@dp.message(F.text == "💰 Продать Stars")
async def sell_stars(message: Message, state: FSMContext):
    await state.clear()
    await send_screen(message, "🚧 <b>Продажа Stars пока в разработке.</b>", main_menu())

@dp.message(F.text == "📦 Мои заказы")
async def my_orders(message: Message, state: FSMContext):
    await state.clear()
    orders = await get_user_orders(message.from_user.id)
    if not orders:
        await send_screen(message, "📦 <b>Мои заказы</b>\n\nУ вас пока нет заказов.", main_menu())
        return
    lines = ["📦 <b>Мои заказы</b>\n"]
    for row in orders[:20]:
        order_id, order_type, amount, price, status, created_at = row
        if stars_order_base(order_type).startswith("STARS"):
            product = stars_product(order_type, amount)
        elif order_type.startswith("PREMIUM_"):
            months = order_type.removeprefix("PREMIUM_").removesuffix("_OPTIMA")
            product = f"Premium на {months} месяцев; получатель {amount}" + (" — Optima 24" if order_type.endswith("_OPTIMA") else "")
        else:
            product = order_type
        status_text = {"WAITING_PAYMENT": "⏳ Ожидает оплаты", "PROCESSING": "🔄 В обработке", "COMPLETED": "✅ Выполнен", "REJECTED": "❌ Отклонён", "PAYMENT_ERROR": "⚠️ Ошибка оплаты"}.get(status, status)
        lines.append(f"🧾 <b>Заказ №{order_id}</b>\nТовар: {esc(product)}\nСумма: {format_usd(price)} ({format_kgs(price)})\nСтатус: {esc(status_text)}\nДата: {esc(created_at)}\n")
    await send_screen(message, "\n".join(lines), main_menu())

@dp.message(F.text == "👤 Профиль")
async def profile(message: Message, state: FSMContext):
    await state.clear()
    orders = await get_user_orders(message.from_user.id)
    uname = f"@{message.from_user.username}" if message.from_user.username else "не установлен"
    await send_screen(message, "👤 <b>Профиль</b>\n\n"
        f"Имя: <b>{esc(message.from_user.full_name)}</b>\nUsername: <b>{esc(uname)}</b>\n"
        f"Telegram ID: <code>{message.from_user.id}</code>\n\n📦 Всего заказов: <b>{len(orders)}</b>", main_menu())

@dp.message(F.text == "💬 Поддержка")
async def support(message: Message, state: FSMContext):
    await state.clear()
    if SUPPORT_USERNAME:
        uname = str(SUPPORT_USERNAME).lstrip("@")
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в поддержку", url=f"https://t.me/{uname}")],
            [InlineKeyboardButton(text="⬅️ В магазин", callback_data="back_main")],
        ])
        await send_screen(message, "💬 <b>Поддержка</b>\n\nЕсли есть вопросы по заказу, напишите в поддержку:", markup)
    else:
        await send_screen(message, "💬 <b>Поддержка пока не настроена.</b>", main_menu())

async def process_crypto_paid_order(order_id):
    order = await get_order(order_id)
    if not order:
        return False
    _, telegram_id, username, order_type, amount, price, status, invoice_id, invoice_url, created_at = order
    if status != "WAITING_PAYMENT":
        return False
    await set_order_status(order_id, "PROCESSING")
    if stars_order_base(order_type).startswith("STARS"):
        product = stars_product(order_type, amount)
        user_text = "Заказ оформлен! Stars будут отправлены указанному получателю в течение 24 часов."
    elif order_type.startswith("PREMIUM_"):
        months = order_type.removeprefix("PREMIUM_")
        product = f"Telegram Premium — {months} месяцев; получатель {amount}"
        user_text = "Заказ оформлен! Telegram Premium будет активирован в течение 24 часов."
    else:
        product = order_type
        user_text = "Заказ оформлен! Заказ будет обработан в течение 24 часов."
    try:
        await bot.send_message(telegram_id, f"✅ <b>{user_text}</b>\n\nЗаказ №<b>{order_id}</b>", reply_markup=inline_back())
    except Exception:
        log.exception("Не удалось уведомить пользователя о заказе %s", order_id)
    try:
        await bot.send_message(ADMIN_ID, "💰 <b>Оплата Crypto Bot подтверждена!</b>\n\n"
            f"Заказ №<b>{order_id}</b>\nПокупатель: <b>{esc(username)}</b>\nTelegram ID: <code>{telegram_id}</code>\n"
            f"Товар: <b>{esc(product)}</b>\nСумма: <b>{format_usd(price)} ({format_kgs(price)})</b>", reply_markup=admin_order_keyboard(order_id))
    except Exception:
        log.exception("Не удалось уведомить администратора о заказе %s", order_id)
    return True

@dp.callback_query(F.data.startswith("check_payment:"))
async def check_payment(callback: CallbackQuery):
    await callback.answer()
    try:
        order_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.message.answer("❌ Ошибка заказа.")
        return
    order = await get_order(order_id)
    if not order:
        await callback.message.answer("❌ Заказ не найден.")
        return
    _, telegram_id, username, order_type, amount, price, status, invoice_id, invoice_url, created_at = order
    if telegram_id != callback.from_user.id:
        await callback.message.answer("❌ Этот заказ вам не принадлежит.")
        return
    if status == "PROCESSING":
        await callback.message.answer("✅ Оплата уже подтверждена. Заказ находится в обработке.")
        return
    if status == "COMPLETED":
        await callback.message.answer("✅ Этот заказ уже выполнен.")
        return
    if status == "REJECTED":
        await callback.message.answer("❌ Этот заказ был отклонён.")
        return
    if status != "WAITING_PAYMENT" or not invoice_id:
        await callback.message.answer("❌ Активный счёт не найден.")
        return
    try:
        invoice = await get_crypto_invoice(invoice_id)
    except Exception:
        log.exception("Crypto payment check failed")
        await callback.message.answer("⚠️ Не удалось проверить оплату. Попробуйте позже.")
        return
    if not invoice:
        await callback.message.answer("⚠️ Счёт не найден в Crypto Bot.")
        return
    if invoice.get("status") != "paid":
        await callback.message.answer("⏳ Оплата пока не найдена. Если уже оплатили, подождите и проверьте снова.")
        return
    if await process_crypto_paid_order(order_id):
        await callback.message.answer(f"✅ Оплата подтверждена! Заказ №<b>{order_id}</b> оформлен.")

async def payment_checker():
    while True:
        try:
            for row in await get_waiting_payment_orders():
                order_id, telegram_id, username, order_type, amount, price, status, invoice_id, invoice_url, created_at = row
                if not invoice_id:
                    continue
                try:
                    invoice = await get_crypto_invoice(invoice_id)
                    if invoice and invoice.get("status") == "paid":
                        await process_crypto_paid_order(order_id)
                except Exception:
                    log.exception("Ошибка проверки оплаты заказа %s", order_id)
        except Exception:
            log.exception("Payment checker error")
        await asyncio.sleep(30)

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    orders = await get_pending_admin_orders()
    if not orders:
        await message.answer("🛠 <b>Админ-панель</b>\n\nНет заказов, ожидающих обработки.")
        return
    await message.answer(f"🛠 <b>Админ-панель</b>\n\nОжидают обработки: <b>{len(orders)}</b>")
    for row in orders:
        order_id, telegram_id, username, order_type, amount, price, status, invoice_id, invoice_url, created_at = row
        if stars_order_base(order_type).startswith("STARS"):
            product = stars_product(order_type, amount)
        elif order_type.startswith("PREMIUM_"):
            months = order_type.removeprefix("PREMIUM_").removesuffix("_OPTIMA")
            product = f"Premium {months} месяцев; получатель {amount}"
        else:
            product = order_type
        await message.answer("📦 <b>Заказ</b>\n\n"
            f"№ <b>{order_id}</b>\nПокупатель: <b>{esc(username or 'не указан')}</b>\nID: <code>{telegram_id}</code>\n"
            f"Товар: <b>{esc(product)}</b>\nСумма: <b>{format_usd(price)} ({format_kgs(price)})</b>\nСтатус: <b>{esc(status)}</b>", reply_markup=admin_order_keyboard(order_id))

@dp.callback_query(F.data.startswith("admin_complete:"))
async def admin_complete(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    try:
        order_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    order = await get_order(order_id)
    if not order:
        await callback.message.answer("❌ Заказ не найден.")
        return
    _, telegram_id, username, order_type, amount, price, status, invoice_id, invoice_url, created_at = order
    if status != "PROCESSING":
        await callback.message.answer(f"⚠️ Этот заказ нельзя завершить. Текущий статус: {status}")
        return
    await set_order_status(order_id, "COMPLETED")
    try:
        await bot.send_message(telegram_id, f"✅ <b>Заказ №{order_id} выполнен!</b>\n\nСпасибо за покупку в Starzo.", reply_markup=inline_back())
    except Exception:
        log.exception("Не удалось уведомить пользователя о выполнении заказа")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(f"✅ Заказ №<b>{order_id}</b> отмечен как выполненный.")

@dp.callback_query(F.data.startswith("admin_reject:"))
async def admin_reject(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    try:
        order_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    order = await get_order(order_id)
    if not order:
        await callback.message.answer("❌ Заказ не найден.")
        return
    if order[6] != "PROCESSING":
        await callback.message.answer("⚠️ Этот заказ уже обработан или ещё не оплачен.")
        return
    await state.set_state(RejectState.waiting_reason)
    await state.update_data(reject_order_id=order_id)
    await callback.message.answer(f"Напишите причину отклонения заказа №{order_id}. Она будет отправлена покупателю.")

@dp.message(RejectState.waiting_reason)
async def reject_reason(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    reason = (message.text or "").strip()
    if len(reason) < 3:
        await message.answer("Укажите причину подробнее (минимум 3 символа).")
        return
    data = await state.get_data()
    order_id = data.get("reject_order_id")
    order = await get_order(order_id) if order_id else None
    if not order or order[6] != "PROCESSING":
        await state.clear()
        await message.answer("⚠️ Заказ не найден или уже обработан.")
        return
    _, telegram_id, username, order_type, amount, price, status, invoice_id, invoice_url, created_at = order
    await set_order_status(order_id, "REJECTED")
    try:
        await bot.send_message(telegram_id, f"❌ <b>Заказ №{order_id} отклонён.</b>\n\nПричина: {esc(reason)}\n\nЕсли у вас остались вопросы, обратитесь в поддержку.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Поддержка", callback_data="support_inline")],
            [InlineKeyboardButton(text="🛍 В магазин", callback_data="back_main")],
        ]))
    except Exception:
        log.exception("Не удалось уведомить пользователя об отклонении")
    await state.clear()
    await message.answer(f"❌ Заказ №<b>{order_id}</b> отклонён. Причина отправлена покупателю.")

@dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    try:
        await callback.message.edit_text("🛍 <b>Магазин Starzo</b>\n\nВыберите нужное действие:", reply_markup=None)
        sent = callback.message
    except Exception:
        sent = await callback.message.answer("🛍 <b>Магазин Starzo</b>\n\nВыберите нужное действие:")
    await clean_screen(callback.from_user.id)
    last_screen[callback.from_user.id] = (sent.chat.id, sent.message_id)
    # Reply keyboard appears by sending a separate message because inline keyboards
    # cannot be replaced by reply keyboards on an edited message.
    await callback.message.answer("Меню Starzo:", reply_markup=main_menu())

@dp.callback_query(F.data == "support_inline")
async def support_inline(callback: CallbackQuery):
    await callback.answer()
    if SUPPORT_USERNAME:
        uname = str(SUPPORT_USERNAME).lstrip("@")
        await callback.message.answer("💬 <b>Поддержка</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в поддержку", url=f"https://t.me/{uname}")],
            [InlineKeyboardButton(text="⬅️ В магазин", callback_data="back_main")],
        ]))
    else:
        await callback.message.answer("Поддержка пока не настроена.", reply_markup=main_menu())

def broadcast_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить всем", callback_data="broadcast_send")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")],
    ])


@dp.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await state.set_state(BroadcastState.waiting_message)
    await message.answer(
        "📣 <b>Рассылка Starzo</b>\n\n"
        "Отправьте следующим сообщением текст, фото, видео или другой материал, который нужно разослать.\n"
        "После этого бот покажет предпросмотр и попросит подтверждение.\n\n"
        "Для отмены отправьте /cancel."
    )


@dp.message(Command("cancel"), BroadcastState.waiting_message)
async def broadcast_cancel_command(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@dp.message(BroadcastState.waiting_message)
async def broadcast_preview(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.")
        return
    users = await get_all_user_ids()
    if not users:
        await state.clear()
        await message.answer("Пока нет пользователей для рассылки. Пользователи попадут в список после запуска бота.")
        return
    await state.update_data(
        broadcast_chat_id=message.chat.id,
        broadcast_message_id=message.message_id,
        broadcast_user_count=len(users),
    )
    try:
        # copy_message не поддерживает reply_markup: сначала копируем материал,
        # затем отдельным сообщением показываем кнопки подтверждения.
        await bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await message.answer(
            "📣 <b>Предпросмотр рассылки</b>\n\n"
            f"👥 Получателей: <b>{len(users)}</b>\n\n"
            "Проверьте материал выше и подтвердите отправку:",
            reply_markup=broadcast_confirm_keyboard(),
        )
    except Exception:
        log.exception("Не удалось показать предпросмотр рассылки")
        await state.clear()
        await message.answer("❌ Не удалось создать предпросмотр. Попробуйте отправить другое сообщение.")
        return
    await state.set_state(None)


@dp.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Рассылка отменена")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("❌ Рассылка отменена.")


@dp.callback_query(F.data == "broadcast_send")
async def broadcast_send(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    source_chat_id = data.get("broadcast_chat_id")
    source_message_id = data.get("broadcast_message_id")
    if not source_chat_id or not source_message_id:
        await state.clear()
        await callback.answer("Предпросмотр устарел. Начните заново через /broadcast", show_alert=True)
        return
    await callback.answer("Рассылка началась")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    user_ids = await get_all_user_ids()
    sent_count = 0
    failed_count = 0
    status_message = await callback.message.answer(
        f"📣 <b>Рассылка выполняется…</b>\nПолучателей: {len(user_ids)}"
    )
    for user_id in user_ids:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
            sent_count += 1
        except Exception as exc:
            failed_count += 1
            log.info("Рассылка не доставлена user_id=%s: %s", user_id, exc)
        await asyncio.sleep(0.04)
    await state.clear()
    try:
        await status_message.edit_text(
            "✅ <b>Рассылка завершена</b>\n\n"
            f"👥 Получателей в списке: <b>{len(user_ids)}</b>\n"
            f"✅ Успешно отправлено: <b>{sent_count}</b>\n"
            f"⚠️ Не доставлено: <b>{failed_count}</b>\n\n"
            "Пользователи, заблокировавшие бота, обычно попадают в число недоставленных."
        )
    except Exception:
        await callback.message.answer(
            f"Рассылка завершена. Успешно: {sent_count}; не доставлено: {failed_count}."
        )


async def main():
    task = None
    try:
        log.info("Starzo: initializing database (existing starzo.db will be preserved)")
        await init_db()
        # Validate Telegram token early, so a bad token appears clearly in logs.
        me = await bot.get_me()
        log.info("Telegram login successful: @%s (id=%s)", me.username, me.id)
        task = asyncio.create_task(payment_checker(), name="starzo-payment-checker")
        log.info("Starting aiogram polling")
        await dp.start_polling(bot, close_bot_session=False)
    except Exception:
        log.exception("Starzo stopped because of an unhandled startup/runtime error")
        raise
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Payment checker stopped with an error")
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Starzo stopped by KeyboardInterrupt")
