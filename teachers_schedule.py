import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from fa_api import FaAPI

# ====== Константы состояний диалога ======
ASK_TEACHER, CHOOSE_TEACHER, CHOOSE_RANGE, ASK_CUSTOM_DATE = range(4)

# ====== Утилиты форматирования ======
_RU_WEEKDAY_ACC = {0:"понедельник", 1:"вторник", 2:"среду", 3:"четверг", 4:"пятницу", 5:"субботу", 6:"воскресенье"}

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

    def build_teachers_schedule_conv() -> ConversationHandler:
        """Возвращает ConversationHandler для сценария расписания преподавателя."""
        return ConversationHandler(
            entry_points=[
                CallbackQueryHandler(start_from_menu, pattern=r"^teachers_schedule$"),
                CommandHandler("teacher_schedule", cmd_start),
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

async def _ask_range(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = True):
    kb = [
        [
            InlineKeyboardButton("Сегодня", callback_data="range:today"),
            InlineKeyboardButton("Завтра", callback_data="range:tomorrow"),
        ],
        [
            InlineKeyboardButton("На неделю", callback_data="range:this_week"),
            InlineKeyboardButton("На след. неделю", callback_data="range:next_week"),
        ],
        [InlineKeyboardButton("Выбрать дату…", callback_data="range:pick_date")],
    ]
    if edit and update.message:
        await update.message.reply_text("Выберите период:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        # пришли из callback — шлём новое сообщение
        await update.effective_chat.send_message("Выберите период:", reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSE_RANGE

def _week_bounds(dt: datetime):
    """Понедельник..Воскресенье, где dt — произвольная дата."""
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday

async def on_pick_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not q.data.startswith("range:"):
        return ConversationHandler.END

    choice = q.data.split(":", 1)[1]
    now = datetime.now()
    today = now.date()
    teacher_id = context.user_data.get("teacher_id")
    teacher_name = context.user_data.get("teacher_name", "Преподаватель")

    if not teacher_id:
        await q.edit_message_text("Сначала выберите преподавателя командой /start.")
        return ConversationHandler.END

    if choice == "today":
        start = end = datetime.combine(today, datetime.min.time())
        text = await _fetch_and_format(teacher_id, start, end, teacher_name)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if choice == "tomorrow":
        d = today + timedelta(days=1)
        start = end = datetime.combine(d, datetime.min.time())
        text = await _fetch_and_format(teacher_id, start, end, teacher_name)
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        return ConversationHandler.END

    if choice == "this_week":
        start, end = _week_bounds(datetime.combine(today, datetime.min.time()))
        # Сначала уберём клавиатуру/уведомим
        await q.edit_message_text(
            f"Расписание на неделю {start.strftime('%d.%m')}–{end.strftime('%d.%m')} — отправляю по дням…"
        )
        await _send_period_by_days(update.effective_chat, teacher_id, start, end, teacher_name)
        return ConversationHandler.END

    if choice == "next_week":
        this_mon, this_sun = _week_bounds(datetime.combine(today, datetime.min.time()))
        start = this_mon + timedelta(days=7)
        end = this_sun + timedelta(days=7)
        await q.edit_message_text(
            f"Расписание на след. неделю {start.strftime('%d.%m')}–{end.strftime('%d.%m')} — отправляю по дням…"
        )
        await _send_period_by_days(update.effective_chat, teacher_id, start, end, teacher_name)
        return ConversationHandler.END

    if choice == "pick_date":
        await q.edit_message_text(
            "Введите дату в формате <b>YYYY-MM-DD</b> или <b>DD.MM.YYYY</b>:",
            parse_mode=ParseMode.HTML
        )
        return ASK_CUSTOM_DATE

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
    return ConversationHandler.END

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
            CHOOSE_RANGE: [CallbackQueryHandler(on_pick_range, pattern=r"^range:")],
            ASK_CUSTOM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_custom_date)],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        name="timetable_conv",
        persistent=False
    )


if __name__ == "__main__":
    main()
