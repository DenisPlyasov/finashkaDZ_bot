from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode


START_TEXT = (
    "1️⃣ *Выберете какое расписание вы хотите посмотреть.*\n"
    "Здесь вы сможете посмотреть расписание любой группы, расписание преподавателя или же лично ваше, когда добавите его в избранное."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Расписание", callback_data="schedule"),
            InlineKeyboardButton("Преподаватель", callback_data="teachers_schedule"),
            InlineKeyboardButton("Избранное", callback_data="select_group"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(START_TEXT, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN,)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "schedule":
        await query.edit_message_text("📅 Раздел с расписанием пока пуст.")
    elif query.data == "select_group":
        await query.edit_message_text("📧 Раздел с почтой пока пуст.")
    elif query.data == "teachers_schedule":
        await teachers_schedule.teacher_schedule_menu(update, context)


token_value = "8204528132:AAE3Fw9H0WJKhxGz5sP_UBiOQr-jyrrlcjo"

def main():
    app = ApplicationBuilder().token(token_value).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))


    print("✅ Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()