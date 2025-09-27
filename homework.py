# homework.py (обновлённый вариант без редактирования/удаления и с ограничением на файлы)
import os
import json
from datetime import datetime
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# -------------------- Конфигурация --------------------
DATA_DIR = "data"
USERS_FILE = os.path.join(DATA_DIR, "users.json")
HOMEWORK_FILE = os.path.join(DATA_DIR, "homework.json")

# Google Sheets
SCOPE = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
GSHEET_NAME = "homework"                       
GSHEET_CREDS = "finashkadzbot-d8415e20cc18.json"  

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
    for p in [USERS_FILE, HOMEWORK_FILE]:
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

def append_homework_to_sheet(group: str, subject: str, deadline: str, task: str, attachment: str):
    sheet = connect_gsheet()
    ws = sheet.worksheet(group.strip())
    ws.append_row([subject, deadline, task, attachment])

def get_homework_from_sheet(group: str):
    sheet = connect_gsheet()
    try:
        ws = sheet.worksheet(group.strip())
        records = ws.get_all_records()
        return records
    except gspread.exceptions.WorksheetNotFound:
        raise Exception(f"В Google Таблице нет вкладки для группы {group}")
    except Exception as e:
        raise Exception(f"Ошибка при чтении Google Sheets: {e}")

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
            "📚 Вы хотите посмотреть домашнюю работу или загрузить?",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "📚 Вы хотите посмотреть домашнюю работу или загрузить?",
            reply_markup=reply_markup
        )

# -------------------- Обработка кнопок --------------------
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

    if data == "hw_to_menu":
        await query.edit_message_text(START_TEXT, reply_markup=START_KEYBOARD)
        context.user_data.clear()
        return

    if data == "hw_add":
        await query.edit_message_text("Введите вашу корпоративную почту:")
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

    # ---- Просмотр домашки ----
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

    # ---- Загрузка домашки ----
    if action == "upload_email":
        context.user_data["email"] = text
        context.user_data["telegram_id"] = uid
        context.user_data["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        users = load_json(USERS_FILE)
        users[str(uid)] = {"email": text, "group": None, "telegram_id": uid, "created_at": context.user_data["created_at"]}
        save_json(USERS_FILE, users)
        await msg.reply_text("Введите номер группы (например, БИ25-1):")
        context.user_data["hw_action"] = "upload_group"
        return

    if action == "upload_group":
        context.user_data["group"] = text
        users = load_json(USERS_FILE)
        users[str(uid)]["group"] = text
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
        await msg.reply_text("📎 Введите название файла или ссылку на задание. "
                             "Работа с файлами и фото временно недоступна.")
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

        # добавление в Google Sheets
        try:
            append_homework_to_sheet(
                entry["group"], entry["subject"], entry["deadline"],
                entry["task"], entry["attachment"]
            )
            # создаём клавиатуру с двумя кнопками
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("Добавить ДЗ", callback_data="hw_add"),
                InlineKeyboardButton("В меню", callback_data="hw_to_menu")
            ]])
            await msg.reply_text(
                "✅ Домашка успешно добавлена в Google Sheets и сохранена локально!",
                reply_markup=kb
            )
        except Exception as e:
            await msg.reply_text(
                f"⚠️ Локально сохранено, но не удалось записать в Google Sheets: {e}"
            )

    context.user_data.clear()
    return
