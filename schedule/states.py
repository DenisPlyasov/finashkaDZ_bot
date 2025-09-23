from aiogram.fsm.state import StatesGroup, State

class BotStates(StatesGroup):
    enter_search = State()   # ждём ввод строки поиска
    select_item  = State()   # выбор из найденного списка
    custom_date  = State()   # ввод произвольной даты
    #fsf