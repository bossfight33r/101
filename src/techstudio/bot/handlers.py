"""Раздел TechStudio в Telegram-боте (aiogram 3). Только TS_ADMIN_IDS; чужим — молчание."""

from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from techstudio.bot import logic
from techstudio.core import log
from techstudio.services import Services

_log = log.get("bot")
COMMANDS = ("studio", "topics", "new", "review", "status", "retry", "publish")
TG_LIMIT = 4000


def keyboard(rows) -> InlineKeyboardMarkup | None:
    if not rows:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
        ]
    )


def split_text(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Режем по строкам (строки гейтов самодостаточны по HTML-тегам), не посреди тега."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        line = line if len(line) <= limit else line[: limit - 1] + "…"
        if cur and len(cur) + 1 + len(line) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


async def send_replies(bot: Bot, chat_id: int, replies: list[logic.Reply]) -> None:
    for r in replies:
        for v in r.videos:
            await bot.send_video(
                chat_id, FSInputFile(v), caption=r.text[:1000] or None, supports_streaming=True
            )
        if r.photos:
            await bot.send_media_group(
                chat_id, [InputMediaPhoto(media=FSInputFile(p)) for p in r.photos]
            )
        for d in r.documents:
            await bot.send_document(chat_id, FSInputFile(d))
        if r.text and not r.videos:
            chunks = split_text(r.text)
            for i, chunk in enumerate(chunks):
                last = i == len(chunks) - 1
                await bot.send_message(
                    chat_id,
                    chunk,
                    reply_markup=keyboard(r.buttons) if last else None,
                    parse_mode="HTML" if r.html else None,
                )


def make_progress(bot: Bot, chat_id: int, message_id: int, loop: asyncio.AbstractEventLoop):
    """Колбэк из рабочего потока: редактирует одно статус-сообщение (последнее значение побеждает)."""
    done: list[str] = []

    def progress(text: str) -> None:
        done.append(text)
        body = (
            "\n".join(f"✓ {t}" for t in done[:-1]) + ("\n" if len(done) > 1 else "") + f"⏳ {text}"
        )
        fut = asyncio.run_coroutine_threadsafe(
            bot.edit_message_text(body, chat_id=chat_id, message_id=message_id), loop
        )
        try:
            fut.result(timeout=15)
        except Exception as e:  # noqa: BLE001 — прогресс не критичен
            _log.warning("bot.progress_failed", error=type(e).__name__)

    return progress


async def run_job(bot: Bot, chat_id: int, job) -> None:
    if job is None:
        return
    status = await bot.send_message(chat_id, "⏳ в работе…")
    progress = make_progress(bot, chat_id, status.message_id, asyncio.get_running_loop())
    replies = await asyncio.to_thread(job, progress=progress)
    try:
        await bot.edit_message_text("✅ готово", chat_id=chat_id, message_id=status.message_id)
    except Exception:  # noqa: BLE001
        pass
    await send_replies(bot, chat_id, replies)


def build_router(svc: Services) -> Router:
    router = Router(name="techstudio")
    admins = svc.settings.admin_id_set
    router.message.filter(F.from_user.id.in_(admins))
    router.callback_query.filter(F.from_user.id.in_(admins))

    @router.message(Command(*COMMANDS))
    async def on_command(message: Message, command: CommandObject, bot: Bot):
        args = (command.args or "").split()
        replies, job = logic.handle_command(svc, command.command, args)
        await send_replies(bot, message.chat.id, replies)
        asyncio.create_task(run_job(bot, message.chat.id, job))

    @router.callback_query(F.data.startswith(logic.PREFIX + ":"))
    async def on_callback(query: CallbackQuery, bot: Bot):
        await query.answer()
        replies, job = logic.handle_callback(svc, query.data)
        await send_replies(bot, query.message.chat.id, replies)
        asyncio.create_task(run_job(bot, query.message.chat.id, job))

    @router.message(F.document)
    async def on_document(message: Message, bot: Bot):
        doc = message.document
        if doc.file_size and doc.file_size > 1_000_000:
            await message.answer("Слишком большой файл для сценария")
            return
        file = await bot.download(doc)
        text = file.read().decode("utf-8", errors="replace")
        await send_replies(
            bot, message.chat.id, logic.handle_document(svc, doc.file_name or "", text)
        )

    return router


async def run_polling(svc: Services) -> None:
    from aiogram import Dispatcher

    token = svc.settings.telegram_bot_token
    if token is None:
        raise RuntimeError("нет TELEGRAM_BOT_TOKEN в .env")
    if not svc.settings.admin_id_set:
        raise RuntimeError("нет TS_ADMIN_IDS в .env — бот никого не обслуживает")
    bot = Bot(token.get_secret_value())
    dp = Dispatcher()
    dp.include_router(build_router(svc))
    _log.info("bot.start", admins=len(svc.settings.admin_id_set))
    await dp.start_polling(bot)


def gate_for(svc: Services, video_id: str) -> list[logic.Reply]:
    from techstudio.schemas import VideoStatus

    rec = svc.db.require_video(video_id)
    if rec.status == VideoStatus.final_review:
        return logic.final_gate(svc, video_id)
    if rec.status == VideoStatus.script_review:
        return logic.script_gate(svc, video_id)
    text = f"{video_id}: {rec.status.value}"
    if rec.failure:
        text += f"\n❌ {rec.failure.stage}: {rec.failure.message[:300]}\n/retry {video_id}"
    return [logic.Reply(text=text)]


async def notify(svc: Services, video_id: str, bot: Bot | None = None) -> int:
    """Отправить админам гейт текущего статуса видео (после CLI-команды). Возвращает число получателей."""
    token = svc.settings.telegram_bot_token
    own = bot is None
    if own:
        if token is None:
            raise RuntimeError("нет TELEGRAM_BOT_TOKEN в .env")
        bot = Bot(token.get_secret_value())
    replies = gate_for(svc, video_id)
    try:
        for admin in sorted(svc.settings.admin_id_set):
            await send_replies(bot, admin, replies)
    finally:
        if own:
            await bot.session.close()
    return len(svc.settings.admin_id_set)
