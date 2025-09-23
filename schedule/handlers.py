import logging
from datetime import date, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from states import BotStates
from keyboards import main_menu_kb, period_menu_kb, results_kb_tokens
from database import init_db, save_user_selection, get_user_selection
from fa_service import FaService, ymd, format_timetable

logger = logging.getLogger("fa-bot")
router = Router()
fs = FaService()

# Память: короткие токены → (kind, real_id, name) по пользователю
PICKS: dict[int, dict[str, tuple[str, str, str]]] = {}

def _pick_id(it: dict) -> str | None:
    # наиболее частые варианты ключей ID в ответах ruz
    for k in ("id", "oid", "groupOid", "teacherOid", "auditoriumOid", "auditoryOid"):
        v = it.get(k)
        if v is not None:
            return str(v)
    return None

def _pick_name(it: dict) -> str:
    return (
        it.get("name")
        or it.get("fullName")
        or it.get("auditorium")
        or it.get("label")
        or it.get("title")
        or it.get("displayName")
        or str(it.get("group", ""))
        or str(it.get("teacher", ""))
        or "Без названия"
    )

# /start
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    init_db()
    await state.clear()
    await message.answer(
        "Привет! Это бот расписания Финансового университета.\n"
        "Выберите категорию или покажите расписание по сохранённому выбору.",
        reply_markup=main_menu_kb()
    )

# /state (отладка)
@router.message(Command("state"))
async def cmd_state(message: Message, state: FSMContext):
    s = await state.get_state()
    await message.answer(f"FSM: {s}")

# Назад в главное меню
@router.callback_query(F.data == "back:main")
async def back_main(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text("Главное меню. Выберите действие:", reply_markup=main_menu_kb())

# Выбор типа: группа/преподаватель/аудитория
@router.callback_query(F.data.startswith("set:"))
async def cb_set_kind(cq: CallbackQuery, state: FSMContext):
    kind = cq.data.split(":", 1)[1]  # group|teacher|auditory
    pretty = {"group": "группу", "teacher": "преподавателя", "auditory": "аудиторию"}.get(kind, "объект")
    await state.set_state(BotStates.enter_search)
    await state.update_data(search_type=kind)
    await cq.message.edit_text(
        f"Введите название для поиска: {pretty}\n\n"
        f"Примеры:\n"
        f"• Группа: ПИ19-5\n"
        f"• Преподаватель: Иванов\n"
        f"• Аудитория: 401"
    )

# Поиск (короткие токены вместо длинного callback_data)
@router.message(BotStates.enter_search)
async def on_search(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        kind = data.get("search_type")
        query = (message.text or "").strip()

        if not kind:
            await message.answer("Сначала нажмите кнопку: группа / преподаватель / аудитория.")
            return
        if not query:
            await message.answer("Пустой запрос. Введите ещё раз.")
            return

        logger.info("SEARCH kind=%s query=%s user=%s", kind, query, message.from_user.id)

        if kind == "group":
            items = fs.search_group(query)
        elif kind == "teacher":
            items = fs.search_teacher(query)
        else:
            items = fs.search_auditory(query)

        if not items:
            await message.answer("Ничего не найдено. Попробуйте уточнить (например: ПИ19-5).")
            return

        # Готовим токены для безопасных callback'ов
        user_id = message.from_user.id
        PICKS[user_id] = {}
        pairs = []
        idx = 0
        for it in items:
            sid = _pick_id(it)
            if not sid:
                continue
            name = _pick_name(it)
            token = str(idx)
            PICKS[user_id][token] = (kind, sid, name)
            pairs.append((token, name))
            idx += 1
            if idx >= 10:
                break

        if not pairs:
            await message.answer("Ничего не найдено. Попробуйте уточнить запрос.")
            return

        await state.set_state(BotStates.select_item)
        await message.answer("Выберите из найденного списка:", reply_markup=results_kb_tokens(pairs))

    except Exception as e:
        logger.exception("SEARCH handler error: %s", e)
        await message.answer(f"Произошла ошибка при поиске: {e}\nПопробуйте снова или выберите другой тип.")

# Выбор конкретного результата по токену
@router.callback_query(BotStates.select_item, F.data.startswith("pick:"))
async def cb_pick_item(cq: CallbackQuery, state: FSMContext):
    token = cq.data.split(":", 1)[1]
    user_id = cq.from_user.id
    rec = PICKS.get(user_id, {}).get(token)
    if not rec:
        await cq.answer("Элемент не найден, выполните поиск ещё раз.", show_alert=False)
        await state.clear()
        await cq.message.edit_text("Главное меню:", reply_markup=main_menu_kb())
        return

    kind, sid, name = rec
    save_user_selection(user_id, kind, int(sid), name)
    # по желанию: очистим, чтобы не плодить память
    PICKS[user_id].pop(token, None)

    await state.clear()
    await cq.message.edit_text(
        f"✅ Сохранено: {name} ({kind}).\nТеперь выберите период:",
        reply_markup=period_menu_kb()
    )

# Меню показа расписания (если уже есть сохранённый выбор)
@router.callback_query(F.data == "show:menu")
async def cb_show_menu(cq: CallbackQuery):
    sel = get_user_selection(cq.from_user.id)
    if not sel:
        await cq.message.edit_text("Сначала выберите группу/преподавателя/аудиторию.", reply_markup=main_menu_kb())
        return
    await cq.message.edit_text(
        f"Текущий выбор: {sel['name']} ({sel['kind']}). Выберите период:",
        reply_markup=period_menu_kb()
    )

# Выбор периода
@router.callback_query(F.data.startswith("period:"))
async def cb_period(cq: CallbackQuery, state: FSMContext):
    choice = cq.data.split(":", 1)[1]
    sel = get_user_selection(cq.from_user.id)
    if not sel:
        await cq.message.edit_text("Сначала выберите объект расписания.", reply_markup=main_menu_kb())
        return

    if choice == "custom":
        await state.set_state(BotStates.custom_date)
        await cq.message.edit_text(
            "Введите дату в формате ГГГГ-ММ-ДД:\nНапример: 2025-09-24",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="back:main")]
            ])
        )
        return

    today = date.today()
    if choice == "today":
        start = end = today
    elif choice == "tomorrow":
        start = end = today + timedelta(days=1)
    elif choice == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif choice == "next":
        start = today + timedelta(days=(7 - today.weekday()))
        end = start + timedelta(days=6)
    else:
        start = end = today

    await _send_timetable(cq, sel, start, end)

# Ввод произвольной даты
@router.message(BotStates.custom_date)
async def on_custom_date(message: Message, state: FSMContext):
    sel = get_user_selection(message.from_user.id)
    txt = (message.text or "").strip()
    try:
        y, m, d = map(int, txt.split("-"))
        the_day = date(y, m, d)
    except Exception:
        await message.answer("Неверный формат. Пример: 2025-09-24")
        return
    await state.clear()
    await _send_timetable(message, sel, the_day, the_day)

# Общая отправка расписания
async def _send_timetable(target, sel, start, end):
    if not sel:
        if hasattr(target, "message"):
            await target.message.answer("Не выбран объект расписания.")
        else:
            await target.answer("Не выбран объект расписания.")
        return

    kind = sel["kind"]
    obj_id = sel["id"]
    if kind == "group":
        data = fs.timetable_group(obj_id, ymd(start), ymd(end))
    elif kind == "teacher":
        data = fs.timetable_teacher(obj_id, ymd(start), ymd(end))
    else:
        data = fs.timetable_auditory(obj_id, ymd(start), ymd(end))

    head = f"📌 {sel['name']} ({kind})\nПериод: {start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}\n\n"
    text = head + format_timetable(data, with_dates=True)

    if hasattr(target, "message"):      # CallbackQuery
        await _edit_or_send_long(target.message, text)
    else:                                # Message
        await _send_long(target, text)

async def _send_long(message: Message, text: str):
    chunk = 3500
    parts = [text[i:i+chunk] for i in range(0, len(text), chunk)] if len(text) > chunk else [text]
    for p in parts:
        await message.answer(p)

async def _edit_or_send_long(message: Message, text: str):
    try:
        if len(text) <= 3500:
            await message.edit_text(text)
        else:
            await message.edit_text(text[:3500])
            await message.answer(text[3500:])
    except Exception:
        await message.answer(text)