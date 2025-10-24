from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

SCHEDULE_START_TEXT = (
    "1️⃣ *Выберете какое расписание вы хотите посмотреть.*\n"
    "Здесь вы сможете посмотреть расписание любой группы, расписание преподавателя, а так же выбрать расписание уведомления которого будут вам приходить (вместе с расписанием группы приходит и ее дз, если же конечно вы его ввели 😉)."
)

async def schedule_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Группы", callback_data="schedule_groups"),
            InlineKeyboardButton("Преподаватели", callback_data="teachers_schedule"),
            InlineKeyboardButton("Настройки", callback_data="settings")
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

async def schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "schedule_groups":
        await query.edit_message_text("📅 Раздел с расписанием пока пуст.")
    elif query.data == "select_group":
        await query.edit_message_text("⭐ Раздел с избранным пока пуст.")
    # ВАЖНО: НЕ обрабатываем "teachers_schedule" здесь — его ловит ConversationHandler из teachers_schedule.py