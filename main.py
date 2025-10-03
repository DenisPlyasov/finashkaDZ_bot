import os
import logging
from mail_check import add_mail_handlers
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler, Defaults
)
from schedule_groups import build_schedule_groups_conv, start as groups_start
from schedule import schedule_menu, schedule_callback
from mail_check import mail_entry
import teachers_schedule as TS  # модуль с логикой преподавателей
from homework import * 
from homework import homework_menu, homework_callback, message_handler

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
        await mail_entry(update, context)
    elif q.data == "homework":
        await homework_menu(update, context)
    elif q.data.startswith("hw_"):
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

token_value = open('token.txt').readline()

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

    # 0) Диалог расписаний ГРУПП — ДОЛЖЕН идти первым
    from schedule_groups import build_schedule_groups_conv, start as groups_start

    schedule_conv = build_schedule_groups_conv(
        entry_points=[
            CallbackQueryHandler(groups_start, pattern=r"^schedule_groups$"),
            CommandHandler("schedule", groups_start),
        ]
    )
    app.add_handler(schedule_conv)

    # 1) Команда старт
    app.add_handler(CommandHandler("start", start))

    # 2) Главные кнопки верхнего уровня
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(schedule|homework|mail)$"))

    # 3) Домашняя работа
    app.add_handler(CallbackQueryHandler(homework_callback, pattern=r"^hw_"))

    # 4) Меню расписания (БЕЗ 'schedule_groups', чтобы не перехватывать вход в диалог)
    app.add_handler(CallbackQueryHandler(schedule_callback, pattern=r"^select_group$"))

    # 5) Диалог расписания преподавателей
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
        per_message=False,
    )
    app.add_handler(teacher_conv)

    # 6) Общий колбэк (ловит прочие callback_data)
    app.add_handler(CallbackQueryHandler(button_handler))

    # 7) Текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # 8) Ошибки — ровно один раз
    app.add_error_handler(on_error)



    print("✅ Бот запущен (polling)…")
    # НИЧЕГО асинхронно не вызываем ДО run_polling — никаких asyncio.run!
    app.run_polling(
        poll_interval=1.0,
        timeout=10,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()