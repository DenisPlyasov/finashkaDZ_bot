from fa_api import FaAPI

START_TEXT = (
    "2️⃣ *Напишите фамилию преподавателя*"
)

from datetime import datetime

_RU_WEEKDAY_ACC = {0:"понедельник", 1:"вторник", 2:"среду", 3:"четверг", 4:"пятницу", 5:"субботу", 6:"воскресенье"}

def _weekday_acc(date_str: str) -> str:
    d = datetime.fromisoformat(date_str)  # "YYYY-MM-DD"
    return _RU_WEEKDAY_ACC[d.weekday()]

def _mins(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h*60 + m

def format_schedule_html(records: list[dict]) -> str:
    if not records:
        return "Занятий не найдено."

    records = sorted(records, key=lambda x: _mins(x["beginLesson"]))
    date_str = records[0]["date"]
    teacher = records[0].get("lecturer_title") or records[0].get("lecturer") or "Преподаватель"

    header = f"<b>Расписание для {teacher} на {_weekday_acc(date_str)}</b>\n({date_str}):\n"

    blocks = []
    for i, r in enumerate(records):
        if r["group"] != "None":
            line1 = f"<b>{r['beginLesson']}–{r['endLesson']}.</b> {r['group']} — {r['auditorium']}."
        else:
            line1 = f"<b>{r['beginLesson']}–{r['endLesson']}.</b> {r['auditorium']}."
        kind = (r.get("kindOfWork") or "").lower()
        kind_short = "семинар" if "семинар" in kind else ""
        line2 = f"{r['discipline']} ({'<i>'+kind_short+'</i>'})." if kind_short else f"{r['discipline']}."
        block = f"{line1}\n{line2}"

        if i + 1 < len(records):
            gap = _mins(records[i+1]["beginLesson"]) - _mins(r["endLesson"])
            if gap > 0:
                block += f"\n<i>Перерыв {gap} минут.</i>"

        blocks.append(block)

    return header + "\n\n".join(blocks)