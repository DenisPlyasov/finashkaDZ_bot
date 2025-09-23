from typing import List, Dict, Optional, Callable
from datetime import date, datetime
from fa_api import FaAPI

class FaService:
    def __init__(self):
        self.fa = FaAPI()

    # Поиск
    def search_group(self, query: str) -> List[Dict]:
        return self.fa.search_group(query)

    def search_teacher(self, query: str) -> List[Dict]:
        return self.fa.search_teacher(query)

    def search_auditory(self, query: str) -> List[Dict]:
        # В разных версиях fa_api названия могут отличаться
        for attr in ("search_auditory", "search_auditorium", "search_room", "search_audience"):
            fn: Optional[Callable] = getattr(self.fa, attr, None)
            if callable(fn):
                return fn(query)
        return []

    # Расписания
    def timetable_group(self, group_id: int, start: Optional[str], end: Optional[str]):
        return self.fa.timetable_group(group_id, start, end)

    def timetable_teacher(self, teacher_id: int, start: Optional[str], end: Optional[str]):
        return self.fa.timetable_teacher(teacher_id, start, end)

    def timetable_auditory(self, aud_id: int, start: Optional[str], end: Optional[str]):
        for attr in ("timetable_auditory", "timetable_auditorium", "timetable_room", "timetable_audience"):
            fn: Optional[Callable] = getattr(self.fa, attr, None)
            if callable(fn):
                return fn(aud_id, start, end)
        return []

def ymd(d: date) -> str:
    return d.strftime("%Y.%m.%d")

def format_timetable(items: List[Dict], with_dates: bool = True) -> str:
    if not items:
        return "Расписание не найдено."
    def key(x):
        return (x.get("date", ""), x.get("beginLesson", ""), x.get("endLesson", ""))
    items = sorted(items, key=key)

    lines, cur_date = [], None
    for x in items:
        d = x.get("date")
        if with_dates and d and d != cur_date:
            try:
                dt = datetime.strptime(d, "%Y.%m.%d").date()
                d_print = dt.strftime("%d.%m.%Y")
            except Exception:
                d_print = d
            lines.append(f"\n📅 {d_print}")
            cur_date = d

        time = f"{x.get('beginLesson','?')}–{x.get('endLesson','?')}"
        subj = x.get("subject") or x.get("discipline") or x.get("nameOfDiscipline") or "Предмет"
        room = x.get("auditorium") or x.get("auditoriumName") or x.get("building", "") or "—"
        teacher = x.get("lecturer") or x.get("teacher") or x.get("teacherName") or ""

        pieces = [f"⏰ {time}", f"• {subj}"]
        if room and room != "—":
            pieces.append(f"🏫 {room}")
        if teacher:
            pieces.append(f"👨‍🏫 {teacher}")
        lines.append("  " + " | ".join(pieces))
#fs
    return "\n".join(lines).lstrip()