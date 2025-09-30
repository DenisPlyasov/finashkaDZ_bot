# schedule.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
# schedule.py
from teachers_schedule import get_conv_handler, main  # 👈 импортируем

async def schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "schedule_groups":
        await query.edit_message_text("📅 Раздел с расписанием пока пуст.")
    elif query.data == "select_group":
        await query.edit_message_text("⭐ Раздел с избранным пока пуст.")
    elif query.data == "teachers_schedule":
        # теперь запускаем диалог преподавателя
        # entry_point ConversationHandler сработает автоматически
        await main()


# Текст для раздела "Расписание"
SCHEDULE_START_TEXT = (
    "1️⃣ *Выберете какое расписание вы хотите посмотреть.*\n"
    "Здесь вы сможете посмотреть расписание любой группы, расписание преподавателя или же лично ваше, когда добавите его в избранное."
)

# Меню расписания
async def schedule_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Расписание", callback_data="schedule_groups"),
            InlineKeyboardButton("Преподаватель", callback_data="teachers_schedule"),
            InlineKeyboardButton("Избранное", callback_data="select_group"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            SCHEDULE_START_TEXT, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            SCHEDULE_START_TEXT, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
        )

# Обработка кнопок внутри меню расписания
async def schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "schedule_groups":
        await query.edit_message_text("📅 Раздел с расписанием пока пуст.")
    elif query.data == "select_group":
        await query.edit_message_text("⭐ Раздел с избранным пока пуст.")
    elif query.data == "teachers_schedule":
        # здесь можно будет вызвать teacher_schedule_menu из другого модуля
        pass