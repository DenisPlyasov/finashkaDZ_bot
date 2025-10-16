import os
import logging
from telegram.request import HTTPXRequest
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler, Defaults
)
from schedule_groups import build_schedule_groups_conv, start as groups_start
from schedule import schedule_menu, schedule_callback
import teachers_schedule as TS  # модуль с логикой преподавателей
from homework import *
from mail_check import add_mail_handlers, mail_checker_task, start_mail
import asyncio
from telegram.ext import Application, JobQueue
# ===== ЛОГГЕРЫ =====
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s: %(message)s"
)
log = logging.getLogger("finashka-bot")

WELCOME_TEXT = (
    "Привет! 👋\n"
    "Я — помощник студентов твоего университета. "
    "Могу напоминать о парах и дз, хранить расписание и показывать дз других групп.\n"
    "Мы только запустили бета тест, поэтому если будут какие-то ошибки или предложения пишите: @crop_uhar\n\n"
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
        await start_mail(update, context)
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

    request = HTTPXRequest(
        read_timeout=30.0,  # ожидание ответа
        write_timeout=30.0,  # отправка тела
        connect_timeout=30.0,  # соединение
        pool_timeout=30.0,  # ожидание свободного соединения
    )

    app = (
        ApplicationBuilder()
        .token(token_value)
        .request(request)  # <-- ВАЖНО
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .build()
    )
    if app.job_queue is None:
        jq = JobQueue()
        jq.set_application(app)
        app.job_queue = jq
    # 0) Диалог расписаний ГРУПП — ДОЛЖЕН идти первым
    from schedule_groups import build_schedule_groups_conv, start as groups_start

# вставить/заменить в mail_check.py

    def add_mail_handlers(application):
        """Register mail handlers in the bot application."""
        from main import start  # используется для возврата в меню

        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(start_mail, pattern=r"^mail$"),
                # можно добавить команду /mail на всякий случай
                # CommandHandler("mail", lambda u,c: start_mail(u,c))
            ],
            states={
                MAIL_SELECT_ACCOUNT: [
                    CallbackQueryHandler(mail_select_callback, pattern=r"^(mail_add|mail_select:\d+|to_menu)$")
                ],
                MAIL_ENTER_EMAIL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, mail_text_handler)
                ],
                MAIL_ENTER_PASSWORD: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, mail_text_handler)
                ],
            },
            fallbacks=[
                CallbackQueryHandler(mail_select_callback, pattern=r"^to_menu$")
            ],
            name="mail_conv",
            persistent=False,
            # важно: отслеживаем разговор по чату, а не по сообщению
            per_message=False,
        )

        application.add_handler(conv_handler)


    schedule_conv = build_schedule_groups_conv(
        entry_points=[
            CallbackQueryHandler(groups_start, pattern=r"^schedule_groups$"),
            CommandHandler("schedule", groups_start),
        ]
    )
    app.add_handler(schedule_conv)

    # 1) Команда старт
    app.add_handler(CommandHandler("start", start))

    # 2) Главные кнопки верхнего уровня (убрал "mail" из паттерна)
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(schedule|homework)$"))

    # 3) Домашняя работа (специфичный обработчик hw_)
    app.add_handler(CallbackQueryHandler(homework_callback, pattern=r"^hw_"))

    # 4) Меню расписания (конкретный паттерн, чтобы не перехватывать другие)
    #app.add_handler(CallbackQueryHandler(schedule_callback, pattern=r"^select_group$"))

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

    # 6) Регистрация обработчиков почты — ДОЛЖНА быть ДО общего ловца колбэков
    from mail_check import add_mail_handlers, mail_checker_task
    add_mail_handlers(app)

    # 7) Общий колбэк (ловит прочие callback_data) — оставляем его в конце
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(schedule|homework|mail|hw_.*)$"))

    # 8) Текстовые сообщения (общие)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))


    # 9) Ошибки
    app.add_error_handler(on_error)

    # 10) Фоновая проверка почты (JobQueue должен быть корректно инициализирован)
    app.job_queue.run_repeating(mail_checker_task, interval=60, first=5)

    print("✅ Бот запущен (polling)…")
    # НИЧЕГО асинхронно не вызываем ДО run_polling — никаких asyncio.run!
    app.run_polling(
        poll_interval=1.0,
        timeout=10,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()