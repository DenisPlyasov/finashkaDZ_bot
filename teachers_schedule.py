import asyncio
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import re
import os, json, threading
_TFAV_FILE = os.path.join(os.path.dirname(__file__), "favorites_teachers.json")
_TFAV_LOCK = threading.Lock()
from telegram.error import BadRequest
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from fa_api import FaAPI

WELCOME_TEXT_MAIN = (
    "Привет! 👋\n"
    "Я — помощник студентов твоего университета. "
    "Могу напоминать о парах и дз, хранить расписание и показывать дз других групп.\n"
    "Мы только запустили бета тест, поэтому если будут какие-то ошибки или предложения пишите: @crop_uhar\n\n"
    "Выбери одну из опций ниже:"
)

def _main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Расписание", callback_data="schedule"),
        InlineKeyboardButton("Домашняя работа", callback_data="homework"),
        InlineKeyboardButton("Почта", callback_data="mail"),
    ]])

# ====== Константы состояний диалога ======
ASK_TEACHER, CHOOSE_TEACHER, CHOOSE_RANGE, ASK_CUSTOM_DATE = range(4)

# ====== Утилиты форматирования ======
_RU_WEEKDAY_ACC = {0:"понедельник", 1:"вторник", 2:"среду", 3:"четверг", 4:"пятницу", 5:"субботу", 6:"воскресенье"}

def _tfav_load() -> dict:
    with _TFAV_LOCK:
        if not os.path.exists(_TFAV_FILE):
            return {}
        try:
            with open(_TFAV_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
        except Exception:
            return {}

def _tfav_save(d: dict) -> None:
    with _TFAV_LOCK:
        tmp = _TFAV_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _TFAV_FILE)

def _normalize_user_entry(entry: dict) -> dict:
    """Гарантирует, что у пользователя есть массив 'teachers': [...]"""
    if not isinstance(entry, dict):
        return {"teachers": []}
    teachers = entry.get("teachers")
    if isinstance(teachers, list):
        out = [t for t in teachers if isinstance(t, dict) and t.get("id")]
    else:
        one = entry.get("teacher")
        out = []
        if isinstance(one, dict) and one.get("id"):
            nm = one.get("name") or one.get("title") or one.get("lecturer_title") or str(one["id"])
            out = [{"id": str(one["id"]), "name": str(nm)}]
    return {"teachers": out}

def get_fav_teachers(user_id: int) -> list[dict]:
    d = _tfav_load()
    key = str(user_id)
    entry = _normalize_user_entry(d.get(key, {}))
    d[key] = entry
    _tfav_save(d)
    return entry["teachers"]

def is_fav_teacher(user_id: int, tid: str) -> bool:
    tid = str(tid)
    return any(str(t.get("id")) == tid for t in get_fav_teachers(user_id))

def add_fav_teacher(user_id: int, tid: str, tname: str):
    d = _tfav_load()
    key = str(user_id)
    entry = _normalize_user_entry(d.get(key, {}))
    tid = str(tid)
    if not any(str(t.get("id")) == tid for t in entry["teachers"]):
        entry["teachers"].append({"id": tid, "name": str(tname or tid)})
    d[key] = entry
    _tfav_save(d)

def remove_fav_teacher(user_id: int, tid: str):
    d = _tfav_load()
    key = str(user_id)
    entry = _normalize_user_entry(d.get(key, {}))
    tid = str(tid)
    entry["teachers"] = [t for t in entry["teachers"] if str(t.get("id")) != tid]
    d[key] = entry
    _tfav_save(d)

def _weekday_acc(date_str: str) -> str:
    d = datetime.fromisoformat(date_str)  # YYYY-MM-DD
    return _RU_WEEKDAY_ACC[d.weekday()]

def _mins(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h*60 + m

def _fmt_day(records: list[dict], teacher_fallback: str = "Преподаватель") -> str:
    if not records:
        return "Занятий не найдено."

    async def start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Точка входа при нажатии кнопки 'Преподаватель' из меню расписания."""
        q = update.callback_query
        if q:
            await q.answer()
        return await cmd_start(update, context)

    def build_teachers_schedule_conv():
        return ConversationHandler(
            entry_points=[
                CallbackQueryHandler(start_from_menu, pattern=r"^teachers_schedule$"),
                CommandHandler("teacher_schedule", cmd_start),
                CallbackQueryHandler(favorite_teacher_entry, pattern=r"^favorite_teacher$"),
            ],
            states={
                ASK_TEACHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_teacher_surname)],
                CHOOSE_TEACHER: [CallbackQueryHandler(on_pick_teacher, pattern=r"^pick_teacher:")],
                CHOOSE_RANGE: [CallbackQueryHandler(on_pick_range, pattern=r"^range:")],
                ASK_CUSTOM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_custom_date)],
            },
            fallbacks=[CommandHandler("teacher_schedule", cmd_start)],
            name="timetable_conv",
            persistent=False,
        )

    def _val(x):  # None -> ""
        return (x or "").strip()

    def _is_http(u: str) -> bool:
        u = (u or "").strip().lower()
        return u.startswith("http://") or u.startswith("https://")

    records = sorted(records, key=lambda x: _mins(x["beginLesson"]))
    date_str = records[0]["date"]
    teacher = (
        records[0].get("lecturer_title")
        or records[0].get("lecturer")
        or teacher_fallback
    )

    # email из любого элемента дня
    email = next((_val(r.get("lecturerEmail")) for r in records if _val(r.get("lecturerEmail"))), "")

    header = f"<b>Расписание для {teacher} на {_weekday_acc(date_str)}</b>\n({date_str}):\n\n"
    blocks = []
    for i, r in enumerate(records):
        begin = _val(r.get("beginLesson"))
        end   = _val(r.get("endLesson"))
        group = _val(r.get("group"))
        aud   = _val(r.get("auditorium"))
        kind  = _val(r.get("kindOfWork"))
        subj  = _val(r.get("discipline"))

        # правая часть без None и лишних дефисов
        right_parts = []
        if group: right_parts.append(group)
        if aud:   right_parts.append(aud)
        right = " — ".join(right_parts)

        line1 = f"<b>{begin}–{end}.</b>" + (f" {right}." if right else "")
        kind_lc = kind.lower()
        kind_hint = "семинар" if "семинар" in kind_lc else ("лекция" if "лекц" in kind_lc else "")
        line2 = f"{subj} ({'<i>'+kind_hint+'</i>'})." if kind_hint else f"{subj}."

        # 🔗 Ссылки выводим и для семинаров, и для лекций
        link_lines = []
        u1, d1 = _val(r.get("url1")), _val(r.get("url1_description"))
        u2, d2 = _val(r.get("url2")), _val(r.get("url2_description"))
        if _is_http(u1):
            link_lines.append(f"🔗 <a href=\"{u1}\">{d1 or 'Ссылка'}</a>")
        if _is_http(u2):
            link_lines.append(f"🔗 <a href=\"{u2}\">{d2 or 'Ссылка 2'}</a>")

        block = f"{line1}\n{line2}"
        if link_lines:
            block += "\n" + "\n".join(link_lines)

        # перерыв до следующей пары
        if i + 1 < len(records):
            next_begin = _val(records[i+1].get("beginLesson"))
            if end and next_begin:
                try:
                    gap = _mins(next_begin) - _mins(end)
                    if gap > 0:
                        block += f"\n<i>Перерыв {gap} минут.</i>"
                except Exception:
                    pass

        blocks.append(block)

    footer = f"\n\n<b>Email:</b> <a href=\"mailto:{email}\">{email}</a>" if email else ""
    return header + "\n\n".join(blocks) + footer


def _fmt_period(all_records: list[dict], teacher_name: str = "Преподаватель") -> str:
    """Группируем по дате и делаем несколько блоков подряд."""
    if not all_records:
        return "Занятий не найдено в выбранном диапазоне."
    by_date = defaultdict(list)
    for r in all_records:
        by_date[r["date"]].append(r)
    parts = []
    for date in sorted(by_date.keys()):
        parts.append(_fmt_day(by_date[date], teacher_fallback=teacher_name))
    return "\n\n".join(parts)

def _to_fa_date(d: datetime) -> str:
    return d.strftime("%Y.%m.%d")

def _parse_user_date(s: str) -> datetime | None:
    """Принимаем YYYY-MM-DD или DD.MM.YYYY."""
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None

# ====== Вызовы fa_api в фоне ======
def _fa_search_teacher(query: str):
    fa = FaAPI()
    return fa.search_teacher(query)  # список преподавателей

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    return s.replace("ё", "е")

def _t_name(t: dict) -> str:
    return (
        (t.get("name") or t.get("full_name") or t.get("title") or t.get("lecturer_title") or "").strip()
    )

def _fa_timetable_teacher(teacher_id, start: datetime, end: datetime):
    fa = FaAPI()
    s = start.strftime("%Y.%m.%d")
    e = end.strftime("%Y.%m.%d")
    return fa.timetable_teacher(teacher_id, s, e)

# ====== Определяем, что источник упал ======
def _is_source_down(exc: Exception) -> bool:
    msg = str(exc).lower()
    # частые сигнатуры сетевых/HTTP-ошибок
    needles = [
        "connection error", "failed to establish a new connection",
        "max retries", "timed out", "timeout",
        "bad gateway", "gateway timeout", "service unavailable",
        "502", "503", "504",
        "cannot connect", "connection refused", "name or service not known",
    ]
    return any(n in msg for n in needles)

# ====== Хендлеры ======
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "2️⃣ Введите <b>фамилию преподавателя</b> \n" "(Например: <i>Неизвестный</i>):",
        parse_mode=ParseMode.HTML
    )
    return ASK_TEACHER

async def jump_in_with_teacher_from_favorites(update, context, teacher_id: str, teacher_name: str):
    """
    Вход в диалог расписания преподавателя с уже выбранным преподавателем (для Избранного).
    Показывает сразу клавиатуру периодов.
    Возвращает состояние CHOOSE_RANGE, чтобы ConversationHandler teachers_schedule продолжил работу.
    """
    context.user_data["teacher_id"] = str(teacher_id)
    context.user_data["teacher_name"] = teacher_name or "Преподаватель"

    # используем уже существующую функцию показа клавиатуры
    return await _ask_range(update, context, edit=False)

async def favorite_teacher_entry(update, context):
    q = update.callback_query
    await q.answer()
    fav_id = context.user_data.get("teacher_id") or (context.user_data.get("fav_teacher") or {}).get("id")
    fav_name = context.user_data.get("teacher_name") or (context.user_data.get("fav_teacher") or {}).get("name")
    if not fav_id:
        await q.edit_message_text("Сначала выберите избранного преподавателя в разделе ⭐ Избранное.")
        return ASK_TEACHER
    context.user_data["teacher_id"] = fav_id
    context.user_data["teacher_name"] = fav_name or "Преподаватель"
    # Показать выбор периода
    return await _ask_range(update, context, edit=False)

async def _send_period_by_days(chat, teacher_id: int, start: datetime, end: datetime, teacher_name: str):
    try:
        raw = await asyncio.to_thread(_fa_timetable_teacher, teacher_id, start, end)
    except Exception as e:
        await chat.send_message(f"Ошибка при запросе расписания: {e}")
        return

    if not raw:
        ds = f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"
        await chat.send_message(f"Занятий не найдено в диапазоне {ds}.")
        return

    by_date = defaultdict(list)
    for r in raw:
        by_date[r["date"]].append(r)

    # Шлём по одному сообщению на каждый день
    for day in sorted(by_date.keys()):
        text = _fmt_day(by_date[day], teacher_fallback=teacher_name)
        await chat.send_message(text, parse_mode=ParseMode.HTML)

def _pick_first(*vals) -> str:
    for v in vals:
        v = (v or "").strip()
        if v:
            return v
    return ""

def _teacher_fio_any(t: dict) -> str:
    # 1) готовые варианты
    fio = _pick_first(
        t.get("full_name"), t.get("fio_full"), t.get("display_name"),
        t.get("lecturer_title"), t.get("fio"), t.get("name"), t.get("title"),
    )
    if fio:
        return fio

    # 2) собрать из частей
    last  = _pick_first(t.get("surname"), t.get("last_name"), t.get("lastname"), t.get("lastName"), t.get("family"))
    first = _pick_first(t.get("first_name"), t.get("firstname"), t.get("firstName"), t.get("name_first"), t.get("given"))
    middle= _pick_first(t.get("middle_name"), t.get("middlename"), t.get("middleName"), t.get("patronymic"), t.get("secondName"))
    parts = [p for p in (last, first, middle) if p]
    if parts:
        return " ".join(parts)

    # 3) резерв: самое длинное поле с кириллицей
    cand = []
    for k, v in t.items():
        if isinstance(v, str):
            s = v.strip()
            if re.search(r"[А-Яа-яЁё]", s) and len(s) >= 4 and "@" not in s:
                cand.append(s)
    if cand:
        cand.sort(key=len, reverse=True)
        return cand[0]

    # 4) fallback — id
    return f"id:{t.get('id')}"

async def on_teacher_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if not query:
        await update.message.reply_text("Пустой ввод. Введите фамилию преподавателя:")
        return ASK_TEACHER

    await update.message.reply_text("Ищу преподавателя…")
    try:
        teachers = await asyncio.to_thread(_fa_search_teacher, query)
    except Exception as e:
        if _is_source_down(e):
            await update.message.reply_text(
                "Похоже, источник с расписанием сейчас <b>не работает</b>. "
                "Мы не можем дать ответ. Попробуйте позже.",
                parse_mode=ParseMode.HTML
            )
            return ConversationHandler.END
        # прочие ошибки — показываем кратко
        await update.message.reply_text(f"Ошибка при поиске преподавателя: {e}")
        return ConversationHandler.END

    #если нет препода
    if len(teachers) == 0:
        await update.message.reply_text(
            "Мы не смогли найти такого преподавателя. Напишите фамилию ещё раз:"
        )
        return ASK_TEACHER

    # если один — берём сразу
    if len(teachers) == 1:
        t = teachers[0]
        context.user_data["teacher_id"] = str(t["id"])
        context.user_data["teacher_name"] = t.get("name") or t.get("full_name") or t.get("title") or "Преподаватель"
        return await _ask_range(update, context)  # клавиатура с «избранным»

    # если несколько — даём кнопки выбора (первые 10)
    buttons = []
    teachers_map = {}
    for t in teachers[:12]:
        fio = _teacher_fio_any(t)

        # опционально добавим контекст (кафедра/должность, email) — помогает отличать однофамильцев
        dept = _pick_first(t.get("department"), t.get("chair"), t.get("cathedra"),
                           t.get("position"), t.get("post"), t.get("lecturer_rank"))
        email = _pick_first(t.get("email"), t.get("lecturerEmail"))

        label = fio if not (dept or email) else f"{fio} — {', '.join(x for x in (dept, email) if x)}"
        if len(label) > 67:
            label = label[:66] + "…"

        buttons.append([InlineKeyboardButton(label, callback_data=f"pick_teacher:{t['id']}")])
        # Сохраняем «чистое» ФИО для заголовков расписания
        teachers_map[str(t["id"])] = fio

    await update.message.reply_text(
        "Найдено несколько. Выберите преподавателя:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    context.user_data["teachers_map"] = teachers_map
    return CHOOSE_TEACHER


async def on_pick_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not q.data.startswith("pick_teacher:"):
        return ConversationHandler.END

    teacher_id = q.data.split(":", 1)[1]
    context.user_data["teacher_id"] = str(teacher_id)
    name = (context.user_data.get("teachers_map") or {}).get(teacher_id) or "Преподаватель"
    context.user_data["teacher_name"] = name
    await q.edit_message_text("Преподаватель выбран.")
    return await _ask_range(update, context, edit=False)

async def _ask_range(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = True):
    teacher_id = str(context.user_data.get("teacher_id") or "")
    teacher_name = context.user_data.get("teacher_name") or "Преподаватель"
    user_id = update.effective_user.id

    rows = [
        [InlineKeyboardButton("Сегодня", callback_data="range:today"),
         InlineKeyboardButton("Завтра", callback_data="range:tomorrow")],
        [InlineKeyboardButton("На неделю", callback_data="range:this_week"),
         InlineKeyboardButton("На след. неделю", callback_data="range:next_week")],
        [InlineKeyboardButton("Выбрать дату", callback_data="range:pick_date"),
         InlineKeyboardButton("Сменить преподавателя", callback_data="range:change_teacher")],
    ]

    if teacher_id:
        if is_fav_teacher(user_id, teacher_id):
            rows.append([InlineKeyboardButton("Убрать из избранного", callback_data=f"fav_teacher:remove:{teacher_id}")])
        else:
            rows.append([InlineKeyboardButton("Добавить в избранное", callback_data=f"fav_teacher:add:{teacher_id}")])

    rows.append([InlineKeyboardButton("Отмена", callback_data="range:cancel")])
    kb = InlineKeyboardMarkup(rows)

    if edit and getattr(update, "message", None):
        await update.message.reply_text("Выберите период:", reply_markup=kb)
    else:
        await update.effective_chat.send_message("Выберите период:", reply_markup=kb)
    return CHOOSE_RANGE

def _week_bounds(dt: datetime):
    """Понедельник..Воскресенье, где dt — произвольная дата."""
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

async def on_pick_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data
    now = datetime.now()
    today = now.date()
    teacher_id = context.user_data.get("teacher_id")
    teacher_name = context.user_data.get("teacher_name", "Преподаватель")

    # --- 1) Кнопки избранного ОБЯЗАТЕЛЬНО раньше проверки "range:" ---
    if data.startswith("fav_teacher:add:"):
        add_tid = data.split(":", 2)[2]
        add_fav_teacher(update.effective_user.id, add_tid, teacher_name)
        # 1) пробуем отредактировать
        logging.ERROR(data)
        try:
            await q.edit_message_text(
                f"✅ Преподаватель <b>{teacher_name}</b> добавлен в избранное.",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            # 2) если нельзя редактировать — шлём НОВОЕ сообщение
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ Преподаватель <b>{teacher_name}</b> добавлен в избранное.",
                parse_mode=ParseMode.HTML
            )
        # 3) перерисовываем меню диапазонов с правильной кнопкой (теперь будет «Убрать…»)
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    if data.startswith("fav_teacher:remove:"):
        rm_tid = data.split(":", 2)[2]
        remove_fav_teacher(update.effective_user.id, rm_tid)
        try:
            await q.edit_message_text(
                f"🚫 Преподаватель <b>{teacher_name}</b> убран из избранного.",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🚫 Преподаватель <b>{teacher_name}</b> убран из избранного.",
                parse_mode=ParseMode.HTML
            )
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    choice = data.split(":", 1)[1]
    # === смена преподавателя ===
    if choice == "change_teacher":
        # очищаем сохранённого преподавателя и просим ввести заново
        context.user_data.pop("teacher_id", None)
        context.user_data.pop("teacher_name", None)
        await q.edit_message_text(
            "2️⃣ Введите <b>фамилию преподавателя</b>\n(Например: <i>Неизвестный</i>):",
            parse_mode=ParseMode.HTML
        )
        return ASK_TEACHER

    # === сегодня ===
    if choice == "today":
        start = end = datetime.combine(today, datetime.min.time())
        text = await _fetch_and_format(teacher_id, start, end, teacher_name)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        # Показать снова меню выбора периода (чтобы не выходить из диалога)
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    if choice == "tomorrow":
        d = today + timedelta(days=1)
        start = end = datetime.combine(d, datetime.min.time())
        text = await _fetch_and_format(teacher_id, start, end, teacher_name)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    # === эта неделя ===
    if choice == "this_week":
        start, end = _week_bounds(datetime.combine(today, datetime.min.time()))
        try:
            await q.edit_message_text(
                f"Расписание на неделю {start.strftime('%d.%m')}–{end.strftime('%d.%m')} — отправляю по дням…"
            )
        except Exception:
            pass
        await _send_period_by_days(update.effective_chat, teacher_id, start, end, teacher_name)
        # завершающее сообщение с кнопками
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    # === следующая неделя ===
    if choice == "next_week":
        this_mon, this_sun = _week_bounds(datetime.combine(today, datetime.min.time()))
        start = this_mon + timedelta(days=7)
        end = this_sun + timedelta(days=7)
        try:
            await q.edit_message_text(
                f"Расписание на след. неделю {start.strftime('%d.%m')}–{end.strftime('%d.%m')} — отправляю по дням…"
            )
        except Exception:
            pass
        await _send_period_by_days(update.effective_chat, teacher_id, start, end, teacher_name)
        # завершающее сообщение с кнопками
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    # === выбрать дату ===
    if choice == "pick_date":
        await q.edit_message_text(
            "Введите дату в формате <b>YYYY-MM-DD</b> или <b>DD.MM.YYYY</b>:",
            parse_mode=ParseMode.HTML
        )
        return ASK_CUSTOM_DATE

    # === отмена — уже починено раньше ===
    if choice == "cancel":
        # вернуть в ГЛАВНОЕ меню (main)
        try:
            await q.edit_message_text(
                WELCOME_TEXT_MAIN,
                reply_markup=_main_menu_kb(),
            )
        except BadRequest:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=WELCOME_TEXT_MAIN,
                reply_markup=_main_menu_kb(),
            )
        return ConversationHandler.END

    return CHOOSE_RANGE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    if getattr(update, "message", None):
        await update.message.reply_text(WELCOME_TEXT_MAIN, reply_markup=_main_menu_kb())
    else:
        await context.bot.send_message(chat_id=chat_id, text=WELCOME_TEXT_MAIN, reply_markup=_main_menu_kb())
    return ConversationHandler.END

async def on_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = (update.message.text or "").strip()
    dt = _parse_user_date(s)
    if not dt:
        await update.message.reply_text("Не понял дату. Пример: 2025-09-30 или 30.09.2025. Попробуйте ещё раз:")
        return ASK_CUSTOM_DATE

    teacher_id = context.user_data.get("teacher_id")
    teacher_name = context.user_data.get("teacher_name", "Преподаватель")
    start = end = dt
    text = await _fetch_and_format(teacher_id, start, end, teacher_name)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    # Снова показать клавиатуру выбора периода
    await _ask_range(update, context, edit=False)
    return CHOOSE_RANGE

async def _fetch_and_format(teacher_id, start: datetime, end: datetime, teacher_name: str, period: bool = False) -> str:
    try:
        raw = await asyncio.to_thread(_fa_timetable_teacher, teacher_id, start, end)
    except Exception as e:
        if _is_source_down(e):
            return ("Похоже, источник с расписанием сейчас <b>не работает</b>.\n"
                    "Мы не можем дать ответ. Попробуйте позже.")
        return f"Ошибка при запросе расписания: {e}"

    if not raw:
        if start == end:
            ds = start.strftime("%Y-%m-%d")
            return f"Занятий не найдено на {ds}."
        else:
            ds = f"{start.strftime('%Y-%m-%d')} — {end.strftime('%Y-%m-%d')}"
            return f"Занятий не найдено в диапазоне {ds}."

    if period:
        return _fmt_period(raw, teacher_name=teacher_name)
    else:
        day_iso = start.strftime("%Y-%m-%d")
        day_items = [r for r in raw if r.get("date") == day_iso]
        if not day_items:
            return f"Занятий не найдено на {day_iso}."
        return _fmt_day(day_items, teacher_fallback=teacher_name)

# ====== Сборка приложения ======
def main():
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ASK_TEACHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_teacher_surname)],
            CHOOSE_TEACHER: [CallbackQueryHandler(on_pick_teacher, pattern=r"^pick_teacher:")],
            CHOOSE_RANGE: [CallbackQueryHandler(on_pick_range, pattern=r"^range:"),
                           CallbackQueryHandler(on_pick_range, pattern=r"^fav_teacher:"),
                           ],
            ASK_CUSTOM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_custom_date)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", cmd_start)],
        name="timetable_conv",
        persistent=False
    )


if __name__ == "__main__":
    main()
