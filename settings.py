# --- Отправка уведомлений ---
from telegram.constants import ParseMode
import json
import os
from datetime import datetime, timedelta, time as dtime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes
from fa_api import FaAPI  # твоя библиотека расписаний
from homework import send_homework_for_date
from schedule_groups import _to_api_date, _filter_lessons_by_date, _fmt_day as fmt_group_day
from teachers_schedule import _fmt_day as fmt_teacher_day
fa = FaAPI()  # создаём объект API

FAV_FILE = os.path.join(os.path.dirname(__file__), "favorites.json")

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

_RU_WEEKDAY_ACC = {
    0: "понедельник", 1: "вторник", 2: "среду",
    3: "четверг", 4: "пятницу", 5: "субботу", 6: "воскресенье"
}

def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m

def _ensure_defaults(user_id: str):
    """Ставит schedule_day='tomorrow' и notify_times=['19:00'], если их нет."""
    data = load_favorites()
    user = data.setdefault(user_id, {})
    changed = False
    if not user.get("schedule_day"):
        user["schedule_day"] = "tomorrow"
        changed = True
    if not user.get("notify_times"):
        user["notify_times"] = ["19:00"]
        changed = True
    if changed:
        save_favorites(data)
    return user, changed

def _weekday_acc(date_iso: str) -> str:
    # date_iso: "YYYY-MM-DD" (что возвращает timetable_teacher)
    d = datetime.fromisoformat(date_iso)
    return _RU_WEEKDAY_ACC[d.weekday()]

def _s(x):  # safe str
    return (x or "").strip()

def _fmt_day_teacher(records: list[dict], teacher_fallback: str = "Преподаватель") -> str:
    if not records:
        return "Занятий не найдено."

    try:
        records = sorted(records, key=lambda r: _mins(_s(r.get("beginLesson"))))
    except Exception:
        pass

    date_iso = _s(records[0].get("date"))  # "YYYY-MM-DD"
    teacher = (
        _s(records[0].get("lecturer_title"))
        or _s(records[0].get("lecturer"))
        or teacher_fallback
    )
    email = ""
    for r in records:
        e = _s(r.get("lecturerEmail"))
        if e:
            email = e
            break

    lines = [
        f"<b>Расписание для {teacher} на {_weekday_acc(date_iso)}</b>",
        f"({date_iso}):",
        ""
    ]

    for i, r in enumerate(records):
        b = _s(r.get("beginLesson"))
        e = _s(r.get("endLesson"))
        grp = _s(r.get("group"))
        aud = _s(r.get("auditorium"))
        kind = _s(r.get("kindOfWork"))
        subj = _s(r.get("discipline"))

        right = " — ".join(x for x in (grp, aud) if x)
        line1 = f"<b>{b}–{e}</b>" + (f". {right}." if right else ".")
        kind_lc = kind.lower()
        hint = "семинар" if "семинар" in kind_lc else ("лекция" if "лекц" in kind_lc else "")
        line2 = f"{subj} ({hint})." if hint else (f"{subj}." if subj else "")

        u1, u2 = _s(r.get("url1")), _s(r.get("url2"))
        if u1.startswith("http"):
            line1 += f' (<a href="{u1}">онлайн</a>)'
        if u2.startswith("http"):
            line1 += f' (<a href="{u2}">онлайн</a>)'

        lines.append(line1)
        if line2:
            lines.append(line2)

        if i + 1 < len(records):
            nb = _s(records[i + 1].get("beginLesson"))
            if e and nb:
                try:
                    gap = _mins(nb) - _mins(e)
                    if gap > 0:
                        lines.append(f"<i>Перерыв {gap} минут.</i>")
                except Exception:
                    pass
        lines.append("")

    if email:
        lines.append(f"<b>Email:</b> <a href=\"mailto:{email}\">{email}</a>")

    return "\n".join(lines).strip()



def _ensure_defaults(user_id: str):
    """
    Гарантирует для пользователя дефолты schedule_day='tomorrow' и notify_times=['19:00'].
    Возвращает (user_data, changed), где changed=True если что-то дописали.
    """
    data = load_favorites()
    user_data = data.setdefault(user_id, {})
    changed = False

    # дефолтный день
    if not user_data.get("schedule_day"):
        user_data["schedule_day"] = "tomorrow"
        changed = True

    # дефолтное время
    times = user_data.get("notify_times")
    if not times:
        user_data["notify_times"] = ["19:00"]
        changed = True

    if changed:
        save_favorites(data)
    return user_data, changed

def load_favorites():
    if not os.path.exists(FAV_FILE):
        return {}
    try:
        with open(FAV_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def save_favorites(d: dict):
    with open(FAV_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def ensure_defaults_for_user(user_id: int) -> bool:
    """
    Ставит schedule_day='tomorrow' и notify_times=['19:00'], если их нет.
    Возвращает True, если что-то изменили/дописали.
    """
    uid = str(user_id)
    data = load_favorites()
    user = data.setdefault(uid, {})
    changed = False
    if not user.get("schedule_day"):
        user["schedule_day"] = "tomorrow"
        changed = True
    if not user.get("notify_times"):
        user["notify_times"] = ["19:00"]
        changed = True
    if changed:
        save_favorites(data)
    return changed

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
        [InlineKeyboardButton("📅 Выбрать день уведомлений", callback_data="choose_notify_day")],
        [InlineKeyboardButton("🔕 Отключить уведомления", callback_data="disable_notifications")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="back_to_schedule")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if q:
        await q.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


# --- Выбор времени уведомлений ---
async def choose_notify_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        await q.answer()
    else:
        await update.message.reply_text("Выберите время уведомлений через меню настроек.")
        return

    user_id = str(update.effective_user.id)

    # ← вот тут автопроставим tomorrow/19:00, если их ещё нет
    user_data, changed = _ensure_defaults(user_id)
    if changed:
        # раз дефолты только что записали — сразу создадим задачи
        register_notification_jobs(context.application)

    selected = set(user_data.get("notify_times", []))

    times = [f"{h:02d}:00" for h in range(6, 24)]
    keyboard = []
    for t in times:
        label = f"✅ {t}" if t in selected else t
        keyboard.append([InlineKeyboardButton(label, callback_data=f"toggle_time_{t}")])

    keyboard.append([InlineKeyboardButton("📋 В меню", callback_data="settings_back")])

    await q.edit_message_text(
        "Выберите время, в которое хотите получать уведомления для избранных групп/преподавателей:\n\n"
        "Нажмите на время, чтобы включить/отключить его. По умолчанию подсвечено 19:00.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# --- Выбор дня уведомлений ---
async def choose_notify_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    text = "Вы хотите получать уведомления на сегодня или на завтра?"
    keyboard = [
        [
            InlineKeyboardButton("Сегодня", callback_data="set_day_today"),
            InlineKeyboardButton("Завтра", callback_data="set_day_tomorrow"),
        ],
        [InlineKeyboardButton("📋 В меню", callback_data="settings_back")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# --- Установка дня уведомлений на сегодня ---
async def set_day_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = str(update.effective_user.id)
    data = load_favorites()
    user_data = data.setdefault(user_id, {})
    user_data["schedule_day"] = "today"
    save_favorites(data)

    text = "✅ Уведомления будут приходить на <b>сегодня</b>."
    keyboard = [[InlineKeyboardButton("📋 В меню", callback_data="settings_back")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# --- Установка дня уведомлений на завтра ---
async def set_day_tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = str(update.effective_user.id)
    data = load_favorites()
    user_data = data.setdefault(user_id, {})
    user_data["schedule_day"] = "tomorrow"
    save_favorites(data)

    text = "✅ Уведомления будут приходить на <b>завтра</b>."
    keyboard = [[InlineKeyboardButton("📋 В меню", callback_data="settings_back")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


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

    # Сортируем по реальному времени (чтобы 09:00 не шло после 19:00)
    def time_key(s):
        h, m = map(int, s.split(":"))
        return h * 60 + m

    user_data["notify_times"] = sorted(times, key=time_key)
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

    # удаляем все задачи из JobQueue, привязанные к этому user_id
    for job in context.application.job_queue.jobs():
        jd = job.data if hasattr(job, "data") else None
        if jd and jd.get("user_id") == int(user_id):
            job.schedule_removal()

    await q.edit_message_text(
        "🔕 Уведомления успешно отключены.\nВы всегда можете снова включить их через меню."
    )

async def clear_notify_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = str(update.effective_user.id)
    data = load_favorites()
    user_data = data.setdefault(user_id, {})
    user_data["notify_times"] = []
    save_favorites(data)

    # удаляем все задачи пользователя
    for job in context.application.job_queue.jobs():
        jd = job.data if hasattr(job, "data") else None
        if jd and jd.get("user_id") == int(user_id):
            job.schedule_removal()

    await q.edit_message_text("✅ Все времена уведомлений сняты.\nВы можете выбрать новые времена.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 В меню", callback_data="settings_back")]]))

# --- отправка уведомлений с расписанием и дз ---
async def send_notifications(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    if not chat_id:
        return
    chat_id = int(chat_id)

    today = datetime.now().date()

    # favorites.json
    try:
        with open(FAV_FILE, "r", encoding="utf-8") as f:
            favorites = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        favorites = {}

    user_data = favorites.get(str(chat_id)) or {}
    fav_groups   = user_data.get("groups")   or []
    fav_teachers = user_data.get("teachers") or []

    if not fav_groups and not fav_teachers:
        await context.bot.send_message(chat_id, "❗ У вас нет избранных групп или преподавателей для уведомлений.")
        return

    # какой день шлём
    day_pref   = user_data.get("schedule_day", "tomorrow")
    target_date = today if day_pref == "today" else (today + timedelta(days=1))
    ds_api   = _to_api_date(target_date)          # "YYYY.MM.DD"
    day_iso  = target_date.strftime("%Y-%m-%d")   # "YYYY-MM-DD"
    date_hum = target_date.strftime("%d.%m.%Y")

    # --- 1) группы
    for group in fav_groups:
        gid = group.get("id")
        gname = group.get("name")
        if not gid or not gname:
            continue

        try:
            raw = fa.timetable_group(gid, ds_api, ds_api)
            lessons = _filter_lessons_by_date(raw, ds_api)
            text = fmt_group_day(ds_api, lessons, gname)

            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)

            # если твоя send_homework_for_date принимает chat_id — оставь аргумент; если нет — убери параметр
            try:
                date_str = target_date.strftime("%d.%m.%Y")
                await send_homework_for_date(None, context, gname, date_str, chat_id=chat_id)
            except Exception:
                pass

        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось получить расписание для {gname}: {e}")

    # --- 2) преподаватели (важно: используем fmt_teacher_day из teachers_schedule)
    for teacher in fav_teachers:
        tid = teacher.get("id")
        tname = teacher.get("name") or "Преподаватель"
        if not tid:
            continue

        try:
            raw = fa.timetable_teacher(tid, ds_api, ds_api)  # список занятий за день/диапазон
            day_records = [r for r in (raw or []) if (r.get("date") or "").strip() == day_iso]

            # форматируем точь-в-точь как в модуле преподавателей
            if day_records:
                text = fmt_teacher_day(day_records, teacher_fallback=tname)
            else:
                text = f"<b>Расписание для {tname} на {day_iso}</b>\n\nЗанятий не найдено."

            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)

        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось получить расписание для {tname}: {e}")

def register_notification_jobs(application):
    import datetime as _dt
    import zoneinfo

    tz = getattr(application.job_queue, "timezone", zoneinfo.ZoneInfo("Europe/Moscow"))
    now = _dt.datetime.now(tz)
    data = load_favorites()

    # Сносим старые задачи для тех юзеров, что есть в favorites
    for job in application.job_queue.jobs():
        if job.data and str(job.data.get("user_id")) in data:
            job.schedule_removal()

    for user_id, info in data.items():
        # Если нет ни групп, ни преподавателей — пропускаем
        if not (info.get("groups") or info.get("teachers")):
            continue

        # ← гарантируем дефолты ('tomorrow', ['19:00']) если их нет
        user_data, _ = _ensure_defaults(user_id)
        notify_times = user_data["notify_times"]
        if not notify_times:
            # теоретически не должно случиться, но на всякий
            continue

        for t in notify_times:
            h, m = map(int, t.split(":"))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)

            # разовое на сегодня (если время ещё не прошло)
            if target > now:
                application.job_queue.run_once(
                    send_notifications,
                    when=(target - now).total_seconds(),
                    data={"user_id": int(user_id)},
                    chat_id=int(user_id),
                    name=f"notify_{user_id}_{t}_once",
                )

            # ежедневное
            application.job_queue.run_daily(
                send_notifications,
                time=_dt.time(hour=h, minute=m),
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
        "Привет! 👋\n"
        "Я — помощник студентов твоего университета. "
        "Могу напоминать о парах и дз, хранить расписание и показывать дз других групп.\n"
        "Мы только запустили бета тест, поэтому если будут какие-то ошибки или предложения пишите: @question_finashkadzbot\n\n"
        "Выбери одну из опций ниже:"
    )

    keyboard = [
        [
            InlineKeyboardButton("Расписание", callback_data="schedule"),
            InlineKeyboardButton("Домашняя работа", callback_data="homework"),
            InlineKeyboardButton("Почта", callback_data="mail"),
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
    # ловим и более свободный matches 'settings' — полезно, если где-то callback немного отличается
    app.add_handler(CallbackQueryHandler(settings_menu, pattern=r"settings"))
    app.add_handler(CallbackQueryHandler(choose_notify_time, pattern=r"^choose_notify_time$"))
    app.add_handler(CallbackQueryHandler(toggle_time, pattern=r"^toggle_time_"))
    app.add_handler(CallbackQueryHandler(clear_notify_times, pattern=r"^clear_notify_times$"))
    app.add_handler(CallbackQueryHandler(disable_notifications, pattern=r"^disable_notifications$"))
    app.add_handler(CallbackQueryHandler(choose_notify_day, pattern=r"^choose_notify_day$"))
    app.add_handler(CallbackQueryHandler(set_day_today, pattern=r"^set_day_today$"))
    app.add_handler(CallbackQueryHandler(set_day_tomorrow, pattern=r"^set_day_tomorrow$"))
    app.add_handler(CallbackQueryHandler(back_to_schedule_menu, pattern=r"^back_to_schedule$"))
    app.add_handler(CallbackQueryHandler(back_to_settings, pattern=r"^settings_back$"))