from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="Выбрать группу",        callback_data="set:group")],
        [InlineKeyboardButton(text="Выбрать преподавателя", callback_data="set:teacher")],
        [InlineKeyboardButton(text="Выбрать аудиторию",     callback_data="set:auditory")],
        [InlineKeyboardButton(text="Показать расписание (мой выбор)", callback_data="show:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def period_menu_kb() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="Сегодня",           callback_data="period:today"),
            InlineKeyboardButton(text="Завтра",            callback_data="period:tomorrow"),
        ],
        [
            InlineKeyboardButton(text="Текущая неделя",    callback_data="period:week"),
            InlineKeyboardButton(text="Следующая неделя",  callback_data="period:next"),
        ],
        [InlineKeyboardButton(text="Выбрать дату…",        callback_data="period:custom")],
        [InlineKeyboardButton(text="◀ Назад",              callback_data="back:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def results_kb_tokens(pairs: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """
    pairs: [(token, name), ...]
    В callback_data уходит только короткий token → строго <= 64 байт.
    """
    rows = []
    for token, name in pairs[:10]:
        rows.append([InlineKeyboardButton(text=name, callback_data=f"pick:{token}")])
    if not rows:
        rows = [[InlineKeyboardButton(text="Ничего не найдено (назад)", callback_data="back:main")]]
    else:
        rows.append([InlineKeyboardButton(text="◀ Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)