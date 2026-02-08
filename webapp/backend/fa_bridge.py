#!/usr/bin/env python3
import json
import sys
import os
import re
from typing import Optional, Tuple, List, Dict, Any
from datetime import date

from fa_api import FaAPI
import concurrent.futures as _fut

FA_TIMEOUT_SEC = float(os.environ.get("FA_TIMEOUT_SEC", "8"))

def _call_with_timeout(fn, *args, timeout: float = FA_TIMEOUT_SEC, **kwargs):
    with _fut.ThreadPoolExecutor(max_workers=1) as ex:
        f = ex.submit(fn, *args, **kwargs)
        try:
            return f.result(timeout=timeout)
        except _fut.TimeoutError:
            raise TimeoutError("FA_TIMEOUT")
        
# ===== Rings (как в боте) =====
_RINGS_DEFAULT = ["08:30", "10:10", "11:50", "14:00", "15:40", "17:25", "18:55", "20:30"]

def _load_rings_starts() -> List[str]:
    rings_path = os.path.join(os.path.dirname(__file__), "rings.json")
    try:
        if os.path.exists(rings_path):
            with open(rings_path, "r", encoding="utf-8") as f:
                arr = json.load(f)
            if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
                return arr
    except Exception:
        pass
    return list(_RINGS_DEFAULT)

_RINGS_STARTS = _load_rings_starts()

# ---------- базовые утилиты ----------
def _first_str(*vals) -> str:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _hhmm_to_min(s: str) -> Optional[int]:
    """
    Принимает 'HH:MM' (или 'H:MM') и возвращает минуты от 00:00.
    """
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", s or "")
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm

def _norm_date(s: str) -> str:
    """
    Приводит дату к формату YYYY.MM.DD.
    Принимает YYYY.MM.DD / YYYY-MM-DD.
    Если пусто или мусор — вернёт сегодняшнюю дату.
    """
    if not isinstance(s, str):
        return date.today().strftime("%Y.%m.%d")
    s = s.strip()
    if not s:
        return date.today().strftime("%Y.%m.%d")

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"

    m = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})$", s)
    if m:
        return s

    m = re.match(r"^(\d{4})\D(\d{1,2})\D(\d{1,2})$", s)
    if m:
        return f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}"

    return date.today().strftime("%Y.%m.%d")

def _join_fio(last: str, first: str, middle: str) -> str:
    parts = [p.strip() for p in (last, first, middle) if isinstance(p, str) and p.strip()]
    return " ".join(parts)

# ---------- парсинг времени (устойчивый) ----------
_TIME_HHMM_RE = re.compile(r"(\d{1,2})[:.](\d{2})")
_TIME_4DIGIT_RE = re.compile(r"\b(\d{1,2})(\d{2})\b")  # 1150 -> 11:50

def _to_hhmm(h: int, m: int) -> str:
    h = max(0, min(23, int(h)))
    m = max(0, min(59, int(m)))
    return f"{h:02d}:{m:02d}"

def _extract_times_from_any(s: str) -> List[str]:
    """
    Достаём список времен HH:MM из любой строки:
    - "11:50-13:20"
    - "11:50 – 13:20"
    - "11.50 — 13.20"
    - "1150-1320"
    """
    if not isinstance(s, str):
        return []
    s = s.strip()
    if not s:
        return []

    out: List[str] = []

    for m in _TIME_HHMM_RE.finditer(s):
        out.append(_to_hhmm(int(m.group(1)), int(m.group(2))))

    if not out:
        for m in _TIME_4DIGIT_RE.finditer(s):
            hh = int(m.group(1))
            mm = int(m.group(2))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                out.append(_to_hhmm(hh, mm))

    return out

def _normalize_time_range(raw: str) -> str:
    """
    Возвращает строго "HH:MM - HH:MM" или "".
    """
    times = _extract_times_from_any(raw)
    if len(times) >= 2:
        return f"{times[0]} - {times[1]}"
    return ""

def _range_to_bounds(time_range: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Поддерживает '-', '–', '—' и пробелы: "11:50 - 13:20"
    """
    if not isinstance(time_range, str):
        return None, None
    s = time_range.strip()
    if not s:
        return None, None

    parts = re.split(r"\s*[-–—]\s*", s, maxsplit=1)
    if len(parts) != 2:
        return None, None

    lt = _extract_times_from_any(parts[0])
    rt = _extract_times_from_any(parts[1])
    if not lt or not rt:
        return None, None

    return _hhmm_to_min(lt[0]), _hhmm_to_min(rt[0])

def _get_time_begin(lesson: dict) -> str:
    raw = _first_str(
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
    times = _extract_times_from_any(raw)
    return times[0] if times else ""

def _get_time_end(lesson: dict) -> str:
    raw = _first_str(
        lesson.get("end"),
        lesson.get("end_time"),
        lesson.get("time_to"),
        lesson.get("finish"),
        lesson.get("timeEnd"),
        lesson.get("endTime"),
        lesson.get("endLesson"),
        lesson.get("time_end"),
    )
    times = _extract_times_from_any(raw)
    return times[0] if times else ""

def _time_range_of(lesson: dict) -> str:
    # 1) иногда приходит сразу интервал одним полем
    raw_range = _first_str(
        lesson.get("time"),
        lesson.get("lesson_time"),
        lesson.get("lessonTime"),
        lesson.get("para"),
    )
    if raw_range:
        norm = _normalize_time_range(raw_range)
        if norm:
            return norm

    # 2) иначе собираем из begin/end
    b = _get_time_begin(lesson)
    e = _get_time_end(lesson)
    if b and e:
        return f"{b} - {e}"

    # 3) шанс: время внутри текста
    for k in ("comment", "note", "desc", "description", "info", "title"):
        v = lesson.get(k)
        if isinstance(v, str):
            norm = _normalize_time_range(v)
            if norm:
                return norm

    return ""

# ---------- номер пары ----------
def _pair_no_for_time_range(time_range: str, tolerance_min: int = 25) -> Optional[int]:
    start_min, _ = _range_to_bounds(time_range)
    if start_min is None:
        return None

    best_idx = None
    best_diff = 10**9
    for idx, hhmm in enumerate(_RINGS_STARTS):
        rm = _hhmm_to_min(hhmm)
        if rm is None:
            continue
        diff = abs(start_min - rm)
        if diff < best_diff:
            best_diff = diff
            best_idx = idx

    if best_idx is not None and best_diff <= tolerance_min:
        return best_idx + 1
    return None

def _pair_no_nearest(time_range: str) -> Optional[int]:
    start_min, _ = _range_to_bounds(time_range)
    if start_min is None:
        return None
    ring_mins = [(_hhmm_to_min(x) or 10**9) for x in _RINGS_STARTS]
    if not ring_mins:
        return None
    idx = min(range(len(ring_mins)), key=lambda k: abs(ring_mins[k] - start_min))
    return idx + 1

def _explicit_pair_no(lesson: dict) -> Optional[int]:
    for k in ("pair_no", "pairNo", "lesson_no", "lessonNo", "number", "num", "paraNo", "para_no"):
        v = lesson.get(k)
        try:
            if v is None:
                continue
            n = int(v)
            if 1 <= n <= 20:
                return n
        except Exception:
            pass
    return None

# ---------- остальная нормализация ----------
def _get_teacher_full(lesson: dict) -> str:
    # FA чаще всего: listOfLecturers[].lecturer_title
    if isinstance(lesson.get("listOfLecturers"), list):
        out = []
        for t in lesson["listOfLecturers"]:
            if isinstance(t, dict):
                fio = _first_str(
                    t.get("lecturer_title"),
                    t.get("full_name"),
                    t.get("fio"),
                    _join_fio(t.get("surname") or "", t.get("name") or "", t.get("patronymic") or ""),
                )
                if fio:
                    out.append(fio.strip())
            elif t:
                out.append(str(t).strip())
        if out:
            return "; ".join(out)

    # другие варианты
    for key in ("teachers", "lecturers"):
        items = lesson.get(key)
        if isinstance(items, list) and items:
            out = []
            for t in items:
                if isinstance(t, dict):
                    fio = _first_str(
                        t.get("lecturer_title"),
                        t.get("teacher_full"),
                        t.get("full_name"),
                        t.get("fio"),
                        _join_fio(t.get("surname") or "", t.get("name") or "", t.get("patronymic") or ""),
                    )
                else:
                    fio = str(t).strip()
                if fio:
                    out.append(fio.strip())
            if out:
                return "; ".join(out)

    return _first_str(
        lesson.get("lecturer_title"),
        lesson.get("teacher_full"),
        lesson.get("teacherFio"),
        lesson.get("teacher_fio"),
        lesson.get("full_name"),
        lesson.get("fio"),
        lesson.get("lecturer"),
        lesson.get("teacher"),
    )

def _normalize_ltype(s: str) -> str:
    if not isinstance(s, str):
        return ""
    x = s.strip().lower()
    if not x:
        return ""
    if "лекци" in x:
        return "лекция"
    if "семинар" in x or "семинарск" in x:
        return "семинар"
    if "практичес" in x:
        return "практика"
    if "лаб" in x:
        return "лабораторная"
    if "зачет" in x or "зачёт" in x:
        return "зачёт"
    if "экзамен" in x:
        return "экзамен"
    return s.strip()

def _extract_title(lesson: dict) -> str:
    return _first_str(
        lesson.get("title"),
        lesson.get("discipline"),
        lesson.get("subject"),
        lesson.get("lesson"),
    )

def _extract_room(lesson: dict) -> str:
    return _first_str(
        lesson.get("room"),
        lesson.get("auditorium"),
        lesson.get("auditory"),
        lesson.get("place"),
        lesson.get("cabinet"),
    )

def _to_upper_type(norm: str) -> str:
    x = (norm or "").strip().lower()
    if not x:
        return "ПАРА"
    return x.upper()

def _start_minutes(time_range: str) -> int:
    s, _ = _range_to_bounds(time_range)
    return s if s is not None else 10**9

def _normalize_lesson(lesson: dict) -> Dict[str, Any]:
    time_range = _time_range_of(lesson)

    ltype_raw = _first_str(
        lesson.get("kindOfWork"),   # FA
        lesson.get("type"),
        lesson.get("lesson_type"),
        lesson.get("format"),
        lesson.get("kind"),
    )
    ltype = _normalize_ltype(ltype_raw)

    pair_no = _explicit_pair_no(lesson)
    if pair_no is None:
        pair_no = _pair_no_for_time_range(time_range)
        if pair_no is None:
            pair_no = _pair_no_nearest(time_range)

    return {
        "type": _to_upper_type(ltype),
        "pair_no": pair_no,
        "title": _extract_title(lesson),
        "teacher": _get_teacher_full(lesson),
        "room": _extract_room(lesson),
        "time": time_range,
        "date": _norm_date(_first_str(lesson.get("date"), lesson.get("day"), lesson.get("lesson_date"), "")),
    }

# ---------- CLI ----------
def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "No command"}))
        return

    cmd = sys.argv[1]
    fa = FaAPI()

    try:
        if cmd in ("search_group", "search_teacher"):
            if len(sys.argv) < 3:
                print(json.dumps({"ok": False, "error": "Missing query"}))
                return
            query = " ".join(sys.argv[2:]).strip()

            if cmd == "search_group":
                items = _call_with_timeout(fa.search_group, query) or []
            else:
                items = _call_with_timeout(fa.search_teacher, query) or []

            out = [{"id": it.get("id"), "title": it.get("label") or it.get("name") or it.get("title") or ""} for it in items]
            print(json.dumps({"ok": True, "items": out}, ensure_ascii=False))
            return

        if cmd in ("timetable_group", "timetable_teacher"):
            if len(sys.argv) < 3:
                print(json.dumps({"ok": False, "error": "Usage: timetable_* <id> [start] [end]"}))
                return

            entity_id = int(sys.argv[2])

            start = _norm_date(sys.argv[3]) if len(sys.argv) >= 4 else _norm_date("")
            end = _norm_date(sys.argv[4]) if len(sys.argv) >= 5 else start
            if len(sys.argv) < 5:
                print(json.dumps({"ok": False, "error": "Usage: timetable_* <id> <start> <end>"}))
                return

            entity_id = int(sys.argv[2])
            start = sys.argv[3]
            end = sys.argv[4]

            if cmd == "timetable_group":
                raw = _call_with_timeout(fa.timetable_group, entity_id, start, end)
            else:
                raw = _call_with_timeout(fa.timetable_teacher, entity_id, start, end)

            # raw может быть dict по датам или list
            lessons: List[dict] = []
            if isinstance(raw, list):
                for x in raw:
                    if isinstance(x, dict):
                        x = dict(x)
                        # если нет даты — хотя бы start
                        x.setdefault("date", start)
                        lessons.append(x)
            elif isinstance(raw, dict) and raw:
                for k, v in raw.items():
                    if isinstance(v, list):
                        for x in v:
                            if isinstance(x, dict):
                                x = dict(x)
                                x["date"] = _norm_date(str(k))
                                lessons.append(x)

            items = [_normalize_lesson(les) for les in lessons]

            # сортируем по началу времени (пустое время уедет вниз)
            items.sort(key=lambda x: _start_minutes(x.get("time") or ""))

            print(json.dumps({"ok": True, "count": len(items), "items": items}, ensure_ascii=False))
            return

        print(json.dumps({"ok": False, "error": f"Unknown cmd: {cmd}"}))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))

if __name__ == "__main__":
    main()