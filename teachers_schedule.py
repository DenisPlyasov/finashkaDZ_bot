import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
import re
from telegram.error import BadRequest
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from fa_api import FaAPI
import os, json, threading
_FAV_FILE = os.path.join(os.path.dirname(__file__), "favorites.json")
_FAV_LOCK = threading.Lock()


WELCOME_TEXT_MAIN = (
    "Привет! 👋\n"
    "Я — помощник студентов твоего университета. "
    "Могу напоминать о парах и дз, хранить расписание и показывать дз других групп.\n"
    "Мы только запустили бета тест, поэтому если будут какие-то ошибки или предложения пишите: @question_finashkadzbot\n\n"
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

RING_STARTS = ["08:30", "10:10", "11:50", "14:00", "15:40", "17:25", "18:55", "20:30"]

def _num_emoji(n: int) -> str:
    """1 -> 1️⃣, 10 -> 🔟, 11 -> 1️⃣1️⃣ и т.д."""
    key = {
        0:"0️⃣", 1:"1️⃣", 2:"2️⃣", 3:"3️⃣", 4:"4️⃣",
        5:"5️⃣", 6:"6️⃣", 7:"7️⃣", 8:"8️⃣"
    }
    if n in key:
        return key[n]
    # для >10 собираем из цифр
    digit = {"0":"0️⃣","1":"1️⃣","2":"2️⃣","3":"3️⃣","4":"4️⃣","5":"5️⃣","6":"6️⃣","7":"7️⃣","8":"8️⃣"}
    return "".join(digit[ch] if ch in digit else ch for ch in str(n))

def _slot_no_from_begin(begin: str) -> int | None:
    """
    Возвращает номер пары по времени начала begin.
    Сначала ищем «почти точное» совпадение (±20 мин), иначе берём ближайшее.
    """
    try:
        b = _mins(begin)
    except Exception:
        return None
    ring_mins = []
    for t in RING_STARTS:
        try:
            ring_mins.append(_mins(t))
        except Exception:
            ring_mins.append(None)
    ring_mins = [m for m in ring_mins if m is not None]
    if not ring_mins:
        return None

    # 1) жёсткая проверка в окне ±20 минут
    for idx, m in enumerate(ring_mins):
        if abs(m - b) <= 20:
            return idx + 1

    # 2) иначе ближайшее
    idx = min(range(len(ring_mins)), key=lambda k: abs(ring_mins[k] - b))
    return idx + 1

def _weekday_acc(date_str: str) -> str:
    d = datetime.fromisoformat(date_str)  # YYYY-MM-DD
    return _RU_WEEKDAY_ACC[d.weekday()]

def _fav_load():
    with _FAV_LOCK:
        if not os.path.exists(_FAV_FILE):
            return {}
        try:
            with open(_FAV_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

def _fav_save(d):
    with _FAV_LOCK:
        tmp = _FAV_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _FAV_FILE)

def _get_user_entry(data, user_id: int):
    key = str(user_id)
    entry = data.get(key) or {}
    if not isinstance(entry, dict):
        entry = {}
    # важно: не трогаем другие разделы (groups и т.п.)
    entry.setdefault("groups", [])
    entry.setdefault("teachers", [])
    return key, entry

def get_fav_teachers(user_id: int):
    d = _fav_load()
    _, entry = _get_user_entry(d, user_id)
    return entry["teachers"]

def is_fav_teacher(user_id: int, tid: str) -> bool:
    tid = str(tid)
    return any(str(t.get("id")) == tid for t in get_fav_teachers(user_id))

def add_fav_teacher(user_id: int, tid: str, tname: str):
    d = _fav_load()
    key, entry = _get_user_entry(d, user_id)
    tid = str(tid)
    if not any(str(t.get("id")) == tid for t in entry["teachers"]):
        entry["teachers"].append({"id": tid, "name": str(tname)})
    d[key] = entry
    _fav_save(d)

def remove_fav_teacher(user_id: int, tid: str):
    d = _fav_load()
    key, entry = _get_user_entry(d, user_id)
    tid = str(tid)
    entry["teachers"] = [t for t in entry["teachers"] if str(t.get("id")) != tid]
    d[key] = entry
    _fav_save(d)

async def favorite_teacher_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    # ожидаем, что в callback_data придёт fav_teacher:open:<id>
    _, _, tid = q.data.split(":", 2)
    # нужно знать имя — можно хранить его рядом с ID и подгрузить из файла:
    favs = {t["id"]: t["name"] for t in get_fav_teachers(update.effective_user.id)}
    context.user_data["teacher_id"] = tid
    context.user_data["teacher_name"] = favs.get(tid, "Преподаватель")
    await q.edit_message_text(f"Выбран: <b>{context.user_data['teacher_name']}</b>", parse_mode=ParseMode.HTML)
    return await _ask_range(update, context, edit=False)

def _mins(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h*60 + m

def _fmt_day(records: list[dict], teacher_fallback: str = "Преподаватель") -> str:
    if not records:
        return "Занятий не найдено."

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

        slot_no = _slot_no_from_begin(begin)
        slot_emo = _num_emoji(slot_no) if slot_no else "•"
        line1 = f"{slot_emo} <b>{begin}–{end}</b>." + (f" {right}." if right else "")
        kind_lc = kind.lower()
        kind_hint = "семинар" if "семинар" in kind_lc else ("лекция" if "лекц" in kind_lc else "")
        line2 = f"{subj} ({'<i>'+kind_hint+'</i>'})." if kind_hint else f"{subj}."

        # 🔗 Ссылки выводим и для семинаров, и для лекций
        link_lines = []
        u1, d1 = _val(r.get("url1")), _val(r.get("url1_description"))
        u2, d2 = _val(r.get("url2")), _val(r.get("url2_description"))
        if _is_http(u1):
            line1 += f' (<a href="{u1}">онлайн</a>)'
        if _is_http(u2):
            line1 += f' (<a href="{u2}">онлайн</a>)'

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
    try:
        reset_selection(context)  # если импортирован — хорошо, нет — просто пропустим
    except Exception:
        pass

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
        context.user_data["teacher_id"] = t["id"]
        context.user_data["teacher_name"] = t.get("name") or t.get("full_name") or t.get("title") or "Преподаватель"
        return await _ask_range(update, context)

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

    teacher_id = q.data.split(":", 1)[1]   # <-- строка, НЕ int
    context.user_data["teacher_id"] = teacher_id

    name = (context.user_data.get("teachers_map") or {}).get(teacher_id) or "Преподаватель"
    context.user_data["teacher_name"] = name

    await q.edit_message_text("Преподаватель выбран.")
    return await _ask_range(update, context, edit=False)

def _kb_range_teacher(user_id: int, teacher_id: str | None, teacher_name: str | None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("Сегодня", callback_data="range:today"),
            InlineKeyboardButton("Завтра", callback_data="range:tomorrow"),
        ],
        [
            InlineKeyboardButton("На неделю", callback_data="range:this_week"),
            InlineKeyboardButton("На след. неделю", callback_data="range:next_week"),
        ],
        [
            InlineKeyboardButton("Выбрать дату", callback_data="range:pick_date"),
            InlineKeyboardButton("Сменить преподавателя", callback_data="range:change_teacher"),
        ],
    ]
    if teacher_id and teacher_name:
        if is_fav_teacher(user_id, teacher_id):
            rows.append([InlineKeyboardButton("Убрать из избранного", callback_data=f"fav_teacher:remove:{teacher_id}")])
        else:
            rows.append([InlineKeyboardButton("Добавить в избранное", callback_data=f"fav_teacher:add:{teacher_id}")])
    rows.append([InlineKeyboardButton("Отмена", callback_data="range:cancel")])
    return InlineKeyboardMarkup(rows)

async def _ask_range(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = True):
    user_id = update.effective_user.id
    teacher_id = context.user_data.get("teacher_id")
    teacher_name = context.user_data.get("teacher_name", "Преподаватель")
    kb = _kb_range_teacher(user_id, teacher_id, teacher_name)

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

def _reset_teacher_selection(context):
    for k in ("teacher_id", "teacher_name", "teachers_map"):
        context.user_data.pop(k, None)

async def start_teacher_from_menu(update, context):
    _reset_teacher_selection(context)
    q = getattr(update, "callback_query", None)
    if q:
        await q.answer()
        send = q.edit_message_text
    else:
        send = update.message.reply_text

    await send(
        text=(
            "⚠️ P.s. После 23:00 бот будет работать медленне, проблема на нашей стороне.\n\n"
            "2️⃣ Введите <b>фамилию преподавателя</b>\n"
            "(Например: <i>Неизвестный</i>):"
        ),
        parse_mode=ParseMode.HTML,
    )
    return ASK_TEACHER

async def on_pick_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # --- Избранное преподавателя (добавить/убрать) ---
    if data.startswith("fav_teacher:"):
        _, action, tid = data.split(":", 2)
        user_id = update.effective_user.id
        teacher_id = context.user_data.get("teacher_id") or tid
        teacher_name = context.user_data.get("teacher_name", "Преподаватель")

        if action == "add":
            add_fav_teacher(user_id, teacher_id, teacher_name)
            from settings import ensure_defaults_for_user, register_notification_jobs
            ensure_defaults_for_user(user_id)
            register_notification_jobs(context.application)
            msg = f"✅ Преподаватель <b>{teacher_name}</b> добавлен в избранное."
        else:
            remove_fav_teacher(user_id, teacher_id)
            msg = f"🚫 Преподаватель <b>{teacher_name}</b> удалён из избранного."

        await q.edit_message_text(
            msg,
            parse_mode=ParseMode.HTML,
            reply_markup=_kb_range_teacher(user_id, teacher_id, teacher_name),
        )
        return CHOOSE_RANGE
    # --- /Избранное ---

    # сюда попадают обычные кнопки выбора периода
    if not data.startswith("range:"):
        return ConversationHandler.END

    choice = data.split(":", 1)[1]
    now = datetime.now()
    today = now.date()

    teacher_id = context.user_data.get("teacher_id")
    teacher_name = context.user_data.get("teacher_name", "Преподаватель")

    # сменить преподавателя
    if choice == "change_teacher":
        context.user_data.pop("teacher_id", None)
        context.user_data.pop("teacher_name", None)
        await q.edit_message_text(
            text=(
                "⚠️ P.s. После 23:00 бот будет работать медленне, проблема на нашей стороне.\n\n"
                "2️⃣ Введите <b>фамилию преподавателя</b>\n"
                "(Например: <i>Неизвестный</i>):"
            ),
            parse_mode=ParseMode.HTML,
        )
        return ASK_TEACHER

    # если пользователь нажал любую «range:*» без выбранного преподавателя (старые кнопки/гонки) — просим ввести фамилию
    if not teacher_id:
        await q.edit_message_text(
            "Сначала выберите преподавателя.\n\nВведите фамилию:",
            parse_mode=ParseMode.HTML,
        )
        return ASK_TEACHER

    # сегодня
    if choice == "today":
        start = end = datetime.combine(today, datetime.min.time())
        text = await _fetch_and_format(teacher_id, start, end, teacher_name)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    # завтра
    if choice == "tomorrow":
        d = today + timedelta(days=1)
        start = end = datetime.combine(d, datetime.min.time())
        text = await _fetch_and_format(teacher_id, start, end, teacher_name)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    # эта неделя (Пн..Вс)
    if choice == "this_week":
        start, end = _week_bounds(datetime.combine(today, datetime.min.time()))
        try:
            await q.edit_message_text(
                f"<b>Расписание на неделю ({start.strftime('%d.%m.%y')}–{end.strftime('%d.%m.%y')})</b>\n\n"
                "Отправляю по дням ниже ⬇️",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        await _send_period_by_days(update.effective_chat, teacher_id, start, end, teacher_name)
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    # следующая неделя
    if choice == "next_week":
        this_mon, this_sun = _week_bounds(datetime.combine(today, datetime.min.time()))
        start = this_mon + timedelta(days=7)
        end = this_sun + timedelta(days=7)
        try:
            await q.edit_message_text(
                f"<b>Расписание на след. неделю ({start.strftime('%d.%m.%y')}–{end.strftime('%d.%m.%y')})</b>\n\n"
                "Отправляю по дням ниже ⬇️",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        await _send_period_by_days(update.effective_chat, teacher_id, start, end, teacher_name)
        await _ask_range(update, context, edit=False)
        return CHOOSE_RANGE

    # выбрать дату
    if choice == "pick_date":
        await q.edit_message_text(
            "Введите дату в формате <b>YYYY-MM-DD</b> или <b>DD.MM.YYYY</b>:",
            parse_mode=ParseMode.HTML,
        )
        return ASK_CUSTOM_DATE

    # отмена → главное меню
    if choice == "cancel":
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

async def teacher_schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start_teacher_from_menu(update, context)

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
teacher_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_teacher_from_menu, pattern=r"^teachers_schedule$"),
        CommandHandler("teacher_schedule", teacher_schedule_cmd),
    ],
    states={
        ASK_TEACHER:    [MessageHandler(filters.TEXT & ~filters.COMMAND, on_teacher_surname)],
        CHOOSE_TEACHER: [CallbackQueryHandler(on_pick_teacher, pattern=r"^pick_teacher:")],
        CHOOSE_RANGE:   [CallbackQueryHandler(on_pick_range, pattern=r"^(range:|fav_teacher:)")],  # ← ВАЖНО
        ASK_CUSTOM_DATE:[MessageHandler(filters.TEXT & ~filters.COMMAND, on_custom_date)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    name="teacher_conv",
    persistent=False,
    allow_reentry=True,
)