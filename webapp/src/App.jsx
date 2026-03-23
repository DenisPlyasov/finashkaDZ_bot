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
const WEEK_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const RU_WEEK = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const defaultWeekdays = ["mon", "tue", "wed", "thu", "fri", "sat"]; // ПН-СБ

const makeId = () => `${Date.now()}_${Math.random().toString(16).slice(2)}`;
const uid = makeId;
const DEFAULT_NOTIFY_WEEKDAYS = ["mon","tue","wed","thu","fri","sat"];

const withIds = (rules) => {
  const arr = Array.isArray(rules) ? rules : [];
  return arr.map((r) => ({
    id: r?.id || makeId(),
    time: String(r?.time || "19:00"),
    day: r?.day === "today" ? "today" : "tomorrow",
  }));
};

const clamp2digits = (v) => String(v || "").replace(/\D+/g, "").slice(0, 2);
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

function normalizeExternalUrl(raw) {
  const s = safeText(raw);
  if (!s) return "";
  if (/^https?:\/\//i.test(s)) return s;
  if (s.startsWith("//")) return `https:${s}`;
  return "";
}

function handleExternalLinkClick(event, href) {
  if (!href) return;
  const tg = window.Telegram?.WebApp;
  if (!tg?.openLink) return;
  event.preventDefault();
  tg.openLink(href);
}

function PairLocationContent({ link, room }) {
  const normalizedLink = normalizeExternalUrl(link);
  const roomText = safeText(room);

  if (normalizedLink) {
    return (
      <>
        <span className="pairVisitLinkWrap">
          <img className="pairVisitLinkIcon" src="/link-ico.svg" alt="" />
          <a
            className="pairVisitLink"
            href={normalizedLink}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => handleExternalLinkClick(e, normalizedLink)}
          >
            ссылка
          </a>
        </span>
        {roomText ? <span className="pairVisitSeparator">•</span> : null}
        {roomText ? <span className="pairRoomText">{roomText}</span> : null}
      </>
    );
  }

  return roomText || "—";
}

function shortenGroupedTeacherName(raw) {
  const full = safeText(raw);
  if (!full) return "";

  const parts = full.split(/\s+/).filter(Boolean);
  if (parts.length < 2) return full;

  const restLooksShort = parts.slice(1).every((part) => /^[A-ZА-ЯЁ]\.?$/i.test(part));
  if (restLooksShort) return full;

  const initials = parts
    .slice(1)
    .map((part) => `${part.charAt(0).toUpperCase()}.`)
    .join(" ");

  return initials ? `${parts[0]} ${initials}` : full;
}

function renderPairNo(n) {
  if (!n) return "";
  return `${n} ПАРА`;
}

function formatRuPairDateLine(d) {
  return `${d.getDate()} ${RU_MONTH[d.getMonth()]}`;
}

function formatScheduleActualAt(ts) {
  const value = Number(ts);
  if (!value) return "";

  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";

  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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

function hasCyrillic(s) {
  return /[А-Яа-яЁё]/.test(String(s || ""));
}

// Частый признак "UTF-8 прочитали как Latin-1/Win1252"
function looksMojibake(s) {
  const str = String(s || "");
  if (!str) return false;
  // типичные символы из кракозябр + при этом нет кириллицы
  return !hasCyrillic(str) && /[ÐÑÃÂ]/.test(str);
}

function latin1ToUtf8(str) {
  try {
    const bytes = Uint8Array.from(String(str), (ch) => ch.charCodeAt(0) & 0xff);
    return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
  } catch {
    return String(str || "");
  }
}

function fixFilenameEncoding(name) {
  let s = safeText(name);
  if (!s) return s;

  // пробуем 1–2 раза (иногда бывает двойная порча)
  for (let i = 0; i < 2; i++) {
    if (!looksMojibake(s)) break;
    const decoded = latin1ToUtf8(s);
    // применяем только если стало "похоже на русский"
    if (decoded && decoded !== s && hasCyrillic(decoded)) s = decoded;
    else break;
  }

  return s;
}

function getNiceFileName(fileObj) {
  // приоритет: display_name (ваше поле) -> original_name -> fallback
  const raw = safeText(fileObj?.display_name) || safeText(fileObj?.original_name) || "file";
  return fixFilenameEncoding(raw);
}
function clampHHMM(value) {
  // оставляем только цифры и двоеточие; автоподстановка ":" после HH
  const raw = String(value ?? "").replace(/[^\d:]/g, "");
  const digits = raw.replace(/:/g, "").slice(0, 4); // максимум HHMM

  const hh = digits.slice(0, 2);
  const mm = digits.slice(2, 4);

  if (digits.length <= 2) return hh;         // "1" / "19"
  return `${hh}:${mm}`;                      // "19:0" / "19:00"
}

function normalizeToValidHHMM(value) {
  // на blur приводим к HH:MM и зажимаем в 00-23 / 00-59
  const s = String(value ?? "");
  const digits = s.replace(/\D/g, "").slice(0, 4);

  let hh = digits.slice(0, 2);
  let mm = digits.slice(2, 4);

  if (hh.length < 2) hh = hh.padEnd(2, "0");
  if (mm.length < 2) mm = mm.padEnd(2, "0");

  let h = Number(hh);
  let m = Number(mm);

  if (Number.isNaN(h)) h = 0;
  if (Number.isNaN(m)) m = 0;

  h = Math.max(0, Math.min(23, h));
  m = Math.max(0, Math.min(59, m));

  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function TimeHHMMInput({ value, onChange, className = "" }) {
  return (
    <input
      className={`timeInput ${className}`}
      inputMode="numeric"
      placeholder="19:00"
      value={value}
      onChange={(e) => {
        const next = clampHHMM(e.target.value);
        onChange?.(next);
      }}
      onBlur={() => {
        const fixed = normalizeToValidHHMM(value);
        if (fixed !== value) onChange?.(fixed);
      }}
      maxLength={5}
    />
  );
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
  const [scheduleActualAt, setScheduleActualAt] = useState(null);
  const [scheduleActualWarning, setScheduleActualWarning] = useState("");

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

  // ===== Files flow (shared) =====
  const fileInputAddRef = useRef(null);
  const fileInputEditRef = useRef(null);

  const [fileNameOpen, setFileNameOpen] = useState(false);
  const [pendingFile, setPendingFile] = useState(null); // File
  const [pendingDisplayName, setPendingDisplayName] = useState("");
  const [pendingFor, setPendingFor] = useState(null); // "draft" | "homework"
  const [filesUploading, setFilesUploading] = useState(false);

  const [hwFiles, setHwFiles] = useState([]);         // files for draft screen
  const [hwEditFiles, setHwEditFiles] = useState([]); // files for edit screen

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

  const [pairsEmptyText, setPairsEmptyText] = useState("На текущую дату пар не найдено");
  const [isFavorite, setIsFavorite] = useState(false);

  const [notifyOpen, setNotifyOpen] = useState(false);
  const [notifyRules, setNotifyRules] = useState([{ id: uid(), time: "19:00", day: "tomorrow" }]);
  const [notifyWeekdays, setNotifyWeekdays] = useState(DEFAULT_NOTIFY_WEEKDAYS);

  // HW flags
  const [hwOnlyMe, setHwOnlyMe] = useState(false);
  const [hwNextPair, setHwNextPair] = useState(false);

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

  const loadNotifySettings = async () => {
    try {
      const r = await fetch("/api/notify/get", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData }),
      });
      const j = await r.json();
      if (r.ok && j.ok && j.settings) {
        // ✅ weekdays (ПН–СБ по умолчанию)
        if (Array.isArray(j.settings.weekdays) && j.settings.weekdays.length > 0) {
          setNotifyWeekdays(j.settings.weekdays);
        } else {
          setNotifyWeekdays(DEFAULT_NOTIFY_WEEKDAYS);
        }
      
        // ✅ правила с устойчивыми id (иначе фокус будет слетать)
        if (Array.isArray(j.settings.rules) && j.settings.rules.length > 0) {
          setNotifyRules(j.settings.rules.map(x => ({ id: uid(), time: x.time, day: x.day })));
        } else {
          // fallback со старых полей
          const times = Array.isArray(j.settings.times) ? j.settings.times : ["19:00"];
          const days = Array.isArray(j.settings.days) ? j.settings.days : ["tomorrow"];
      
          const day = days.includes("today") ? "today" : "tomorrow";
          setNotifyRules(times.map(t => ({ id: uid(), time: t, day })));
        }
      } else {
        setNotifyWeekdays(DEFAULT_NOTIFY_WEEKDAYS);
        setNotifyRules([{ id: uid(), time: "19:00", day: "tomorrow" }]);
      }
    } catch {}
  };
  
  const saveNotifySettings = async () => {
    const r = await fetch("/api/notify/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initData,
        rules: notifyRules.map(({ id, ...rest }) => rest),
        weekdays: notifyWeekdays,
      }),
    });
    const j = await r.json().catch(()=> ({}));
    if (!r.ok || !j.ok) throw new Error(j?.error || "Не удалось сохранить настройки");
  };

  const refreshFavoriteState = async () => {
    // если выбран не group — избранного/настроек быть не должно
    if (selection?.target_type !== "group") {
      setIsFavorite(false);
      setNotifyOpen(false);
      return;
    }

    try {
      const fr = await fetch("/api/favorites/is", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData }),
      });
      const fj = await fr.json();

      if (fr.ok && fj?.ok) {
        const fav = !!fj.favorited;
        setIsFavorite(fav);

        // если не фаворит — закрываем настройки и не показываем шестерёнку
        if (!fav) {
          setNotifyOpen(false);
        } else {
          // если фаворит — подтягиваем настройки (чтобы UI был актуален)
          await loadNotifySettings();
        }
      }
    } catch {
      // если сеть упала — лучше не показывать настройки
      setIsFavorite(false);
      setNotifyOpen(false);
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
  
      if (r.ok && res.ok) {
        const items = res.items || [];
        setPairs(items);
        setHasPairs(items.length > 0);
        setPairsEmptyText("На текущую дату пар не найдено");
        setScheduleActualAt(res?.actualAt || null);
        setScheduleActualWarning(String(res?.warning || ""));
      } else {
        setPairs([]);
        setHasPairs(false);
        setPairsEmptyText(res?.error === "FA_TIMEOUT"
          ? "Время ожидания ответа от API превышено"
          : "На текущую дату пар не найдено"
        );
        setScheduleActualAt(null);
        setScheduleActualWarning("");
      }
    } catch {
      setPairs([]);
      setHasPairs(false);
      setPairsEmptyText("Время ожидания ответа от API превышено");
      setScheduleActualAt(null);
      setScheduleActualWarning("");
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

  useEffect(() => {
    if (step !== "schedule") return;
    if (!initData) return;
    if (!selection) return;

    refreshFavoriteState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection?.target_type, selection?.target_id, step, initData]);

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

        try {
          const fr = await fetch("/api/favorites/is", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ initData: data }),
          });
          const fj = await fr.json();
          if (fr.ok && fj?.ok) {
            const fav = !!fj.favorited;
            setIsFavorite(fav);
            if (fav) await loadNotifySettings();
          }
        } catch {}

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

  const uploadPendingFile = async () => {
    try {
      if (!pendingFile) return;

      const init = String(initData ?? "").trim();
      if (!init) {
        window.Telegram?.WebApp?.showAlert?.("initData пустой — откройте миниапп в Telegram");
        return;
      }

      const rawName = safeText(pendingDisplayName) || safeText(pendingFile?.name);
      const displayName = fixFilenameEncoding(rawName) || "file";

      const fd = new FormData();
      fd.append("initData", init);
      fd.append("display_name", displayName);
      fd.append("file", pendingFile);

      let url = "";
      if (pendingFor === "draft") {
        if (!hwDraftId) return;
        fd.append("draft_id", String(hwDraftId));
        url = "/api/hw/draft/file/add";
      } else {
        if (!hwEditItem?.id) return;
        fd.append("homework_id", String(hwEditItem.id));
        url = "/api/hw/file/add";
      }

      setFilesUploading(true);
      const r = await fetch(url, { method: "POST", body: fd });
      const res = await r.json();
      if (!r.ok || !res.ok) throw new Error(res?.error || "upload failed");

      if (pendingFor === "draft") setHwFiles(res.files || []);
      else setHwEditFiles(res.files || []);

      setFileNameOpen(false);
      setPendingFile(null);
      setPendingDisplayName("");
      setPendingFor(null);
    } catch (e) {
      window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
    } finally {
      setFilesUploading(false);
    }
  };

  const onFileClick = async ({ homework_id, file_id, displayDate }) => {
    const tg = window.Telegram?.WebApp;

    const notify = (msg) => {
      if (tg?.showAlert) tg.showAlert(msg);
      else alert(msg);
    };

    try {
      const r = await fetch("/api/hw/file/send_to_chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          initData: String(initData ?? "").trim(),
          homework_id,
          file_id,
          display_date: displayDate || null,
        }),
      });

      const j = await r.json().catch(() => ({}));

      if (j?.ok) {
        const text =
          j.toast ||
          "Из-за ограничений на скачивание файлов в телеграмм-миниапп файл был отправлен в чат с ботом.";
        notify(text);
      } else {
        notify(j?.error || "Не удалось отправить файл");
      }
    } catch (e) {
      notify(String(e?.message || e));
    }
  };

  // ===== Files remove =====
const removeDraftFile = async (fileId) => {
  try {
    if (!hwDraftId) return;

    const r = await fetch("/api/hw/draft/file/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initData: String(initData ?? "").trim(),
        draft_id: hwDraftId,
        file_id: fileId,
      }),
    });

    const res = await r.json();
    if (!r.ok || !res.ok) throw new Error(res?.error || "remove failed");

    setHwFiles(res.files || []);
  } catch (e) {
    window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
  }
};

const removeHomeworkFile = async (fileId) => {
  try {
    if (!hwEditItem?.id) return;

    const r = await fetch("/api/hw/file/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initData: String(initData ?? "").trim(),
        homework_id: hwEditItem.id,
        file_id: fileId,
      }),
    });

    const res = await r.json();
    if (!r.ok || !res.ok) throw new Error(res?.error || "remove failed");

    setHwEditFiles(res.files || []);
  } catch (e) {
    window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
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
          pair_teacher: pair.hw_teacher ?? pair.teacher ?? "",
          pair_type: pair.type || "",
        }),
      });
      const res = await r.json();
      if (!r.ok) throw new Error(res?.error || "draft create failed");

      setHwPair(pair);
      setHwDraftId(res.draft_id);
      setHwText("");
      setHwOnlyMe(false);
      setHwNextPair(false);
      setHwDeadline(null);
      setHwCalBaseMonth(startOfMonth(selectedDate));
      setHwOpen(true);
      setHwFiles([]);
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

    // NEW:
    try {
      const arr = JSON.parse(hw?.files_json || "[]");
      setHwEditFiles(Array.isArray(arr) ? arr : []);
    } catch {
      setHwEditFiles([]);
    }

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
      await refreshFavoriteState();
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
    const dayKeyUTC = (d) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());

    const wsKey = dayKeyUTC(ws);
    const selKey = dayKeyUTC(selectedDate);
    
    const selectedIdxRaw = Math.round((selKey - wsKey) / 86400000);
    const selectedIdx = Math.max(0, Math.min(6, selectedIdxRaw));

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
          <div className="topLeftActions">
            <button
              className="iconBtn"
              aria-label="favorite"
              onClick={async () => {
                // избранное только для групп
                if (selection?.target_type !== "group") {
                  window.Telegram?.WebApp?.showAlert?.("Избранное доступно только для групп");
                  return;
                }
                try {
                  const r = await fetch("/api/favorites/toggle", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ initData }),
                  });
                  const j = await r.json();
                  if (r.ok && j.ok) {
                    const fav = !!j.favorited;
                    setIsFavorite(fav);
                  
                    const msg = fav
                      ? "Группа добавлена в избранное, отредактировать время получения уведомлений можно в настройках рядом с избранным"
                      : "☆ Группа удалена из избранного";
                    window.Telegram?.WebApp?.showAlert?.(msg);
                  
                    if (fav) await loadNotifySettings();
                  } else {
                    window.Telegram?.WebApp?.showAlert?.(j?.error || "Не удалось изменить избранное");
                  }
                } catch (e) {
                  window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
                }
              }}
            >
              <img src={isFavorite ? "/star-filled.png" : "/star-empty.png"} alt="fav" />
            </button>

            {selection?.target_type === "group" && isFavorite && (
              <button
                className="iconBtn"
                aria-label="settings"
                onClick={async () => {
                  await loadNotifySettings();
                  setNotifyOpen(true);
                }}
              >
                <img src="/settings-icon.png" alt="settings" />
              </button>
            )}
          </div>

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
        {scheduleActualAt ? (
          <div className={`scheduleActualLine ${scheduleActualWarning ? "isSaved" : ""}`}>
            Актуально на {formatScheduleActualAt(scheduleActualAt)}
          </div>
        ) : null}
        {scheduleActualWarning ? (
          <div className="scheduleActualWarn">{scheduleActualWarning}</div>
        ) : null}

        <div
          className={`scheduleBody ${hasPairs ? "hasPairs" : "noPairs"} ${pairsLoading ? "isLoading" : ""}`}
          onTouchStart={(e) => handleTouchStart(touchMain, e)}
          onTouchEnd={(e) => handleTouchEnd(touchMain, swipeMain, e)}
        >
          {pairsLoading ? (
            "Проверяем пары…"
          ) : hasPairs ? (
            <div className="pairsList">
              {pairs.map((p, idx) => {
                const pairVariants = Array.isArray(p.variants)
                  ? p.variants.filter((variant) => (
                    safeText(variant?.teacher) ||
                    safeText(variant?.room) ||
                    normalizeExternalUrl(variant?.link)
                  ))
                  : [];
                const showVariantList = pairVariants.length > 1;
                const pairLink = normalizeExternalUrl(p.link);
                const pairRoom = safeText(p.room);
                const pairTeacher = safeText(p.teacher);

                return (
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
                      {showVariantList ? (
                        <div className="pairVariantList">
                          {pairVariants.map((variant, variantIdx) => (
                            <div
                              className="pairVariantRow"
                              key={`${variant.teacher || "teacher"}-${variant.room || "room"}-${variant.link || "link"}-${variantIdx}`}
                            >
                              <span className="pairVariantTeacher">
                                {shortenGroupedTeacherName(variant.teacher) || "Преподаватель не указан"}
                              </span>
                              {(safeText(variant.room) || normalizeExternalUrl(variant.link)) ? (
                                <span className="pairVariantSeparator">•</span>
                              ) : null}
                              {(safeText(variant.room) || normalizeExternalUrl(variant.link)) ? (
                                <span className="pairVariantLocation">
                                  <PairLocationContent link={variant.link} room={variant.room} />
                                </span>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <>
                          <div className="pairTeacher">{pairTeacher || "—"}</div>
                          <div className="pairRoom">
                            <PairLocationContent link={pairLink} room={pairRoom} />
                          </div>
                        </>
                      )}
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

                          {/* ✅ прикреплённые файлы — между текстом и датой */}
                          {(() => {
                            let files = [];
                            try {
                              files = JSON.parse(h?.files_json || "[]");
                            } catch {
                              files = [];
                            }
                            if (!Array.isArray(files) || files.length === 0) return null;

                            return (
                              <div className="hwAttachList">
                                {files.map((f) => (
                                  <button
                                    key={f.id}
                                    type="button"
                                    className="hwAttachBtn"
                                    onClick={() =>
                                      onFileClick({
                                        homework_id: h.id,
                                        file_id: f.id,
                                        displayDate: formatFaDate(selectedDate), // или null, если не надо
                                      })
                                    }
                                    title={getNiceFileName(f)}
                                  >
                                    <img className="hwAttachIcon" src="/load-file.png" alt="" />
                                    <span className="hwAttachName">{getNiceFileName(f)}</span>
                                  </button>
                                ))}
                              </div>
                            );
                          })()}

                          {h.deadline_date && (
                            <div className="hwDeadline">К {h.deadline_date}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                );
              })}
            </div>
          ) : (
            pairsEmptyText
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
              <div className="hwChecks">
                <label className="hwCheckRow">
                  <input
                    type="checkbox"
                    checked={hwOnlyMe}
                    onChange={async (e) => {
                      const v = e.target.checked;
                      setHwOnlyMe(v);
                      if (hwDraftId) {
                        await fetch("/api/hw/draft/update", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ initData, draft_id: hwDraftId, only_for_me: v }),
                        });
                      }
                    }}
                  />
                  Только для меня
                </label>

                <label className="hwCheckRow">
                  <input
                    type="checkbox"
                    checked={hwNextPair}
                    onChange={async (e) => {
                      const v = e.target.checked;
                      setHwNextPair(v);
                      if (hwDraftId) {
                        await fetch("/api/hw/draft/update", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ initData, draft_id: hwDraftId, next_pair: v }),
                        });
                      }
                    }}
                  />
                  На следующую пару
                </label>
              </div>

              {/* список прикреплённых файлов */}
              {hwFiles.length > 0 && (
                <div className="hwFilesList">
                  {hwFiles.map((f) => (
                    <div className="hwFileRow" key={f.id}>
                      <div className="hwFileLeft">
                        <img className="hwFileIcon" src="/load-file.png" alt="" />
                        <div
                          className="hwFileTitle"
                          title={getNiceFileName(f)}
                        >
                          {getNiceFileName(f)}
                        </div>
                      </div>

                      <button
                        className="fileRemoveBtn"
                        type="button"
                        aria-label="remove"
                        onClick={() => removeDraftFile(f.id)}
                      >
                        <span>×</span>
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* кнопка добавления */}
              <button
                className="hwActionRow"
                type="button"
                onClick={() => {
                  if (hwFiles.length >= 5) {
                    window.Telegram?.WebApp?.showAlert?.("Максимум 5 файлов");
                    return;
                  }
                  setPendingFor("draft");
                  fileInputAddRef.current?.click();
                }}
              >
                <input
                  ref={fileInputAddRef}
                  type="file"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (!f) return;
                    setPendingFile(f);
                    setPendingDisplayName("");
                    setFileNameOpen(true);
                  }}
                />
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
              {/* список прикреплённых файлов */}
              {hwEditFiles.length > 0 && (
                <div className="hwFilesList">
                  {hwEditFiles.map((f) => (
                    <div className="hwFileRow" key={f.id}>
                      <div className="hwFileLeft">
                        <img className="hwFileIcon" src="/load-file.png" alt="" />
                        <div className="hwFileTitle" title={getNiceFileName(f)}>
                          {getNiceFileName(f)}
                        </div>
                      </div>

                      <button
                        className="fileRemoveBtn"
                        type="button"
                        aria-label="remove"
                        onClick={() => removeHomeworkFile(f.id)}
                      >
                        <span>×</span>
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {/* файлы пока не делаем */}
              <button
                className="hwActionRow"
                type="button"
                onClick={() => {
                  if (hwEditFiles.length >= 5) {
                    window.Telegram?.WebApp?.showAlert?.("Максимум 5 файлов");
                    return;
                  }
                  setPendingFor("homework");
                  fileInputEditRef.current?.click();
                }}
              >
                <input
                  ref={fileInputEditRef}
                  type="file"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (!f) return;
                    setPendingFile(f);
                    setPendingDisplayName("");
                    setFileNameOpen(true);
                  }}
                />
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

        {fileNameOpen && pendingFile && (
          <div className="fileFull">
            <div className="fileContent">
              <div className="fileTitle">Добавление файла</div>

              <div className="fileCard">
                <div className="fileRow">
                  <div className="fileLabel">Файл</div>
                  <div className="fileValue">{fixFilenameEncoding(pendingFile.name)}</div>
                </div>
                <div className="fileRow">
                  <div className="fileLabel">Размер</div>
                  <div className="fileValue">{Math.ceil(pendingFile.size / 1024)} KB</div>
                </div>
              </div>

              <div className="fileSectionTitle">Короткое название</div>
              <input
                className="fileInput"
                placeholder="Например: Лекция 3"
                value={pendingDisplayName}
                onChange={(e) => setPendingDisplayName(e.target.value)}
              />

              <div className="fileBtns">
                <button
                  className="hwBtn hwBtnPrimary"
                  type="button"
                  disabled={filesUploading}
                  onClick={uploadPendingFile}
                >
                  {filesUploading ? "Загружаем..." : "Подтвердить"}
                </button>

                <button
                  className="hwBtn hwBtnSecondary"
                  type="button"
                  disabled={filesUploading}
                  onClick={() => {
                    setFileNameOpen(false);
                    setPendingFile(null);
                    setPendingDisplayName("");
                    setPendingFor(null);
                  }}
                >
                  Отменить
                </button>
              </div>
            </div>
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

        {notifyOpen && (
          <div className="notifyFull">
            <div className="notifyContent">
              <div className="notifyTitle">Настройки</div>

              <div className="notifyCard">
                <div className="notifyCardTitle">Уведомления</div>
                <div className="notifyCardSub">
                  Добавьте любое количество времен. Для каждого времени выберите: расписание на сегодня или на завтра.
                </div>

                <div className="notifyRules">
                {notifyRules.map((r, idx) => (
                  <div className="notifyRuleRow" key={r.id}>
                    <TimeHHMMInput
                      value={r.time}
                      onChange={(nextTime) => {
                        setNotifyRules(prev => prev.map((x, i) => i === idx ? { ...x, time: nextTime } : x));
                      }}
                    />

                    <button
                      type="button"
                      className={`pill ${r.day === "today" ? "on" : ""}`}
                      onClick={() => setNotifyRules(prev => prev.map((x, i) => i === idx ? { ...x, day: "today" } : x))}
                    >
                      сегодня
                    </button>

                    <button
                      type="button"
                      className={`pill ${r.day === "tomorrow" ? "on" : ""}`}
                      onClick={() => setNotifyRules(prev => prev.map((x, i) => i === idx ? { ...x, day: "tomorrow" } : x))}
                    >
                      завтра
                    </button>

                    <button
                      type="button"
                      className="notifyRemoveRule"
                      onClick={() => setNotifyRules(prev => prev.filter((_, i) => i !== idx))}
                      aria-label="remove"
                    >
                      ×
                    </button>
                  </div>
                ))}
                </div>

                <button
                  className="notifyAddRuleBtn"
                  type="button"
                  onClick={() =>
                    setNotifyRules((prev) => [...prev, { id: makeId(), time: "19:00", day: "tomorrow" }])
                  }
                >
                  + Добавить время
                </button>
              </div>

              <div className="notifyCard">
                <div className="notifyCardTitle">Выбор дня</div>
                <div className="notifyCardSub">
                  Выберите, в какие дни вы хотите получать уведомления с расписанием избранных групп
                </div>
                <div className="notifyPills" style={{ marginTop: 12 }}>
                  {WEEK_KEYS.map((k, i) => {
                    const on = notifyWeekdays.includes(k);
                    return (
                      <button
                        key={k}
                        type="button"
                        className={`pill ${on ? "on" : ""}`}
                        onClick={() => {
                          setNotifyWeekdays((prev) => {
                            const has = prev.includes(k);
                            const next = has ? prev.filter((x) => x !== k) : [...prev, k];
                            // хотя бы один день должен остаться
                            return next.length ? next : prev;
                          });
                        }}
                      >
                        {RU_WEEK[i]}
                      </button>
                    );
                  })}
                </div>
                </div>
              </div>

              <div className="notifyCard">
                <div className="notifyCardTitle">Отключение уведомлений</div>
                <div className="notifyCardSub">
                  Нажав кнопку ниже вы отключите уведомления с расписанием в боте. Включить - добавив группу в избранное
                </div>

                <button
                  className="notifyDangerBtn"
                  type="button"
                  onClick={async () => {
                    try {
                      await fetch("/api/notify/disable", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ initData }),
                      });
                      setNotifyOpen(false);
                      setIsFavorite(false);
                      setNotifyRules([{ id: uid(), time: "19:00", day: "tomorrow" }]);
                      setNotifyWeekdays(DEFAULT_NOTIFY_WEEKDAYS);
                      window.Telegram?.WebApp?.showAlert?.("Уведомления отключены. Группа удалена из избранного.");
                    } catch {}
                  }}
                >
                  Отключить
                </button>
              </div>

              <button
                className="notifySaveBtn"
                type="button"
                onClick={async () => {
                  try {
                    const isValidHHMM = (s) => /^\d{2}:\d{2}$/.test(String(s||"")) &&
                    Number(s.slice(0,2)) >= 0 && Number(s.slice(0,2)) <= 23 &&
                    Number(s.slice(3,5)) >= 0 && Number(s.slice(3,5)) <= 59;
                  
                  if (!notifyRules.length) {
                    window.Telegram?.WebApp?.showAlert?.("Добавьте хотя бы одно время");
                    return;
                  }
                  
                  for (const r of notifyRules) {
                    if (!isValidHHMM(r.time)) {
                      window.Telegram?.WebApp?.showAlert?.(`Некорректное время: ${r.time}. Формат HH:MM`);
                      return;
                    }
                    if (r.day !== "today" && r.day !== "tomorrow") {
                      window.Telegram?.WebApp?.showAlert?.("Выберите 'сегодня' или 'завтра' для каждого времени");
                      return;
                    }
                  }
                  if (!Array.isArray(notifyWeekdays) || notifyWeekdays.length === 0) {
                    window.Telegram?.WebApp?.showAlert?.("Выберите хотя бы один день недели");
                    return;
                  }
                    await saveNotifySettings();
                    setNotifyOpen(false);
                  } catch (e) {
                    window.Telegram?.WebApp?.showAlert?.(String(e?.message || e));
                  }
                }}
              >
                Сохранить и выйти
              </button>
            
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
