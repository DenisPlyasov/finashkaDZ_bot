import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const CHANNEL_LINK = "https://t.me/question_finashkadzbot";

// ===== Helpers / constants =====
const RU_DOW = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const RU_MONTH = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря"
];

function startOfWeekMonday(d) {
  const x = new Date(d);
  const day = x.getDay(); // 0 Sun .. 6 Sat
  const diff = (day === 0 ? -6 : 1 - day); // monday start
  x.setDate(x.getDate() + diff);
  x.setHours(0, 0, 0, 0);
  return x;
}

function addDays(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  x.setHours(0, 0, 0, 0);
  return x;
}

function formatFaDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}.${m}.${day}`;
}

function formatRuLine(d) {
  const day = d.getDate();
  const month = RU_MONTH[d.getMonth()];

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dd = new Date(d);
  dd.setHours(0, 0, 0, 0);

  const diff = Math.round((dd - today) / 86400000);

  let tail = "";
  if (diff === 0) tail = "сегодня";
  else if (diff === -1) tail = "вчера";
  else if (diff === 1) tail = "завтра";
  else if (diff <= -7 && diff > -14) tail = "неделю назад";
  else if (diff >= 7 && diff < 14) tail = "через неделю";

  return `${day} ${month}${tail ? " • " + tail : ""}`;
}

export default function App() {
  const [initData, setInitData] = useState("");
  const [step, setStep] = useState("loading"); // loading | subscribe | groupGate | groupInput | schedule
  const [status, setStatus] = useState("idle"); // idle | loading | ok | fail
  const [message, setMessage] = useState("");

  // group/teacher flow
  const [mode, setMode] = useState("group"); // group | teacher
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [picked, setPicked] = useState(null); // {id,title}
  const [selection, setSelection] = useState(null); // {target_type,target_id,target_title}
  const debounceRef = useRef(null);

  // schedule states
  const [selectedDate, setSelectedDate] = useState(() => {
    const t = new Date();
    t.setHours(0, 0, 0, 0);
    return t;
  });
  const [weekStart, setWeekStart] = useState(() => startOfWeekMonday(new Date()));
  const [hasPairs, setHasPairs] = useState(false);
  const [pairsLoading, setPairsLoading] = useState(false);

  // history dropdown
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState([]); // last 5 items from backend

  // animation direction for schedule text
  const [animDir, setAnimDir] = useState(""); // "left" | "right" | ""
  const animTimerRef = useRef(null);

  // touch refs
  const touchMain = useRef(null);
  const touchWeek = useRef(null);

  const canWorkInsideTelegram = useMemo(() => !!window.Telegram?.WebApp, []);

  // ===== API calls =====
  const loadHistory = async (data = initData) => {
    try {
      const r = await fetch("/api/selection/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: data }),
      });
      const res = await r.json();
      if (r.ok) setHistory(res.items || []);
    } catch {
      // ignore
    }
  };

  const fetchHasPairs = async (d, data = initData) => {
    setPairsLoading(true);
    try {
      const r = await fetch("/api/timetable/has", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: data, date: formatFaDate(d) }),
      });
      const res = await r.json();
      if (r.ok) setHasPairs(!!res.hasPairs);
      else setHasPairs(false);
    } catch {
      setHasPairs(false);
    } finally {
      setPairsLoading(false);
    }
  };

  // ===== init =====
  useEffect(() => {
    const tg = window.Telegram?.WebApp;

    if (tg) {
      tg.ready();
      try { tg.expand(); } catch {}
      const data = tg.initData || "";
      setInitData(data);

      if (data) {
        autoCheckSubscription(data);
      } else {
        setStep("subscribe");
      }
    } else {
      setStep("subscribe");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ===== subscription gate =====
  const autoCheckSubscription = async (data) => {
    setStep("loading");
    try {
      const r = await fetch("/api/subscription/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: data }),
      });

      const res = await r.json();

      if (r.ok && res.subscribed) {
        await gateSelection(data);
        return;
      }

      setStep("subscribe");
      if (r.ok && res.subscribed === false) {
        setStatus("fail");
        setMessage("⚠️ Для использования необходимо подписаться на канал проекта.");
      } else if (!r.ok) {
        setStatus("fail");
        setMessage(res?.error || "Не удалось проверить подписку.");
      }
    } catch (e) {
      setStep("subscribe");
      setStatus("fail");
      setMessage("Не удалось связаться с сервером для проверки подписки.");
    }
  };

  const gateSelection = async (data) => {
    setStep("groupGate");
    try {
      const r = await fetch("/api/selection/get", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: data }),
      });
      const res = await r.json();
      if (!r.ok) throw new Error(res?.error || "selection get failed");

      if (res.selection) {
        setSelection(res.selection);

        // schedule init: today
        const t = new Date();
        t.setHours(0, 0, 0, 0);
        setSelectedDate(t);
        setWeekStart(startOfWeekMonday(t));
        setHistoryOpen(false);

        // подгрузка статуса пары + история
        await loadHistory(data);
        await fetchHasPairs(t, data);

        setStep("schedule");
      } else {
        setStep("groupInput");
      }
    } catch {
      setStep("groupInput");
    }
  };

  // ===== subscribe page actions =====
  const openChannel = () => {
    const tg = window.Telegram?.WebApp;
    if (tg?.openTelegramLink) {
      tg.openTelegramLink(CHANNEL_LINK);
      return;
    }
    window.open(CHANNEL_LINK, "_blank", "noopener,noreferrer");
  };

  const checkSubscription = async () => {
    setStatus("loading");
    setMessage("");

    try {
      const r = await fetch("/api/subscription/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData }),
      });

      const data = await r.json();

      if (!r.ok) {
        setStatus("fail");
        setMessage(data?.error || "Ошибка проверки подписки");
        return;
      }

      if (data.subscribed) {
        setStatus("ok");
        setMessage("✅ Спасибо за подписку! Доступ открыт.");
        await gateSelection(initData);
      } else {
        setStatus("fail");
        setMessage("❌ Вы всё ещё не подписаны на канал.");
        window.Telegram?.WebApp?.showAlert?.("❌ Вы всё ещё не подписаны на канал.");
      }
    } catch (e) {
      setStatus("fail");
      setMessage("Сеть недоступна или сервер не отвечает.");
    }
  };

  // ===== group input logic =====
  const requestSuggestions = async (text, currentMode) => {
    if (!text || text.trim().length < 2) {
      setSuggestions([]);
      return;
    }

    try {
      const r = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData, type: currentMode, q: text }),
      });

      const res = await r.json();
      if (r.ok) setSuggestions(res.items || []);
      else setSuggestions([]);
    } catch {
      setSuggestions([]);
    }
  };

  const onChangeQuery = (v) => {
    setQuery(v);
    setPicked(null);

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      requestSuggestions(v, mode);
    }, 250);
  };

  const onPick = (it) => {
    setPicked(it);
    setQuery(it.title);
    setSuggestions([]);
  };

  const onSearch = async () => {
    setStatus("loading");
    setMessage("");

    try {
      let chosen = picked;

      if (!chosen) {
        const r = await fetch("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ initData, type: mode, q: query }),
        });
        const res = await r.json();
        const first = (res.items || [])[0];
        if (!r.ok || !first) {
          setStatus("fail");
          setMessage(mode === "group" ? "Группа не найдена" : "Преподаватель не найден");
          return;
        }
        chosen = first;
      }

      const save = await fetch("/api/selection/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData,
          type: mode,
          id: chosen.id,
          title: chosen.title,
        }),
      });
      const saveRes = await save.json();
      if (!save.ok) throw new Error(saveRes?.error || "save failed");

      setSelection({
        target_type: mode,
        target_id: chosen.id,
        target_title: chosen.title,
      });

      // schedule init: today
      const t = new Date();
      t.setHours(0, 0, 0, 0);
      setSelectedDate(t);
      setWeekStart(startOfWeekMonday(t));
      setHistoryOpen(false);

      await loadHistory(initData);
      await fetchHasPairs(t, initData);

      setStatus("ok");
      setStep("schedule");
    } catch (e) {
      setStatus("fail");
      setMessage("Ошибка сохранения выбора. Попробуйте ещё раз.");
    }
  };

  // ===== schedule helpers =====
  const setAnim = (dir) => {
    setAnimDir(dir);
    if (animTimerRef.current) clearTimeout(animTimerRef.current);
    animTimerRef.current = setTimeout(() => setAnimDir(""), 220);
  };

  const handleTouchStart = (ref, e) => {
    const t = e.touches[0];
    ref.current = { x: t.clientX, y: t.clientY };
  };

  const handleTouchEnd = (ref, onSwipe, e) => {
    const start = ref.current;
    if (!start) return;

    const t = e.changedTouches[0];
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;

    // horizontal swipe only
    if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.2) {
      onSwipe(dx < 0 ? "left" : "right");
    }
    ref.current = null;
  };

  const goToSearch = () => {
    setHistoryOpen(false);
    setSuggestions([]);
    setPicked(null);
    setQuery("");
    setStep("groupInput");
  };

  const switchToFromHistory = async (item) => {
    // item format from backend: {target_type,target_id,target_title,...}
    setHistoryOpen(false);
    setStatus("loading");

    try {
      const save = await fetch("/api/selection/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData,
          type: item.target_type,
          id: item.target_id,
          title: item.target_title,
        }),
      });
      const saveRes = await save.json();
      if (!save.ok) throw new Error(saveRes?.error || "save failed");

      setSelection({
        target_type: item.target_type,
        target_id: item.target_id,
        target_title: item.target_title,
      });

      await loadHistory(initData);

      const t = new Date();
      t.setHours(0, 0, 0, 0);
      setSelectedDate(t);
      setWeekStart(startOfWeekMonday(t));
      await fetchHasPairs(t, initData);
    } catch {
      // ignore
    } finally {
      setStatus("idle");
    }
  };

  // ===== screens =====
  if (step === "loading") {
    return (
      <div className="page">
        <div className="card cardWide cardLoading">
          <div className="spinner" />
          <div>
            <div className="title">Проверяем доступ…</div>
            <div className="subtitle">Пожалуйста, подождите</div>
          </div>
        </div>
      </div>
    );
  }

  if (step === "groupGate") {
    return (
      <div className="page">
        <div className="card cardWide cardLoading">
          <div className="spinner" />
          <div>
            <div className="title">Загружаем профиль…</div>
            <div className="subtitle">Проверяем, вводили ли вы группу ранее</div>
          </div>
        </div>
      </div>
    );
  }

  if (step === "schedule") {
    const ws = weekStart;
    const days = Array.from({ length: 7 }, (_, i) => addDays(ws, i));

    const wsTime = ws.getTime();
    const selTime = new Date(selectedDate).getTime();
    const selectedIdx = Math.round((selTime - wsTime) / 86400000);

    const onPickDay = async (i) => {
      const d = addDays(ws, i);
      setAnim(d < selectedDate ? "left" : "right");
      setSelectedDate(d);
      setHistoryOpen(false);
      await fetchHasPairs(d, initData);
    };

    // свайп влево = следующий день, вправо = предыдущий
    const swipeMain = async (dir) => {
      const next = dir === "right" ? addDays(selectedDate, -1) : addDays(selectedDate, 1);
      setAnim(dir === "right" ? "left" : "right"); // анимацию оставим "логичной": назад = left, вперёд = right
      setSelectedDate(next);
      setWeekStart(startOfWeekMonday(next));
      setHistoryOpen(false);
      await fetchHasPairs(next, initData);
    };

    // свайп влево = следующая неделя, вправо = предыдущая
    const swipeWeek = async (dir) => {
      const weekday = selectedDate.getDay() === 0 ? 6 : selectedDate.getDay() - 1; // Mon=0..Sun=6
      const base = dir === "right" ? addDays(weekStart, -7) : addDays(weekStart, 7);
      setWeekStart(base);

      const next = addDays(base, weekday);
      setAnim(dir === "right" ? "left" : "right");
      setSelectedDate(next);
      setHistoryOpen(false);
      await fetchHasPairs(next, initData);
    };

    return (
      <div className="scheduleShell">
        <div className="topBar">
          <button className="iconBtn" aria-label="plus">
            <img src="/hw-plus.png" alt="+" />
          </button>

          <div className="topTitle">
            <div className="topTitleMain">Расписание</div>

            <button
              className="topTitleSub"
              onClick={() => setHistoryOpen((v) => !v)}
            >
              {selection?.target_title || ""}
            </button>

            {historyOpen && (
              <div className="historyDropdown">
                {history.length === 0 ? (
                  <div className="historyEmpty">История пуста</div>
                ) : (
                  history.map((h, idx) => (
                    <button
                      key={idx}
                      className="historyItem"
                      onClick={() => switchToFromHistory(h)}
                    >
                      {h.target_title}
                      <span className="historyTag">
                        {h.target_type === "teacher" ? "препод" : "группа"}
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>

          <div className="topActions">
            <button className="iconBtn" aria-label="search" onClick={goToSearch}>
              <img src="/group-search.png" alt="search" />
            </button>
            <button className="iconBtn" aria-label="date">
              <img src="/date-choose.png" alt="date" />
            </button>
          </div>
        </div>

        <div
          className="weekRow"
          onTouchStart={(e) => handleTouchStart(touchWeek, e)}
          onTouchEnd={(e) => handleTouchEnd(touchWeek, swipeWeek, e)}
        >
          {days.map((d, i) => {
            const isSel = i === selectedIdx;
            return (
              <button
                key={i}
                className={`dayCell ${isSel ? "selected" : ""}`}
                onClick={() => onPickDay(i)}
              >
                <div className="dayNum">{d.getDate()}</div>
                <div className="dayDow">{RU_DOW[i]}</div>
              </button>
            );
          })}
        </div>

        <div className="dateLine">{formatRuLine(selectedDate)}</div>

        <div
          className="scheduleBody"
          onTouchStart={(e) => handleTouchStart(touchMain, e)}
          onTouchEnd={(e) => handleTouchEnd(touchMain, swipeMain, e)}
        >
          <div className={`scheduleHint ${animDir ? `anim ${animDir}` : ""}`}>
            {pairsLoading
              ? "Проверяем пары…"
              : hasPairs
                ? "На текущую дату есть пары"
                : "На текущую дату пар не найдено"}
          </div>
        </div>
      </div>
    );
  }

  if (step === "groupInput") {
    return (
      <div className="page">
        <div className="card">
          <div className="iconWrap">
            <img className="iconImg" src="/fa-icon.png" alt="FA" />
          </div>

          <div className="title">Введите группу или преподавателя</div>
          <div className="subtitle">Можно начать ввод — появятся подсказки</div>

          <div className="segmented">
            <button
              className={`segBtn ${mode === "group" ? "active" : ""}`}
              onClick={() => {
                setMode("group");
                setPicked(null);
                setSuggestions([]);
                if (query.trim().length >= 2) requestSuggestions(query, "group");
              }}
            >
              Группа
            </button>
            <button
              className={`segBtn ${mode === "teacher" ? "active" : ""}`}
              onClick={() => {
                setMode("teacher");
                setPicked(null);
                setSuggestions([]);
                if (query.trim().length >= 2) requestSuggestions(query, "teacher");
              }}
            >
              Преподаватель
            </button>
          </div>

          <div className="inputWrap">
            <input
              className="input"
              value={query}
              onChange={(e) => onChangeQuery(e.target.value)}
              placeholder={mode === "group" ? "Например: ПИ19-5" : "Например: Милованов"}
            />
          </div>

          {suggestions.length > 0 && (
            <div className="suggestBox">
              {suggestions.map((it) => (
                <button
                  key={String(it.id)}
                  className="suggestItem"
                  onClick={() => onPick(it)}
                >
                  {it.title}
                </button>
              ))}
            </div>
          )}

          <div className="buttons one">
            <button
              className="btn btnPrimary"
              onClick={onSearch}
              disabled={!initData || status === "loading" || query.trim().length < 2}
            >
              {status === "loading" ? "Ищем..." : "Поиск"}
            </button>
          </div>

          {message && (
            <div className={`result ${status === "ok" ? "ok" : "fail"}`}>
              {message}
            </div>
          )}
        </div>
      </div>
    );
  }

  // subscribe screen (only for NOT subscribed)
  return (
    <div className="page">
      <div className="card">
        <div className="iconWrap">
          <div className="iconGlow" />
          <img className="iconImg" src="/tg-icon.png" alt="Telegram" />
        </div>

        <div className="title">
          Перед началом использования подпишитесь на наш ТГ-канал!
        </div>
        <div className="subtitle">Никакого спама - только новости о проекте</div>

        <div className="buttons">
          <button className="btn btnPrimary" onClick={openChannel}>
            Подписаться
          </button>

          <button
            className="btn btnSecondary"
            onClick={checkSubscription}
            disabled={!initData || status === "loading"}
            title={!initData ? "Откройте мини-приложение внутри Telegram" : ""}
          >
            {status === "loading" ? "Проверяем..." : "Проверить"}
          </button>
        </div>

        {!canWorkInsideTelegram && (
          <div className="hint">
            Откройте эту страницу внутри Telegram Mini App, чтобы появилась initData.
          </div>
        )}

        {message && (
          <div className={`result ${status === "ok" ? "ok" : "fail"}`}>
            {message}
          </div>
        )}
      </div>
    </div>
  );
}