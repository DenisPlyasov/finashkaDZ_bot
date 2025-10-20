import os
import random
import sqlite3
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import re
import logging

logger = logging.getLogger(__name__)

# -------------------- Конфигурация --------------------
DATA_DIR = "data"
DB_PATH = os.path.join(DATA_DIR, "homework.db")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "finashkadzbot@gmail.com"
SMTP_PASSWORD = open("password_mail.txt").readline().strip()

# Google Sheets
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
GSHEET_NAME = "homework_backup"
GSHEET_CREDS = "finashkadzbot-d8415e20cc18.json"

DATE_INPUT_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")

# -------------------- SQLite --------------------
def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            email TEXT,
            group_name TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            email TEXT,
            group_name TEXT,
            subject TEXT,
            deadline TEXT,
            task TEXT,
            attachment TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS valid_emails (
            email TEXT PRIMARY KEY,
            telegram_id INTEGER,
            verified_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            email TEXT PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()

def add_homework(entry):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO homework (telegram_id, email, group_name, subject, deadline, task, attachment, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entry["telegram_id"],
        entry["email"],
        entry["group"],
        entry["subject"],
        entry["deadline"],
        entry["task"],
        entry["attachment"],
        entry["created_at"]
    ))
    conn.commit()
    conn.close()

def get_homework_by_group(group_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT subject, deadline, task, attachment FROM homework WHERE group_name = ?", (group_name,))
    rows = c.fetchall()
    conn.close()
    return [{"subject": r[0], "deadline": r[1], "task": r[2], "attachment": r[3]} for r in rows]

def get_homework_by_date(group_name, date_str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT subject, deadline, task, attachment FROM homework WHERE group_name = ? AND deadline = ?", (group_name, date_str))
    rows = c.fetchall()
    conn.close()
    return [{"subject": r[0], "deadline": r[1], "task": r[2], "attachment": r[3]} for r in rows]

# -------------------- Google Sheets Backup --------------------
def connect_gsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(GSHEET_CREDS, SCOPE)
    client = gspread.authorize(creds)
    return client.open(GSHEET_NAME)

def backup_to_gsheet():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT group_name, subject, deadline, task, attachment FROM homework")
    rows = c.fetchall()
    conn.close()
    if not rows:
        return
    sheet = connect_gsheet()
    grouped = {}
    for g, subj, dl, task, att in rows:
        grouped.setdefault(g, []).append([subj, dl, task, att])
    for group, records in grouped.items():
        try:
            ws = sheet.worksheet(group)
        except gspread.exceptions.WorksheetNotFound:
            ws = sheet.add_worksheet(title=group, rows="100", cols="10")
        ws.clear()
        ws.append_row(["subject", "deadline", "task", "attachment"])
        ws.append_rows(records)

# -------------------- Email --------------------
def send_email_code(email: str, code: str):
    msg = MIMEText(f"Ваш код подтверждения: {code}")
    msg["Subject"] = "Код подтверждения для бота"
    msg["From"] = SMTP_USER
    msg["To"] = email
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

# -------------------- Главное меню --------------------
START_TEXT = (
    "Привет! 👋\nЯ — помощник студентов твоего университета.\n"
    "Могу напоминать о парах, хранить расписание и помогать с домашкой.\n\n"
    "Выбери одну из опций ниже:"
)
START_KEYBOARD = InlineKeyboardMarkup(
    [[
        InlineKeyboardButton("Расписание", callback_data="schedule"),
        InlineKeyboardButton("Домашняя работа", callback_data="homework"),
        InlineKeyboardButton("Почта", callback_data="mail"),
    ]]
)

# -------------------- Меню домашки --------------------
async def homework_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("Посмотреть", callback_data="hw_view"),
        InlineKeyboardButton("Загрузить", callback_data="hw_upload"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "📚 Вы хотите посмотреть домашнюю работу или загрузить?",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "📚 Вы хотите посмотреть домашнюю работу или загрузить?",
            reply_markup=reply_markup
        )

# -------------------- Обработка callback --------------------
async def homework_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "hw_view":
        await query.edit_message_text("Введите номер группы (например, БИ25-1):")
        context.user_data["hw_action"] = "view_group"
        return
    if data == "hw_upload":
        await query.edit_message_text("Введите вашу корпоративную почту:")
        context.user_data["hw_action"] = "upload_email"
        return
    if data == "hw_add":
        # Если уже есть подтверждённая почта, пропускаем ввод
        email = context.user_data.get("email")
        if email:
            await query.edit_message_text("Введите номер группы:")
            context.user_data["hw_action"] = "upload_group"
        else:
            await query.edit_message_text("Введите вашу корпоративную почту:")
            context.user_data["hw_action"] = "upload_email"
        return
    if data == "hw_to_menu":
        await query.edit_message_text(START_TEXT, reply_markup=START_KEYBOARD)
        context.user_data.clear()
        return

# -------------------- Обработчик сообщений --------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    msg = update.message
    if msg is None:
        return
    text = (msg.text or "").strip()
    uid = msg.from_user.id
    action = context.user_data.get("hw_action")

    if not action:
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ---- Просмотр ----
    if action == "view_group":
        group = text
        records = get_homework_by_group(group)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Добавить ДЗ", callback_data="hw_add"),
                                    InlineKeyboardButton("В меню", callback_data="hw_to_menu")]])
        if not records:
            await msg.reply_text("❌ В этой группе пока нет домашки.", reply_markup=kb)
        else:
            out = f"📖 Домашка для *{group}:*\n\n"
            for idx, r in enumerate(records, start=1):
                out += (f"#{idx}\n📘 *{r['subject']}*\n📅 Дедлайн: {r['deadline']}\n"
                        f"✏️ {r['task']}\n📎 {r['attachment']}\n\n")
            await msg.reply_text(out, parse_mode="Markdown", reply_markup=kb)
        context.user_data.clear()
        conn.close()
        return

    # ---- Верификация email ----
    if action == "upload_email":
        email = text
        if not email.endswith("@edu.fa.ru"):
            await msg.reply_text("❌ Разрешены только адреса на @edu.fa.ru")
            conn.close()
            return
        c.execute("SELECT email FROM blacklist WHERE email = ?", (email,))
        if c.fetchone():
            await msg.reply_animation(animation="https://i.pinimg.com/originals/5c/81/de/5c81de8be60ed702e94a5fffc682db51.gif",
                                      caption="Вы были забанены за нарушение правил!")
            conn.close()
            return
        c.execute("SELECT telegram_id FROM valid_emails WHERE email = ?", (email,))
        row = c.fetchone()
        if row:
            if row[0] == uid:
                context.user_data.update(email=email, telegram_id=uid,
                                         created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                await msg.reply_text("Введите номер группы (например, БИ25-1):")
                context.user_data["hw_action"] = "upload_group"
            else:
                await msg.reply_text("❌ Эта почта уже привязана к другому пользователю.")
            conn.close()
            return
        code = str(random.randint(100000, 999999))
        context.user_data.update(pending_email=email, pending_code=code)
        try:
            send_email_code(email, code)
            await msg.reply_text("Введите код, отправленный на вашу почту.")
            context.user_data["hw_action"] = "verify_code"
        except Exception as e:
            await msg.reply_text(f"⚠️ Не удалось отправить письмо: {e}")
        conn.close()
        return

    if action == "verify_code":
        if text == context.user_data.get("pending_code"):
            email = context.user_data["pending_email"]
            c.execute("INSERT OR REPLACE INTO valid_emails VALUES (?, ?, ?)",
                      (email, uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            context.user_data.update(email=email, telegram_id=uid,
                                     created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            await msg.reply_text("✅ Почта подтверждена!\nВведите номер группы:")
            context.user_data["hw_action"] = "upload_group"
        else:
            await msg.reply_text("❌ Неверный код. Попробуйте снова.")
        conn.close()
        return

    # ---- Добавление ДЗ ----
    if action == "upload_group":
        context.user_data["group"] = text
        c.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
                  (uid, context.user_data["email"], text, context.user_data["created_at"]))
        conn.commit()
        await msg.reply_text("📘 По какому предмету домашка?")
        context.user_data["hw_action"] = "upload_subject"
        conn.close()
        return

    if action == "upload_subject":
        context.user_data["subject"] = text
        await msg.reply_text("📅 Введите дедлайн (например: 25.09.2025):")
        context.user_data["hw_action"] = "upload_deadline"
        return

    if action == "upload_deadline":
        context.user_data["deadline"] = text
        await msg.reply_text("✏️ Введите текст задания:")
        context.user_data["hw_action"] = "upload_task"
        return

    if action == "upload_task":
        context.user_data["task"] = text
        await msg.reply_text("📎 Введите название файла или ссылку на задание (или 'нет'):")
        context.user_data["hw_action"] = "upload_attachment"
        return

    if action == "upload_attachment":
        attachment = text if text.lower() != "нет" else "-"
        context.user_data["attachment"] = attachment
        entry = {
            "telegram_id": uid,
            "email": context.user_data["email"],
            "group": context.user_data["group"],
            "subject": context.user_data["subject"],
            "deadline": context.user_data["deadline"],
            "task": context.user_data["task"],
            "attachment": attachment,
            "created_at": context.user_data["created_at"]
        }
        add_homework(entry)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Добавить ДЗ", callback_data="hw_add"),
                                    InlineKeyboardButton("В меню", callback_data="hw_to_menu")]])
        await msg.reply_text("✅ Домашка успешно добавлена!", reply_markup=kb)
        # Не очищаем email — пользователь может сразу добавить следующее ДЗ
        context.user_data.pop("subject", None)
        context.user_data.pop("deadline", None)
        context.user_data.pop("task", None)
        context.user_data.pop("attachment", None)
        context.user_data["hw_action"] = "upload_group"
        return

# -------------------- Отправка домашки по дате --------------------
async def send_homework_for_date(update, context, group: str, date_str: str):
    records = get_homework_by_date(group, date_str)
    if not records:
        return
    text_lines = [f"🧩 <b>Домашняя работа на {date_str}:</b>"]
    for hw in records:
        text_lines.append(f"📘 <b>{hw['subject']}</b>: {hw['task']} (до {hw['deadline']})")
        if hw["attachment"] and hw["attachment"] != "-":
            text_lines.append(f"📎 {hw['attachment']}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(text_lines), parse_mode="HTML")