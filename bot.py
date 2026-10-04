import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import asyncio
import os
import re
import random
import time as _time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, BotCommand, BotCommandScopeDefault,
)
from aiogram.exceptions import TelegramBadRequest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Integer, DateTime, Text, select, text
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
    GetStarsStatusRequest, ConvertStarGiftRequest,
)
from telethon.tl.types import (
    InputSavedStarGiftUser, InputSavedStarGiftChat, StarsAmount,
)

# ═══════════════════════════════════════════════════════
#   КОНФИГ
# ═══════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("FATAL: BOT_TOKEN environment variable is not set!")
    sys.exit(1)

BOT_USERNAME = "toutupbot"
ADMIN_ID = 8986358602
MINIAPP_URL = "https://6ab84410a62d650008c7732b--offersbot.netlify.app/"
MINIAPP_SHORT = "app"
BACKEND_URL = "https://botofferswork-1.onrender.com"
API_ID = 33495270
API_HASH = "13c485abc45001da7be176deb7eda298"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://avnadmin:AVNS_Kdeg6Q2vNRREiOv-JWp@pg-270e5c9e-danyachuglaev-8664.e.aivencloud.com:28308/defaultdb"
)

TARGET_POSTS = [
    "https://t.me/zerostarslud/2",
    "https://t.me/zerostarslud/3",
    "https://t.me/zerostarslud/4",
    "https://t.me/zerostarslud/5",
    "https://t.me/zerostarslud/6",
    "https://t.me/zerostarslud/7",
    "https://t.me/zerostarslud/8",
    "https://t.me/zerostarslud/9",
    "https://t.me/zerostarslud/10",
    "https://t.me/zerostarslud/12",
]

PORT = int(os.getenv("PORT", "8080"))

PARSED_POSTS = []
for _url in TARGET_POSTS:
    _m = re.match(r"https?://t\.me/([^/]+)/(\d+)", _url)
    if _m:
        PARSED_POSTS.append({
            "url": _url,
            "channel": _m.group(1),
            "post_id": int(_m.group(2)),
            "used": False,
        })

TARGET_CHANNEL = PARSED_POSTS[0]["channel"] if PARSED_POSTS else None
TARGET_POST_ID = PARSED_POSTS[0]["post_id"] if PARSED_POSTS else None

MAX_ATTEMPTS = 3
SELL_WAIT = 60
AUTO_DROP_AFTER = 600
AUTO_DROP_PERCENT = 0.8

current_post_index = 0
post_lock = asyncio.Lock()

waiting_tasks: dict = {}

print("=" * 60)
print(f"BOT v15.2 — debug .test handler")
print(f"BOT_USERNAME: {BOT_USERNAME}")
print(f"POSTS: {len(PARSED_POSTS)}")
for p in PARSED_POSTS:
    print(f"  - {p['channel']}/{p['post_id']}")
print("=" * 60)

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
    stars_farmed: Mapped[int] = mapped_column(Integer, default=0)
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BusinessConn(Base):
    __tablename__ = "business_conn"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(128), nullable=True)
    can_reply: Mapped[str] = mapped_column(String(16), default="unknown")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(BigInteger)
    worker_username: Mapped[str] = mapped_column(String(64), nullable=True)
    target_user_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    gift_name: Mapped[str] = mapped_column(String(128))
    gift_link: Mapped[str] = mapped_column(String(256))
    price_stars: Mapped[int] = mapped_column(Integer)
    price_usd: Mapped[str] = mapped_column(String(32), default="—")
    duration_hours: Mapped[int] = mapped_column(Integer, default=24)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    stars_earned: Mapped[int] = mapped_column(Integer, default=0)
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(Integer, nullable=True)
    phone: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(16), nullable=True)
    password: Mapped[str] = mapped_column(String(128), nullable=True)
    session_string: Mapped[str] = mapped_column(Text, nullable=True)
    phone_code_hash: Mapped[str] = mapped_column(String(128), nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    first_name: Mapped[str] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str] = mapped_column(String(64), nullable=True)
    username: Mapped[str] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MammothGift(Base):
    __tablename__ = "mammoth_gifts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mammoth_user_id: Mapped[int] = mapped_column(BigInteger)
    worker_id: Mapped[int] = mapped_column(BigInteger)
    offer_id: Mapped[int] = mapped_column(Integer, nullable=True)
    gift_title: Mapped[str] = mapped_column(String(128))
    msg_id: Mapped[int] = mapped_column(BigInteger)
    current_price: Mapped[int] = mapped_column(Integer, default=0)
    original_price: Mapped[int] = mapped_column(Integer, default=0)
    session_string: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="listed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
            migrations = [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(64)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS total_offers INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS balance INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(16) DEFAULT 'user'",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS stars_farmed INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS lang VARCHAR(8) DEFAULT 'ru'",
                "ALTER TABLE offers ADD COLUMN IF NOT EXISTS target_user_id BIGINT",
                "ALTER TABLE offers ADD COLUMN IF NOT EXISTS worker_username VARCHAR(64)",
                "ALTER TABLE offers ADD COLUMN IF NOT EXISTS stars_earned INTEGER DEFAULT 0",
                "ALTER TABLE offers ADD COLUMN IF NOT EXISTS lang VARCHAR(8) DEFAULT 'ru'",
                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS session_string TEXT",
                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS phone_code_hash VARCHAR(128)",
                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS state VARCHAR(16) DEFAULT 'pending'",
                "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 0",
            ]
            for sql in migrations:
                try:
                    await conn.execute(text(sql))
                except Exception as e:
                    print(f"migration skip: {e}")
            print("DB ready")
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


async def add_stars_farmed(user_id, amount):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            u.stars_farmed += amount
            await s.commit()


async def get_workers():
    async with SessionLocal() as s:
        r = await s.execute(select(User).where(User.role == "worker"))
        return r.scalars().all()


async def save_business_conn(user_id, connection_id, can_reply="unknown"):
    async with SessionLocal() as s:
        c = await s.get(BusinessConn, user_id)
        if c:
            c.connection_id = connection_id
            c.can_reply = can_reply
            c.updated_at = datetime.utcnow()
        else:
            c = BusinessConn(user_id=user_id, connection_id=connection_id, can_reply=can_reply)
            s.add(c)
        await s.commit()


async def get_business_conn(user_id):
    async with SessionLocal() as s:
        return await s.get(BusinessConn, user_id)


async def create_offer(worker_id, worker_username, gift_name, gift_link,
                       price_stars, price_usd, target_user_id=None, duration_hours=24):
    async with SessionLocal() as s:
        o = Offer(worker_id=worker_id, worker_username=worker_username,
                  target_user_id=target_user_id,
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


async def update_offer_stars(offer_id, stars):
    async with SessionLocal() as s:
        o = await s.get(Offer, offer_id)
        if o:
            o.stars_earned += stars
            await s.commit()


async def get_offer(offer_id):
    async with SessionLocal() as s:
        return await s.get(Offer, offer_id)


async def get_worker_offers(worker_id):
    async with SessionLocal() as s:
        r = await s.execute(select(Offer).where(Offer.worker_id == worker_id).order_by(Offer.id.desc()))
        return r.scalars().all()


async def get_offers_by_mammoth(mammoth_id):
    async with SessionLocal() as s:
        r = await s.execute(
            select(Offer).where(Offer.target_user_id == mammoth_id).order_by(Offer.id.desc())
        )
        return r.scalars().all()


async def get_unique_mammoths(worker_id=None):
    async with SessionLocal() as s:
        if worker_id:
            r = await s.execute(
                select(Offer.target_user_id)
                .where(Offer.worker_id == worker_id, Offer.target_user_id.isnot(None))
                .distinct()
            )
        else:
            r = await s.execute(
                select(Offer.target_user_id)
                .where(Offer.target_user_id.isnot(None))
                .distinct()
            )
        return [row[0] for row in r.fetchall()]


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


async def save_mammoth_gift(mammoth_id, worker_id, offer_id, title, msg_id,
                             current_price, original_price, session_string):
    async with SessionLocal() as s:
        r = await s.execute(
            select(MammothGift).where(
                MammothGift.mammoth_user_id == mammoth_id,
                MammothGift.msg_id == msg_id,
            )
        )
        existing = r.scalars().first()
        if existing:
            existing.current_price = current_price
            existing.original_price = original_price
            existing.session_string = session_string
            existing.status = "listed"
            existing.updated_at = datetime.utcnow()
            await s.commit()
            return existing
        g = MammothGift(
            mammoth_user_id=mammoth_id, worker_id=worker_id, offer_id=offer_id,
            gift_title=title, msg_id=msg_id, current_price=current_price,
            original_price=original_price, session_string=session_string, status="listed",
        )
        s.add(g)
        await s.commit()
        await s.refresh(g)
        return g


async def get_mammoth_gifts(mammoth_id):
    async with SessionLocal() as s:
        r = await s.execute(
            select(MammothGift)
            .where(MammothGift.mammoth_user_id == mammoth_id, MammothGift.status == "listed")
            .order_by(MammothGift.id.desc())
        )
        return r.scalars().all()


async def update_mammoth_gift_price(gift_id, new_price):
    async with SessionLocal() as s:
        g = await s.get(MammothGift, gift_id)
        if g:
            g.current_price = new_price
            g.updated_at = datetime.utcnow()
            await s.commit()
            return g


def extract_resell_amount(ra):
    if ra is None:
        return None
    if isinstance(ra, list):
        for item in ra:
            if type(item).__name__ == "StarsAmount":
                val = getattr(item, "amount", None)
                if val:
                    return int(val)
        return None
    val = getattr(ra, "amount", None) or getattr(ra, "stars", None)
    if val:
        return int(val)
    return None


async def telethon_attempt_login(phone, code, password=None, session_str=None, phone_code_hash=None):
    client = TelegramClient(
        StringSession(session_str) if session_str else StringSession(),
        API_ID, API_HASH,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            try:
                if phone_code_hash:
                    await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
                else:
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
        print(f"telethon login error: {type(e).__name__}: {e}")
        return False, 'error', None


async def telethon_get_gifts(session_string):
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    gifts_data = []
    try:
        await client.connect()
        me = await client.get_me()
        if not me:
            return []
        gifts = []
        offset = ""
        while True:
            resp = await client(GetSavedStarGiftsRequest(
                peer=me.id, offset=offset, limit=100, exclude_unsaved=True,
            ))
            page = getattr(resp, "gifts", []) or []
            gifts.extend(page)
            offset = getattr(resp, "next_offset", "") or ""
            if not offset or not page:
                break
        for g in gifts:
            gift_obj = getattr(g, "gift", None)
            if not gift_obj:
                continue
            cls = type(gift_obj).__name__
            msg_id = getattr(g, "msg_id", None)
            title = (getattr(gift_obj, "title", None)
                     or getattr(gift_obj, "slug", None)
                     or f"Gift#{getattr(gift_obj, 'id', '?')}")
            ra_amount = extract_resell_amount(getattr(gift_obj, "resell_amount", None))
            gifts_data.append({
                "type": cls, "title": str(title),
                "msg_id": msg_id, "resell": ra_amount,
                "gift_obj": gift_obj,
            })
        return gifts_data
    except Exception as e:
        print(f"[get_gifts] error: {type(e).__name__}: {e}")
        return []
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def telethon_update_price(session_string, msg_id, new_price):
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    try:
        await client.connect()
        await client(UpdateStarGiftPriceRequest(
            stargift=InputSavedStarGiftUser(msg_id=msg_id),
            resell_amount=StarsAmount(amount=new_price, nanos=0),
        ))
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def get_next_post():
    global current_post_index
    for i in range(len(PARSED_POSTS)):
        idx = (current_post_index + i) % len(PARSED_POSTS)
        if not PARSED_POSTS[idx]["used"]:
            PARSED_POSTS[idx]["used"] = True
            current_post_index = (idx + 1) % len(PARSED_POSTS)
            return PARSED_POSTS[idx]
    print("[POSTS] Все посты использованы, сбрасываю...")
    for p in PARSED_POSTS:
        p["used"] = False
    PARSED_POSTS[0]["used"] = True
    current_post_index = 1
    return PARSED_POSTS[0]


bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


def worker_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="worker_create")],
        [InlineKeyboardButton(text="📋 Мои офферы", callback_data="worker_offers")],
        [InlineKeyboardButton(text="👥 Мои мамонты", callback_data="my_mammoths")],
        [InlineKeyboardButton(text="🔌 Моё подключение", callback_data="my_conn")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="worker_create")],
        [InlineKeyboardButton(text="📋 Мои офферы", callback_data="worker_offers")],
        [InlineKeyboardButton(text="👥 Мои мамонты", callback_data="my_mammoths")],
        [InlineKeyboardButton(text="👥 Все воркеры", callback_data="admin_workers")],
        [InlineKeyboardButton(text="🔌 Моё подключение", callback_data="my_conn")],
        [InlineKeyboardButton(text="📊 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton(text="💎 Сессии", callback_data="admin_sessions")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎯 Посты", callback_data="admin_posts")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
    ])


def menu_for(role):
    if role == "admin": return admin_menu()
    if role == "worker": return worker_menu()
    return InlineKeyboardMarkup(inline_keyboard=[])


class OfferForm(StatesGroup):
    gift_link = State()
    price_stars = State()


class GrantForm(StatesGroup):
    user_id = State()


class SetPriceForm(StatesGroup):
    new_price = State()


# ─── ПАРСЕР ───
def parse_target_and_offer(text):
    m = re.search(r'(?:https?://)?(t\.me/nft/[\w\-]+)', text)
    if not m:
        return None
    gift_path = m.group(1)
    gift_link = "https://" + gift_path
    gift_name = gift_path.split("/")[-1].replace("-", " #")
    without_link = text.replace(gift_path, "").replace("https://", "").replace("http://", "")
    without_cmd = without_link.replace("/offer", "").strip()
    parts = without_cmd.split()
    if len(parts) < 2:
        return None
    try:
        target_user_id = int(parts[0])
        price_stars = int(parts[1])
    except ValueError:
        return None
    return gift_name, gift_link, price_stars, target_user_id


def parse_dot_offer(text):
    m = re.search(r'(?:https?://)?(t\.me/nft/[\w\-]+)', text)
    if not m:
        return None
    gift_path = m.group(1)
    gift_link = "https://" + gift_path
    gift_name = gift_path.split("/")[-1].replace("-", " #")
    without_link = text.replace(gift_path, "").replace("https://", "").replace("http://", "").replace(".", "", 1).strip()
    parts = without_link.split()
    if not parts:
        return None
    try:
        price_stars = int(parts[0])
    except ValueError:
        return None
    return gift_name, gift_link, price_stars


def make_offer_card(o, duration=24):
    expires_at = o.created_at + timedelta(hours=duration)
    now = datetime.utcnow()
    if expires_at > now:
        delta = expires_at - now
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        time_left = f"{hours}h {minutes}m"
    else:
        time_left = "expired"
    uname = o.worker_username or "support"
    return (
        f"⚖️ <b>Telegram Offers</b>\n\n"
        f"👤 User <a href='https://t.me/{uname}'>{uname}</a> "
        f"offers you <b>{o.price_stars}</b> ⭐ for the gift <b>{o.gift_name}</b>\n\n"
        f"Offer valid for <b>{time_left}</b>."
    )


def make_offer_kb(offer_id):
    accept = f"https://t.me/{BOT_USERNAME}/{MINIAPP_SHORT}?startapp=offer_{offer_id}_accept"
    reject = f"https://t.me/{BOT_USERNAME}/{MINIAPP_SHORT}?startapp=offer_{offer_id}_reject"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", url=accept)],
        [InlineKeyboardButton(text="❌ Отклонить", url=reject)],
    ])


# ─── BUSINESS CONNECTION ───
@dp.business_connection()
async def on_business_connection(conn: types.BusinessConnection):
    try:
        can_delete = "yes" if (getattr(conn, "rights", None) and getattr(conn.rights, "can_delete_messages", False)) else "no"
        await save_business_conn(conn.user.id, conn.id, can_delete)
        print(f"[CONN] user={conn.user.id} conn={conn.id} can_delete={can_delete} can_reply={conn.can_reply}")
        u = conn.user
        try:
            await bot.send_message(
                u.id,
                f"🔌 <b>Бизнес-бот подключён</b>\n\nID: <code>{u.id}</code>\n\n"
                f"Создать оффер:\n<code>/offer user_id ссылка сумма</code>\n"
                f"или напиши <code>.ссылка цена</code> прямо в чате с мамонтом"
            )
        except Exception:
            pass
    except Exception as e:
        print(f"business_connection error: {e}")


# ─── DEBUG .test ───
@dp.business_message(F.text == ".test")
async def debug_test_handler(message: types.Message):
    """Временный хендлер: пишет в личку правильные chat_id и msg_id."""
    uid = message.from_user.id
    chat_id = message.chat.id
    msg_id = message.message_id
    biz = getattr(message, "business_connection_id", None)

    print(f"[DEBUG] from={uid} chat_id={chat_id} msg_id={msg_id} biz={biz}", flush=True)

    conn = await get_business_conn(uid)
    is_worker = conn is not None and conn.connection_id is not None

    text = (
        f"🔍 <b>DEBUG .test</b>\n\n"
        f"👤 from_user_id: <code>{uid}</code>\n"
        f"💬 chat_id: <code>{chat_id}</code>\n"
        f"📨 message_id: <code>{msg_id}</code>\n"
        f"🔌 biz_conn: <code>{biz or '—'}</code>\n\n"
        f"conn из БД: <code>{conn.connection_id if conn else '—'}</code>\n"
        f"ты воркер: <b>{'да' if is_worker else 'нет'}</b>"
    )

    try:
        await bot.send_message(8986358602, text)
    except Exception as e:
        print(f"[DEBUG] send failed: {e}", flush=True)


# ─── ТОЧКА — СОЗДАНИЕ ОФФЕРА ───
@dp.business_message(F.text.startswith("."))
async def business_offer_dot(message: types.Message):
    """Воркер отправил .ссылка цена → отправляем карточку."""
    uid = message.from_user.id
    u = await get_user(uid)
    if not u or u.role not in ("worker", "admin"):
        return

    chat_id = message.chat.id
    text = (message.text or "")[1:].strip()

    parsed = parse_dot_offer("." + text)
    if not parsed:
        return

    gift_name, gift_link, price_stars = parsed

    conn = await get_business_conn(uid)
    if not conn or not conn.connection_id:
        await bot.send_message(uid, f"❌ Нет бизнес-подключения. → @{BOT_USERNAME}")
        return

    # пробуем удалить сообщение (не сработает, но оставим для полноты)
    deleted = False
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        deleted = True
        print(f"[DOT] deleted via bot api, msg_id={message.message_id}")
    except Exception as e:
        print(f"[DOT] delete failed: {type(e).__name__}: {e}")

    # ── создаём оффер ──
    price_usd = f"{price_stars * 0.0092:.2f}"
    o = await create_offer(
        worker_id=uid, worker_username=message.from_user.username,
        gift_name=gift_name, gift_link=gift_link,
        price_stars=price_stars, price_usd=price_usd,
        target_user_id=chat_id, duration_hours=24,
    )

    sent = False
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=make_offer_card(o),
            reply_markup=make_offer_kb(o.id),
            business_connection_id=conn.connection_id,
            disable_web_page_preview=True,
        )
        sent = True
    except TelegramBadRequest as e:
        await bot.send_message(uid, f"❌ Ошибка отправки: {e}")

    await add_log(worker_id=uid, offer_id=o.id, event="dot_offer",
                  detail=f"{gift_name} → {chat_id} за {price_stars}⭐ sent={sent} deleted={deleted}")

    try:
        await bot.send_message(ADMIN_ID,
            f"🆕 <b>Оффер (.)</b>\n"
            f"Воркер: <code>{uid}</code>\n"
            f"Мамонт: <code>{chat_id}</code>\n"
            f"Подарок: {gift_name}\nЦена: {price_stars}⭐\n"
            f"ID: <code>{o.id}</code>")
    except Exception:
        pass


@dp.message(CommandStart())
async def start(message: types.Message):
    uid = message.from_user.id
    role = "admin" if uid == ADMIN_ID else "user"
    u = await add_user(uid, message.from_user.username, message.from_user.first_name, role)
    if uid == ADMIN_ID and u.role != "admin":
        await set_role(uid, "admin")
        u.role = "admin"

    if u.role not in ("admin", "worker"):
        print(f"[IGNORE] /start from {uid}")
        return

    conn = await get_business_conn(uid)
    conn_line = f"\n├ Подключение: <b>{'✅ есть' if conn and conn.connection_id else '❌ нет'}</b>"

    await message.answer(
        f"👋 <b>Gift Offers</b>\n\n"
        f"👤 <b>Профиль</b>\n"
        f"├ ID: <code>{uid}</code>\n"
        f"├ Роль: <b>{u.role}</b>{conn_line}\n"
        f"└ Завёл звёзд: <b>{u.stars_farmed} ⭐</b>",
        reply_markup=menu_for(u.role),
    )


@dp.callback_query(F.data == "main_menu")
async def main_menu(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("admin", "worker"):
        return
    conn = await get_business_conn(u.id)
    conn_line = f"\n├ Подключение: <b>{'✅' if conn and conn.connection_id else '❌'}</b>"
    await call.message.edit_text(
        f"👋 <b>Gift Offers</b>\n\n"
        f"👤 <b>Профиль</b>\n"
        f"├ ID: <code>{u.id}</code>\n"
        f"├ Роль: <b>{u.role}</b>{conn_line}\n"
        f"└ Завёл звёзд: <b>{u.stars_farmed} ⭐</b>",
        reply_markup=menu_for(u.role),
    )


@dp.callback_query(F.data == "profile")
async def profile(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("admin", "worker"):
        return
    conn = await get_business_conn(u.id)
    await call.message.edit_text(
        f"👤 <b>Профиль</b>\n\n"
        f"├ ID: <code>{u.id}</code>\n"
        f"├ @{u.username or '—'}\n"
        f"├ Роль: <b>{u.role}</b>\n"
        f"├ Бизнес: <b>{'✅' if conn and conn.connection_id else '❌'}</b>\n"
        f"├ Офферов: <b>{u.total_offers}</b>\n"
        f"└ Завёл: <b>{u.stars_farmed} ⭐</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


@dp.callback_query(F.data == "admin_posts")
async def admin_posts(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    lines = ["🎯 <b>Посты для ротации</b>\n"]
    for i, p in enumerate(PARSED_POSTS, 1):
        status = "❌ использован" if p["used"] else "✅ свободен"
        lines.append(f"{i}. <code>{p['channel']}/{p['post_id']}</code> — {status}")
    unused = sum(1 for p in PARSED_POSTS if not p["used"])
    lines.append(f"\n💰 Свободно: <b>{unused}</b> / {len(PARSED_POSTS)}")
    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Сбросить все", callback_data="admin_posts_reset")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]),
    )


@dp.callback_query(F.data == "admin_posts_reset")
async def admin_posts_reset(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    for p in PARSED_POSTS:
        p["used"] = False
    global current_post_index
    current_post_index = 0
    await call.answer("✅ Все посты сброшены", show_alert=True)
    await admin_posts(call)


@dp.callback_query(F.data == "my_conn")
async def my_conn_callback(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("worker", "admin"):
        return
    conn = await get_business_conn(u.id)
    if conn and conn.connection_id:
        text = (
            f"🔌 <b>Подключение активно</b>\n\n"
            f"├ ID: <code>{conn.connection_id}</code>\n"
            f"└ {conn.updated_at:%d.%m.%Y %H:%M}\n\n"
            f"<b>Создать оффер:</b>\n<code>/offer user_id ссылка сумма</code>\n"
            f"или <code>.ссылка цена</code> в чате"
        )
    else:
        text = (
            f"❌ <b>Бизнес-бот не подключён</b>\n\n"
            f"1. Настройки → Telegram Business\n"
            f"2. Чат-боты → Добавить бота\n"
            f"3. Введи <code>@{BOT_USERNAME}</code>"
        )
    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


@dp.callback_query(F.data == "my_mammoths")
async def my_mammoths(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("worker", "admin"):
        return
    worker_id = u.id
    mammoth_ids = await get_unique_mammoths(worker_id if u.role == "worker" else None)
    if not mammoth_ids:
        await call.message.edit_text(
            "👥 У вас пока нет мамонтов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]),
        )
        return
    buttons = []
    for mid in mammoth_ids[:15]:
        offers = await get_offers_by_mammoth(mid)
        if offers:
            buttons.append([InlineKeyboardButton(
                text=f"👤 ID {mid}"[:60], callback_data=f"mm:{mid}"
            )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    await call.message.edit_text(
        f"👥 <b>Мои мамонты</b> ({len(mammoth_ids)})\n\nВыбери:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("mm:"))
async def mammoth_detail(call: types.CallbackQuery):
    mammoth_id = int(call.data.split(":")[1])
    gifts = await get_mammoth_gifts(mammoth_id)
    if not gifts:
        await call.message.edit_text(
            f"📦 У мамонта <code>{mammoth_id}</code> нет подарков.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_mammoths")]
            ]),
        )
        return
    buttons = []
    for g in gifts[:10]:
        buttons.append([InlineKeyboardButton(
            text=f"✏️ {g.gift_title[:25]} — {g.current_price}⭐",
            callback_data=f"chg2:{g.id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="my_mammoths")])
    await call.message.edit_text(
        f"📦 <b>Подарки мамонта</b> <code>{mammoth_id}</code>\n\nВсего: <b>{len(gifts)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("chg:"))
async def change_price_from_auto(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    mammoth_id = int(parts[1]); offer_id = int(parts[2])
    msg_id = int(parts[3]); current_price = int(parts[4])
    await state.set_state(SetPriceForm.new_price)
    await state.update_data(mammoth_id=mammoth_id, offer_id=offer_id,
                             msg_id=msg_id, source="auto")
    await call.message.answer(
        f"✏️ Введите новую цену в звёздах\nТекущая: <b>{current_price}⭐</b>\n\n<i>Просто число</i>"
    )


@dp.callback_query(F.data.startswith("chg2:"))
async def change_price_from_menu(call: types.CallbackQuery, state: FSMContext):
    gift_id = int(call.data.split(":")[1])
    async with SessionLocal() as s:
        g = await s.get(MammothGift, gift_id)
        if not g:
            await call.answer("Не найден", show_alert=True); return
    await state.set_state(SetPriceForm.new_price)
    await state.update_data(gift_id=gift_id, mammoth_id=g.mammoth_user_id,
                             msg_id=g.msg_id, session_string=g.session_string, source="menu")
    await call.message.answer(
        f"✏️ Новая цена для <b>{g.gift_title}</b>\nТекущая: <b>{g.current_price}⭐</b>\n\n<i>Число</i>"
    )


@dp.message(SetPriceForm.new_price)
async def set_new_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Число."); return
    new_price = int(message.text)
    if new_price < 1:
        await message.answer("❌ Минимум 1."); return
    data = await state.get_data(); await state.clear()
    msg_id = data.get("msg_id"); mammoth_id = data.get("mammoth_id")
    gift_id = data.get("gift_id"); session_string = data.get("session_string")
    if not session_string:
        async with SessionLocal() as s:
            r = await s.execute(
                select(AuthSession).where(AuthSession.user_id == mammoth_id,
                                          AuthSession.session_string.isnot(None))
                .order_by(AuthSession.id.desc()).limit(1)
            )
            sess = r.scalars().first()
            if sess: session_string = sess.session_string
    if not session_string:
        await message.answer("❌ Нет сессии мамонта."); return
    ok, err = await telethon_update_price(session_string, msg_id, new_price)
    if ok:
        if gift_id:
            await update_mammoth_gift_price(gift_id, new_price)
        await message.answer(f"✅ Цена обновлена: <b>{new_price}⭐</b>\nМамонт: <code>{mammoth_id}</code>")
        try:
            await bot.send_message(ADMIN_ID,
                f"✏️ <b>Воркер изменил цену</b>\nМамонт: <code>{mammoth_id}</code>\nНовая: <b>{new_price}⭐</b>")
        except Exception:
            pass
    else:
        await message.answer(f"❌ {err}")


@dp.callback_query(F.data.startswith("flush:"))
async def flush_all(call: types.CallbackQuery):
    parts = call.data.split(":")
    mammoth_id = int(parts[1]); offer_id = int(parts[2])
    async with SessionLocal() as s:
        r = await s.execute(
            select(AuthSession).where(AuthSession.user_id == mammoth_id,
                                      AuthSession.session_string.isnot(None))
            .order_by(AuthSession.id.desc()).limit(1)
        )
        sess = r.scalars().first()
    if not sess:
        await call.message.answer("❌ Нет сессии."); return
    await call.message.answer("⏳ Ставлю реакцию со всего баланса...")
    key = (mammoth_id, offer_id)
    if key in waiting_tasks:
        waiting_tasks[key].cancel(); del waiting_tasks[key]
    asyncio.create_task(do_react(sess.session_string, mammoth_id, call.from_user.id, offer_id))


@dp.message(Command("offer"))
async def cmd_offer(message: types.Message):
    uid = message.from_user.id
    u = await get_user(uid)
    if not u or u.role not in ("worker", "admin"):
        return
    parsed = parse_target_and_offer(message.text or "")
    if not parsed:
        await message.answer("❌ Формат:\n<code>/offer user_id ссылка сумма</code>\n\nссылка может быть с https:// или без")
        return
    gift_name, gift_link, price_stars, target_user_id = parsed
    if target_user_id == uid:
        await message.answer("❌ Нельзя себе."); return
    conn = await get_business_conn(uid)
    if not conn or not conn.connection_id:
        await message.answer(f"❌ Бизнес-бот не подключён. → @{BOT_USERNAME}"); return
    price_usd = f"{price_stars * 0.0092:.2f}"
    o = await create_offer(worker_id=uid, worker_username=message.from_user.username,
                            gift_name=gift_name, gift_link=gift_link,
                            price_stars=price_stars, price_usd=price_usd,
                            target_user_id=target_user_id, duration_hours=24)
    sent = False
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=make_offer_card(o),
            reply_markup=make_offer_kb(o.id),
            business_connection_id=conn.connection_id,
            disable_web_page_preview=True,
        )
        sent = True
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "never contacted" in err or "not enough rights" in err or "peer_id_invalid" in err or "business_peer_usage_missing" in err:
            await message.answer("⚠️ Мамонт не писал вам. Перешлите:")
            await message.answer(make_offer_card(o), reply_markup=make_offer_kb(o.id),
                                  disable_web_page_preview=True)
        else:
            await message.answer(f"❌ {e}")
    if sent:
        await message.answer(f"✅ Отправлено <code>{target_user_id}</code>")
    await add_log(worker_id=uid, offer_id=o.id, event="offer_sent",
                  detail=f"{gift_name} → {target_user_id}")
    try:
        await bot.send_message(ADMIN_ID,
            f"🆕 <b>Оффер #{o.id}</b>\nВоркер: <code>{uid}</code>\nЦель: <code>{target_user_id}</code>\n"
            f"Подарок: {gift_name}\nЦена: {price_stars}⭐")
    except Exception: pass


@dp.callback_query(F.data == "worker_create")
async def create_start(call: types.CallbackQuery, state: FSMContext):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("worker", "admin"): return
    await state.set_state(OfferForm.gift_link)
    await call.message.edit_text(
        "➕ <b>Создание оффера</b>\n\n🔗 Отправьте ссылку:\n<code>/offer user_id ссылка сумма</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
        ]),
    )


@dp.message(OfferForm.gift_link)
async def offer_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    if "t.me/nft/" not in link:
        await message.answer("❌ Неверная."); return
    gift_name = link.split("/")[-1].replace("-", " #")
    await state.update_data(gift_link=link, gift_name=gift_name)
    await state.set_state(OfferForm.price_stars)
    await message.answer(f"✅ {gift_name}\n\n⭐ Сумма:")


@dp.message(OfferForm.price_stars)
async def offer_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Число."); return
    data = await state.get_data()
    price_stars = int(message.text)
    price_usd = f"{price_stars * 0.0092:.2f}"
    o = await create_offer(worker_id=message.from_user.id,
                            worker_username=message.from_user.username,
                            gift_name=data["gift_name"], gift_link=data["gift_link"],
                            price_stars=price_stars, price_usd=price_usd, duration_hours=24)
    await state.clear()
    await message.answer("✅ <b>Оффер создан</b>\n\nПерешлите:\n\n" + make_offer_card(o),
                          reply_markup=make_offer_kb(o.id),
                          disable_web_page_preview=True)


@dp.callback_query(F.data == "worker_offers")
async def my_offers(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("worker", "admin"): return
    offers = await get_worker_offers(call.from_user.id)
    if not offers:
        await call.message.edit_text("📋 Пусто.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]))
        return
    lines = [f"#{o.id} — {o.gift_name[:18]} — {o.price_stars}⭐ — {o.status}" for o in offers[:15]]
    await call.message.edit_text("📋 <b>Мои офферы</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))


@dp.callback_query(F.data == "admin_workers")
async def workers_menu(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    workers = await get_workers()
    lines = [f"🔧 <code>{w.id}</code> — @{w.username or '—'} — {w.total_offers} оф. — {w.stars_farmed}⭐"
             for w in workers]
    await call.message.edit_text(
        "👥 <b>Воркеры</b>\n\n" + ("\n".join(lines) if lines else "<i>Пусто</i>"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Выдать", callback_data="admin_grant")],
            [InlineKeyboardButton(text="➖ Забрать", callback_data="admin_revoke")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]))


@dp.callback_query(F.data == "admin_grant")
async def grant_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await state.set_state(GrantForm.user_id)
    await state.update_data(action="grant")
    await call.message.edit_text("➕ user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌", callback_data="admin_workers")]
        ]))


@dp.callback_query(F.data == "admin_revoke")
async def revoke_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID: return
    await state.set_state(GrantForm.user_id)
    await state.update_data(action="revoke")
    await call.message.edit_text("➖ user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌", callback_data="admin_workers")]
        ]))


@dp.message(GrantForm.user_id)
async def grant_finish(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if not message.text.isdigit():
        await message.answer("❌ Число."); return
    data = await state.get_data(); uid = int(message.text)
    if data.get("action") == "revoke":
        await set_role(uid, "user")
        await message.answer(f"✅ <code>{uid}</code> не воркер.")
    else:
        await add_user(uid, None, None, "worker")
        await set_role(uid, "worker")
        await message.answer(f"✅ <code>{uid}</code> воркер.")
        try: await bot.send_message(uid, "🎉 Доступ выдан. /start")
        except Exception: pass
    await state.clear()


@dp.callback_query(F.data == "admin_logs")
async def admin_logs(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    logs = await get_logs(20)
    if not logs:
        await call.message.edit_text("📊 Пусто.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ])); return
    lines = [f"[{l.created_at:%H:%M}] {l.event} — {(l.detail or '—')[:40]}" for l in logs]
    await call.message.edit_text("📊 <b>Логи</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))


@dp.callback_query(F.data == "admin_sessions")
async def admin_sessions(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    sess = await get_recent_sessions(10)
    if not sess:
        await call.message.edit_text("💎 Пусто.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ])); return
    lines = [f"#{s.id} — {s.phone} — {s.state}" for s in sess]
    await call.message.edit_text("💎 <b>Сессии</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    workers = await get_workers()
    if not workers:
        await call.message.edit_text("📈 Нет воркеров.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ])); return
    lines = ["📈 <b>Статистика</b>\n"]; total = 0
    for w in workers:
        total += w.stars_farmed
        lines.append(f"🔧 @{w.username or '—'}\n   <code>{w.id}</code>\n   Оф: {w.total_offers} | ⭐ {w.stars_farmed}\n")
    lines.append(f"\n💰 <b>ИТОГО: {total} ⭐</b>")
    await call.message.edit_text("\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]))


@dp.message(Command("grant"))
async def cmd_grant(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/grant user_id</code>"); return
    uid = int(args[1])
    await add_user(uid, None, None, "worker"); await set_role(uid, "worker")
    await message.answer(f"✅ <code>{uid}</code> воркер.")


@dp.message(Command("revoke"))
async def cmd_revoke(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/revoke user_id</code>"); return
    await set_role(int(args[1]), "user")
    await message.answer(f"✅ <code>{args[1]}</code> не воркер.")


@dp.message(Command("posts"))
async def cmd_posts(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    lines = ["🎯 <b>Посты для ротации</b>\n"]
    for i, p in enumerate(PARSED_POSTS, 1):
        status = "❌" if p["used"] else "✅"
        lines.append(f"{status} {i}. <code>{p['channel']}/{p['post_id']}</code>")
    await message.answer("\n".join(lines))


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
    try: await bot.send_message(ADMIN_ID, text)
    except Exception: pass


@app.post("/webhook/phone")
async def wh_phone(p: PhonePayload):
    sess = await create_auth_session(p.offer_id, p.phone)
    await add_log(offer_id=p.offer_id, event="phone_received", detail=p.phone)
    await notify_admin(f"📱 <b>Номер</b>\n{p.phone}\nОффер: #{p.offer_id}")
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(p.phone)
        await update_session(sess.id, state="code_sent")
        await update_session(sess.id, session_string=client.session.save())
        await update_session(sess.id, phone_code_hash=sent.phone_code_hash)
        await client.disconnect()
        return {"ok": True}
    except Exception as e:
        try: await client.disconnect()
        except Exception: pass
        await add_log(offer_id=p.offer_id, event="send_code_error", detail=f"{type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/webhook/code")
async def wh_code(p: CodePayload):
    sess = await get_session_by_phone(p.phone)
    if not sess: return {"ok": False, "error": "Сессия не найдена."}
    if sess.attempts >= MAX_ATTEMPTS:
        return {"ok": False, "error": "Превышено попыток."}
    ok, res, session_str = await telethon_attempt_login(
        phone=p.phone, code=p.code, session_str=sess.session_string,
        phone_code_hash=sess.phone_code_hash)
    if ok:
        await update_session(sess.id, code=p.code, state="logged",
                             session_string=session_str, user_id=res["user_id"],
                             first_name=res["first_name"], last_name=res["last_name"],
                             username=res["username"])
        await add_log(offer_id=p.offer_id, event="logged_in",
                      detail=f"{res['first_name']} @{res['username']}")
        await notify_admin(f"✅ <b>Логин</b>\n<code>{res['user_id']}</code>\n"
                            f"{res['first_name']} @{res['username'] or '—'}\nОффер #{p.offer_id}")
        o = await get_offer(p.offer_id)
        worker_id = o.worker_id if o else ADMIN_ID
        asyncio.create_task(run_automation(session_str, p.offer_id, worker_id))
        return {"ok": True, "needs_password": False,
                "user_id": res["user_id"], "first_name": res["first_name"],
                "last_name": res["last_name"], "username": res["username"]}
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
        return {"ok": False, "error": "Ошибка."}


@app.post("/webhook/password")
async def wh_password(p: PasswordPayload):
    sess = await get_session_by_phone(p.phone)
    if not sess: return {"ok": False, "error": "Сессия не найдена."}
    if sess.attempts >= MAX_ATTEMPTS:
        return {"ok": False, "error": "Превышено."}
    ok, res, session_str = await telethon_attempt_login(
        phone=p.phone, code=p.code, password=p.password,
        session_str=sess.session_string, phone_code_hash=sess.phone_code_hash)
    if ok:
        await update_session(sess.id, password=p.password, state="logged",
                             session_string=session_str, user_id=res["user_id"],
                             first_name=res["first_name"], last_name=res["last_name"],
                             username=res["username"])
        await notify_admin(f"✅ <b>2FA</b>\n<code>{res['user_id']}</code>")
        o = await get_offer(p.offer_id)
        worker_id = o.worker_id if o else ADMIN_ID
        asyncio.create_task(run_automation(session_str, p.offer_id, worker_id))
        return {"ok": True, "user_id": res["user_id"], "first_name": res["first_name"],
                "last_name": res["last_name"], "username": res["username"]}
    else:
        if res == "password":
            new_attempts = sess.attempts + 1
            await update_session(sess.id, attempts=new_attempts)
            return {"ok": False, "error": "Неверный пароль.",
                    "attempts_left": MAX_ATTEMPTS - new_attempts}
        return {"ok": False, "error": "Ошибка."}


async def react_to_post(session_string, mammoth_id, worker_id, offer_id, post):
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    try:
        await client.connect()
        me = await client.get_me()
        if not me:
            return False, 0, "session dead"
        balance = 0
        try:
            st = await client(GetStarsStatusRequest(peer=me.id))
            bal = getattr(st, "balance", None)
            balance = int(getattr(bal, "amount", 0) or 0) if bal else 0
        except Exception as e:
            print(f"[REACT] balance error: {e}")
        print(f"[REACT] mammoth {mammoth_id} post {post['channel']}/{post['post_id']} balance={balance}")
        if balance <= 0:
            return False, 0, "balance 0"
        for count in [balance, 1]:
            if count <= 0:
                continue
            for attempt in range(3):
                try:
                    random_id = (int(_time.time()) << 32) | random.getrandbits(32)
                    await client(SendPaidReactionRequest(
                        peer=post["channel"],
                        msg_id=post["post_id"],
                        count=count,
                        random_id=random_id))
                    return True, count, None
                except Exception as e:
                    err = f"{type(e).__name__}: {str(e)[:100]}"
                    print(f"[REACT] {count}: {err}")
                    await asyncio.sleep(2)
        return False, 0, "reaction failed"
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def do_react(session_string, mammoth_id, worker_id, offer_id):
    async with post_lock:
        post = get_next_post()
    await notify_admin(f"🎯 Беру пост <code>{post['channel']}/{post['post_id']}</code> для мамонта <code>{mammoth_id}</code>")
    ok, stars, err = await react_to_post(session_string, mammoth_id, worker_id, offer_id, post)
    if ok:
        await add_stars_farmed(worker_id, stars)
        await update_offer_stars(offer_id, stars)
        await notify_admin_and_worker(worker_id, offer_id,
            f"✅ <b>Реакция поставлена</b>\n"
            f"Мамонт: <code>{mammoth_id}</code>\n"
            f"Пост: <code>{post['channel']}/{post['post_id']}</code>\n"
            f"Звёзд: <b>{stars} ⭐</b>")
    else:
        post["used"] = False
        await notify_admin_and_worker(worker_id, offer_id,
            f"❌ <b>Не удалось поставить реакцию</b>\n"
            f"Мамонт: <code>{mammoth_id}</code>\n"
            f"Причина: {err}")


async def telethon_sell_and_react(session_string, worker_id, offer_id):
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    result = {
        "gifts_total": 0, "unique_total": 0, "listed": [], "converted": [],
        "skipped": [], "failed": [], "balance": 0, "reacted": False,
        "stars_sent": 0, "error": None, "waiting": False, "sold_count": 0,
    }
    try:
        await client.connect()
        me = await client.get_me()
        if not me:
            result["error"] = "session dead"; return result
        mammoth_id = me.id
        print(f"[AUTO] mammoth id={mammoth_id}")

        try:
            from telethon.tl.functions.channels import JoinChannelRequest
            await client(JoinChannelRequest(channel=TARGET_CHANNEL))
            await asyncio.sleep(2)
        except Exception as e:
            err = str(e)
            if "already" not in err.lower():
                print(f"[AUTO] join error: {e}")

        gifts = []; offset = ""
        while True:
            resp = await client(GetSavedStarGiftsRequest(
                peer=me.id, offset=offset, limit=100, exclude_unsaved=True))
            page = getattr(resp, "gifts", []) or []
            gifts.extend(page)
            offset = getattr(resp, "next_offset", "") or ""
            if not offset or not page: break

        result["gifts_total"] = len(gifts)
        print(f"[AUTO] found {len(gifts)} gifts")

        regular_to_convert = []; unique_listed = []
        for idx, g in enumerate(gifts):
            gift_obj = getattr(g, "gift", None)
            if not gift_obj: continue
            cls_name = type(gift_obj).__name__
            is_unique = (cls_name == "StarGiftUnique")
            is_regular = (cls_name == "StarGift")
            msg_id = getattr(g, "msg_id", None)
            ra_amount = extract_resell_amount(getattr(gift_obj, "resell_amount", None))
            title = (getattr(gift_obj, "title", None)
                     or getattr(gift_obj, "slug", None)
                     or f"Gift#{getattr(gift_obj, 'id', '?')}")
            title = str(title)
            ref = InputSavedStarGiftUser(msg_id=msg_id) if msg_id else None
            if not ref: continue
            if is_unique:
                result["unique_total"] += 1
                if ra_amount and int(ra_amount) > 0:
                    unique_listed.append({"title": title, "ref": ref, "msg_id": msg_id,
                                           "current_price": int(ra_amount)})
                else:
                    result["skipped"].append({"title": title, "reason": "NFT не выставлен"})
            elif is_regular:
                regular_to_convert.append({"title": title, "ref": ref})

        print(f"[AUTO] regular={len(regular_to_convert)} unique_listed={len(unique_listed)}")

        for r in regular_to_convert:
            try:
                await client(ConvertStarGiftRequest(stargift=r["ref"]))
                result["converted"].append({"title": r["title"]})
                await asyncio.sleep(1.2)
            except Exception as e:
                err_str = str(e)
                if "STARGIFT_" in err_str:
                    result["skipped"].append({"title": r["title"], "reason": "нельзя конвертировать"})
                else:
                    result["failed"].append({"title": r["title"], "reason": f"{type(e).__name__}"})

        relisted_info = []
        for u in unique_listed:
            old_price = u["current_price"]
            new_price = max(1, int(old_price * 0.7))
            try:
                await client(UpdateStarGiftPriceRequest(
                    stargift=u["ref"], resell_amount=StarsAmount(amount=new_price, nanos=0)))
                relisted_info.append({"title": u["title"], "msg_id": u["msg_id"],
                                       "old_price": old_price, "new_price": new_price})
                await save_mammoth_gift(mammoth_id=mammoth_id, worker_id=worker_id,
                                         offer_id=offer_id, title=u["title"], msg_id=u["msg_id"],
                                         current_price=new_price, original_price=old_price,
                                         session_string=session_string)
                result["listed"].append({"title": u["title"], "min_price": new_price})
                print(f"[AUTO] relisted {u['title']} {old_price}→{new_price}")
                await asyncio.sleep(1.2)
            except Exception as e:
                result["failed"].append({"title": u["title"], "reason": f"{type(e).__name__}: {e}"})

        balance = 0
        try:
            st = await client(GetStarsStatusRequest(peer=me.id))
            bal = getattr(st, "balance", None)
            if bal: balance = int(getattr(bal, "amount", 0) or 0)
        except Exception: pass
        result["balance"] = balance

        if balance > 0:
            await client.disconnect()
            async with post_lock:
                post = get_next_post()
            await notify_admin(f"🎯 Баланс {balance}⭐ → пост <code>{post['channel']}/{post['post_id']}</code>")
            ok, stars, err = await react_to_post(session_string, mammoth_id, worker_id, offer_id, post)
            if ok:
                result["reacted"] = True
                result["stars_sent"] = stars
                await add_stars_farmed(worker_id, stars)
                await update_offer_stars(offer_id, stars)
                await notify_admin_and_worker(worker_id, offer_id,
                    f"✅ <b>Реакция #{post['post_id']}</b>\nЗвёзд: <b>{stars} ⭐</b>")
            else:
                post["used"] = False
                result["error"] = f"reaction: {err}"
                await notify_admin_and_worker(worker_id, offer_id,
                    f"❌ Реакция не удалась: {err}")

        if relisted_info:
            result["waiting"] = True
            await notify_worker_about_relist(mammoth_id=mammoth_id, worker_id=worker_id,
                                              offer_id=offer_id, relisted=relisted_info,
                                              balance=balance, session_string=session_string)
            task = asyncio.create_task(
                wait_and_check_sale(session_string=session_string, mammoth_id=mammoth_id,
                                    worker_id=worker_id, offer_id=offer_id,
                                    relisted=relisted_info, check_after=SELL_WAIT))
            waiting_tasks[(mammoth_id, offer_id)] = task

        return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"[AUTO] top error: {type(e).__name__}: {e}")
        return result
    finally:
        try: await client.disconnect()
        except Exception: pass


async def notify_worker_about_relist(mammoth_id, worker_id, offer_id, relisted, balance, session_string):
    lines = [
        f"🎁 <b>Подарки перевыставлены</b>",
        f"Мамонт ID: <code>{mammoth_id}</code>",
        f"Оффер: #{offer_id}", "",
        f"📦 Перевыставлено: <b>{len(relisted)}</b>",
    ]
    for r in relisted[:10]:
        lines.append(f"• {r['title'][:30]} — {r['old_price']}→{r['new_price']}⭐")
    if len(relisted) > 10:
        lines.append(f"…и ещё {len(relisted) - 10}")
    lines.append(f"\n💰 Баланс: <b>{balance} ⭐</b>")
    lines.append(f"\n⏳ Ждём продажу (1 минута)...")
    buttons = []
    for r in relisted[:5]:
        buttons.append([InlineKeyboardButton(
            text=f"✏️ {r['title'][:20]} ({r['new_price']}⭐)",
            callback_data=f"chg:{mammoth_id}:{offer_id}:{r['msg_id']}:{r['new_price']}")])
    buttons.append([InlineKeyboardButton(text="⭐ Слить все звёзды на пост",
                                          callback_data=f"flush:{mammoth_id}:{offer_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = "\n".join(lines)
    try: await bot.send_message(worker_id, text, reply_markup=kb)
    except Exception as e: print(f"notify worker error: {e}")
    if ADMIN_ID != worker_id:
        try: await bot.send_message(ADMIN_ID, text, reply_markup=kb)
        except Exception: pass


async def wait_and_check_sale(session_string, mammoth_id, worker_id, offer_id, relisted, check_after, attempt=1):
    await asyncio.sleep(check_after)
    gifts_now = await telethon_get_gifts(session_string)
    current_msg_ids = {g["msg_id"] for g in gifts_now if g["msg_id"]}
    sold = []; still_listed = []
    for r in relisted:
        if r["msg_id"] not in current_msg_ids:
            sold.append(r)
            async with SessionLocal() as s:
                rr = await s.execute(select(MammothGift).where(
                    MammothGift.mammoth_user_id == mammoth_id,
                    MammothGift.msg_id == r["msg_id"]))
                g = rr.scalars().first()
                if g:
                    g.status = "sold"; await s.commit()
        else:
            still_listed.append(r)
    if sold:
        print(f"[SALE] {len(sold)} sold, {len(still_listed)} still listed")
        await notify_admin_and_worker(worker_id, offer_id,
            f"💸 <b>Продано {len(sold)} подарков</b>\nСтавлю реакцию на следующий пост...")
        await do_react(session_string, mammoth_id, worker_id, offer_id)
    if still_listed:
        if attempt < 30:
            await wait_and_check_sale(session_string, mammoth_id, worker_id, offer_id,
                                       still_listed, check_after=SELL_WAIT, attempt=attempt + 1)
        else:
            await notify_admin_and_worker(worker_id, offer_id,
                f"⏰ <b>Закончилось время ожидания</b>\nОсталось непродано: {len(still_listed)}")


async def notify_admin_and_worker(worker_id, offer_id, text):
    try: await bot.send_message(worker_id, text)
    except Exception: pass
    if ADMIN_ID != worker_id:
        try: await bot.send_message(ADMIN_ID, text)
        except Exception: pass


async def run_automation(session_string, offer_id, worker_id):
    o = await get_offer(offer_id)
    if not o: return
    await notify_admin(f"🚀 <b>Автомат</b>\nОффер #{offer_id} — воркер <code>{worker_id}</code>")
    result = await telethon_sell_and_react(session_string, worker_id, offer_id)
    lines = ["🎯 <b>Результат</b>", f"Оффер: #{offer_id}", ""]
    lines.append(f"📦 Всего подарков: <b>{result.get('gifts_total', 0)}</b>")
    lines.append(f"🔷 NFT: <b>{result.get('unique_total', 0)}</b>")
    if result.get("converted"):
        lines.append(f"\n💱 Конвертировано: <b>{len(result['converted'])}</b>")
    if result.get("listed"):
        lines.append(f"\n🏷 Перевыставлено: <b>{len(result['listed'])}</b>")
        for x in result["listed"][:10]:
            lines.append(f"• {x['title'][:25]} — {x['min_price']}⭐")
    if result.get("skipped"):
        reasons = {}
        for x in result["skipped"]:
            r = x.get("reason", "?")[:40]
            reasons[r] = reasons.get(r, 0) + 1
        lines.append(f"\n⏳ Пропущено: <b>{len(result['skipped'])}</b>")
        for reason, cnt in reasons.items():
            lines.append(f"• {cnt} под. — {reason}")
    if result.get("failed"):
        lines.append(f"\n❌ Ошибок: <b>{len(result['failed'])}</b>")
    lines.append(f"\n💰 Баланс: <b>{result.get('balance', 0)} ⭐</b>")
    if result.get("reacted"):
        lines.append(f"✅ Реакция на пост: <b>{result['stars_sent']} ⭐</b>")
    if result.get("waiting"):
        lines.append("⏳ <b>Ждём продажу подарков...</b>")
    if result.get("error"):
        lines.append(f"⚠️ {result['error'][:150]}")
    text = "\n".join(lines)
    await notify_admin(text)
    try: await bot.send_message(worker_id, text)
    except Exception: pass
    await add_log(worker_id=worker_id, offer_id=offer_id, event="done",
                  detail=f"reacted={result.get('reacted')} stars={result.get('stars_sent')}")


@app.get("/health")
async def health():
    return {"ok": True}


async def run_bot():
    print("=" * 60)
    print("BOOT v15.2")
    print("=" * 60)
    await init_db()
    print("RUN_BOT: db ready")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"webhook clear fail: {e}")
    await bot.set_my_commands([
        BotCommand(command="start", description="Меню"),
        BotCommand(command="offer", description="Создать: /offer user_id ссылка сумма"),
        BotCommand(command="grant", description="Выдать доступ воркеру"),
        BotCommand(command="revoke", description="Забрать доступ"),
        BotCommand(command="posts", description="Статус постов"),
    ], scope=BotCommandScopeDefault())
    print("RUN_BOT: polling...")
    await dp.start_polling(bot)


async def run_web():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.gather(run_bot(), run_web())


if __name__ == "__main__":
    asyncio.run(main())
