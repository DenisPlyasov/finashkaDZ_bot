from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import homework
from homework import homework_menu, homework_callback, message_handler
from schedule import schedule_menu, schedule_callback
from teachers_schedule import get_conv_handler,conv


WELCOME_TEXT = (
    "Привет! 👋\n"
    "Я — помощник студентов твоего университета. "
    "Могу напоминать о парах, хранить расписание и помогать с домашкой.\n\n"
    "Выбери одну из опций ниже:"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Расписание", callback_data="schedule"),
            InlineKeyboardButton("Домашняя работа", callback_data="homework"),
            InlineKeyboardButton("Почта", callback_data="mail"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "schedule":
        await schedule_menu(update, context)
    elif query.data == "mail":
        await query.edit_message_text("📧 Раздел с почтой пока пуст.")
    elif query.data == "homework":
        await homework.homework_menu(update, context)
    elif query.data.startswith("hw_"):
        # все команды hw_* обрабатывает homework.homework_callback
        await homework.homework_callback(update, context)


token_value = open('token.txt').readline()

def main():
    app = ApplicationBuilder().token(token_value).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(get_conv_handler())
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, homework.message_handler))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(schedule|select_group)$"))
    app.add_handler(CallbackQueryHandler(homework_callback, pattern="^hw_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(conv)

    print("✅ Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()