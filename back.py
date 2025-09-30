import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler, Defaults
)

from schedule import schedule_menu, schedule_callback
import teachers_schedule as TS  # модуль с логикой преподавателей
from homework import *
# ===== ЛОГГЕРЫ =====
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s: %(message)s"
)
log = logging.getLogger("finashka-bot")

WELCOME_TEXT = (
    "Привет! 👋\n"
    "Я — помощник студентов твоего университета. "
    "Могу напоминать о парах, хранить расписание и помогать с домашкой.\n\n"
    "Выбери одну из опций ниже:"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("Расписание", callback_data="schedule"),
        InlineKeyboardButton("Домашняя работа", callback_data="homework"),
        InlineKeyboardButton("Почта", callback_data="mail"),
    ]]
    await update.message.reply_text(WELCOME_TEXT, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "schedule":
        await schedule_menu(update, context)
    elif q.data == "mail":
        await q.edit_message_text("📧 Раздел с почтой пока пуст.")
    elif q.data == "homework":
        await homework_callback(update, context)

# вход из кнопки «Преподаватель»
async def start_teacher_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
        # Показываем приглашение прямо в том же сообщении
        await q.edit_message_text(
            "2️⃣ Введите <b>фамилию преподавателя</b>\n(Например: <i>Неизвестный</i>):",
            parse_mode=ParseMode.HTML
        )
    else:
        # На всякий случай: если когда-нибудь зайдём не из callback
        await update.effective_chat.send_message(
            "2️⃣ Введите <b>фамилию преподавателя</b>\n(Например: <i>Неизвестный</i>):",
            parse_mode=ParseMode.HTML
        )
    return TS.ASK_TEACHER

async def on_error(update: object, context):
    log.exception("Unhandled error: %r", context.error)
    try:
        if hasattr(update, "callback_query") and update.callback_query:
            await update.callback_query.answer("⚠️ Ошибка соединения. Попробуйте ещё раз.", show_alert=False)
    except Exception:
        pass

token_value = "8386694816:AAF-cqnzapG3xvWX2ZNIcSTbBkyms1FcQTY"

def main():
    # Отключаем возможные системные прокси, чтобы httpx не лез в них
    for var in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"):
        os.environ.pop(var, None)

    app = (
        ApplicationBuilder()
        .token(token_value)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .build()
    )

    # Хендлеры главного меню
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(schedule|homework|mail)$"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, homework.message_handler))
    app.add_handler(CallbackQueryHandler(homework_callback, pattern="^hw_"))
    # Внутри меню расписания: «Расписание» и «Избранное»
    app.add_handler(CallbackQueryHandler(schedule_callback, pattern=r"^(schedule_groups|select_group)$"))

    # Диалог расписания преподавателя (вход — кнопка «Преподаватель» или команда)
    teacher_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_teacher_from_menu, pattern=r"^teachers_schedule$"),
            CommandHandler("teacher_schedule", TS.cmd_start),
        ],
        states={
            TS.ASK_TEACHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, TS.on_teacher_surname)],
            TS.CHOOSE_TEACHER: [CallbackQueryHandler(TS.on_pick_teacher, pattern=r"^pick_teacher:")],
            TS.CHOOSE_RANGE: [CallbackQueryHandler(TS.on_pick_range, pattern=r"^range:")],
            TS.ASK_CUSTOM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, TS.on_custom_date)],
        },
        fallbacks=[CommandHandler("teacher_schedule", TS.cmd_start)],
        name="timetable_conv",
        persistent=False,
        # ВАЖНО: per_message должен быть False, т.к. есть MessageHandler
        per_message=False,
    )
    app.add_handler(teacher_conv)

    app.add_error_handler(on_error)

    log.info("✅ Бот запущен (polling)…")
    # НИЧЕГО асинхронно не вызываем ДО run_polling — никаких asyncio.run!
    app.run_polling(
        poll_interval=1.0,
        timeout=10,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()