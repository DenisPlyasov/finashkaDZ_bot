# mail_check.py
import imaplib
import email
import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

# === Константы и состояния ===
(
    MAIL_SELECT_ACCOUNT,
    MAIL_ENTER_EMAIL,
    MAIL_ENTER_PASSWORD,
) = range(3)

ACCOUNTS_FILE = "mail_accounts.json"
CHECK_INTERVAL = 60  # Проверка почты каждые 60 секунд
logger = logging.getLogger(__name__)
user_last_uid = {}  # {chat_id: {email: last_uid}}

# === Вспомогательные функции ===
def load_accounts(chat_id):
    """Загрузка сохранённых аккаунтов"""
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(str(chat_id), [])
    except Exception as e:
        logger.error(f"Ошибка чтения {ACCOUNTS_FILE}: {e}")
        return []

def save_account(chat_id, email_addr, password):
    """Сохранение нового аккаунта"""
    data = {}
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            pass
    chat_accounts = data.get(str(chat_id), [])
    chat_accounts = [acc for acc in chat_accounts if acc["email"] != email_addr]
    chat_accounts.append({"email": email_addr, "password": password})
    data[str(chat_id)] = chat_accounts
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

def guess_imap_server(email_addr):
    """Определяет IMAP-сервер по домену"""
    domain = email_addr.split("@")[-1].lower()
    if "gmail.com" in domain:
        return "imap.gmail.com"
    if "yandex" in domain:
        return "imap.yandex.ru"
    if "mail.ru" in domain:
        return "imap.mail.ru"
    if "outlook" in domain or "hotmail" in domain or "live" in domain:
        return "imap-mail.outlook.com"
    return f"imap.{domain}"

def parse_email_message(raw_message):
    """Извлекает имя и фамилию отправителя"""
    msg = email.message_from_bytes(raw_message)
    from_header = msg.get("From", "")
    from_name, from_email = email.utils.parseaddr(from_header)
    name_parts = from_name.split()
    if len(name_parts) >= 2:
        first_name = name_parts[0]
        last_name = " ".join(name_parts[1:])
    else:
        first_name = from_name
        last_name = ""
    return first_name, last_name, from_email

# === Основная логика ===
async def start_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск меню почты"""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    accounts = load_accounts(chat_id)

    if accounts:
        keyboard = [[InlineKeyboardButton(acc["email"], callback_data=f"mail_select:{i}")]
                    for i, acc in enumerate(accounts)]
        keyboard.append([InlineKeyboardButton("➕ Добавить почту", callback_data="mail_add")])
        keyboard.append([InlineKeyboardButton("🏠 В меню", callback_data="to_menu")])
        await query.edit_message_text("📧 Выберите почту или добавьте новую:", reply_markup=InlineKeyboardMarkup(keyboard))
        return MAIL_SELECT_ACCOUNT
    else:
        context.user_data["mail_state"] = MAIL_ENTER_EMAIL
        await query.edit_message_text("📧 Введите корпоративный email:")
        return MAIL_ENTER_EMAIL

async def mail_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текста при вводе email или пароля"""
    text = update.message.text.strip()
    state = context.user_data.get("mail_state")

    if state == MAIL_ENTER_EMAIL:
        context.user_data["mail_email"] = text
        context.user_data["mail_state"] = MAIL_ENTER_PASSWORD
        await update.message.reply_text(
            "🔑 Введите пароль приложения от почты.\n"
            "Если у вас нет пароля приложения, создайте его по инструкции:\n"
            "👉 https://telegra.ph"
        )
        return MAIL_ENTER_PASSWORD

    elif state == MAIL_ENTER_PASSWORD:
        email_addr = context.user_data.get("mail_email")
        password = text
        server = guess_imap_server(email_addr)
        text = update.message.text.strip()
        state = context.user_data.get("mail_state")
        logger.debug(f"[mail] got text={text!r} state={state!r} chat={update.effective_chat.id}")
        # ... остальной код без изменений ...
        try:
            imap = imaplib.IMAP4_SSL(server)
            imap.login(email_addr, password)
        except Exception as e:
            logger.error(f"Ошибка входа: {e}")
            await update.message.reply_text("❌ Ошибка входа. Проверьте логин и ПАРОЛЬ ПРИЛОЖЕНИЯ.")
            context.user_data["mail_state"] = MAIL_ENTER_EMAIL
            return MAIL_ENTER_EMAIL

        # Успешный вход
        save_account(update.message.chat.id, email_addr, password)
        await update.message.reply_text(
            f"✅ Почта {email_addr} успешно подключена!\n"
            "📨 Уведомления включены. Скоро появится возможность читать письма прямо здесь."
        )
        imap.logout()
        return ConversationHandler.END

async def mail_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор почты или добавление новой"""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id

    if data == "mail_add":
        context.user_data["mail_state"] = MAIL_ENTER_EMAIL
        await query.edit_message_text("📧 Введите адрес корпоративной почты:")
        return MAIL_ENTER_EMAIL

    if data.startswith("mail_select:"):
        idx = int(data.split(":")[1])
        accounts = load_accounts(chat_id)
        if idx < len(accounts):
            email_addr = accounts[idx]["email"]
            await query.edit_message_text(f"✅ Почта {email_addr} уже подключена.")
        return ConversationHandler.END

# === Проверка новых писем ===
async def mail_checker_task(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет новые письма и отправляет уведомления"""
    bot = context.bot
    if not os.path.exists(ACCOUNTS_FILE):
        return
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return

    for chat_id, accounts in data.items():
        for acc in accounts:
            email_addr = acc["email"]
            password = acc["password"]
            server = guess_imap_server(email_addr)
            try:
                imap = imaplib.IMAP4_SSL(server)
                imap.login(email_addr, password)
                imap.select("INBOX")
                status, data_uids = imap.search(None, "ALL")
                if status != "OK":
                    imap.logout()
                    continue
                uids = data_uids[0].split()
                if not uids:
                    imap.logout()
                    continue

                last_uid = uids[-1]
                prev_uid = user_last_uid.get(chat_id, {}).get(email_addr)

                if prev_uid != last_uid:
                    status, msg_data = imap.fetch(last_uid, "(RFC822)")
                    if status == "OK":
                        raw_email = msg_data[0][1]
                        first_name, last_name, from_email = parse_email_message(raw_email)
                        await bot.send_message(
                            chat_id=int(chat_id),
                            text=f"📩 На вашу корпоративную почту пришло новое сообщение. Посмотри, вдруг там что-то важное!"
                        )
                        user_last_uid.setdefault(chat_id, {})[email_addr] = last_uid
                imap.logout()
            except Exception as e:
                logger.error(f"Ошибка при проверке {email_addr}: {e}")
                continue

# === Регистрация хэндлеров ===
def add_mail_handlers(application):
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_mail, pattern=r"^mail$")],
        states={
            MAIL_SELECT_ACCOUNT: [CallbackQueryHandler(mail_select_callback)],
            MAIL_ENTER_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, mail_text_handler)],
            MAIL_ENTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, mail_text_handler)],
        },
        fallbacks=[],
        name="mail_conv",
        persistent=False,
    )
    application.add_handler(conv_handler)