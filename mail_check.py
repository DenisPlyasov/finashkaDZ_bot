# mail_check.py

import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import os
import json
import logging
from io import BytesIO
from html import unescape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)

# States for the mail conversation
(
    MAIL_SELECT_ACCOUNT,
    MAIL_ENTER_EMAIL,
    MAIL_ENTER_PASSWORD,
    MAIL_NAVIGATION
) = range(4)

# File for saving mail accounts
ACCOUNTS_FILE = "mail_accounts.json"
logger = logging.getLogger(__name__)

def load_accounts(chat_id):
    """Load saved accounts for this chat from JSON file."""
    try:
        if not os.path.exists(ACCOUNTS_FILE):
            return []
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(str(chat_id), [])
    except Exception as e:
        logger.error(f"Failed to load accounts file: {e}")
        return []

def save_account(chat_id, email_addr, password):
    """Save or update a mail account for this chat in JSON file."""
    data = {}
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read accounts file: {e}")
    data = data or {}
    chat_accounts = data.get(str(chat_id), [])
    # If this email is new, append; if exists, update password
    if not any(acc["email"] == email_addr for acc in chat_accounts):
        chat_accounts.append({"email": email_addr, "password": password})
    else:
        for acc in chat_accounts:
            if acc["email"] == email_addr:
                acc["password"] = password
                break
    data[str(chat_id)] = chat_accounts
    try:
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Failed to save accounts file: {e}")

def guess_imap_server(email_addr):
    """Guess IMAP server from email domain (basic heuristic)."""
    domain = email_addr.split("@")[-1].lower()
    if "gmail.com" in domain or "googlemail.com" in domain:
        return "imap.gmail.com"
    if "yandex" in domain:
        return "imap.yandex.com"
    if domain in ("outlook.com", "hotmail.com", "live.com", "msn.com"):
        return "imap-mail.outlook.com"
    return f"imap.{domain}"

def fetch_mail_uids(imap, limit=None):
    """Fetch all email UIDs sorted by date descending (newest first)."""
    imap.select("INBOX")
    status, data = imap.search(None, "ALL")
    if status != "OK":
        return []
    uids = data[0].split()
    uid_dates = []
    for uid in uids:
        status, msg_data = imap.fetch(uid, "(INTERNALDATE)")
        if status != "OK":
            continue
        raw = msg_data[0].decode(errors="ignore")
        date_value = ""
        if "INTERNALDATE" in raw:
            idx = raw.find("INTERNALDATE")
            try:
                date_part = raw[idx:].split('"', 1)[1]
                date_value = date_part.split('"')[0]
            except Exception:
                date_value = ""
        try:
            dt = parsedate_to_datetime(date_value)
        except Exception:
            dt = None
        if dt:
            uid_dates.append((uid, dt))
    # Sort by date (descending)
    uid_dates.sort(key=lambda x: x[1], reverse=True)
    sorted_uids = [uid for uid, _ in uid_dates]
    if limit:
        return sorted_uids[:limit]
    return sorted_uids

def parse_email_message(raw_message):
    """Parse raw email bytes into sender name, email, body text, and attachments."""
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
    body = ""
    if msg.is_multipart():
        text_part = None
        html_part = None
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                text_part = part
                break
            if ctype == "text/html":
                html_part = part
        if text_part:
            charset = text_part.get_content_charset() or "utf-8"
            try:
                body = text_part.get_payload(decode=True).decode(charset, errors="ignore")
            except Exception:
                body = text_part.get_payload(decode=True).decode("utf-8", errors="ignore")
        elif html_part:
            charset = html_part.get_content_charset() or "utf-8"
            try:
                html_content = html_part.get_payload(decode=True).decode(charset, errors="ignore")
            except Exception:
                html_content = html_part.get_payload(decode=True).decode("utf-8", errors="ignore")
            import re
            body = re.sub(r'<[^>]+>', '', html_content)  # strip HTML tags
            body = unescape(body)
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="ignore")
            except Exception:
                body = ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                body = payload.decode(charset, errors="ignore")
            except Exception:
                body = payload.decode("utf-8", errors="ignore")
        else:
            body = ""
    attachments = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment":
            filename = part.get_filename()
            if filename:
                try:
                    fname, enc = decode_header(filename)[0]
                    if isinstance(fname, bytes):
                        filename = fname.decode(enc or "utf-8", errors="ignore")
                except Exception:
                    pass
                data = part.get_payload(decode=True)
                if data:
                    attachments.append((filename, data))
    return first_name, last_name, from_email, body, attachments

async def start_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initial handler when 'Mail' button is pressed."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    accounts = load_accounts(chat_id)
    if accounts:
        keyboard = []
        for i, acc in enumerate(accounts):
            btn = InlineKeyboardButton(acc["email"], callback_data=f"mail_select:{i}")
            keyboard.append([btn])
        keyboard.append([InlineKeyboardButton("➕ Добавить почту", callback_data="mail_add")])
        keyboard.append([InlineKeyboardButton("В меню", callback_data="to_menu")])
        text = "Выберите почтовый ящик или добавьте новый:"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return MAIL_SELECT_ACCOUNT
    else:
        context.user_data["mail_account_temp"] = {}
        context.user_data["mail_state"] = MAIL_ENTER_EMAIL
        await query.edit_message_text("📧 Введите адрес корпоративной почты:")
        return MAIL_ENTER_EMAIL

async def mail_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle mailbox selection ('mail_select:i'), adding ('mail_add'), or returning to menu."""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id

    if data == "to_menu":
        from main import start
        return await start(query, context)
    if data == "mail_add":
        context.user_data["mail_account_temp"] = {}
        context.user_data["mail_state"] = MAIL_ENTER_EMAIL
        await query.edit_message_text("📧 Введите адрес корпоративной почты:")
        return MAIL_ENTER_EMAIL
    if data.startswith("mail_select:"):
        idx = int(data.split(":")[1])
        accounts = load_accounts(chat_id)
        if idx < 0 or idx >= len(accounts):
            await query.edit_message_text("❌ Неверный выбор.")
            return MAIL_SELECT_ACCOUNT
        account = accounts[idx]
        email_addr = account["email"]
        password = account["password"]
        context.user_data["mail_account"] = {"email": email_addr, "password": password}
        server = guess_imap_server(email_addr)
        try:
            imap = imaplib.IMAP4_SSL(server)
            imap.login(email_addr, password)
        except Exception as e:
            logger.error(f"IMAP login failed: {e}")
            await query.edit_message_text("❌ Не удалось войти. Проверьте логин и пароль.")
            return ConversationHandler.END
        uids = fetch_mail_uids(imap)
        context.user_data["mail_uids"] = uids
        context.user_data["mail_index"] = 0
        await display_emails(query, context, imap, start=0)
        imap.logout()
        return MAIL_NAVIGATION

async def mail_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input for email (state=MAIL_ENTER_EMAIL) or password (state=MAIL_ENTER_PASSWORD)."""
    text = update.message.text.strip()
    state = context.user_data.get("mail_state")
    if state == MAIL_ENTER_EMAIL:
        context.user_data["mail_account_temp"]["email"] = text
        context.user_data["mail_state"] = MAIL_ENTER_PASSWORD
        await update.message.reply_text("🔑 Введите пароль:")
        return MAIL_ENTER_PASSWORD
    elif state == MAIL_ENTER_PASSWORD:
        email_addr = context.user_data.get("mail_account_temp", {}).get("email")
        password = text
        if not email_addr:
            await update.message.reply_text("❌ Адрес почты не указан. Попробуйте снова.")
            context.user_data["mail_state"] = MAIL_ENTER_EMAIL
            return MAIL_ENTER_EMAIL
        server = guess_imap_server(email_addr)
        try:
            imap = imaplib.IMAP4_SSL(server)
            imap.login(email_addr, password)
        except Exception as e:
            logger.error(f"IMAP login failed: {e}")
            await update.message.reply_text("❌ Не удалось войти. Проверьте логин и пароль.")
            context.user_data["mail_state"] = MAIL_ENTER_EMAIL
            return MAIL_ENTER_EMAIL
        save_account(update.message.chat.id, email_addr, password)
        context.user_data["mail_account"] = {"email": email_addr, "password": password}
        uids = fetch_mail_uids(imap)
        context.user_data["mail_uids"] = uids
        context.user_data["mail_index"] = 0
        await update.message.reply_text(f"✅ Почта добавлена. Показываю письма для {email_addr}:")
        await display_emails(update, context, imap, start=0)
        imap.logout()
        return MAIL_NAVIGATION

async def display_emails(update_or_query, context: ContextTypes.DEFAULT_TYPE, imap_conn, start=0):
    """Fetch three emails from index 'start' and display them."""
    if isinstance(update_or_query, CallbackQuery):
        chat_id = update_or_query.message.chat.id
        method = "edit"
    else:
        chat_id = update_or_query.message.chat.id
        method = "send_message"
    uids = context.user_data.get("mail_uids", [])
    if not uids:
        text = "📭 Письма отсутствуют."
        if method == "send_message":
            await context.bot.send_message(chat_id, text)
        else:
            await update_or_query.edit_message_text(text)
        return
    end = min(start + 3, len(uids))
    text_list = []
    for idx in range(start, end):
        uid = uids[idx]
        status, msg_data = imap_conn.fetch(uid, "(RFC822)")
        if status != "OK":
            continue
        raw_email = msg_data[0][1]
        first_name, last_name, from_email, body, attachments = parse_email_message(raw_email)
        header = f"✉️ Письмо {idx+1} из {len(uids)}\n"
        sender = f"От: {first_name} {last_name} <{from_email}>\n"
        content = body or ""
        message_text = header + sender + "\n" + content
        if attachments:
            attach_names = ", ".join([name for name, _ in attachments])
            message_text += f"\n\n📎 Вложения: {attach_names}"
        text_list.append(message_text)
        # Send attachment files if any
        for fname, fdata in attachments:
            bio = BytesIO(fdata)
            bio.name = fname
            await context.bot.send_document(chat_id, document=bio, filename=fname)
    combined_text = "\n\n".join(text_list)
    keyboard = []
    if start - 3 >= 0:
        keyboard.append(InlineKeyboardButton("⬅️ Назад", callback_data="mail_prev"))
    keyboard.append(InlineKeyboardButton("В меню", callback_data="to_menu"))
    if end < len(uids):
        keyboard.append(InlineKeyboardButton("➡️ Вперёд", callback_data="mail_next"))
    markup = InlineKeyboardMarkup([keyboard])
    if method == "send_message":
        await context.bot.send_message(chat_id, combined_text, reply_markup=markup)
    else:
        await update_or_query.edit_message_text(combined_text, reply_markup=markup)

async def mail_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Next' or 'Prev' navigation in mail list."""
    query = update.callback_query
    await query.answer()
    data = query.data
    start = context.user_data.get("mail_index", 0)
    uids = context.user_data.get("mail_uids", [])
    if not uids:
        await query.edit_message_text("📭 Письма отсутствуют.")
        return ConversationHandler.END
    if data == "mail_next":
        new_start = start + 3
        if new_start >= len(uids):
            return
        context.user_data["mail_index"] = new_start
        start = new_start
    elif data == "mail_prev":
        new_start = max(start - 3, 0)
        context.user_data["mail_index"] = new_start
        start = new_start
    else:
        return
    account = context.user_data.get("mail_account")
    if not account:
        await query.edit_message_text("❌ Аккаунт не найден.")
        return ConversationHandler.END
    email_addr = account["email"]
    password = account["password"]
    server = guess_imap_server(email_addr)
    try:
        imap = imaplib.IMAP4_SSL(server)
        imap.login(email_addr, password)
    except Exception as e:
        logger.error(f"IMAP login failed: {e}")
        await query.edit_message_text("❌ Не удалось подключиться к почте.")
        return ConversationHandler.END
    await display_emails(query, context, imap, start=start)
    imap.logout()
    return MAIL_NAVIGATION

def add_mail_handlers(application):
    """Register mail handlers in the bot application."""
    from main import start
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_mail, pattern=r"^mail$")],
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
            MAIL_NAVIGATION: [
                CallbackQueryHandler(mail_nav_callback, pattern=r"^(mail_prev|mail_next)$"),
                CallbackQueryHandler(mail_select_callback, pattern=r"^to_menu$")
            ]
        },
        fallbacks=[
            CallbackQueryHandler(mail_select_callback, pattern=r"^to_menu$")
        ],
        name="mail_conv",
        persistent=False,
        per_message=False,
    )
    application.add_handler(conv_handler)

async def mail_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Точка входа в раздел Почта (для вызова из main.py)."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        # просто вызываем стандартный стартовый обработчик
        return await start_mail(update, context)
    else:
        # если вдруг вызов не через кнопку
        await update.message.reply_text("📧 Открываю раздел почты...")
        return await start_mail(update, context)