# --- Отправка уведомлений ---
from telegram.constants import ParseMode
import json
import os
from datetime import datetime, time as dtime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes
from fa_api import FaAPI  # твоя библиотека расписаний
from homework import send_homework_for_date
from schedule_groups import _to_api_date, _filter_lessons_by_date, _fmt_day

fa = FaAPI()  # создаём объект API

FAV_FILE = "favorites.json"


# --- Работа с файлом избранных ---
def load_favorites():
    if not os.path.exists(FAV_FILE):
        return {}
    with open(FAV_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_favorites(data):
    with open(FAV_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# --- Главное меню настроек ---
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
    text = (
        "⚙️ <b>Меню настроек</b>\n\n"
        "В этом меню вы можете распоряжаться уведомлениями и не только.\n"
        "Выберите следующее действие:"
    )
    keyboard = [
        [InlineKeyboardButton("🕓 Выбрать время уведомлений", callback_data="choose_notify_time")],
        [InlineKeyboardButton("🔕 Отключить уведомления", callback_data="disable_notifications")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_schedule")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if q:
        await q.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


# --- Выбор времени уведомлений ---
async def choose_notify_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = str(update.effective_user.id)
    data = load_favorites()
    user_data = data.get(user_id, {})
    selected = set(user_data.get("notify_times", []))

    times = [f"{h:02d}:00" for h in range(6, 24)]
    keyboard = []

    for t in times:
        label = f"✅ {t}" if t in selected else t
        keyboard.append([InlineKeyboardButton(label, callback_data=f"toggle_time_{t}")])
    keyboard.append([InlineKeyboardButton("📋 В меню", callback_data="settings_back")])

    await q.edit_message_text(
        "Выберите время, в которое хотите получать уведомления для избранных групп:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# --- Переключение времени (галочка включается/выключается) ---
async def toggle_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    time_str = q.data.replace("toggle_time_", "")

    user_id = str(update.effective_user.id)
    data = load_favorites()
    user_data = data.setdefault(user_id, {})
    times = set(user_data.get("notify_times", []))

    if time_str in times:
        times.remove(time_str)
    else:
        times.add(time_str)

    user_data["notify_times"] = sorted(times)
    save_favorites(data)
    # пересоздаём задачи с учётом нового выбора
    register_notification_jobs(context.application)

    await choose_notify_time(update, context)


# --- Отключение уведомлений ---
async def disable_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = str(update.effective_user.id)
    data = load_favorites()
    user_data = data.get(user_id)
    if user_data:
        user_data["notify_times"] = []
        save_favorites(data)

    # удаляем все задачи из JobQueue
    for job in context.application.job_queue.jobs():
        if job.data and job.data.get("user_id") == int(user_id):
            job.schedule_removal()

    await q.edit_message_text(
        "🔕 Уведомления успешно отключены.\nВы всегда можете снова включить их через меню."
    )




# --- отправка уведомлений с расписанием и дз ---
async def send_notifications(context):
    job = context.job
    chat_id = job.chat_id
    today = datetime.now().date()
    ds = _to_api_date(today)
    job = context.job
    chat_id = job.chat_id or (job.data or {}).get("user_id")
    if not chat_id:
        # нет адресата — тихо выходим
        return
    chat_id = int(chat_id)
    # Загружаем избранные группы пользователя
    try:
        with open("favorites.json", "r", encoding="utf-8") as f:
            favorites = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        favorites = {}

    user_data = favorites.get(str(chat_id))
    if not user_data or "groups" not in user_data or not user_data["groups"]:
        await context.bot.send_message(chat_id, "❗ У вас нет избранных групп для уведомлений.")
        return

    # Для каждой группы — отправляем расписание и дз
    for group in user_data["groups"]:
        gid = group.get("id")
        gname = group.get("name")

        if not gid or not gname:
            continue

        try:
            raw = fa.timetable_group(gid)  # вызываем через объект fa
            lessons = _filter_lessons_by_date(raw, ds)
            text = _fmt_day(ds, lessons, gname)

            # 1️⃣ Отправляем расписание
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML
            )

            # 2️⃣ Отправляем домашку (если есть)
            date_str = today.strftime("%d.%m.%Y")
            try:
                await send_homework_for_date(None, context, gname, date_str)
            except Exception as e:
                print(f"[WARN] Ошибка при отправке ДЗ для {gname}: {e}")

        except Exception as e:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Не удалось получить расписание для {gname}: {e}"
            )




def register_notification_jobs(application):
    """Перерегистрировать уведомления для всех пользователей"""
    import datetime
    import zoneinfo

    tz = getattr(application.job_queue, "timezone", zoneinfo.ZoneInfo("Europe/Moscow"))
    now = datetime.datetime.now(tz)
    data = load_favorites()

    # Удаляем старые задачи пользователей
    for job in application.job_queue.jobs():
        if job.data and str(job.data.get("user_id")) in data:
            job.schedule_removal()

    for user_id, info in data.items():
        for t in info.get("notify_times", []):
            h, m = map(int, t.split(":"))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)

            # Разовое уведомление на сегодня (если время ещё не прошло)
            if target > now:
                application.job_queue.run_once(
                    send_notifications,
                    when=(target - now).total_seconds(),
                    data={"user_id": int(user_id)},
                    chat_id=int(user_id),
                    name=f"notify_{user_id}_{t}_once",
                )

            # Ежедневное уведомление
            application.job_queue.run_daily(
                send_notifications,
                time=datetime.time(hour=h, minute=m),
                data={"user_id": int(user_id)},
                chat_id=int(user_id),
                name=f"notify_{user_id}_{t}_daily",
            )

# --- Возврат в меню расписаний (плавно, без пересоздания сообщения) ---
async def back_to_schedule_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    q = update.callback_query
    await q.answer()

    text = (
        "1️⃣ Выберете какое расписание вы хотите посмотреть.\n"
        "Здесь вы сможете посмотреть расписание любой группы, расписание преподавателя, "
        "а так же выбрать расписание уведомления которого будут вам приходить "
        "(вместе с расписанием группы приходит и ее дз, если же конечно вы его ввели 😉)."
    )

    keyboard = [
        [
            InlineKeyboardButton("📘 Группы", callback_data="schedule_groups"),
            InlineKeyboardButton("👨‍🏫 Преподаватели", callback_data="teachers_schedule"),
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings")
        ]
    ]

    await q.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def back_to_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await settings_menu(update, context)


# --- Регистрация хендлеров ---
def add_settings_handlers(app):
    app.add_handler(CallbackQueryHandler(settings_menu, pattern=r"^settings$"))
    app.add_handler(CallbackQueryHandler(choose_notify_time, pattern=r"^choose_notify_time$"))
    app.add_handler(CallbackQueryHandler(toggle_time, pattern=r"^toggle_time_"))
    app.add_handler(CallbackQueryHandler(disable_notifications, pattern=r"^disable_notifications$"))
    app.add_handler(CallbackQueryHandler(back_to_schedule_menu, pattern=r"^back_to_schedule$"))
    app.add_handler(CallbackQueryHandler(back_to_settings, pattern=r"^settings_back$"))

