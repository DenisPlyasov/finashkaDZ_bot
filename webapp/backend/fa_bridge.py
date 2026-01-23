#!/usr/bin/env python3
import json
import sys
from fa_api import FaAPI

def main():
    # usage:
    # python fa_bridge.py search_group "<query>"
    # python fa_bridge.py search_teacher "<query>"
    # python fa_bridge.py timetable_group <id> <start YYYY.MM.DD> <end YYYY.MM.DD>
    # python fa_bridge.py timetable_teacher <id> <start YYYY.MM.DD> <end YYYY.MM.DD>

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
                items = fa.search_group(query) or []
            else:
                items = fa.search_teacher(query) or []

            out = [{"id": it.get("id"), "title": it.get("label") or it.get("name") or it.get("title") or ""} for it in items]
            print(json.dumps({"ok": True, "items": out}, ensure_ascii=False))
            return

        if cmd in ("timetable_group", "timetable_teacher"):
            if len(sys.argv) < 5:
                print(json.dumps({"ok": False, "error": "Usage: timetable_* <id> <start> <end>"}))
                return

            entity_id = int(sys.argv[2])
            start = sys.argv[3]
            end = sys.argv[4]

            if cmd == "timetable_group":
                tt = fa.timetable_group(entity_id, start, end)
            else:
                tt = fa.timetable_teacher(entity_id, start, end)

            # tt обычно list; нам пока важен только факт наличия пар
            count = len(tt) if isinstance(tt, list) else (len(tt or []) if tt else 0)
            print(json.dumps({"ok": True, "count": count}, ensure_ascii=False))
            return

        print(json.dumps({"ok": False, "error": f"Unknown cmd: {cmd}"}))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))

if __name__ == "__main__":
    main()