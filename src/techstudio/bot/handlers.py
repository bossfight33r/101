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
            await bot.send_message(
                chat_id, r.text[:TG_LIMIT], reply_markup=keyboard(r.buttons), parse_mode="HTML"
            )


async def run_job(bot: Bot, chat_id: int, job) -> None:
    if job is None:
        return
    replies = await asyncio.to_thread(job)
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
