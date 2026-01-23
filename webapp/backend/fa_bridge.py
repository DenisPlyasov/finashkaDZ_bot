#!/usr/bin/env python3
import json
import sys
from fa_api import FaAPI

def main():
    # usage:
    # python3 fa_bridge.py search_group "<query>"
    # python3 fa_bridge.py search_teacher "<query>"
    if len(sys.argv) < 3:
        print(json.dumps({"ok": False, "error": "Usage: fa_bridge.py <search_group|search_teacher> <query>"}))
        return

    cmd = sys.argv[1]
    query = " ".join(sys.argv[2:]).strip()

    fa = FaAPI()

    try:
        if cmd == "search_group":
            items = fa.search_group(query) or []
            # нормализуем поля, чтобы фронту было удобно
            out = [{"id": it.get("id"), "title": it.get("label") or it.get("name") or it.get("title") or ""} for it in items]
            print(json.dumps({"ok": True, "items": out}, ensure_ascii=False))
            return

        if cmd == "search_teacher":
            items = fa.search_teacher(query) or []
            out = [{"id": it.get("id"), "title": it.get("label") or it.get("name") or it.get("title") or ""} for it in items]
            print(json.dumps({"ok": True, "items": out}, ensure_ascii=False))
            return

        print(json.dumps({"ok": False, "error": f"Unknown cmd: {cmd}"}))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))

if __name__ == "__main__":
    main()