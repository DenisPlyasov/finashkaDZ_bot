import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler, Defaults, JobQueue
)
from telegram.request import HTTPXRequest
from schedule_groups import build_schedule_groups_conv, start as groups_start
from schedule import schedule_menu, schedule_callback
import teachers_schedule as TS
from settings import add_settings_handlers, register_notification_jobs
from homework import *
from mail_check import add_mail_handlers, mail_checker_task, start_mail

# ===== ЛОГГЕР =====
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s: %(message)s"
)
log = logging.getLogger("finashka-bot")


# ===== КАНАЛ ДЛЯ ПОДПИСКИ =====
CHANNEL_LINK = open("required_chanel_link.txt", "r", encoding="utf-8").readline().strip()
CHANNEL_USERNAME = open("required_chaned_id.txt", "r", encoding="utf-8").readline().strip()  # username канала для get_chat_member

WELCOME_TEXT = (
    "Привет! 👋\n"
    "Я — помощник студентов твоего университета. "
    "Могу напоминать о парах и дз, хранить расписание и показывать дз других групп.\n"
    "Мы только запустили бета тест, поэтому если будут какие-то ошибки или предложения пишите: @question_finashkadzbot\n\n"
    "Выбери одну из опций ниже:"
)

# ===== СОСТОЯНИЯ =====
ASK_SUBSCRIPTION = 0

# ===== ФУНКЦИИ =====
async def check_user_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверка подписки пользователя на канал"""
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ("member", "creator", "administrator")
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Старт бота с проверкой подписки"""
    user_id = update.effective_user.id
    try:
        context.user_data.clear()
        if update.effective_chat:
            context.application.chat_data.pop(update.effective_chat.id, None)
    except Exception:
        pass
    if await check_user_subscription(user_id, context):
        await show_main_menu(update, context)
        return ConversationHandler.END
    else:
        keyboard = [
            [InlineKeyboardButton("Подписаться на канал", url=CHANNEL_LINK)],
            [InlineKeyboardButton("Проверить подписку", callback_data="check_subs")]
        ]
        await update.message.reply_text(
            "⚠️ Для использования бота необходимо подписаться на канал проекта.\n\n"
            "Нажмите кнопку ниже, чтобы подписаться, а затем проверьте подписку.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ASK_SUBSCRIPTION

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка подписки при нажатии кнопки"""
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    if await check_user_subscription(user_id, context):
        await q.edit_message_text("✅ Спасибо за подписку! Доступ открыт.")
        await show_main_menu(q, context)
        return ConversationHandler.END
    else:
        await q.answer("❌ Вы всё ещё не подписаны на канал.", show_alert=True)
        return ASK_SUBSCRIPTION

def reset_selection(context):
    """Очистка всего пользовательского контекста, чтобы диалоги не залипали."""
    for k in ("group", "group_candidates", "teacher_id", "teacher_name",
              "teachers_map", "mail_state", "mail_email", "hw_action"):
        context.user_data.pop(k, None)

async def show_main_menu(update_or_q, context):
    """Показать главное меню"""
    keyboard = [[
        InlineKeyboardButton("Расписание", callback_data="schedule"),
        InlineKeyboardButton("Домашняя работа", callback_data="homework"),
        InlineKeyboardButton("Почта", callback_data="mail"),
    ]]
    if isinstance(update_or_q, Update):
        await update_or_q.message.reply_text(WELCOME_TEXT, reply_markup=InlineKeyboardMarkup(keyboard))
    else:  # callback_query
        await update_or_q.message.reply_text(WELCOME_TEXT, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главные кнопки верхнего уровня с проверкой подписки"""
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    if not await check_user_subscription(user_id, context):
        keyboard = [
            [InlineKeyboardButton("Подписаться на канал", url=CHANNEL_LINK)],
            [InlineKeyboardButton("Проверить подписку", callback_data="check_subs")]
        ]
        await q.edit_message_text(
            "⚠️ Для использования бота необходимо подписаться на канал проекта.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if q.data == "schedule":
        await schedule_menu(update, context)
    elif q.data == "mail":
        await start_mail(update, context)
    elif q.data == "homework":
        await homework_menu(update, context)
    elif q.data.startswith("hw_"):
        await homework_callback(update, context)

async def start_teacher_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Старт диалога с преподавателями с проверкой подписки"""
    q = update.callback_query
    user_id = q.from_user.id if q else update.effective_user.id
    if not await check_user_subscription(user_id, context):
        keyboard = [
            [InlineKeyboardButton("Подписаться на канал", url=CHANNEL_LINK)],
            [InlineKeyboardButton("Проверить подписку", callback_data="check_subs")]
        ]
        if q:
            await q.edit_message_text(
                "⚠️ Для использования бота необходимо подписаться на канал проекта.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.effective_chat.send_message(
                "⚠️ Для использования бота необходимо подписаться на канал проекта.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return ConversationHandler.END

    if q:
        await q.answer()
        await q.edit_message_text(
            "⚠️ P.s. После 23:00 бот будет работать медленне, проблема на нашей стороне.\n\n2️⃣ Введите <b>фамилию преподавателя</b> \n" "(Например: <i>Неизвестный</i>): ",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.effective_chat.send_message(
            "⚠️ P.s. После 23:00 бот будет работать медленне, проблема на нашей стороне.\n\n2️⃣ Введите <b>фамилию преподавателя</b> \n" "(Например: <i>Неизвестный</i>): ",
            parse_mode=ParseMode.HTML
        )
    return TS.ASK_TEACHER

from telegram.error import BadRequest
import traceback

async def on_error(update: object, context):
    error = context.error

    try:
        # 1️⃣ Специальная защита от старых callback-ов (основная причина падений)
        if isinstance(error, BadRequest) and (
            "Query is too old" in str(error)
            or "query id is invalid" in str(error)
            or "response timeout expired" in str(error)
        ):
            # Просто тихо игнорируем ошибку — не показываем пользователю, не падаем
            log.warning("⚠️ Игнорирую устаревший callback (Query too old / invalid id)")
            return

        # 2️⃣ Логируем остальные ошибки, но не роняем бота
        log.exception("❗ Unhandled error: %r", error)
        log.debug("".join(traceback.format_exception(None, error, error.__traceback__)))

        # 3️⃣ Можно уведомить пользователя об общей ошибке (если callback живой)
        if hasattr(update, "callback_query") and update.callback_query:
            try:
                await update.callback_query.answer(
                    "⚠️ Ошибка соединения. Попробуйте ещё раз.",
                    show_alert=False
                )
            except Exception:
                pass  # если callback уже невалиден — просто игнорируем

    except Exception as e:
        log.critical("Ошибка внутри on_error(): %s", e)

def reset_selection(context):
    """Сбрасывает текущие выборы пользователя (группа/преподаватель) в user_data."""
    for k in ("group", "group_candidates", "teacher_id", "teacher_name", "teachers_map"):
        context.user_data.pop(k, None)

def main():
    for var in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"):
        os.environ.pop(var, None)

    request = HTTPXRequest(
        read_timeout=30.0,
        write_timeout=30.0,
        connect_timeout=30.0,
        pool_timeout=30.0,
    )

    app = (
        ApplicationBuilder()
        .token(open('token.txt').readline())
        .request(request)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .build()
    )

    if app.job_queue is None:
        jq = JobQueue()
        jq.set_application(app)
        app.job_queue = jq

    # ===== РАЗГОВОР ДЛЯ ПОДПИСКИ =====
    ssubs_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ASK_SUBSCRIPTION: [CallbackQueryHandler(check_subscription, pattern="^check_subs$")]},
        fallbacks=[CommandHandler("start", start)],
        name="subscription_conv",
        per_message=False,
        persistent=False,
    )
    app.add_handler(ssubs_conv, group=0)

    # 2) Расписание групп (ConversationHandler уже собирается в build_schedule_groups_conv)
    schedule_conv = build_schedule_groups_conv()
    app.add_handler(schedule_conv, group=0)

    # 3) Расписание преподавателей
    teacher_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(TS.start_teacher_from_menu, pattern=r"^teachers_schedule$"),
            # опционально: CommandHandler("teacher_schedule", TS.teacher_schedule_cmd),
        ],
        states={
            TS.ASK_TEACHER:    [MessageHandler(filters.TEXT & ~filters.COMMAND, TS.on_teacher_surname)],
            TS.CHOOSE_TEACHER: [CallbackQueryHandler(TS.on_pick_teacher, pattern=r"^pick_teacher:")],
            TS.CHOOSE_RANGE:   [CallbackQueryHandler(TS.on_pick_range, pattern=r"^(range:|fav_teacher:)")],
            TS.ASK_CUSTOM_DATE:[MessageHandler(filters.TEXT & ~filters.COMMAND, TS.on_custom_date)],
        },
        fallbacks=[
            CommandHandler("cancel", TS.cancel),
            # /start в этом разговоре просто завершает его, чтобы не залипал
            CommandHandler("start", lambda u, c: ConversationHandler.END),
        ],
        allow_reentry=True,
        name="teacher_conv",
        per_message=False,
        persistent=False,
    )
    app.add_handler(teacher_conv, group=0)

    # 4) Почта (разговор внутри add_mail_handlers)
    add_mail_handlers(app)  # пусть регистрируется в group=0 по умолчанию

    # 5) Кнопки верхнего уровня
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(schedule|homework|mail|hw_.*)$"), group=0)

    # 6) ГЛОБАЛЬНЫЙ обработчик текстов (домашка и прочее) — только в group=1!
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler), group=1)

    # 7) Общий обработчик ошибок
    app.add_error_handler(on_error)

    add_settings_handlers(app)
    register_notification_jobs(app)
    app.job_queue.run_repeating(mail_checker_task, interval=60, first=5)

    print("✅ Бот запущен (polling)…")
    app.run_polling(
        poll_interval=1.0,
        timeout=10,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()