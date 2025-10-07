import re
import sys
import logging
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Any, Optional
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
)
from fa_api import FaAPI  # библиотека расписаний

# ================== НАСТРОЙКИ / СОСТОЯНИЯ ==================
ASK_GROUP, CHOOSE_GROUP, CHOOSE_RANGE, ASK_CUSTOM_DATE = range(4)

DATE_INPUT_RE = re.compile(r"^(\d{2})[.](\d{2})[.](\d{4})$")  # DD.MM.YYYY
DATE_FMT_API = "%Y.%m.%d"
DATE_FMT_HUMAN = "%d.%m.%Y"

fa = FaAPI()

logger = logging.getLogger("fa-bot")

_URL_RE = re.compile(r"(https?://[^\s<>()]+)", re.IGNORECASE)

# ================== ВСПОМОГАТЕЛЬНОЕ ==================
_RU_WEEKDAY_NOM = {
    0: "понедельник",
    1: "вторник",
    2: "среду",
    3: "четверг",
    4: "пятницу",
    5: "субботу",
    6: "воскресенье",
}
_RU_WEEKDAY_SHORT = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}

def _norm_api_date_key(s: str) -> Optional[str]:
    if not isinstance(s, str):
        return None
    s = s.strip()
    m = re.match(r"^(\d{4})[.\-\/](\d{2})[.\-\/](\d{2})$", s)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}.{mo}.{d}"

def _to_api_date(d: datetime) -> str:
    return d.strftime(DATE_FMT_API)

def _to_human_date(d: datetime) -> str:
    return d.strftime(DATE_FMT_HUMAN)

def _week_bounds(dt: datetime) -> Tuple[datetime, datetime]:
    start = dt - timedelta(days=dt.weekday())
    end = start + timedelta(days=6)
    return start, end

def _lesson_date_api(lesson: dict) -> str:
    raw = (
        lesson.get("date") or lesson.get("day") or lesson.get("date_str")
        or lesson.get("lesson_date") or lesson.get("start") or lesson.get("datetime")
    )
    if isinstance(raw, str) and raw:
        s = raw.strip()
        if re.match(r"^\d{4}\.\d{2}\.\d{2}$", s):
            return s
        m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})", s)
        if m:
            y, mo, d = m.groups()
            return f"{y}.{mo}.{d}"
    return datetime.now().strftime("%Y.%m.%d")

def _first_str(*vals) -> str:
    """Вернёт первый непустой str из набора значений."""
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _get_time_begin(lesson: dict) -> str:
    # самые частые алиасы «начала»
    return _first_str(
        lesson.get("begin"),
        lesson.get("begin_time"),
        lesson.get("time_from"),
        lesson.get("start_time"),
        lesson.get("start"),
        lesson.get("timeStart"),
        lesson.get("startTime"),
        lesson.get("beginLesson"),
        lesson.get("time_begin"),
    )

def _get_time_end(lesson: dict) -> str:
    # самые частые алиасы «конца»
    return _first_str(
        lesson.get("end"),
        lesson.get("end_time"),
        lesson.get("time_to"),
        lesson.get("finish"),
        lesson.get("timeEnd"),
        lesson.get("endTime"),
        lesson.get("endLesson"),
        lesson.get("time_end"),
    )

def _time_range_of(lesson: dict) -> str:
    """Вернёт 'HH:MM-HH:MM' из множества возможных полей."""
    # иногда API отдаёт сразу интервал одним полем
    t = _first_str(
        lesson.get("time"),
        lesson.get("lesson_time"),
        lesson.get("lessonTime"),
        lesson.get("para"),          # у некоторых API «пара» уже строкой "08:30-10:00"
    )
    if t:
        return t

    b = _get_time_begin(lesson)
    e = _get_time_end(lesson)
    return f"{b}-{e}" if b and e else ""

# ------- парсинг времени в минуты для расчёта перерывов

def _join_fio(last: str, first: str, middle: str) -> str:
    parts = [p.strip() for p in (last, first, middle) if isinstance(p, str) and p.strip()]
    return " ".join(parts)

# «Фамилия И. О.» / «Фамилия И.О.»
_INITIALS_RE = re.compile(r"^[А-ЯA-ZЁ][а-яa-zё\-]+(?:\s+[А-ЯA-Z]\.\s*[А-ЯA-Z]\.)$")

def _fio_from_dict(t: dict) -> str:
    # Явные «полные» поля
    full = (
        t.get("teacher_full") or t.get("full_name") or t.get("fio_full")
        or t.get("fioFull") or t.get("name_full") or t.get("display_name")
    )
    if isinstance(full, str) and full.strip():
        return full.strip()

    # Раздельные поля: и snake_case, и camelCase
    last  = t.get("last_name")   or t.get("lastName")   or t.get("surname") or t.get("family") or t.get("family_name")
    first = t.get("first_name")  or t.get("firstName")  or t.get("given_name") or t.get("name")
    mid   = t.get("middle_name") or t.get("middleName") or t.get("patronymic") or t.get("second_name") or t.get("secondName")

    fio = _join_fio(last or "", first or "", mid or "")
    if fio:
        return fio

    # Иногда кладут «fio», но там бывает короткое — отфильтруем инициалы
    fio_any = t.get("fio") or t.get("teacher") or t.get("lecturer") or t.get("title") or t.get("short_name")
    if isinstance(fio_any, str) and fio_any.strip() and not _INITIALS_RE.match(fio_any.strip()):
        return fio_any.strip()

    # Фолбэк — что есть
    return (fio_any or "").strip()


def _hhmm_to_min(s: str) -> Optional[int]:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", s or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))

def _get_teacher_full(lesson: dict) -> str:
    # 0) FA-список с полным именем
    if isinstance(lesson.get("listOfLecturers"), list):
        out = []
        for t in lesson["listOfLecturers"]:
            if isinstance(t, dict):
                # В FA полное: lecturer_title
                fio = t.get("lecturer_title") or t.get("full_name") or t.get("fio")
                if not fio:
                    fio = _join_fio(t.get("surname") or t.get("last_name") or "",
                                    t.get("name") or t.get("first_name") or "",
                                    t.get("patronymic") or t.get("middle_name") or "")
                if fio:
                    out.append(fio.strip())
            else:
                out.append(str(t).strip())
        if out:
            return "; ".join(out)

    # 1) массив/список преподов из других API
    for key in ("teachers", "lecturers"):
        items = lesson.get(key)
        if isinstance(items, list) and items:
            out = []
            for t in items:
                if isinstance(t, dict):
                    fio = (
                        t.get("lecturer_title") or t.get("teacher_full") or t.get("full_name") or t.get("fio") or
                        _join_fio(t.get("surname") or t.get("last_name") or "",
                                  t.get("name") or t.get("first_name") or "",
                                  t.get("patronymic") or t.get("middle_name") or "")
                    )
                else:
                    fio = str(t)
                if fio:
                    out.append(fio.strip())
            if out:
                return "; ".join(out)

    # 2) единичный словарь
    for key in ("teacher", "lecturer", "teacher_info"):
        t = lesson.get(key)
        if isinstance(t, dict):
            return (
                t.get("lecturer_title") or t.get("teacher_full") or t.get("full_name") or t.get("fio") or
                _join_fio(t.get("surname") or t.get("last_name") or "",
                          t.get("name") or t.get("first_name") or "",
                          t.get("patronymic") or t.get("middle_name") or "")
            ).strip()

    # 3) строковые поля
    return (
        lesson.get("lecturer_title") or
        lesson.get("teacher_full") or lesson.get("teacherFio") or lesson.get("teacher_fio") or
        lesson.get("full_name") or lesson.get("fio") or
        lesson.get("lecturer") or lesson.get("teacher") or
        lesson.get("teacher_name") or lesson.get("prepod") or ""
    ).strip()

def _normalize_ltype(s: str) -> str:
    if not isinstance(s, str):
        return ""
    x = s.strip().lower()
    if not x:
        return ""
    # смотрим по подстрокам, чтобы покрыть "Лекции", "Практические (семинарские) занятия"
    if "лекци" in x:         # лекция/лекции
        return "лекция"
    if "семинар" in x or "семинарск" in x:
        return "семинар"
    if "практичес" in x:
        return "практика"
    if "лаб" in x:
        return "лабораторная"
    if "коллоквиум" in x:
        return "коллоквиум"
    if "консультац" in x:
        return "консультация"
    if "зачет" in x or "зачёт" in x:
        return "зачёт"
    if "экзамен" in x:
        return "экзамен"
    return s.strip()


_URL_RE = re.compile(r"(https?://[^\s<>\)\]]+)", re.IGNORECASE)

def _find_online_link(lesson: dict) -> str:
    # прямые ключи из разных API
    candidates = [
        lesson.get("link"), lesson.get("url"), lesson.get("webinar"),
        lesson.get("web_url"), lesson.get("online_link"), lesson.get("conference_url"),
        lesson.get("zoom"), lesson.get("teams"), lesson.get("meet"), lesson.get("bbb"),
        lesson.get("lms_url"), lesson.get("stream_url"), lesson.get("broadcast"),
        lesson.get("video_link"),
        # ⬇️ FA: url1/url2
        lesson.get("url1"), lesson.get("url2"),
    ]

    # частые текстовые поля, где ссылка может “прятаться”
    text_fields = [
        "comment", "note", "notes", "desc", "description", "details", "info",
        "message", "commentary", "extra", "remark", "title", "subject",
        # ⬇️ FA: подписи к ссылкам
        "url1_description", "url2_description",
    ]
    for k in text_fields:
        val = lesson.get(k)
        if isinstance(val, str):
            m = _URL_RE.search(val)
            if m:
                candidates.append(m.group(1))

    # вложенные объекты
    for k in ("online", "conference", "webinar", "meeting", "stream"):
        obj = lesson.get(k)
        if isinstance(obj, dict):
            candidates.extend([obj.get("url"), obj.get("link")])
            for tv in text_fields:
                val = obj.get(tv)
                if isinstance(val, str):
                    m = _URL_RE.search(val)
                    if m:
                        candidates.append(m.group(1))

    # вложения-списки
    for k in ("attachments", "files", "links"):
        arr = lesson.get(k)
        if isinstance(arr, list):
            for it in arr:
                if isinstance(it, dict):
                    u = it.get("url") or it.get("link")
                    if isinstance(u, str):
                        candidates.append(u)

    # первый валидный http(s)
    for c in candidates:
        if isinstance(c, str):
            url = c.strip().strip(").,]}>")
            if url.lower().startswith(("http://", "https://")):
                return url
    return ""

def _is_online_lesson(lesson: dict) -> bool:
    for k in ("online", "is_online", "remote", "distance", "distance_learning", "distant", "online_lesson"):
        v = lesson.get(k)
        if isinstance(v, bool) and v:
            return True
        if isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "да"):
            return True

    room = (lesson.get("room") or lesson.get("auditorium") or lesson.get("place") or "") or ""
    building = (lesson.get("building") or "") or ""
    room_l = str(room).lower()
    building_l = str(building).lower()

    # ключевые маркеры
    if any(x in room_l for x in ("онлайн", "дистан", "zoom", "teams", "webinar", "вкс", "bbb", "meet", "в.з.", "д.а.")):
        return True
    if "виртуаль" in building_l:  # "Виртуальное"
        return True

    if _find_online_link(lesson):
        return True

    return False

def _range_to_bounds(time_range: str) -> Tuple[Optional[int], Optional[int]]:
    """Вернёт (start_min, end_min) для 'HH:MM-HH:MM'."""
    if not isinstance(time_range, str) or "-" not in time_range:
        return None, None
    left, right = time_range.split("-", 1)
    return _hhmm_to_min(left), _hhmm_to_min(right)

def _int_or_zero(x) -> int:
    try:
        return int(x)
    except Exception:
        return 0

def _extract_lesson_fields(lesson: dict) -> dict:
    time_range = _time_range_of(lesson)
    teacher = _get_teacher_full(lesson)  # полное ФИО

    room = (
        lesson.get("room")
        or lesson.get("auditorium")
        or lesson.get("auditory")
        or lesson.get("place")
        or ""
    )

    title = (
        lesson.get("title")
        or lesson.get("discipline")
        or lesson.get("subject")
        or lesson.get("lesson")
        or ""
    ).strip()

    ltype_raw = (
            lesson.get("kindOfWork")  # ⬅️ FA
            or lesson.get("type")
            or lesson.get("lesson_type")
            or lesson.get("format")
            or lesson.get("kind")
            or ""
    )
    ltype = _normalize_ltype(ltype_raw)

    brk = (
        lesson.get("break")
        or lesson.get("break_min")
        or lesson.get("break_minutes")
        or lesson.get("pause")
        or 0
    )

    link = _find_online_link(lesson)
    is_online = _is_online_lesson(lesson)

    return {
        "time": time_range,
        "teacher": str(teacher).strip(),
        "room": str(room).strip(),
        "title": title,
        "ltype": ltype,
        "break": _int_or_zero(brk),
        "link": link,
        "is_online": is_online,
    }

def _group_by_date(data) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            k2 = _norm_api_date_key(k)
            if k2 is None:
                continue
            grouped.setdefault(k2, []).extend(list(v or []))
        return grouped
    if isinstance(data, list):
        for les in data:
            ds = _lesson_date_api(les)
            grouped.setdefault(ds, []).append(les)
    return grouped

def _filter_lessons_by_date(data, target_api_date: str):
    if isinstance(data, dict):
        for k, v in data.items():
            k2 = _norm_api_date_key(k)
            if k2 == target_api_date:
                return list(v or [])
        return []
    if isinstance(data, list):
        return [les for les in data if _lesson_date_api(les) == target_api_date]
    return []

def _fmt_day(date_str: str, lessons: List[Dict[str, Any]], group_name_for_header: Optional[str] = None) -> str:
    d = datetime.strptime(date_str, DATE_FMT_API)
    dow_nom = _RU_WEEKDAY_NOM[d.weekday()]

    gtitle = (group_name_for_header or "").strip()
    header = f"Расписание <b>{gtitle}</b> на {dow_nom} ({d.strftime('%Y-%m-%d')}):"

    if not lessons:
        return f"{header}\n\nНет занятий"

    norm = []
    for x in lessons:
        f = _extract_lesson_fields(x)
        if not f["time"]:
            f["time"] = _time_range_of(x)
        norm.append(f)

    slots: Dict[str, List[dict]] = {}
    for f in norm:
        slots.setdefault(f["time"], []).append(f)

    def _range_to_bounds(t: str):
        m = re.match(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$", t or "")
        if not m:
            return None, None
        h1, m1, h2, m2 = map(int, m.groups())
        return h1 * 60 + m1, h2 * 60 + m2

    def _time_key(t: str) -> int:
        s, _ = _range_to_bounds(t)
        return s if s is not None else 10**9

    slot_keys = sorted(slots.keys(), key=_time_key)

    lines: List[str] = [header, ""]

    for i, t in enumerate(slot_keys):
        slot = slots[t]

        if i > 0:
            lines.append("")  # пустая строка между слотами

        for f in slot:
            first_line_parts = []
            if f["time"]:
                first_line_parts.append(f"<b>{f['time']}</b>.")
            if f["teacher"]:
                # удобно копировать: тэг code
                first_line_parts.append(f"<code>{f['teacher']}</code>")
            if f["room"]:
                first_line_parts.append(f"— {f['room']}.")

            # пометка онлайн/ссылка
            if f.get("link"):
                first_line_parts.append(f'(<a href="{f["link"]}">онлайн</a>)')
            elif f.get("is_online"):
                first_line_parts.append("(онлайн)")

            first_line = " ".join(first_line_parts).strip()
            if not first_line.endswith(".") and not first_line.endswith(")"):
                first_line += "."
            lines.append(first_line)

            # 2-я строка: "Предмет (<i>тип</i>)."
            second_line = f["title"].strip()
            if f["ltype"]:
                second_line += f" ({f['ltype']})"
            if second_line and not second_line.endswith("."):
                second_line += "."
            lines.append(second_line)

        # Перерыв между слотами
        cur_start, cur_end = _range_to_bounds(t)
        if cur_end is None:
            cur_end = max((_range_to_bounds(f["time"])[1] or 0) for f in slot)
        if i + 1 < len(slot_keys):
            next_start, _ = _range_to_bounds(slot_keys[i + 1])
            if next_start is not None and cur_end is not None:
                gap = next_start - cur_end
                declared = max((f.get("break") or 0) for f in slot)
                brk = max(gap, declared)
                if brk and brk > 0:
                    lines.append(f"<i>Перерыв {brk} минут.</i>")

    return "\n".join(lines).rstrip()

def _group_id(g: Dict[str, Any]):
    return g.get("id") or g.get("group_id") or g.get("gid") or g.get("uuid") or g.get("_id")

def _group_name(g: Dict[str, Any]) -> str:
    return (
        g.get("name")
        or g.get("title")
        or g.get("label")
        or g.get("group")
        or g.get("group_name")
        or g.get("fullname")
        or g.get("display")
        or str(g.get("id") or g)
    )

def _kb_ranges() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Сегодня", callback_data="rng:today"),
            InlineKeyboardButton("Завтра", callback_data="rng:tomorrow"),
        ],
        [
            InlineKeyboardButton("На неделю", callback_data="rng:this_week"),
            InlineKeyboardButton("След. неделя", callback_data="rng:next_week"),
        ],
        [
            InlineKeyboardButton("Выбрать дату", callback_data="rng:pick_date"),
            InlineKeyboardButton("Изменить группу", callback_data="rng:change_group"),
        ],
        [
            InlineKeyboardButton("Отмена", callback_data="rng:cancel"),
        ],
    ])

# ================== ОБРАБОТЧИКИ ДИАЛОГА ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # entry-point из меню: может прийти как callback_query, так и /schedule
    if update.callback_query:
        await update.callback_query.answer()
        send = update.callback_query.edit_message_text
    else:
        send = update.message.reply_text

    await send(
        "👋 Введите <b>название группы</b> (например, ПИ19-6):",
        parse_mode=ParseMode.HTML,
    )
    context.user_data.clear()
    return ASK_GROUP

async def ask_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query_text = (update.message.text or "").strip()
    if not query_text:
        await update.message.reply_text("Введите название группы ещё раз.")
        return ASK_GROUP
    try:
        groups = fa.search_group(query_text)
    except Exception as e:
        logger.exception("Ошибка поиска группы: %s", e)
        await update.message.reply_text("Произошла ошибка при поиске. Попробуйте ещё раз.")
        return ASK_GROUP

    if not groups:
        await update.message.reply_text("Мы не нашли такую группу. Пожалуйста, введите название ещё раз.")
        return ASK_GROUP

    query_l = query_text.lower()
    exact = [g for g in groups if _group_name(g).strip().lower() == query_l]
    chosen = exact[0] if len(exact) == 1 else (groups[0] if len(groups) == 1 else None)
    if chosen:
        context.user_data["group"] = chosen
        await update.message.reply_text(
            f"Вы выбрали группу: <b>{_group_name(chosen)}</b>\nТеперь выберите период:",
            parse_mode=ParseMode.HTML,
            reply_markup=_kb_ranges(),
        )
        return CHOOSE_RANGE

    only_groups = [g for g in groups if g.get("type") == "group"] or groups
    only_groups = only_groups[:10]

    buttons = [[InlineKeyboardButton(_group_name(g), callback_data=f"grp:{_group_id(g)}")] for g in only_groups]
    buttons.append([InlineKeyboardButton("Ввести заново", callback_data="grp:retry")])

    await update.message.reply_text(
        "Найдено несколько вариантов, выберите нужную группу:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    context.user_data["group_candidates"] = {str(_group_id(g)): g for g in only_groups}
    return CHOOSE_GROUP

async def choose_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "grp:retry":
        await query.edit_message_text("Введите название группы ещё раз:")
        return ASK_GROUP
    if not data.startswith("grp:"):
        return CHOOSE_GROUP

    gid = data.split(":", 1)[1]
    candidates = context.user_data.get("group_candidates") or {}
    chosen = candidates.get(gid)
    if not chosen:
        await query.edit_message_text("Не удалось определить группу. Введите название ещё раз:")
        return ASK_GROUP

    context.user_data["group"] = chosen
    await query.edit_message_text(
        f"Вы выбрали группу: <b>{_group_name(chosen)}</b>\nТеперь выберите период:",
        parse_mode=ParseMode.HTML,
        reply_markup=_kb_ranges(),
    )
    return CHOOSE_RANGE

async def choose_range(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "rng:cancel":
        await query.edit_message_text("Отменено. Используйте /start чтобы начать снова.")
        return ConversationHandler.END

    if action == "rng:change_group":
        await query.edit_message_text("Введите новое название группы:")
        return ASK_GROUP

    group = context.user_data.get("group")
    if not group:
        await query.edit_message_text("Группа не выбрана. Введите название группы:")
        return ASK_GROUP

    gid = _group_id(group)
    gname = _group_name(group)
    if not gid:
        await query.edit_message_text("Не удалось определить ID группы. Введите название ещё раз:")
        return ASK_GROUP

    today = datetime.now()

    if action == "rng:today":
        d = today
        ds = _to_api_date(d)
        try:
            chat_id = update.effective_chat.id
            raw = fa.timetable_group(gid)
            lessons = _filter_lessons_by_date(raw, ds)
            text = _fmt_day(ds, lessons, gname)
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, reply_markup=_kb_ranges())
        except Exception as e:
            logger.exception("Ошибка timetable today: %s", e)
            await query.edit_message_text("Источник временно недоступен. Попробуйте позже.", reply_markup=_kb_ranges())
        return CHOOSE_RANGE

    if action == "rng:tomorrow":
        d = today + timedelta(days=1)
        ds = _to_api_date(d)
        try:
            chat_id = update.effective_chat.id
            start = _to_api_date(today)
            end = _to_api_date(today + timedelta(days=1))
            raw = fa.timetable_group(gid, start, end)
            grouped = _group_by_date(raw)
            lessons = grouped.get(ds, [])
            text = _fmt_day(ds, lessons, gname)
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, reply_markup=_kb_ranges())
        except Exception as e:
            logger.exception("Ошибка timetable tomorrow: %s", e)
            await query.edit_message_text("Источник временно недоступен. Попробуйте позже.", reply_markup=_kb_ranges())
        return CHOOSE_RANGE

    if action == "rng:this_week":
        ws, we = _week_bounds(today)
        ds, de = _to_api_date(ws), _to_api_date(we)
        grouped = {}
        try:
            raw = fa.timetable_group(gid, ds, de)
            grouped = _group_by_date(raw)
        except Exception as e:
            logger.exception("Ошибка timetable this_week: %s", e)
            await query.edit_message_text("Источник временно недоступен. Попробуйте позже.", reply_markup=_kb_ranges())
            return CHOOSE_RANGE

        await query.edit_message_text(
            f"<b>Расписание для {gname} на неделю ({_to_human_date(ws)}–{_to_human_date(we)})</b>\n\nОтправляю по дням ниже ⬇️",
            parse_mode=ParseMode.HTML,
        )

        chat_id = update.effective_chat.id
        sent_any = False
        for date_str in sorted(grouped.keys()):
            d = datetime.strptime(date_str, DATE_FMT_API)
            if ws <= d <= we:
                text_day = _fmt_day(date_str, grouped.get(date_str, []), gname)
                await context.bot.send_message(chat_id=chat_id, text=text_day, parse_mode=ParseMode.HTML)
                sent_any = True
        if not sent_any:
            await context.bot.send_message(chat_id=chat_id, text="Нет занятий на этой неделе.")
        await context.bot.send_message(chat_id=chat_id, text="Выберите период:", reply_markup=_kb_ranges())
        return CHOOSE_RANGE

    if action == "rng:next_week":
        ws, we = _week_bounds(today + timedelta(days=7))
        ds, de = _to_api_date(ws), _to_api_date(we)
        grouped = {}
        try:
            raw = fa.timetable_group(gid, ds, de)
            grouped = _group_by_date(raw)
        except Exception as e:
            logger.exception("Ошибка timetable next_week: %s", e)
            await query.edit_message_text("Источник временно недоступен. Попробуйте позже.", reply_markup=_kb_ranges())
            return CHOOSE_RANGE

        await query.edit_message_text(
            f"<b>Расписание для {gname} на след. неделю ({_to_human_date(ws)}–{_to_human_date(we)})</b>\n\nОтправляю по дням ниже ⬇️",
            parse_mode=ParseMode.HTML,
        )

        chat_id = update.effective_chat.id
        sent_any = False
        for date_str in sorted(grouped.keys()):
            d = datetime.strptime(date_str, DATE_FMT_API)
            if ws <= d <= we:
                text_day = _fmt_day(date_str, grouped.get(date_str, []), gname)
                await context.bot.send_message(chat_id=chat_id, text=text_day, parse_mode=ParseMode.HTML)
                sent_any = True
        if not sent_any:
            await context.bot.send_message(chat_id=chat_id, text="Нет занятий на следующей неделе.")
        await context.bot.send_message(chat_id=chat_id, text="Выберите период:", reply_markup=_kb_ranges())
        return CHOOSE_RANGE

    if action == "rng:pick_date":
        await query.edit_message_text("Введите дату в формате <b>ДД.ММ.ГГГГ</b>:", parse_mode=ParseMode.HTML)
        return ASK_CUSTOM_DATE

    return CHOOSE_RANGE

async def ask_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    m = DATE_INPUT_RE.match((update.message.text or "").strip())
    if not m:
        await update.message.reply_text("Неверный формат. Введите дату как ДД.ММ.ГГГГ")
        return ASK_CUSTOM_DATE

    dd, mm, yyyy = map(int, m.groups())
    try:
        d = datetime(year=yyyy, month=mm, day=dd)
    except ValueError:
        await update.message.reply_text("Такой даты не существует. Попробуйте ещё раз.")
        return ASK_CUSTOM_DATE

    group = context.user_data.get("group")
    if not group:
        await update.message.reply_text("Сначала выберите группу: /start")
        return ConversationHandler.END

    gid = _group_id(group)
    gname = _group_name(group)
    if not gid:
        await update.message.reply_text("Не удалось определить ID группы. Введите название ещё раз.")
        return ASK_GROUP

    ds = _to_api_date(d)
    try:
        raw = fa.timetable_group(gid)
        lessons = _filter_lessons_by_date(raw, ds)
    except Exception as e:
        logger.exception("Ошибка timetable by date: %s", e)
        await update.message.reply_text("Источник временно недоступен. Попробуйте позже.")
        return CHOOSE_RANGE

    text = _fmt_day(ds, lessons, gname)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=_kb_ranges())
    return CHOOSE_RANGE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено. Используйте /start чтобы начать заново.")
    return ConversationHandler.END

# ================== СБОРКА CONVERSATION ==================
def build_schedule_groups_conv(entry_points):
    """
    Собирает ConversationHandler диалога расписаний.
    entry_points: список entry-хендлеров (например, кнопка с pattern='^schedule_groups$').
    """
    return ConversationHandler(
        entry_points=entry_points,
        states={
            ASK_GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_group)],
            CHOOSE_GROUP: [CallbackQueryHandler(choose_group, pattern=r"^grp:")],
            CHOOSE_RANGE: [CallbackQueryHandler(choose_range, pattern=r"^rng:")],
            ASK_CUSTOM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_custom_date)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="schedule_conv",
        persistent=False,
        per_message=False,
    )
