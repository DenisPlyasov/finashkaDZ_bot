import os
import re
import sys
import logging
from datetime import datetime, timedelta
from typing import Tuple, Dict, List, Any, Optional
from collections import defaultdict  # если ещё не импортировал
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from fa_api import FaAPI  # библиотека расписаний

# ================== НАСТРОЙКИ / СОСТОЯНИЯ ==================
ASK_GROUP, CHOOSE_GROUP, CHOOSE_RANGE, ASK_CUSTOM_DATE = range(4)

DATE_INPUT_RE = re.compile(r"^(\d{2})[.](\d{2})[.](\d{4})$")  # DD.MM.YYYY
DATE_FMT_API = "%Y.%m.%d"
DATE_FMT_HUMAN = "%d.%m.%Y"

fa = FaAPI()

logging.basicConfig(
    level=logging.WARNING,  # не шумим логами
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fa-bot")

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

# --- ДОБАВЬ помощник рядом с остальными утилитами ---
def _norm_api_date_key(s: str) -> Optional[str]:
    """Привести строку-дату к виду YYYY.MM.DD или вернуть None, если это не дата."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    m = re.match(r"^(\d{4})[.\-\/](\d{2})[.\-\/](\d{2})$", s)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}.{mo}.{d}"  # единый формат с точками


def _to_api_date(d: datetime) -> str:
    return d.strftime(DATE_FMT_API)


def _to_human_date(d: datetime) -> str:
    return d.strftime(DATE_FMT_HUMAN)


def _week_bounds(dt: datetime) -> Tuple[datetime, datetime]:
    """Понедельник..Воскресенье для недели dt."""
    start = dt - timedelta(days=dt.weekday())
    end = start + timedelta(days=6)
    return start, end


def _lesson_date_api(lesson: dict) -> str:
    """Возвращает дату занятия в формате 'YYYY.MM.DD' из разных полей."""
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


def _time_range_of(lesson: dict) -> str:
    """Возвращает 'HH:MM-HH:MM' из разных полей."""
    t = (lesson.get("time") or "").strip()
    if t:
        return t
    b = (lesson.get("begin") or lesson.get("time_from") or lesson.get("start_time") or "").strip()
    e = (lesson.get("end") or lesson.get("time_to") or lesson.get("end_time") or "").strip()
    return f"{b}-{e}" if b and e else ""


def _int_or_zero(x) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def _extract_lesson_fields(lesson: dict) -> dict:
    """Нормализует поля пары: время, преподаватель, аудитория, предмет, тип, перерыв."""
    time_range = _time_range_of(lesson)

    teacher = (
        lesson.get("teacher")
        or lesson.get("lecturer")
        or lesson.get("teacher_name")
        or lesson.get("prepod")
        or ""
    )
    if isinstance(teacher, dict):
        teacher = teacher.get("name", "")
    if isinstance(teacher, list):
        teacher = ", ".join([t.get("name", "") if isinstance(t, dict) else str(t) for t in teacher])

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

    ltype = (
        lesson.get("type")
        or lesson.get("lesson_type")
        or lesson.get("format")
        or lesson.get("kind")
        or ""
    ).strip()

    brk = (
        lesson.get("break")
        or lesson.get("break_min")
        or lesson.get("break_minutes")
        or lesson.get("pause")
        or 0
    )

    return {
        "time": time_range,
        "teacher": str(teacher).strip(),
        "room": str(room).strip(),
        "title": title,
        "ltype": ltype,       # печатаем в (круглых скобках), без курсива
        "break": _int_or_zero(brk),
    }


def _group_by_date(data) -> Dict[str, List[dict]]:
    """Вернуть dict {'YYYY.MM.DD': [lessons]} независимо от входного формата."""
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
    """
    Оставить занятия только на заданную дату (YYYY.MM.DD).
    Поддерживает list и dict (в dict ключи могут быть с точками/дефисами — нормализуем).
    """
    if isinstance(data, dict):
        # нормализуем ключи к YYYY.MM.DD
        for k, v in data.items():
            k2 = _norm_api_date_key(k)
            if k2 == target_api_date:
                return list(v or [])
        return []
    if isinstance(data, list):
        return [les for les in data if _lesson_date_api(les) == target_api_date]
    return []


def _fmt_day(date_str: str, lessons: List[Dict[str, Any]], group_name_for_header: Optional[str] = None) -> str:
    """
    Вывод «как в примере»:
    - Заголовок: 'Расписание для ГРУППА на вторник (YYYY-MM-DD):'
    - Для каждого тайм-слота подряд идут пары (по 2 строки), затем 'Перерыв N минут.'
    - Пустая строка только между разными тайм-слотами.
    """
    d = datetime.strptime(date_str, DATE_FMT_API)
    dow_nom = _RU_WEEKDAY_NOM[d.weekday()]
    header_title = f"Расписание для {group_name_for_header or ''}".strip()
    header = f"<b>{header_title} на {dow_nom} ({d.strftime('%Y-%m-%d')}):</b>"

    if not lessons:
        return f"{header}\n\nНет занятий"

    # нормализуем и группируем по времени
    norm = [_extract_lesson_fields(x) for x in lessons]
    slots: Dict[str, List[dict]] = {}
    for f in norm:
        slots.setdefault(f["time"], []).append(f)

    def _time_key(t: str) -> int:
        m = re.match(r"^(\d{2}):(\d{2})", t or "")
        return (int(m.group(1)) * 60 + int(m.group(2))) if m else 10**9

    lines: List[str] = [header, ""]
    first_slot = True
    for t in sorted(slots.keys(), key=_time_key):
        slot = slots[t]
        if not first_slot:
            lines.append("")  # пустая строка между разными слотами
        first_slot = False

        # пары внутри одного времени — без пустых строк между ними
        for f in slot:
            # 1-я строка: "08:30-10:00. ФИО — Ауд."
            first_line = ""
            if f["time"]:
                first_line += f"{f['time']}."
            if f["teacher"]:
                first_line += f" {f['teacher']}"
            if f["room"]:
                first_line += f" — {f['room']}."
            lines.append(first_line.strip())

            # 2-я строка: "Предмет (тип)."
            second_line = f["title"]
            if f["ltype"]:
                second_line += f" ({f['ltype']})"
            if second_line and not second_line.endswith("."):
                second_line += "."
            lines.append(second_line.strip())

        # строка «Перерыв N минут.» — один раз на слот
        brk = max((f["break"] or 0) for f in slot)
        if brk > 0:
            lines.append(f"Перерыв {brk} минут.")

    return "\n".join(lines).rstrip()


def _fmt_week(title_prefix: str, grouped_by_date: Dict[str, List[dict]], gname: str) -> str:
    """Собирает неделю одним сообщением (несколько заголовков-дней подряд)."""
    if not grouped_by_date:
        return f"<b>{title_prefix}</b>\n\nНет занятий"
    parts: List[str] = []
    for date_str in sorted(grouped_by_date.keys()):
        parts.append(_fmt_day(date_str, grouped_by_date[date_str], gname))
    return "\n\n".join(parts).strip()


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

def _fmt_period(title: str, data_by_date) -> str:
    """
    Принимает либо dict {'YYYY.MM.DD': [lessons...]},
    либо list [lesson, ...] — тогда сгруппирует по датам сам.
    """
    # 1) Уже словарь дата -> занятия
    if isinstance(data_by_date, dict):
        if not data_by_date:
            return f"<b>{title}</b>\n\nНет занятий"
        parts = [f"<b>{title}</b>", ""]
        for date_str in sorted(data_by_date.keys()):
            parts.append(_fmt_day(date_str, data_by_date.get(date_str, [])))
        return "\n".join(parts).strip()

    # 2) Пришёл список занятий — сгруппуем по дате
    if isinstance(data_by_date, list):
        grouped = defaultdict(list)
        for les in data_by_date:
            ds = _lesson_date_api(les)
            grouped[ds].append(les)

        if not grouped:
            return f"<b>{title}</b>\n\nНет занятий"

        parts = [f"<b>{title}</b>", ""]
        for date_str in sorted(grouped.keys()):
            parts.append(_fmt_day(date_str, grouped[date_str]))
        return "\n".join(parts).strip()

    # 3) Неподдерживаемый формат
    return f"<b>{title}</b>\n\nНет данных для отображения"

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

# ================== ОБРАБОТЧИКИ ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "👋 Привет! Введите <b>название группы</b> (например, ПИ19-6):",
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

    # Точное совпадение
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

    # Несколько вариантов — предложим кнопки (до 10)
    only_groups = [g for g in groups if g.get("type") == "group"] or groups
    only_groups = only_groups[:10]

    buttons = [
        [InlineKeyboardButton(_group_name(g), callback_data=f"grp:{_group_id(g)}")] for g in only_groups
    ]
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

    # === СЕГОДНЯ ===
    if action == "rng:today":
        d = today
        ds = _to_api_date(d)
        try:
            chat_id = update.effective_chat.id  # <-- ТАК
            raw = fa.timetable_group(gid)
            lessons = _filter_lessons_by_date(raw, ds)
            text = _fmt_day(ds, lessons, gname)
            await context.bot.send_message(
                chat_id=chat_id,  # <-- именованный аргумент
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=_kb_ranges(),
            )
        except Exception as e:
            logger.exception("Ошибка timetable today: %s", e)
            await query.edit_message_text("Источник временно недоступен. Попробуйте позже.",
                                          reply_markup=_kb_ranges())
        return CHOOSE_RANGE

    # === ЗАВТРА ===
    if action == "rng:tomorrow":
        await query.answer("Получаю расписание на завтра…", show_alert=False)
        d = today + timedelta(days=1)
        ds = _to_api_date(d)
        try:
            chat_id = update.effective_chat.id  # <-- ТАК
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            # узкий диапазон: сегодня..завтра — часто надёжнее
            start = _to_api_date(today)
            end = _to_api_date(today + timedelta(days=1))
            raw = fa.timetable_group(gid, start, end)
            grouped = _group_by_date(raw)
            lessons = grouped.get(ds, [])
            text = _fmt_day(ds, lessons, gname)
            await context.bot.send_message(
                chat_id=chat_id,  # <-- именованный
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=_kb_ranges(),
            )
        except Exception as e:
            logger.exception("Ошибка timetable tomorrow: %s", e)
            await query.edit_message_text("Источник временно недоступен. Попробуйте позже.",
                                          reply_markup=_kb_ranges())
        return CHOOSE_RANGE

    # === ЭТОЙ/СЛЕД. НЕДЕЛИ — рассылка по дням ===
    # ...после вычисления grouped/ws/we:
    if action == "rng:this_week":
        ws, we = _week_bounds(today)
        ds, de = _to_api_date(ws), _to_api_date(we)

        grouped = {}  # <-- чтобы не было UnboundLocalError
        try:
            raw = fa.timetable_group(gid, ds, de)
            grouped = _group_by_date(raw)
        except Exception as e:
            logger.exception("Ошибка timetable this_week: %s", e)
            await query.edit_message_text("Источник временно недоступен. Попробуйте позже.",
                                          reply_markup=_kb_ranges())
            return CHOOSE_RANGE  # <-- ранний выход

        # заголовок в исходном сообщении
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

    # === СЛЕДУЮЩАЯ НЕДЕЛЯ (по дням отдельными сообщениями) ===
    if action == "rng:next_week":
        ws, we = _week_bounds(today + timedelta(days=7))
        ds, de = _to_api_date(ws), _to_api_date(we)

        grouped = {}  # <-- чтобы не было UnboundLocalError
        try:
            raw = fa.timetable_group(gid, ds, de)
            grouped = _group_by_date(raw)
        except Exception as e:
            logger.exception("Ошибка timetable next_week: %s", e)
            await query.edit_message_text("Источник временно недоступен. Попробуйте позже.",
                                          reply_markup=_kb_ranges())
            return CHOOSE_RANGE  # <-- ранний выход

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

    # === ВЫБОР ДАТЫ ===
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
        raw = fa.timetable_group(gid)  # берём все и фильтруем по дате (как делает оф. бот)
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


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception while handling update: %s", update)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(update.effective_chat.id, "Произошла ошибка. Попробуйте ещё раз.")
    except Exception:
        pass


# ================== MAIN ==================
def main() -> None:
    TOKEN = "8204528132:AAE3Fw9H0WJKhxGz5sP_UBiOQr-jyrrlcjo"
    logger.info(
        "PTB version = %s | Python = %s",
        getattr(telegram, "__version__", "?"),
        sys.version.replace("\n", " "),
    )
    if not TOKEN or TOKEN != "8204528132:AAE3Fw9H0WJKhxGz5sP_UBiOQr-jyrrlcjo":
        raise SystemExit("Не задан BOT_TOKEN. Укажи его в переменных окружения или впиши в код.")

    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_GROUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_group)],
            CHOOSE_GROUP: [CallbackQueryHandler(choose_group, pattern=r"^grp:")],
            CHOOSE_RANGE: [CallbackQueryHandler(choose_range, pattern=r"^rng:")],
            ASK_CUSTOM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_custom_date)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="schedule_conv",
        persistent=False,
    )

    app.add_handler(conv)
    app.add_error_handler(on_error)

    # единоразовый старт — никаких автоперезапусков и рассылок
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
