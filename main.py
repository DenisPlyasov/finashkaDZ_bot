from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

WELCOME_TEXT = (
    "Привет! 👋\n"
    "Я — помощник студентов твоего университета. Могу напоминать о парах, "
    "хранить расписание и помогать с домашкой.\n\n"
    "Выбери одну из опций ниже — пока они пустые, но скоро будут работать!"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Расписание", callback_data="schedule"),
            InlineKeyboardButton("Домашка",    callback_data="homework"),
            InlineKeyboardButton("Почта",      callback_data="mail"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=reply_markup)

if __name__ == "__main__":
    app = ApplicationBuilder().token("8386694816:AAF-cqnzapG3xvWX2ZNIcSTbBkyms1FcQTY").build()
    app.add_handler(CommandHandler("start", start))
    print("Бот запущен...")
    app.run_polling()