import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const CHANNEL_LINK = "https://t.me/question_finashkadzbot";

// ===== Helpers / constants =====
const RU_DOW = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const RU_MONTH = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря"
];

const RU_DOW_CAL = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const RU_MONTH_CAP = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
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

function startOfMonth(d) {
  const x = new Date(d);
  x.setDate(1);
  x.setHours(0, 0, 0, 0);
  return x;
}

function addMonths(d, n) {
  const x = new Date(d);
  x.setDate(1);
  x.setMonth(x.getMonth() + n);
  x.setHours(0, 0, 0, 0);
  return x;
}

function sameDay(a, b) {
  if (!a || !b) return false;
  const x = new Date(a); x.setHours(0,0,0,0);
  const y = new Date(b); y.setHours(0,0,0,0);
  return x.getTime() === y.getTime();
}

function daysInMonth(d) {
  const x = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  return x.getDate();
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

function safeText(s) {
  return (s ?? "").toString().trim();
}

function renderPairNo(n) {
  if (!n) return "";
  return `${n} ПАРА`;
}

function formatRuPairDateLine(d) {
  return `${d.getDate()} ${RU_MONTH[d.getMonth()]}`;
}

function formatDeadlineRu(d) {
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yy = d.getFullYear();
  return `${dd}.${mm}.${yy}`;
}

function parseFaDateString(s) {
  const str = String(s || "").trim(); // "YYYY.MM.DD"
  const m = str.match(/^(\d{4})\.(\d{2})\.(\d{2})$/);
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  d.setHours(0, 0, 0, 0);
  return d;
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
  const [pairs, setPairs] = useState([]); // <-- NEW

  // calendar (full screen like mock)
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarBaseMonth, setCalendarBaseMonth] = useState(() => startOfMonth(new Date()));
  const calScrollRef = useRef(null);

  // history dropdown
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState([]); // last 5 items from backend

  // animation direction for schedule text
  const [animDir, setAnimDir] = useState(""); // "left" | "right" | ""
  const animTimerRef = useRef(null);


  // ===== HW add flow =====
  const [hwOpen, setHwOpen] = useState(false);
  const [hwPair, setHwPair] = useState(null); // выбранная пара
  const [hwDraftId, setHwDraftId] = useState(null);
  const [hwText, setHwText] = useState("");
  const [hwDeadline, setHwDeadline] = useState(null); // Date | null
  const [hwCalOpen, setHwCalOpen] = useState(false);
  const [hwCalBaseMonth, setHwCalBaseMonth] = useState(() => startOfMonth(new Date()));
  const [hwCancelAsk, setHwCancelAsk] = useState(false);

  // ===== HW edit flow =====
  const [hwEditOpen, setHwEditOpen] = useState(false);
  const [hwEditPair, setHwEditPair] = useState(null);     // пара, к которой относится дз
  const [hwEditItem, setHwEditItem] = useState(null);     // само дз (id, text, deadline_date)
  const [hwEditText, setHwEditText] = useState("");
  const [hwEditDeadline, setHwEditDeadline] = useState(null); // Date|null
  const [hwEditCalOpen, setHwEditCalOpen] = useState(false);
  const [hwEditCalBaseMonth, setHwEditCalBaseMonth] = useState(() => startOfMonth(new Date()));

  // универсальное подтверждение ("пуш" с 2 кнопками)
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const confirmActionRef = useRef(null);

  const openConfirm = (text, onConfirm) => {
    setConfirmText(text);
    confirmActionRef.current = onConfirm;
    setConfirmOpen(true);
  };

  const closeConfirm = () => {
    setConfirmOpen(false);
    setConfirmText("");
    confirmActionRef.current = null;
  };

  const confirmYes = async () => {
    const fn = confirmActionRef.current;
    closeConfirm();
    if (typeof fn === "function") await fn();
  };


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

  // NEW: грузим пары за день
  const fetchPairsForDate = async (d, data = initData) => {
    setPairsLoading(true);
    try {
      const r = await fetch("/api/timetable/day", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: data, date: formatFaDate(d) }),
      });
      const res = await r.json();
  
      if (r.ok) {
        const items = res.items || [];
        setPairs(items);
        setHasPairs(items.length > 0);
      } else {
        setPairs([]);
        setHasPairs(false);
      }
    } catch {
      setPairs([]);
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

  useEffect(() => {
    if (!calendarOpen) return;
    const elId = `cal-month-${calendarBaseMonth.getFullYear()}-${calendarBaseMonth.getMonth()}`;
    requestAnimationFrame(() => {
      const el = document.getElementById(elId);
      el?.scrollIntoView({ block: "start" });
    });
  }, [calendarOpen, calendarBaseMonth]);

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

        const t = new Date();
        t.setHours(0, 0, 0, 0);
        setSelectedDate(t);
        setWeekStart(startOfWeekMonday(t));
        setHistoryOpen(false);

        await loadHistory(data);
        await fetchPairsForDate(t, data);

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

  const openAddHwForPair = async (pair) => {
    try {
      // создаём draft в БД сразу
      const r = await fetch("/api/hw/draft/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData,
          pair_date: formatFaDate(selectedDate),
          pair_title: pair.title || "",
          pair_time: pair.time || "",
          pair_no: pair.pair_no ?? null,
        }),
      });
      const res = await r.json();
      if (!r.ok) throw new Error(res?.error || "draft create failed");

      setHwPair(pair);
      setHwDraftId(res.draft_id);
      setHwText("");
      setHwDeadline(null);
      setHwCalBaseMonth(startOfMonth(selectedDate));
      setHwOpen(true);
    } catch (e) {
      window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
    }
  };

  const cancelHwDraft = async () => {
    try {
      if (hwDraftId) {
        await fetch("/api/hw/draft/cancel", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ initData, draft_id: hwDraftId }),
        });
      }
    } finally {
      setHwCancelAsk(false);
      setHwOpen(false);
      setHwPair(null);
      setHwDraftId(null);
      setHwText("");
      setHwDeadline(null);
      setHwCalOpen(false);
    }
  };

  const submitHwDraft = async () => {
    try {
      if (!hwDraftId) return;

      // сохраним текст (чтобы без лишних запросов на каждую букву)
      await fetch("/api/hw/draft/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData, draft_id: hwDraftId, text: hwText }),
      });

      const r = await fetch("/api/hw/draft/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData, draft_id: hwDraftId }),
      });
      const res = await r.json();
      if (!r.ok) throw new Error(res?.error || "submit failed");

      // закрываем экран и перезагружаем день, чтобы задание появилось под парой
      setHwOpen(false);
      setHwPair(null);
      setHwDraftId(null);
      setHwText("");
      setHwDeadline(null);
      setHwCalOpen(false);

      await fetchPairsForDate(selectedDate, initData);
    } catch (e) {
      window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
    }
  };

  const openEditHw = (pair, hw) => {
    setHwEditPair(pair);
    setHwEditItem(hw);
    setHwEditText(hw?.text || "");
    setHwEditDeadline(hw?.deadline_date ? parseFaDateString(hw.deadline_date) : null);
    setHwEditCalBaseMonth(startOfMonth(selectedDate));
    setHwEditOpen(true);
  };

  const submitHwEdit = async () => {
    try {
      if (!hwEditItem?.id) return;

      const text = safeText(hwEditText);
      if (!text) {
        window.Telegram?.WebApp?.showAlert?.("Текст задания пустой");
        return;
      }

      const r = await fetch("/api/hw/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData: String(initData ?? "").trim(),
          homework_id: hwEditItem.id,
          text,
          deadline_date: hwEditDeadline ? formatFaDate(hwEditDeadline) : null,
        }),
      });
      const res = await r.json();
      if (!r.ok) throw new Error(res?.error || "update failed");

      setHwEditOpen(false);
      setHwEditPair(null);
      setHwEditItem(null);
      setHwEditText("");
      setHwEditDeadline(null);
      setHwEditCalOpen(false);

      await fetchPairsForDate(selectedDate, initData);
    } catch (e) {
      window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
    }
  };

  const deleteHw = async () => {
    try {
      if (!hwEditItem?.id) return;

      const r = await fetch("/api/hw/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData: String(initData ?? "").trim(),
          homework_id: hwEditItem.id,
        }),
      });
      const res = await r.json();
      if (!r.ok) throw new Error(res?.error || "delete failed");

      setHwEditOpen(false);
      setHwEditPair(null);
      setHwEditItem(null);
      setHwEditText("");
      setHwEditDeadline(null);
      setHwEditCalOpen(false);

      await fetchPairsForDate(selectedDate, initData);
    } catch (e) {
      window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
    }
  };

  const askCancelEdit = () => {
    openConfirm(
      "Вы уверены? При подтверждении отменить результаты данного действия будет невозможно.",
      async () => {
        setHwEditOpen(false);
        setHwEditPair(null);
        setHwEditItem(null);
        setHwEditText("");
        setHwEditDeadline(null);
        setHwEditCalOpen(false);
      }
    );
  };

  const askDeleteHw = () => {
    openConfirm(
      "Вы уверены? При подтверждении удалить задание будет невозможно отменить.",
      deleteHw
    );
  };

  const pickHwEditDeadline = (d) => {
    const next = new Date(d);
    next.setHours(0, 0, 0, 0);
    setHwEditDeadline(next);
    setHwEditCalOpen(false);
  };


  const pickHwDeadline = async (d) => {
    const next = new Date(d);
    next.setHours(0, 0, 0, 0);
    setHwDeadline(next);
    setHwCalOpen(false);

    // ВАЖНО: по ТЗ — сразу записываем в БД
    if (hwDraftId) {
      await fetch("/api/hw/draft/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData,
          draft_id: hwDraftId,
          deadline_date: formatFaDate(next),
        }),
      });
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

      const t = new Date();
      t.setHours(0, 0, 0, 0);
      setSelectedDate(t);
      setWeekStart(startOfWeekMonday(t));
      setHistoryOpen(false);

      await loadHistory(initData);
      await fetchPairsForDate(t, initData);

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

  const openCalendar = () => {
    setHistoryOpen(false);
    const base = startOfMonth(selectedDate);
    setCalendarBaseMonth(base);
    setCalendarOpen(true);
  };

  const closeCalendar = () => setCalendarOpen(false);

  const pickCalendarDate = async (d) => {
    const next = new Date(d);
    next.setHours(0, 0, 0, 0);

    setAnim(next < selectedDate ? "left" : "right");
    setSelectedDate(next);
    setWeekStart(startOfWeekMonday(next));
    setHistoryOpen(false);

    setCalendarOpen(false);
    await fetchPairsForDate(next, initData);
  };

  const switchToFromHistory = async (item) => {
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
      await fetchPairsForDate(t, initData);
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
      await fetchPairsForDate(d, initData);
    };

    // свайп влево = следующий день, вправо = предыдущий
    const swipeMain = async (dir) => {
      const next = dir === "right" ? addDays(selectedDate, -1) : addDays(selectedDate, 1);
      setAnim(dir === "right" ? "left" : "right");
      setSelectedDate(next);
      setWeekStart(startOfWeekMonday(next));
      setHistoryOpen(false);
      await fetchPairsForDate(next, initData);
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
      await fetchPairsForDate(next, initData);
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
            <button className="iconBtn" aria-label="date" onClick={openCalendar}>
              <img src="/date-choose.png" alt="date" />
            </button>
          </div>
        </div>

        {calendarOpen && (() => {
          const months = Array.from({ length: 25 }, (_, i) => addMonths(calendarBaseMonth, i - 12));

          return (
            <div className="calFull">
              <div className="calTop">
                <div className="calTopLeft" />
                <div className="calTopTitle">Календарь</div>
                <button className="calTopHide" onClick={closeCalendar} type="button">
                  Скрыть
                </button>
              </div>

              <div className="calScroll" ref={calScrollRef}>
                {months.map((m) => {
                  const y = m.getFullYear();
                  const mo = m.getMonth();
                  const first = new Date(y, mo, 1);
                  first.setHours(0, 0, 0, 0);

                  const leading = (first.getDay() + 6) % 7; // 0..6 (Пн..Вс)
                  const dim = daysInMonth(first);
                  const totalCells = Math.ceil((leading + dim) / 7) * 7;

                  const cells = Array.from({ length: totalCells }, (_, idx) => {
                    const dayNum = idx - leading + 1;
                    if (dayNum < 1 || dayNum > dim) return null;
                    const d = new Date(y, mo, dayNum);
                    d.setHours(0, 0, 0, 0);
                    return d;
                  });

                  return (
                    <div className="calMonthBlock" key={`${y}-${mo}`} id={`cal-month-${y}-${mo}`}>
                      <div className="calMonthTitle">
                        {RU_MONTH_CAP[mo]} {y}
                      </div>

                      <div className="calDowRow">
                        {RU_DOW_CAL.map((d) => (
                          <div key={d} className="calDowCell">{d}</div>
                        ))}
                      </div>

                      <div className="calGrid">
                        {cells.map((d, idx) => {
                          if (!d) return <div key={idx} className="calEmpty" />;

                          const isSel = sameDay(d, selectedDate);
                          return (
                            <button
                              key={idx}
                              type="button"
                              className={`calDay ${isSel ? "sel" : ""}`}
                              onClick={() => pickCalendarDate(d)}
                            >
                              {d.getDate()}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}

                <div className="calBottomPad" />
              </div>
            </div>
          );
        })()}


        <div
          className="weekRow"
          onTouchStart={(e) => handleTouchStart(touchWeek, e)}
          onTouchEnd={(e) => handleTouchEnd(touchWeek, swipeWeek, e)}
        >
          <div
            className="weekIndicator"
            style={{ "--i": selectedIdx < 0 ? 0 : selectedIdx > 6 ? 6 : selectedIdx }}
          />
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
          className={`scheduleBody ${hasPairs ? "hasPairs" : "noPairs"} ${pairsLoading ? "isLoading" : ""}`}
          onTouchStart={(e) => handleTouchStart(touchMain, e)}
          onTouchEnd={(e) => handleTouchEnd(touchMain, swipeMain, e)}
        >
          {pairsLoading ? (
            "Проверяем пары…"
          ) : hasPairs ? (
            <div className="pairsList">
              {pairs.map((p, idx) => (
                <div className="pairBlock" key={`${p.time}-${idx}`}>
                  <div className="pairCard">
                    <div className="pairTop">
                      <div className="pairMeta">
                        <img className="pairIcon" src="/pair-icon.png" alt="" />
                        <span className="pairType">{p.type || "ПАРА"}</span>
                        <span className="pairDot">•</span>
                        <span className="pairNo">{p.pair_no ? `${p.pair_no} ПАРА` : "ПАРА"}</span>
                      </div>

                      <button
                        className="pairAddBtn"
                        aria-label="add"
                        type="button"
                        onClick={() => openAddHwForPair(p)}
                      >
                        <img src="/add-hw-to-pair.png" alt="+" />
                      </button>
                    </div>

                    <div className="pairTitle">{p.title || "Без названия"}</div>
                    <div className="pairTeacher">{p.teacher || "—"}</div>
                    <div className="pairRoom">{p.room || "—"}</div>
                    <div className="pairTime">{p.time || ""}</div>
                  </div>

                  {Array.isArray(p.homeworks) && p.homeworks.length > 0 && (
                    <div className="hwList">
                      {p.homeworks.map((h) => (
                        <div className="hwCard" key={h.id}>
                          <div className="hwTop">
                            <div className="hwMeta">
                              <img className="hwIcon" src="/hw-icon.png" alt="" />
                              <span className="hwMetaText">Задание</span>
                              <span className="hwDot">•</span>
                              <span className="hwMetaText">{p.title || ""}</span>
                            </div>
                          </div>

                          {/* кнопка теперь отдельно — позиционируется absolute снизу справа */}
                          <button
                            className="hwEditBtn"
                            type="button"
                            aria-label="edit"
                            onClick={() => openEditHw(p, h)}
                          >
                            <img src="/edit-hw-to-pair.png" alt="edit" />
                          </button>

                          <div className="hwTitle">{h.text}</div>

                          {h.deadline_date && (
                            <div className="hwDeadline">К {h.deadline_date}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            "На текущую дату пар не найдено"
          )}
        </div>

        {hwOpen && hwPair && (
          <div className="hwFull">

            <div className="hwContent">
              <div className="hwHeader">
                Задание для группы <span className="hwGroup">{selection?.target_title || ""}</span>
              </div>

              <div className="hwPairCard">
                <div className="hwPairMeta">
                  <span className="hwSquare" />
                  <span className="hwPairType">{(hwPair.type || "").toUpperCase() || "ПАРА"}</span>
                  <span className="hwDot">•</span>
                  <span className="hwPairNo">{renderPairNo(hwPair.pair_no)}</span>
                </div>
                <div className="hwPairTitle">{hwPair.title || "Без названия"}</div>
                <div className="hwPairTeacher">{hwPair.teacher || "—"}</div>
                <div className="hwPairLine">
                  На {formatRuPairDateLine(selectedDate)} <span className="hwDot">•</span> {hwPair.time || ""}
                </div>
              </div>

              <div className="hwSectionTitle">Добавление задания</div>

              <textarea
                className="hwTextarea"
                placeholder="Текст задания..."
                value={hwText}
                onChange={(e) => setHwText(e.target.value)}
              />

              <button className="hwActionRow" type="button" disabled>
                <span className="hwPlus">+</span>
                Добавить файлы (максимум 5)
              </button>

              <button className="hwActionRow" type="button" onClick={() => { setHwCalBaseMonth(startOfMonth(selectedDate)); setHwCalOpen(true); }}>
                <span className="hwPlus">+</span>
                {hwDeadline ? `Кастомная дата дедлайна: ${formatDeadlineRu(hwDeadline)}` : "Кастомная дата дедлайна"}
              </button>

              <div className="hwBottomButtons">
                <button className="hwBtn hwBtnPrimary" type="button" onClick={submitHwDraft}>
                  Подтвердить
                </button>
                <button className="hwBtn hwBtnSecondary" type="button" onClick={() => setHwCancelAsk(true)}>
                  Отменить
                </button>
              </div>
            </div>

            {hwCancelAsk && (
              <div className="hwModalOverlay">
                <div className="hwModal">
                  <div className="hwModalText">
                    Вы точно уверены что хотите отменить заполнение задания?
                    Повторное заполнение займет много времени
                  </div>
                  <div className="hwModalBtns">
                    <button className="hwBtn hwBtnPrimary" type="button" onClick={cancelHwDraft}>
                      подтвердить
                    </button>
                    <button className="hwBtn hwBtnSecondary" type="button" onClick={() => setHwCancelAsk(false)}>
                      назад
                    </button>
                  </div>
                </div>
              </div>
            )}

            {hwCalOpen && (() => {
              const months = Array.from({ length: 25 }, (_, i) => addMonths(hwCalBaseMonth, i - 12));
              return (
                <div className="calFull">
                  <div className="calTop">
                    <div className="calTopLeft" />
                    <div className="calTopTitle">Календарь</div>
                    <button className="calTopHide" onClick={() => setHwCalOpen(false)} type="button">
                      Скрыть
                    </button>
                  </div>

                  <div className="calScroll">
                    {months.map((m) => {
                      const y = m.getFullYear();
                      const mo = m.getMonth();
                      const first = new Date(y, mo, 1);
                      first.setHours(0, 0, 0, 0);

                      const leading = (first.getDay() + 6) % 7;
                      const dim = daysInMonth(first);
                      const totalCells = Math.ceil((leading + dim) / 7) * 7;

                      const cells = Array.from({ length: totalCells }, (_, idx) => {
                        const dayNum = idx - leading + 1;
                        if (dayNum < 1 || dayNum > dim) return null;
                        const d = new Date(y, mo, dayNum);
                        d.setHours(0, 0, 0, 0);
                        return d;
                      });

                      return (
                        <div className="calMonthBlock" key={`${y}-${mo}`}>
                          <div className="calMonthTitle">{RU_MONTH_CAP[mo]} {y}</div>
                          <div className="calDowRow">
                            {RU_DOW_CAL.map((d) => <div key={d} className="calDowCell">{d}</div>)}
                          </div>
                          <div className="calGrid">
                            {cells.map((d, idx) => {
                              if (!d) return <div key={idx} className="calEmpty" />;
                              const isSel = hwDeadline ? sameDay(d, hwDeadline) : false;
                              return (
                                <button
                                  key={idx}
                                  type="button"
                                  className={`calDay ${isSel ? "sel" : ""}`}
                                  onClick={() => pickHwDeadline(d)}
                                >
                                  {d.getDate()}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                    <div className="calBottomPad" />
                  </div>
                </div>
              );
            })()}
          </div>
        )}

        {hwEditOpen && hwEditPair && hwEditItem && (
          <div className="hwFull">

            <div className="hwContent">
              <div className="hwHeader">
                Задание для группы <span className="hwGroup">{selection?.target_title || ""}</span>
              </div>

              <div className="hwPairCard">
                <div className="hwPairMeta">
                  <span className="hwSquare" />
                  <span className="hwPairType">{(hwEditPair.type || "").toUpperCase() || "ПАРА"}</span>
                  <span className="hwDot">•</span>
                  <span className="hwPairNo">{renderPairNo(hwEditPair.pair_no)}</span>
                </div>

                <div className="hwPairTitle">{hwEditPair.title || "Без названия"}</div>
                <div className="hwPairTeacher">{hwEditPair.teacher || "—"}</div>

                <div className="hwPairLine">
                  На {formatRuPairDateLine(selectedDate)} <span className="hwDot">•</span> {hwEditPair.time || ""}
                </div>
              </div>

              <div className="hwSectionTitle">Редактирование задания</div>

              <textarea
                className="hwTextarea"
                placeholder="Текст задания..."
                value={hwEditText}
                onChange={(e) => setHwEditText(e.target.value)}
              />

              {/* файлы пока не делаем */}
              <button className="hwActionRow" type="button" disabled>
                <span className="hwPlus">+</span>
                Добавить файлы (максимум 5)
              </button>

              <button
                className="hwActionRow"
                type="button"
                onClick={() => { setHwEditCalBaseMonth(startOfMonth(selectedDate)); setHwEditCalOpen(true); }}
              >
                <span className="hwPlus">+</span>
                {hwEditDeadline
                  ? `Кастомная дата дедлайна: ${formatDeadlineRu(hwEditDeadline)}`
                  : "Кастомная дата дедлайна"}
              </button>

              <button className="hwActionRow" type="button" onClick={askDeleteHw}>
                Удалить задание
              </button>

              <div className="hwBottomButtons">
                <button className="hwBtn hwBtnPrimary" type="button" onClick={submitHwEdit}>
                  Редактировать
                </button>
                <button className="hwBtn hwBtnSecondary" type="button" onClick={askCancelEdit}>
                  Отменить
                </button>
              </div>
            </div>

            {hwEditCalOpen && (() => {
              const months = Array.from({ length: 25 }, (_, i) => addMonths(hwEditCalBaseMonth, i - 12));
              return (
                <div className="calFull">
                  <div className="calTop">
                    <div className="calTopLeft" />
                    <div className="calTopTitle">Календарь</div>
                    <button className="calTopHide" onClick={() => setHwEditCalOpen(false)} type="button">
                      Скрыть
                    </button>
                  </div>

                  <div className="calScroll">
                    {months.map((m) => {
                      const y = m.getFullYear();
                      const mo = m.getMonth();
                      const first = new Date(y, mo, 1);
                      first.setHours(0, 0, 0, 0);

                      const leading = (first.getDay() + 6) % 7;
                      const dim = daysInMonth(first);
                      const totalCells = Math.ceil((leading + dim) / 7) * 7;

                      const cells = Array.from({ length: totalCells }, (_, idx) => {
                        const dayNum = idx - leading + 1;
                        if (dayNum < 1 || dayNum > dim) return null;
                        const d = new Date(y, mo, dayNum);
                        d.setHours(0, 0, 0, 0);
                        return d;
                      });

                      return (
                        <div className="calMonthBlock" key={`${y}-${mo}`}>
                          <div className="calMonthTitle">{RU_MONTH_CAP[mo]} {y}</div>
                          <div className="calDowRow">
                            {RU_DOW_CAL.map((d) => <div key={d} className="calDowCell">{d}</div>)}
                          </div>
                          <div className="calGrid">
                            {cells.map((d, idx) => {
                              if (!d) return <div key={idx} className="calEmpty" />;
                              const isSel = hwEditDeadline ? sameDay(d, hwEditDeadline) : false;
                              return (
                                <button
                                  key={idx}
                                  type="button"
                                  className={`calDay ${isSel ? "sel" : ""}`}
                                  onClick={() => pickHwEditDeadline(d)}
                                >
                                  {d.getDate()}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                    <div className="calBottomPad" />
                  </div>
                </div>
              );
            })()}
          </div>
        )}

        {confirmOpen && (
          <div className="hwModalOverlay">
            <div className="hwModal">
              <div className="hwModalText">{confirmText}</div>
              <div className="hwModalBtns">
                <button className="hwBtn hwBtnPrimary" type="button" onClick={confirmYes}>
                  Подтвердить
                </button>
                <button className="hwBtn hwBtnSecondary" type="button" onClick={closeConfirm}>
                  Назад
                </button>
              </div>
            </div>
          </div>
        )}

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