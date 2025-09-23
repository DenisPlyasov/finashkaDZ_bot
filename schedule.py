from fa_api import FaAPI

#Создаем объект расписания
fa = FaAPI()

#Ищем группу ПИ19-5
group = fa.search_group("БИ25-6")
#Получаем инфо о расписании группы ПИ19-5 на сегодня
timetable = fa.timetable_group(group[0]["id"])

#Ищем группу ПИ19-3
group = fa.search_group("БИ25-6")
#Получаем инфо о расписании группы ПИ19-3 с 01.10.2020 по 06.10.2020
timetable = fa.timetable_group(group[0]["id"], "23.09.2025", "25.09.2025")

#Выводим list с расписанием
print(timetable)