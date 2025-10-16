# homework.py (с верификацией email через код)
import os
import json
import random
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# -------------------- Конфигурация --------------------
DATA_DIR = "data"
USERS_FILE = os.path.join(DATA_DIR, "users.json")
HOMEWORK_FILE = os.path.join(DATA_DIR, "homework.json")
VALID_EMAILS_FILE = os.path.join(DATA_DIR, "valid_emails.json")
BLACK_LIST = os.path.join(DATA_DIR, "black_list.json")

# Google Sheets
SCOPE = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
GSHEET_NAME = "homework"
GSHEET_CREDS = "finashkadzbot-d8415e20cc18.json"

# SMTP (настрой под себя!)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "finashkadzbot@gmail.com"       # заменишь на свой email
SMTP_PASSWORD = open('password_mail.txt').readline()      # app password для SMTP

# Главное меню
START_TEXT = (
    "Привет! 👋\n"
    "Я — помощник студентов твоего университета.\n"
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

# -------------------- Утилиты --------------------
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    for p in [USERS_FILE, HOMEWORK_FILE, VALID_EMAILS_FILE, BLACK_LIST]:  # ← добавили BLACK_LIST
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# -------------------- Google Sheets --------------------
def connect_gsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(GSHEET_CREDS, SCOPE)
    client = gspread.authorize(creds)
    return client.open(GSHEET_NAME)

# -------------------- Google Sheets --------------------
def connect_gsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(GSHEET_CREDS, SCOPE)
    client = gspread.authorize(creds)
    return client.open(GSHEET_NAME)

def append_homework_to_sheet(group: str, subject: str, deadline: str, task: str, attachment: str):
    """
    Добавляет домашку в Google Sheets.
    Если вкладка с названием группы не существует — создаёт её и добавляет заголовки.
    """
    sheet = connect_gsheet()
    group_name = group.strip()

    try:
        ws = sheet.worksheet(group_name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=group_name, rows="100", cols="10")
        ws.append_row(["subject", "deadline", "task", "attachment"])

    ws.append_row([subject, deadline, task, attachment])

def get_homework_from_sheet(group: str):
    """
    Получает домашку из указанной вкладки.
    """
    sheet = connect_gsheet()
    group_name = group.strip()
    try:
        ws = sheet.worksheet(group_name)
        records = ws.get_all_records()
        return records
    except gspread.exceptions.WorksheetNotFound:
        raise Exception(f"В Google Таблице нет вкладки для группы {group_name}")
    except Exception as e:
        raise Exception(f"Ошибка при чтении Google Sheets: {e}")

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
async def homework_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Посмотреть", callback_data="hw_view"),
            InlineKeyboardButton("Загрузить", callback_data="hw_upload"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            "1️⃣ Здесь вы можете или посмотреть дз, какой-то группы или добавить дз в свою группу",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "1️⃣ Здесь вы можете или посмотреть дз, какой-то группы или добавить дз в свою группу",
            reply_markup=reply_markup
        )

# -------------------- Обработка кнопок --------------------
async def homework_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "hw_view":
        await query.edit_message_text("3️⃣ Введите номер вашей группы (например, ПИ19-6):")
        context.user_data["hw_action"] = "view_group"
        return

    if data == "hw_upload":
        await query.edit_message_text("2️⃣ Введите вашу корпоративную почту, это нужно для вашей верификации и защиты от спама")
        context.user_data["hw_action"] = "upload_email"
        return

    if data == "hw_to_menu":
        await query.edit_message_text(START_TEXT, reply_markup=START_KEYBOARD)
        context.user_data.clear()
        return

    if data == "hw_add":
        await query.edit_message_text("2️⃣ Введите вашу корпоративную почту, это нужно для вашей верификации и защиты от спама")
        context.user_data["hw_action"] = "upload_email"
        return

# -------------------- Обработчик сообщений --------------------
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_dirs()
    msg = update.message
    if msg is None:
        return
    text = (msg.text or "").strip()
    uid = msg.from_user.id

    if "hw_action" not in context.user_data:
        return
    action = context.user_data["hw_action"]

    # ---- Просмотр ----
    if action == "view_group":
        group = text
        try:
            records = get_homework_from_sheet(group)
            if not records:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Добавить ДЗ", callback_data="hw_add"),
                    InlineKeyboardButton("В меню", callback_data="hw_to_menu")
                ]])
                await msg.reply_text("❌ В этой группе пока нет домашки.", reply_markup=kb)
            else:
                out = f"📖 Домашка для *{group}:*\n\n"
                for r_idx, r in enumerate(records, start=1):
                    subj = r.get("subject", "-")
                    dl = r.get("deadline", "-")
                    task = r.get("task", "-")
                    att = r.get("attachment", "-")
                    out += (
                        f"#{r_idx}\n"
                        f"📘 *{subj}*\n"
                        f"📅 Дедлайн: {dl}\n"
                        f"✏️ {task}\n"
                        f"📎 {att}\n\n"
                    )
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Добавить ДЗ", callback_data="hw_add"),
                    InlineKeyboardButton("В меню", callback_data="hw_to_menu")
                ]])
                await msg.reply_text(out, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            await msg.reply_text(f"⚠️ Ошибка: {e}")
        context.user_data.clear()
        return

    # ---- Верификация email ----
    if action == "upload_email":
        email = text
        if not email.endswith("@edu.fa.ru"):
            await msg.reply_text("❌ Разрешены только адреса на @edu.fa.ru")
            return

        valid_emails = load_json(VALID_EMAILS_FILE)
        black_list = load_json(BLACK_LIST)

        # Если в бане — сообщение и выходим
        if email in black_list:
            await update.message.reply_animation(
                animation="https://i.pinimg.com/originals/5c/81/de/5c81de8be60ed702e94a5fffc682db51.gif",
                caption="Вы были забанены за нарушение правил сообщества!"
            )
            return

        entry = valid_emails.get(email)

        # --- Новый формат: {"telegram_id": 12345, "verified_at": "..."} ---
        if isinstance(entry, dict) and "telegram_id" in entry:
            if entry["telegram_id"] == uid:
                # владелец совпадает — пускаем дальше, как подтверждённого
                context.user_data["email"] = email
                context.user_data["telegram_id"] = uid
                context.user_data["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                await msg.reply_text("3️⃣ Введите номер вашей группы (например, ПИ19-6):")
                context.user_data["hw_action"] = "upload_group"
            else:
                # владелец другой
                await msg.reply_text(
                    "❌ По нашим данным эта почта принадлежит другому человеку. "
                    "Проверьте, не совершили ли вы ошибку при вводе и попробуйте заново."
                )
                # остаёмся в состоянии upload_email
            return

        # --- Старый формат: True — миграция в новый формат на текущего пользователя ---
        if entry is True:
            valid_emails[email] = {
                "telegram_id": uid,
                "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_json(VALID_EMAILS_FILE, valid_emails)

            context.user_data["email"] = email
            context.user_data["telegram_id"] = uid
            context.user_data["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await msg.reply_text("3️⃣ Введите номер вашей группы (например, ПИ19-6):")
            context.user_data["hw_action"] = "upload_group"
            return

        # --- Нет записи — запускаем отправку кода ---
        code = str(random.randint(100000, 999999))
        context.user_data["pending_email"] = email
        context.user_data["pending_code"] = code
        try:
            send_email_code(email, code)
            await msg.reply_text(
                "Для верификации осталось совсем чучуть, введите код, отправленный на вашу почту. "
            )
            context.user_data["hw_action"] = "verify_code"
        except Exception as e:
            await msg.reply_text(f"⚠️ Не удалось отправить письмо: {e}")
        return

    if action == "verify_code":
        if text == context.user_data.get("pending_code"):
            email = context.user_data["pending_email"]
            valid_emails = load_json(VALID_EMAILS_FILE)
            # Сохраняем новый формат: email -> {telegram_id, verified_at}
            valid_emails[email] = {
                "telegram_id": msg.from_user.id,
                "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_json(VALID_EMAILS_FILE, valid_emails)

            context.user_data["email"] = email
            context.user_data["telegram_id"] = msg.from_user.id
            context.user_data["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            await msg.reply_text("✅ Почта подтверждена!\n3️⃣ Введите номер вашей группы (например, ПИ19-6):")
            context.user_data["hw_action"] = "upload_group"
        else:
            await msg.reply_text("❌ Неверный код. Попробуйте снова.")
        return

    # ---- Добавление ДЗ ----
    if action == "upload_group":
        context.user_data["group"] = text
        users = load_json(USERS_FILE)
        users[str(uid)] = {
            "email": context.user_data["email"],
            "group": text,
            "telegram_id": uid,
            "created_at": context.user_data["created_at"]
        }
        save_json(USERS_FILE, users)
        await msg.reply_text("📘 По какому предмету домашка?")
        context.user_data["hw_action"] = "upload_subject"
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

        hw_data = load_json(HOMEWORK_FILE)
        new_id = str(len(hw_data) + 1)
        entry = {
            "id": new_id,
            "user_id": context.user_data["telegram_id"],
            "email": context.user_data["email"],
            "group": context.user_data["group"],
            "subject": context.user_data["subject"],
            "deadline": context.user_data["deadline"],
            "task": context.user_data["task"],
            "attachment": attachment,
            "created_at": context.user_data["created_at"]
        }
        hw_data[new_id] = entry
        save_json(HOMEWORK_FILE, hw_data)

        try:
            append_homework_to_sheet(
                entry["group"], entry["subject"], entry["deadline"],
                entry["task"], entry["attachment"]
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("Добавить ДЗ", callback_data="hw_add"),
                InlineKeyboardButton("В меню", callback_data="hw_to_menu")
            ]])
            await msg.reply_text(
                "✅ Домашка успешно добавлена теперь каждый может ее увидеть",
                reply_markup=kb
            )
        except Exception as e:
            await msg.reply_text(f"⚠️ Не удалось сохранить: {e}")

        context.user_data.clear()
        return

# Вставьте/замените эту версию в homework.py
import re
from datetime import datetime, timedelta

async def send_homework_for_date(update, context, group: str, date_str: str):
    """Отправляет домашнюю работу из Google Sheets для указанной группы и даты (ДД.MM.ГГГГ)."""
    try:
        try:
            homework_list = get_homework_from_sheet(group) or []
        except Exception:
            return

        def _normalize_deadline(dl):
            if dl is None:
                return ""
            if isinstance(dl, dict):
                for k in ("deadline", "date", "day", "date_str", "start", "datetime", "value", "raw"):
                    if k in dl and dl[k]:
                        nd = _normalize_deadline(dl[k])
                        if nd:
                            return nd
                if all(k in dl for k in ("year", "month", "day")):
                    try:
                        return datetime(int(dl["year"]), int(dl["month"]), int(dl["day"])).strftime("%d.%m.%Y")
                    except Exception:
                        pass
                return ""
            if isinstance(dl, (list, tuple)):
                for it in dl:
                    nd = _normalize_deadline(it)
                    if nd:
                        return nd
                return ""
            if isinstance(dl, (int, float)):
                try:
                    base = datetime(1899, 12, 30)
                    date = base + timedelta(days=int(dl))
                    return date.strftime("%d.%m.%Y")
                except Exception:
                    return str(dl)
            if isinstance(dl, datetime):
                return dl.strftime("%d.%m.%Y")
            if isinstance(dl, str):
                s = dl.strip()
                if not s:
                    return ""
                fmts = [
                    "%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d",
                    "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"
                ]
                for fmt in fmts:
                    try:
                        return datetime.strptime(s, fmt).strftime("%d.%m.%Y")
                    except Exception:
                        pass
                m = re.search(r"(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})", s)
                if m:
                    y, mo, day = m.groups()
                    return f"{int(day):02d}.{int(mo):02d}.{int(y)}"
                m2 = re.search(r"(\d{1,2})[.\-\/](\d{1,2})[.\-\/](\d{4})", s)
                if m2:
                    dd, mm, yyyy = m2.groups()
                    return f"{int(dd):02d}.{int(mm):02d}.{int(yyyy)}"
                return s
            return str(dl)

        todays_hw = []
        for hw in homework_list:
            if not isinstance(hw, dict):
                continue
            raw_deadline = hw.get("deadline")
            norm = _normalize_deadline(raw_deadline)
            if not norm:
                for alt in ("date", "deadline_date", "due", "due_date"):
                    norm = _normalize_deadline(hw.get(alt))
                    if norm:
                        break
            if norm == date_str:
                todays_hw.append(hw)

        if not todays_hw:
            return

        text_lines = [f"🧩 <b>Домашняя работа на {date_str}:</b>"]
        for hw in todays_hw:
            subject = hw.get("subject", "-")
            task = hw.get("task", "-")
            dl_out = hw.get("deadline", "-")
            att = hw.get("attachment", "")
            text_lines.append(f"📘 <b>{subject}</b>: {task} (до {dl_out})")
            if att and att != "-":
                text_lines.append(f"📎 {att}")

        text = "\n".join(text_lines)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML")

    except Exception:
        return
