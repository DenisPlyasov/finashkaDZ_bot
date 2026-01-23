import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const CHANNEL_LINK = "https://t.me/question_finashkadzbot";

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
  const [selection, setSelection] = useState(null); // сохранённый выбор {target_type,target_id,target_title}
  const debounceRef = useRef(null);

  const canWorkInsideTelegram = useMemo(() => !!window.Telegram?.WebApp, []);

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
        // дальше проверяем, вводил ли уже группу/препода
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
        setStep("schedule");
      } else {
        setStep("groupInput");
      }
    } catch {
      // если что-то пошло не так — просто покажем ввод
      setStep("groupInput");
    }
  };

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

  // ---- group input logic ----
  const requestSuggestions = async (text, currentMode) => {
    if (!text || text.trim().length < 2) {
      setSuggestions([]);
      return;
    }

    const r = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initData, type: currentMode, q: text }),
    });

    const res = await r.json();
    if (r.ok) setSuggestions(res.items || []);
    else setSuggestions([]);
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
      // если юзер ничего не выбрал из подсказок — попробуем поискать и взять первый результат
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

      // сохраняем выбор
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
      setStatus("ok");
      setStep("schedule");
    } catch (e) {
      setStatus("fail");
      setMessage("Ошибка сохранения выбора. Попробуйте ещё раз.");
    }
  };

  // ---- screens ----

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
    const t = selection?.target_type === "teacher" ? "преподавателя" : "группы";
    return (
      <div className="page">
        <div className="card">
          <div className="title">
            Здесь скоро будет расписание для {t}:
          </div>
          <div className="subtitle strongLine">{selection?.target_title}</div>
        </div>
      </div>
    );
  }

  if (step === "groupInput") {
    return (
      <div className="page">
        <div className="card">
          <div className="iconWrap">
            <img className="iconImg" src="/fa_icon.png" alt="FA" />
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
                <button key={String(it.id)} className="suggestItem" onClick={() => onPick(it)}>
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

  // subscribe screen (как было)
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