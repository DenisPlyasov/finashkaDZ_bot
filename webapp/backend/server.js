import 'dotenv/config';
import express from 'express';
import { validate } from '@tma.js/init-data-node';
import Database from 'better-sqlite3';
import { spawn } from 'node:child_process'; 
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import crypto from 'node:crypto';
import multer from 'multer';



// -------- helpers --------
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const UPLOAD_ROOT = path.join(__dirname, 'uploads');
ensureDir(UPLOAD_ROOT);

const app = express();
app.use(express.json());
app.use('/files', express.static(UPLOAD_ROOT));

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function safeSlug(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[^a-z0-9а-яё]+/gi, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80) || 'item';
}

function safeExt(originalName) {
  const ext = path.extname(String(originalName || '')).slice(0, 10);
  return ext && ext.length <= 10 ? ext : '';
}

function readFilesJson(v) {
  try {
    const arr = JSON.parse(v || '[]');
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function uniqueName(originalName) {
  const ext = safeExt(originalName);
  const rnd = crypto.randomBytes(8).toString('hex');
  return `${Date.now()}_${rnd}${ext}`;
}

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 25 * 1024 * 1024, // 25MB (подстрой)
  },
});

function requireToken() {
  const token = process.env.BOT_TOKEN;
  if (!token) throw new Error('BOT_TOKEN not set');
  return token;
}

function normalizeInitData(input) {
  let s = String(input ?? '').trim();
  if (!s) throw new Error('initData missing or empty');

  // если initData пришёл уже url-encoded (часто при проксах/передаче)
  if (/%3D|%26/i.test(s)) {
    try { s = decodeURIComponent(s); } catch {}
  }

  // если где-то "плюсы" превратились в пробелы — вернём обратно
  // (в initData пробелов быть не должно)
  if (s.includes(' ')) s = s.replace(/ /g, '+');

  return s;
}



function getUserIdFromInitData(initData) {
  const token = requireToken();

  const init = normalizeInitData(initData);

  validate(init, token);

  const params = new URLSearchParams(init);
  const userRaw = params.get('user');
  if (!userRaw) throw new Error('No user in initData');

  const user = JSON.parse(userRaw);
  if (!user?.id) throw new Error('No userId in initData.user');
  return user.id;
}

function runPython(cmd, args = []) {
  return new Promise((resolve, reject) => {
    const sh = path.join(__dirname, 'fa_bridge.sh');   // <-- обёртка
    const py = spawn('bash', [sh, cmd, ...args.map(String)], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let out = '';
    let err = '';

    py.stdout.on('data', (d) => (out += d.toString('utf-8')));
    py.stderr.on('data', (d) => (err += d.toString('utf-8')));

    // ВАЖНО: ловим ошибку запуска (файл не найден/нет прав)
    py.on('error', (e) => reject(new Error(`spawn failed: ${e.message}`)));

    py.on('close', (code) => {
      if (code !== 0) return reject(new Error(err || `python exit code ${code}`));
      try {
        const json = JSON.parse(out);
        if (!json.ok) return reject(new Error(json.error || 'python error'));
        resolve(json);
      } catch (e) {
        reject(new Error(`bad python json: ${String(e)} | out=${out.slice(0, 200)}`));
      }
    });
    console.log('[runPython]', sh, cmd, args);
  });
}

// -------- DB (SQLite) --------
const db = new Database(path.join(__dirname, 'miniapp.sqlite'));
db.pragma('journal_mode = WAL');

db.exec(`
CREATE TABLE IF NOT EXISTS user_selection (
  telegram_user_id INTEGER PRIMARY KEY,
  target_type TEXT NOT NULL,           -- 'group' | 'teacher'
  target_id INTEGER NOT NULL,
  target_title TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
`);

db.exec(`
CREATE TABLE IF NOT EXISTS favorites (
  telegram_user_id INTEGER NOT NULL,
  group_id INTEGER NOT NULL,
  group_title TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (telegram_user_id, group_id)
);
CREATE INDEX IF NOT EXISTS idx_fav_user_time
  ON favorites (telegram_user_id, created_at DESC);
`);

db.exec(`
CREATE TABLE IF NOT EXISTS notify_settings (
  telegram_user_id INTEGER NOT NULL,
  group_id INTEGER NOT NULL,
  group_title TEXT NOT NULL,
  times_json TEXT NOT NULL DEFAULT '["19:00"]',
  days_json  TEXT NOT NULL DEFAULT '["tomorrow"]',
  enabled INTEGER NOT NULL DEFAULT 1,
  updated_at INTEGER NOT NULL,
  last_error_at INTEGER,
  last_error_text TEXT,
  PRIMARY KEY (telegram_user_id, group_id)
);

CREATE TABLE IF NOT EXISTS notify_log (
  telegram_user_id INTEGER NOT NULL,
  group_id INTEGER NOT NULL,
  day_type TEXT NOT NULL,      -- today/tomorrow
  schedule_date TEXT NOT NULL, -- YYYY.MM.DD
  hhmm TEXT NOT NULL,          -- HH:MM
  sent_at INTEGER NOT NULL,
  PRIMARY KEY (telegram_user_id, group_id, day_type, schedule_date, hhmm)
);
`);

db.exec(`
CREATE TABLE IF NOT EXISTS user_selection_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_user_id INTEGER NOT NULL,
  target_type TEXT NOT NULL,
  target_id INTEGER NOT NULL,
  target_title TEXT NOT NULL,
  used_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_selection_history_user_time
  ON user_selection_history (telegram_user_id, used_at DESC);
`);


db.exec(`
CREATE TABLE IF NOT EXISTS homework (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type TEXT NOT NULL,          -- 'group' | 'teacher'
  target_id INTEGER NOT NULL,
  target_title TEXT NOT NULL,

  pair_date TEXT NOT NULL,            -- 'YYYY.MM.DD'
  pair_title TEXT NOT NULL,
  pair_time TEXT,
  pair_no INTEGER,

  created_by_telegram_user_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  deadline_date TEXT,                 -- 'YYYY.MM.DD' | NULL
  files_json TEXT NOT NULL DEFAULT '[]',

  created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_homework_lookup
  ON homework (target_type, target_id, pair_date);
`);

db.exec(`
CREATE TABLE IF NOT EXISTS homework_drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_user_id INTEGER NOT NULL,

  target_type TEXT NOT NULL,
  target_id INTEGER NOT NULL,
  target_title TEXT NOT NULL,

  pair_date TEXT NOT NULL,
  pair_title TEXT NOT NULL,
  pair_time TEXT,
  pair_no INTEGER,

  text TEXT NOT NULL DEFAULT '',
  deadline_date TEXT,
  files_json TEXT NOT NULL DEFAULT '[]',

  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);



CREATE INDEX IF NOT EXISTS idx_hw_drafts_user
  ON homework_drafts (telegram_user_id, updated_at DESC);
`);


function tryAlter(sql) {
  try { db.exec(sql); } catch { /* ignore */ }
}

// миграции (добавляем колонки, если раньше их не было)
tryAlter(`ALTER TABLE homework ADD COLUMN pair_teacher TEXT`);
tryAlter(`ALTER TABLE homework ADD COLUMN only_for_user_id INTEGER`);
tryAlter(`ALTER TABLE homework ADD COLUMN next_pair INTEGER`);

tryAlter(`ALTER TABLE homework_drafts ADD COLUMN pair_teacher TEXT`);
tryAlter(`ALTER TABLE homework_drafts ADD COLUMN only_for_user_id INTEGER`);
tryAlter(`ALTER TABLE homework_drafts ADD COLUMN next_pair INTEGER`);
tryAlter(`ALTER TABLE homework ADD COLUMN pair_type TEXT`);
tryAlter(`ALTER TABLE homework_drafts ADD COLUMN pair_type TEXT`);
tryAlter(`ALTER TABLE notify_settings ADD COLUMN rules_json TEXT`);
tryAlter(`ALTER TABLE notify_settings ADD COLUMN weekdays_json TEXT`);

// -------- existing endpoints --------
app.get('/api/ping', (req, res) => {
  res.json({ ok: true, ts: Date.now() });
});

app.post('/api/auth/telegram', (req, res) => {
  try {
    const { initData } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });

    const init = normalizeInitData(initData);

    requireToken();
    validate(init, process.env.BOT_TOKEN);

    return res.json({ ok: true, message: 'initData is valid' });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/subscription/check', async (req, res) => {
  try {
    const { initData } = req.body || {};
    if (!initData) return res.status(400).json({ error: 'initData missing' });

    const token = requireToken();
    const channel = process.env.REQUIRED_CHANNEL;
    if (!channel) return res.status(500).json({ error: 'REQUIRED_CHANNEL not set' });

    const userId = getUserIdFromInitData(initData);

    const url = `https://api.telegram.org/bot${token}/getChatMember?chat_id=${encodeURIComponent(channel)}&user_id=${encodeURIComponent(userId)}`;
    const tgRes = await fetch(url);
    const tgData = await tgRes.json();

    const status = tgData?.result?.status;
    const subscribed = status === 'member' || status === 'administrator' || status === 'creator';

    return res.json({ subscribed, status });
  } catch (e) {
    return res.status(401).json({ error: String(e?.message || e) });
  }
});

// -------- NEW: selection logic --------

// 1) получить сохранённый выбор (если есть)
app.post('/api/selection/get', (req, res) => {
  try {
    const { initData } = req.body || {};
    if (!initData) return res.status(400).json({ error: 'initData missing' });

    const userId = getUserIdFromInitData(initData);
    const row = db.prepare('SELECT target_type, target_id, target_title FROM user_selection WHERE telegram_user_id = ?')
      .get(userId);

    return res.json({ ok: true, selection: row || null });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/favorites/get', (req, res) => {
  try {
    const { initData } = req.body || {};
    const userId = getUserIdFromInitData(initData);

    const rows = db.prepare(`
      SELECT group_id, group_title, created_at
      FROM favorites
      WHERE telegram_user_id = ?
      ORDER BY created_at DESC
      LIMIT 50
    `).all(userId);

    return res.json({ ok: true, items: rows });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/notify/get', (req, res) => {
  try {
    const { initData } = req.body || {};
    const userId = getUserIdFromInitData(initData);

    const sel = getSelectionForUser(userId);
    if (!sel || sel.target_type !== 'group') return res.json({ ok: true, settings: null });

    const row = db.prepare(`
      SELECT group_id, group_title, times_json, days_json, rules_json, weekdays_json, enabled
      FROM notify_settings
      WHERE telegram_user_id = ? AND group_id = ?
    `).get(userId, Number(sel.target_id));

    if (!row) return res.json({ ok: true, settings: null });

    let rules = null;
    try { rules = row.rules_json ? JSON.parse(row.rules_json) : null; } catch { rules = null; }
    
    let weekdays = null;
    try { weekdays = row.weekdays_json ? JSON.parse(row.weekdays_json) : null; } catch { weekdays = null; }
    
    return res.json({
      ok: true,
      settings: {
        group_id: row.group_id,
        group_title: row.group_title,
        enabled: !!row.enabled,
    
        rules: Array.isArray(rules) ? rules : null,
        weekdays: Array.isArray(weekdays) && weekdays.length > 0 ? weekdays : null,
    
        times: JSON.parse(row.times_json || '["19:00"]'),
        days: JSON.parse(row.days_json || '["tomorrow"]'),
      }
    });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

function isValidHHMM(s) {
  return /^\d{2}:\d{2}$/.test(String(s || "")) &&
    Number(s.slice(0,2)) >= 0 && Number(s.slice(0,2)) <= 23 &&
    Number(s.slice(3,5)) >= 0 && Number(s.slice(3,5)) <= 59;
}

function isValidDayType(x) {
  return x === "today" || x === "tomorrow";
}

function normalizeRules(rules) {
  if (!Array.isArray(rules)) return [];

  const out = [];
  for (const r of rules) {
    const time = String(r?.time || "").trim();
    const day = String(r?.day || "").trim();

    if (!isValidHHMM(time)) continue;
    if (!isValidDayType(day)) continue;

    // уникальность по (time, day)
    if (!out.find(x => x.time === time && x.day === day)) {
      out.push({ time, day });
    }
  }

  // сортировка по времени
  out.sort((a, b) => a.time.localeCompare(b.time));
  return out;
}

function buildRulesFromLegacy(times, days) {
  const t = Array.isArray(times) ? times.map(String).filter(isValidHHMM) : [];
  const d = Array.isArray(days) ? days.map(String).filter(isValidDayType) : [];
  const out = [];
  for (const time of t) {
    for (const day of d) out.push({ time, day });
  }
  return normalizeRules(out);
}

app.post('/api/notify/set', (req, res) => {
  try {
    const { initData, times, days, rules, weekdays } = req.body || {};
    const userId = getUserIdFromInitData(initData);

    const sel = getSelectionForUser(userId);
    if (!sel || sel.target_type !== 'group') {
      return res.status(400).json({ ok: false, error: 'Only groups can have notifications' });
    }

    const gid = Number(sel.target_id);
    const title = String(sel.target_title || '').trim() || 'Группа';

    // проверим, что группа реально в избранном
    const fav = db.prepare(`SELECT 1 FROM favorites WHERE telegram_user_id=? AND group_id=?`).get(userId, gid);
    if (!fav) return res.status(400).json({ ok: false, error: 'Group is not favorited' });
    const WEEK_KEYS = ["mon","tue","wed","thu","fri","sat","sun"];
    const DEFAULT_WEEKDAYS = ["mon","tue","wed","thu","fri","sat"];

    function normalizeWeekdays(arr) {
      if (!Array.isArray(arr)) return DEFAULT_WEEKDAYS;
      const set = new Set();
      for (const x of arr) {
        const k = String(x || "").trim().toLowerCase();
        if (WEEK_KEYS.includes(k)) set.add(k);
      }
      const out = [...set];
      return out.length ? out : DEFAULT_WEEKDAYS;
    }

    const normRules = normalizeRules(rules);
    const normWeekdays = normalizeWeekdays(weekdays);

    // если пришли rules — используем их
    if (normRules.length > 0) {
      db.prepare(`
        INSERT INTO notify_settings (
          telegram_user_id, group_id, group_title,
          rules_json, weekdays_json,
          times_json, days_json,
          enabled, updated_at
        )
        VALUES (?, ?, ?, ?, ?, '[]', '[]', 1, ?)
        ON CONFLICT(telegram_user_id, group_id) DO UPDATE SET
          group_title=excluded.group_title,
          rules_json=excluded.rules_json,
          weekdays_json=excluded.weekdays_json,
          times_json='[]',
          days_json='[]',
          enabled=1,
          updated_at=excluded.updated_at
      `).run(
        userId,
        gid,
        title,
        JSON.stringify(normRules),
        JSON.stringify(normWeekdays),
        Date.now()
      );

      return res.json({ ok: true });
    }

    // иначе — fallback на старую схему times/days
    const t = Array.isArray(times) ? times.map(String).filter(isValidHHMM) : [];
    const d = Array.isArray(days) ? days.map(String).filter(x => x === "today" || x === "tomorrow") : [];

    if (t.length === 0) return res.status(400).json({ ok: false, error: 'times empty' });
    if (d.length === 0) return res.status(400).json({ ok: false, error: 'days empty' });

    db.prepare(`
      INSERT INTO notify_settings (telegram_user_id, group_id, group_title, times_json, days_json, weekdays_json, enabled, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, 1, ?)
      ON CONFLICT(telegram_user_id, group_id) DO UPDATE SET
        group_title=excluded.group_title,
        times_json=excluded.times_json,
        days_json=excluded.days_json,
        weekdays_json=excluded.weekdays_json,
        enabled=1,
        updated_at=excluded.updated_at
    `).run(userId, gid, title, JSON.stringify(t), JSON.stringify(d), JSON.stringify(normWeekdays), Date.now());

    return res.json({ ok: true });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/notify/disable', (req, res) => {
  try {
    const { initData } = req.body || {};
    const userId = getUserIdFromInitData(initData);

    const sel = getSelectionForUser(userId);
    if (!sel || sel.target_type !== 'group') return res.json({ ok: true });

    const gid = Number(sel.target_id);

    db.prepare(`DELETE FROM favorites WHERE telegram_user_id=? AND group_id=?`).run(userId, gid);
    db.prepare(`DELETE FROM notify_settings WHERE telegram_user_id=? AND group_id=?`).run(userId, gid);

    return res.json({ ok: true });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/favorites/toggle', async (req, res) => {
  try {
    const { initData } = req.body || {};
    const userId = getUserIdFromInitData(initData);

    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });
    if (sel.target_type !== 'group') return res.status(400).json({ ok: false, error: 'Only groups can be favorited' });

    const gid = Number(sel.target_id);
    const title = String(sel.target_title || '').trim() || 'Группа';

    const exists = db.prepare(`
      SELECT 1 FROM favorites WHERE telegram_user_id = ? AND group_id = ?
    `).get(userId, gid);

    if (exists) {
      db.prepare(`DELETE FROM favorites WHERE telegram_user_id = ? AND group_id = ?`).run(userId, gid);
      db.prepare(`DELETE FROM notify_settings WHERE telegram_user_id = ? AND group_id = ?`).run(userId, gid);
      return res.json({ ok: true, favorited: false });
    }

    db.prepare(`
      INSERT INTO favorites (telegram_user_id, group_id, group_title, created_at)
      VALUES (?, ?, ?, ?)
    `).run(userId, gid, title, Date.now());

    // создаём дефолтные настройки уведомлений (если ещё нет)
    db.prepare(`
      INSERT OR IGNORE INTO notify_settings
      (telegram_user_id, group_id, group_title, rules_json, weekdays_json, times_json, days_json, enabled, updated_at)
      VALUES (?, ?, ?, ?, ?, '[]', '[]', 1, ?)
    `).run(
      userId,
      gid,
      title,
      JSON.stringify([{ time: "19:00", day: "tomorrow" }]),
      JSON.stringify(["mon","tue","wed","thu","fri","sat"]),
      Date.now()
    );

    return res.json({ ok: true, favorited: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/favorites/is', (req, res) => {
  try {
    const { initData } = req.body || {};
    const userId = getUserIdFromInitData(initData);
    const sel = getSelectionForUser(userId);
    if (!sel || sel.target_type !== 'group') return res.json({ ok: true, favorited: false });

    const row = db.prepare(`
      SELECT 1 FROM favorites WHERE telegram_user_id = ? AND group_id = ?
    `).get(userId, Number(sel.target_id));

    return res.json({ ok: true, favorited: !!row });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

// 2) поиск подсказок (group/teacher)
app.post('/api/search', async (req, res) => {
  try {
    const { initData, type, q } = req.body || {};
    if (!initData) return res.status(400).json({ error: 'initData missing' });
    if (!q || String(q).trim().length < 2) return res.json({ ok: true, items: [] });

    getUserIdFromInitData(initData);

    const query = String(q).trim();
    const cmd = type === 'teacher' ? 'search_teacher' : 'search_group';

    const py = await runPython(cmd, [query]);
    const items = (py.items || []).slice(0, 7);

    return res.json({ ok: true, items });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

// 3) сохранить выбранный вариант
app.post('/api/selection/set', (req, res) => {
  try {
    const { initData, type, id, title } = req.body || {};
    if (!initData) return res.status(400).json({ error: 'initData missing' });
    if (!type || !id || !title) return res.status(400).json({ error: 'type/id/title required' });

    const userId = getUserIdFromInitData(initData);
    const now = Date.now();

    const stmt = db.prepare(`
      INSERT INTO user_selection (telegram_user_id, target_type, target_id, target_title, updated_at)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(telegram_user_id) DO UPDATE SET
        target_type=excluded.target_type,
        target_id=excluded.target_id,
        target_title=excluded.target_title,
        updated_at=excluded.updated_at
    `);

    stmt.run(userId, type, Number(id), String(title), now);

    // обновляем историю: убираем дубль и добавляем как “последний”
    db.prepare(`
    DELETE FROM user_selection_history
    WHERE telegram_user_id = ? AND target_type = ? AND target_id = ?
    `).run(userId, type, Number(id));

    db.prepare(`
    INSERT INTO user_selection_history (telegram_user_id, target_type, target_id, target_title, used_at)
    VALUES (?, ?, ?, ?, ?)
    `).run(userId, type, Number(id), String(title), now);

    // ограничиваем историю до 5 записей
    db.prepare(`
    DELETE FROM user_selection_history
    WHERE telegram_user_id = ?
      AND id NOT IN (
        SELECT id FROM user_selection_history
        WHERE telegram_user_id = ?
        ORDER BY used_at DESC
        LIMIT 5
      )
    `).run(userId, userId);

    return res.json({ ok: true });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/selection/history', (req, res) => {
  try {
    const { initData } = req.body || {};
    if (!initData) return res.status(400).json({ error: 'initData missing' });

    const userId = getUserIdFromInitData(initData);

    const rows = db.prepare(`
      SELECT target_type, target_id, target_title, used_at
      FROM user_selection_history
      WHERE telegram_user_id = ?
      ORDER BY used_at DESC
      LIMIT 5
    `).all(userId);

    return res.json({ ok: true, items: rows });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});



app.post('/api/timetable/has', async (req, res) => {
  try {
    const { initData, date } = req.body || {};
    if (!initData) return res.status(400).json({ error: 'initData missing' });
    if (!date) return res.status(400).json({ error: 'date missing' }); // "YYYY.MM.DD"

    const userId = getUserIdFromInitData(initData);

    const sel = db.prepare(`
      SELECT target_type, target_id, target_title
      FROM user_selection
      WHERE telegram_user_id = ?
    `).get(userId);

    if (!sel) return res.status(404).json({ error: 'No selection' });

    const cmd = sel.target_type === 'teacher' ? 'timetable_teacher' : 'timetable_group';

    // Запрашиваем один день: start=end=date
    const py = await runPython(cmd, [sel.target_id, date, date]);

    const count = Number(py.count || 0);
    return res.json({ ok: true, hasPairs: count > 0, count });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/hw/draft/file/add', upload.single('file'), (req, res) => {
  try {
    const initData = String(req.body?.initData ?? '').trim();
    const draft_id = Number(req.body?.draft_id);
    const display_name = String(req.body?.display_name ?? '').trim();

    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!draft_id) return res.status(400).json({ ok: false, error: 'draft_id required' });
    if (!req.file) return res.status(400).json({ ok: false, error: 'file required' });

    const userId = getUserIdFromInitData(initData);

    const draft = db.prepare(`
      SELECT id, telegram_user_id, target_type, target_id, target_title, pair_date, files_json
      FROM homework_drafts
      WHERE id = ? AND telegram_user_id = ?
    `).get(draft_id, userId);

    if (!draft) return res.status(404).json({ ok: false, error: 'Draft not found' });

    const files = readFilesJson(draft.files_json);
    if (files.length >= 5) return res.status(400).json({ ok: false, error: 'Максимум 5 файлов' });

    // папка: uploads/<type>_<id>/<YYYY.MM.DD>/
    const groupFolder = `${draft.target_type}_${draft.target_id}`;
    const dateFolder = String(draft.pair_date || 'unknown_date');
    const dir = path.join(UPLOAD_ROOT, groupFolder, dateFolder);
    ensureDir(dir);

    const stored_name = uniqueName(req.file.originalname);
    const rel_path = path.join(groupFolder, dateFolder, stored_name).replaceAll('\\', '/');
    const abs_path = path.join(UPLOAD_ROOT, rel_path);
    fs.writeFileSync(abs_path, req.file.buffer);

    const item = {
      id: crypto.randomUUID(),
      display_name: display_name || path.basename(req.file.originalname),
      original_name: req.file.originalname,
      stored_name,
      rel_path,                 // относительный путь внутри uploads
      mime: req.file.mimetype,
      size: req.file.size,
      created_at: Date.now(),
    };

    files.push(item);

    db.prepare(`
      UPDATE homework_drafts
      SET files_json = ?, updated_at = ?
      WHERE id = ? AND telegram_user_id = ?
    `).run(JSON.stringify(files), Date.now(), draft_id, userId);

    return res.json({ ok: true, item, files });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/hw/file/add', upload.single('file'), (req, res) => {
  try {
    const initData = String(req.body?.initData ?? '').trim();
    const homework_id = Number(req.body?.homework_id);
    const display_name = String(req.body?.display_name ?? '').trim();

    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!homework_id) return res.status(400).json({ ok: false, error: 'homework_id required' });
    if (!req.file) return res.status(400).json({ ok: false, error: 'file required' });

    const userId = getUserIdFromInitData(initData);
    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });

    const hw = db.prepare(`
      SELECT id, target_type, target_id, pair_date, files_json
      FROM homework
      WHERE id = ?
    `).get(homework_id);

    if (!hw) return res.status(404).json({ ok: false, error: 'Homework not found' });

    if (hw.target_type !== sel.target_type || Number(hw.target_id) !== Number(sel.target_id)) {
      return res.status(403).json({ ok: false, error: 'Forbidden' });
    }

    const files = readFilesJson(hw.files_json);
    if (files.length >= 5) return res.status(400).json({ ok: false, error: 'Максимум 5 файлов' });

    const groupFolder = `${hw.target_type}_${hw.target_id}`;
    const dateFolder = String(hw.pair_date || 'unknown_date');
    const dir = path.join(UPLOAD_ROOT, groupFolder, dateFolder);
    ensureDir(dir);

    const stored_name = uniqueName(req.file.originalname);
    const rel_path = path.join(groupFolder, dateFolder, stored_name).replaceAll('\\', '/');
    const abs_path = path.join(UPLOAD_ROOT, rel_path);
    fs.writeFileSync(abs_path, req.file.buffer);

    const item = {
      id: crypto.randomUUID(),
      display_name: display_name || path.basename(req.file.originalname),
      original_name: req.file.originalname,
      stored_name,
      rel_path,
      mime: req.file.mimetype,
      size: req.file.size,
      created_at: Date.now(),
    };

    files.push(item);

    db.prepare(`
      UPDATE homework
      SET files_json = ?
      WHERE id = ?
    `).run(JSON.stringify(files), homework_id);

    return res.json({ ok: true, item, files });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

function safeUnlink(absPath) {
  try {
    if (absPath && fs.existsSync(absPath)) fs.unlinkSync(absPath);
  } catch {
    // ignore
  }
}



function safeJoinUpload(relPath) {
  const abs = path.join(UPLOAD_ROOT, String(relPath || ""));
  // защита от выходов из папки uploads
  if (!abs.startsWith(UPLOAD_ROOT)) return null;
  return abs;
}

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function buildShortTelegramFilename(fileItem) {
  const original = String(fileItem?.display_name || fileItem?.original_name || 'file').trim() || 'file';
  const ext = safeExt(fileItem?.original_name || original);

  let base = original;
  // уберём расширение из display_name, если оно там есть
  if (ext && base.toLowerCase().endsWith(ext.toLowerCase())) {
    base = base.slice(0, -ext.length);
  }

  base = base.trim() || 'file';
  // укоротим
  if (base.length > 32) base = base.slice(0, 32).trim();

  // подчищаем странные символы для имени файла (Telegram нормально, но лучше)
  base = base.replace(/[\/\\:*?"<>|]+/g, '_');

  return `${base}${ext}`;
}

async function tgSendDocumentToUser({ userId, absPath, filename, captionHtml, mime }) {
  const token = requireToken();

  const url = `https://api.telegram.org/bot${token}/sendDocument`;

  const form = new FormData();
  form.append('chat_id', String(userId));
  form.append('caption', String(captionHtml || ''));
  form.append('parse_mode', 'HTML');

  // читаем файл (до 25MB у тебя лимит — ок)
  const buf = fs.readFileSync(absPath);
  const blob = new Blob([buf], { type: mime || 'application/octet-stream' });
  form.append('document', blob, filename);

  const tgRes = await fetch(url, { method: 'POST', body: form });
  const tgData = await tgRes.json().catch(() => ({}));

  if (!tgRes.ok || tgData?.ok !== true) {
    const desc = tgData?.description || `Telegram API error (${tgRes.status})`;
    const err = new Error(desc);
    err.tg = tgData;
    throw err;
  }

  return tgData;
}

async function tgSendMessageToUser({ userId, text }) {
  const token = requireToken();
  const url = `https://api.telegram.org/bot${token}/sendMessage`;

  const form = new FormData();
  form.append('chat_id', String(userId));
  form.append('text', String(text || ''));
  form.append('parse_mode', 'HTML');

  const tgRes = await fetch(url, { method: 'POST', body: form });
  const tgData = await tgRes.json().catch(() => ({}));

  if (!tgRes.ok || tgData?.ok !== true) {
    const desc = tgData?.description || `Telegram API error (${tgRes.status})`;
    const err = new Error(desc);
    err.tg = tgData;
    throw err;
  }
  return tgData;
}

function formatScheduleText(items, dateStr, groupTitle) {
  if (!items || items.length === 0) return `Расписание на ${dateStr} для «${escapeHtml(groupTitle)}»: пар не найдено.`;
  const lines = items.map((p, i) => {
    const t = escapeHtml(p.time || '');
    const title = escapeHtml(p.title || '—');
    const teacher = escapeHtml(p.teacher || '—');
    const room = escapeHtml(p.room || '—');
    const no = p.pair_no ? `${p.pair_no} пара` : `${i + 1} пара`;
    return `<b>${no}</b> • ${t}\n${title}\n${teacher}\n${room}`;
  });
  return `<b>Расписание на ${escapeHtml(dateStr)} для «${escapeHtml(groupTitle)}»</b>\n\n` + lines.join('\n\n');
}

function buildDownloadName(fileItem) {
  const base = String(fileItem?.display_name || fileItem?.original_name || "file").trim() || "file";
  const ext = safeExt(fileItem?.original_name || "");
  if (ext && base.toLowerCase().endsWith(ext.toLowerCase())) return base;
  return `${base}${ext}`;
}


app.post('/api/hw/file/send_to_chat', async (req, res) => {
  try {
    const initData = String(req.body?.initData ?? '').trim();
    const homework_id = Number(req.body?.homework_id);
    const file_id = String(req.body?.file_id ?? '').trim();

    // опционально: если у тебя в UI есть кастомная дата
    const display_date = req.body?.display_date ? String(req.body.display_date) : null;

    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!homework_id) return res.status(400).json({ ok: false, error: 'homework_id required' });
    if (!file_id) return res.status(400).json({ ok: false, error: 'file_id required' });

    const userId = getUserIdFromInitData(initData);

    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });

    const hw = db.prepare(`
      SELECT id, target_type, target_id, pair_title, pair_date, files_json
      FROM homework
      WHERE id = ?
    `).get(homework_id);

    if (!hw) return res.status(404).json({ ok: false, error: 'Homework not found' });

    if (hw.target_type !== sel.target_type || Number(hw.target_id) !== Number(sel.target_id)) {
      return res.status(403).json({ ok: false, error: 'Forbidden' });
    }

    const files = readFilesJson(hw.files_json);
    const file = files.find((x) => String(x.id) === file_id);
    if (!file) return res.status(404).json({ ok: false, error: 'File not found' });

    const abs = safeJoinUpload(file.rel_path);
    if (!abs || !fs.existsSync(abs)) {
      return res.status(404).json({ ok: false, error: 'File missing on disk' });
    }

    const dateLabel = display_date || String(hw.pair_date || '');
    const caption = `Файл к паре «${escapeHtml(hw.pair_title || '')}» на ${escapeHtml(dateLabel)}:\n`;

    const shortFilename = buildShortTelegramFilename(file);

    await tgSendDocumentToUser({
      userId,
      absPath: abs,
      filename: shortFilename,
      captionHtml: caption,
      mime: file.mime,
    });

    return res.json({
      ok: true,
      toast: 'Из-за ограничений на скачивание файлов в телеграмм-миниапп файл был отправлен в чат с ботом.',
    });

  } catch (e) {
    const msg = String(e?.message || e);

    // типичный кейс: пользователь не открыл чат с ботом/заблокировал
    if (/chat not found|bot was blocked|Forbidden/i.test(msg)) {
      return res.status(403).json({
        ok: false,
        error: 'Похоже, вы не открывали чат с ботом или заблокировали его. Откройте бота и нажмите /start, затем попробуйте снова.',
      });
    }

    return res.status(500).json({ ok: false, error: msg });
  }
});

// удалить файл из draft + с диска
app.post('/api/hw/draft/file/remove', (req, res) => {
  try {
    const initData = String(req.body?.initData ?? '').trim();
    const draft_id = Number(req.body?.draft_id);
    const file_id = String(req.body?.file_id ?? '').trim();

    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!draft_id) return res.status(400).json({ ok: false, error: 'draft_id required' });
    if (!file_id) return res.status(400).json({ ok: false, error: 'file_id required' });

    const userId = getUserIdFromInitData(initData);

    const draft = db.prepare(`
      SELECT id, telegram_user_id, files_json
      FROM homework_drafts
      WHERE id = ? AND telegram_user_id = ?
    `).get(draft_id, userId);

    if (!draft) return res.status(404).json({ ok: false, error: 'Draft not found' });

    const files = readFilesJson(draft.files_json);
    const idx = files.findIndex((x) => String(x.id) === file_id);
    if (idx === -1) return res.json({ ok: true, files }); // уже нет — ок

    const [removed] = files.splice(idx, 1);

    // удаляем физически
    if (removed?.rel_path) {
      const abs = safeJoinUpload(removed.rel_path);
      if (abs) safeUnlink(abs);
    }

    db.prepare(`
      UPDATE homework_drafts
      SET files_json = ?, updated_at = ?
      WHERE id = ? AND telegram_user_id = ?
    `).run(JSON.stringify(files), Date.now(), draft_id, userId);

    return res.json({ ok: true, files });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

// удалить файл из homework + с диска
app.post('/api/hw/file/remove', (req, res) => {
  try {
    const initData = String(req.body?.initData ?? '').trim();
    const homework_id = Number(req.body?.homework_id);
    const file_id = String(req.body?.file_id ?? '').trim();

    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!homework_id) return res.status(400).json({ ok: false, error: 'homework_id required' });
    if (!file_id) return res.status(400).json({ ok: false, error: 'file_id required' });

    const userId = getUserIdFromInitData(initData);
    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });

    const hw = db.prepare(`
      SELECT id, target_type, target_id, files_json
      FROM homework
      WHERE id = ?
    `).get(homework_id);

    if (!hw) return res.status(404).json({ ok: false, error: 'Homework not found' });

    if (hw.target_type !== sel.target_type || Number(hw.target_id) !== Number(sel.target_id)) {
      return res.status(403).json({ ok: false, error: 'Forbidden' });
    }

    const files = readFilesJson(hw.files_json);
    const idx = files.findIndex((x) => String(x.id) === file_id);
    if (idx === -1) return res.json({ ok: true, files });

    const [removed] = files.splice(idx, 1);

    if (removed?.rel_path) {
      const abs = path.join(UPLOAD_ROOT, String(removed.rel_path));
      safeUnlink(abs);
    }

    db.prepare(`
      UPDATE homework
      SET files_json = ?
      WHERE id = ?
    `).run(JSON.stringify(files), homework_id);

    return res.json({ ok: true, files });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

app.post('/api/timetable/day', async (req, res) => {
  try {
    const { initData, date } = req.body || {};
    if (!initData) return res.status(400).json({ error: 'initData missing' });
    if (!date) return res.status(400).json({ error: 'date missing' }); // "YYYY.MM.DD"

    const userId = getUserIdFromInitData(initData);

    const sel = db.prepare(`
      SELECT target_type, target_id, target_title
      FROM user_selection
      WHERE telegram_user_id = ?
    `).get(userId);

    if (!sel) return res.status(404).json({ error: 'No selection' });

    const cmd = sel.target_type === 'teacher' ? 'timetable_teacher' : 'timetable_group';

    // один день
    const py = await runPython(cmd, [sel.target_id, date, date]);

    const items = (py.items || []).map((p) => {
      const hws = db.prepare(`
        SELECT id, text, deadline_date, files_json
        FROM homework
        WHERE target_type = ?
          AND target_id = ?
          AND pair_date = ?
          AND pair_title = ?
          AND COALESCE(pair_teacher,'') = COALESCE(?, '')
          AND COALESCE(pair_type,'')    = COALESCE(?, '')
          AND COALESCE(pair_time,'')    = COALESCE(?, '')
          AND (only_for_user_id IS NULL OR only_for_user_id = ?)
        ORDER BY created_at DESC
      `).all(
        sel.target_type,
        sel.target_id,
        String(date),
        String(p.title || ''),
        p.teacher ? String(p.teacher) : null,
        p.type ? String(p.type) : null,
        p.time ? String(p.time) : null,
        userId
      );
    
      return { ...p, homeworks: hws };
    });
    
    return res.json({
      ok: true,
      items,
      count: Number(py.count || 0),
    });

  } catch (e) {
    const msg = String(e?.message || e);
    if (/FA_TIMEOUT|timeout/i.test(msg)) {
      return res.status(504).json({ ok: false, error: 'FA_TIMEOUT' });
    }
    return res.status(500).json({ ok: false, error: msg });
  }
});


function getSelectionForUser(userId) {
  return db.prepare(`
    SELECT target_type, target_id, target_title
    FROM user_selection
    WHERE telegram_user_id = ?
  `).get(userId);
}



// Создать draft (когда открыли экран добавления)
app.post('/api/hw/draft/create', (req, res) => {
  try {
    const { initData, pair_date, pair_title, pair_time, pair_no, pair_teacher, pair_type } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!pair_date || !pair_title) return res.status(400).json({ ok: false, error: 'pair_date/pair_title required' });

    const userId = getUserIdFromInitData(initData);
    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });

    const now = Date.now();

    const info = db.prepare(`
    INSERT INTO homework_drafts (
      telegram_user_id, target_type, target_id, target_title,
      pair_date, pair_title, pair_time, pair_no, pair_teacher, pair_type,
      only_for_user_id, next_pair,
      text, deadline_date, files_json,
      created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, '', NULL, '[]', ?, ?)
  `).run(
    userId,
    sel.target_type, sel.target_id, sel.target_title,
    String(pair_date), String(pair_title),
    pair_time ? String(pair_time) : null,
    pair_no != null ? Number(pair_no) : null,
    pair_teacher ? String(pair_teacher) : null,
    pair_type ? String(pair_type) : null,
    now, now
  );

    return res.json({ ok: true, draft_id: Number(info.lastInsertRowid) });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

// Обновить draft (текст и/или deadline)
app.post('/api/hw/draft/update', (req, res) => {
  try {
    const { initData, draft_id, text, deadline_date, only_for_me, next_pair } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!draft_id) return res.status(400).json({ ok: false, error: 'draft_id required' });

    const userId = getUserIdFromInitData(initData);

    const draft = db.prepare(`
      SELECT id FROM homework_drafts
      WHERE id = ? AND telegram_user_id = ?
    `).get(Number(draft_id), userId);

    if (!draft) return res.status(404).json({ ok: false, error: 'Draft not found' });

    const now = Date.now();

    // частичное обновление
    if (typeof text === 'string') {
      db.prepare(`UPDATE homework_drafts SET text = ?, updated_at = ? WHERE id = ? AND telegram_user_id = ?`)
        .run(String(text), now, Number(draft_id), userId);
    }

    if (deadline_date === null || typeof deadline_date === 'string') {
      db.prepare(`UPDATE homework_drafts SET deadline_date = ?, updated_at = ? WHERE id = ? AND telegram_user_id = ?`)
        .run(deadline_date, now, Number(draft_id), userId);
    }

    if (typeof only_for_me === 'boolean') {
      db.prepare(`UPDATE homework_drafts SET only_for_user_id = ?, updated_at = ? WHERE id = ? AND telegram_user_id = ?`)
        .run(only_for_me ? userId : null, now, Number(draft_id), userId);
    }
    
    if (typeof next_pair === 'boolean') {
      db.prepare(`UPDATE homework_drafts SET next_pair = ?, updated_at = ? WHERE id = ? AND telegram_user_id = ?`)
        .run(next_pair ? 1 : 0, now, Number(draft_id), userId);
    }

    return res.json({ ok: true });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

// Отменить draft
app.post('/api/hw/draft/cancel', (req, res) => {
  try {
    const { initData, draft_id } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!draft_id) return res.status(400).json({ ok: false, error: 'draft_id required' });

    const userId = getUserIdFromInitData(initData);

    db.prepare(`DELETE FROM homework_drafts WHERE id = ? AND telegram_user_id = ?`)
      .run(Number(draft_id), userId);

    return res.json({ ok: true });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});


async function findNextPairForDraft(draft) {
  // ищем в ближайшие 30 дней следующую пару по тому же предмету + teacher
  const start = addDaysStr(draft.pair_date, 1);
  const end = addDaysStr(draft.pair_date, 30);

  const cmd = draft.target_type === 'teacher' ? 'timetable_teacher' : 'timetable_group';
  const py = await runPython(cmd, [draft.target_id, start, end]);
  const items = py.items || [];

  const wantTitle = String(draft.pair_title || '').trim();
  const wantTeacher = String(draft.pair_teacher || '').trim();
  const wantType = String(draft.pair_type || '').trim();

  for (const p of items) {
    const t = String(p.title || '').trim();
    const teach = String(p.teacher || '').trim();
    if (!t) continue;

    // title must match строго, teacher — если есть в draft
    if (
      t === wantTitle &&
      (!wantTeacher || teach === wantTeacher) &&
      (!wantType || String(p.type || '').trim() === wantType)
    ) {
      // НО: нам ещё нужна дата этой пары — её нет в item’ах сейчас
      // поэтому ниже — требование: fa_bridge.py должен возвращать date в уроке (мы добавим)
      if (p.date) {
        return {
          pair_date: String(p.date),
          pair_title: String(p.title || ''),
          pair_time: p.time ? String(p.time) : null,
          pair_no: p.pair_no != null ? Number(p.pair_no) : null,
          pair_teacher: p.teacher ? String(p.teacher) : null,
          pair_type: p.type ? String(p.type) : null,
        };
      }
    }
  }
  return null;
}

// Подтвердить (перенос draft -> homework)
app.post('/api/hw/draft/submit', async (req, res) => {
  try {
    const { initData, draft_id } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!draft_id) return res.status(400).json({ ok: false, error: 'draft_id required' });

    const userId = getUserIdFromInitData(initData);

    const d = db.prepare(`
      SELECT *
      FROM homework_drafts
      WHERE id = ? AND telegram_user_id = ?
    `).get(Number(draft_id), userId);

    if (!d) return res.status(404).json({ ok: false, error: 'Draft not found' });

    const text = String(d.text || '').trim();
    if (!text) return res.status(400).json({ ok: false, error: 'Текст задания пустой' });

    const now = Date.now();

    let finalPair = {
      pair_date: d.pair_date,
      pair_title: d.pair_title,
      pair_time: d.pair_time,
      pair_no: d.pair_no,               // хранить можно, но next_pair его игнорит
      pair_teacher: d.pair_teacher || null,
      pair_type: d.pair_type || null,
    };

    if (Number(d.next_pair || 0) === 1) {
      const next = await findNextPairForDraft(d);
      if (next) finalPair = next;
    }

    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });

    const info = db.prepare(`
      INSERT INTO homework (
        target_type, target_id, target_title,
        pair_date, pair_title, pair_time, pair_no, pair_teacher, pair_type,
        created_by_telegram_user_id,
        only_for_user_id, next_pair,
        text, deadline_date, files_json,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      sel.target_type,
      sel.target_id,
      sel.target_title,

      finalPair.pair_date,
      finalPair.pair_title,
      finalPair.pair_time,
      finalPair.pair_no,
      finalPair.pair_teacher,
      finalPair.pair_type,

      userId,
      d.only_for_user_id ?? null,
      Number(d.next_pair || 0),

      text,
      d.deadline_date ?? null,
      d.files_json ?? '[]',

      now
    );

    db.prepare(`DELETE FROM homework_drafts WHERE id = ? AND telegram_user_id = ?`)
      .run(Number(draft_id), userId);

    return res.json({ ok: true, homework_id: Number(info.lastInsertRowid) });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
  }
});

// ===== HW edit endpoints =====

// обновить задание
app.post('/api/hw/update', (req, res) => {
  try {
    const { initData, homework_id, text, deadline_date } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!homework_id) return res.status(400).json({ ok: false, error: 'homework_id required' });

    const userId = getUserIdFromInitData(initData);
    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });

    const hw = db.prepare(`
      SELECT id, target_type, target_id
      FROM homework
      WHERE id = ?
    `).get(Number(homework_id));

    if (!hw) return res.status(404).json({ ok: false, error: 'Homework not found' });

    // редактировать можно только в рамках текущего выбора (группа/препод)
    if (hw.target_type !== sel.target_type || Number(hw.target_id) !== Number(sel.target_id)) {
      return res.status(403).json({ ok: false, error: 'Forbidden' });
    }

    const newText = String(text || '').trim();
    if (!newText) return res.status(400).json({ ok: false, error: 'Текст задания пустой' });

    db.prepare(`
      UPDATE homework
      SET text = ?, deadline_date = ?
      WHERE id = ?
    `).run(
      newText,
      deadline_date === null ? null : (deadline_date ? String(deadline_date) : null),
      Number(homework_id)
    );

    return res.json({ ok: true });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

// удалить задание
app.post('/api/hw/delete', (req, res) => {
  try {
    const { initData, homework_id } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!homework_id) return res.status(400).json({ ok: false, error: 'homework_id required' });

    const userId = getUserIdFromInitData(initData);
    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });

    const hw = db.prepare(`
      SELECT id, target_type, target_id
      FROM homework
      WHERE id = ?
    `).get(Number(homework_id));

    if (!hw) return res.status(404).json({ ok: false, error: 'Homework not found' });

    if (hw.target_type !== sel.target_type || Number(hw.target_id) !== Number(sel.target_id)) {
      return res.status(403).json({ ok: false, error: 'Forbidden' });
    }

    db.prepare(`DELETE FROM homework WHERE id = ?`).run(Number(homework_id));
    return res.json({ ok: true });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
  }
});

function ruDowFull(d) {
  return ["воскресенье","понедельник","вторник","среду","четверг","пятницу","субботу"][d.getDay()];
}
function ruDowTitle(d) {
  return ["воскресенье","понедельник","вторник","среда","четверг","пятница","суббота"][d.getDay()];
}
function dateToYMDdot(dt) {
  const y = dt.getFullYear();
  const m = String(dt.getMonth()+1).padStart(2,'0');
  const d = String(dt.getDate()).padStart(2,'0');
  return `${y}.${m}.${d}`;
}
function parseStartMinutes(range) {
  // ожидаем "HH:MM - HH:MM" или "HH:MM-HH:MM"
  const m = String(range||"").match(/(\d{2}):(\d{2})/);
  if (!m) return 1e9;
  return Number(m[1])*60 + Number(m[2]);
}
function emojiNum(n) {
  const map = ["0️⃣","1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"];
  if (n >= 0 && n <= 10) return map[n];
  return `${n}️⃣`;
}
function diffMinutes(aMin, bMin) {
  return Math.max(0, bMin - aMin);
}

function formatBotLikeSchedule({ groupTitle, targetDate, items }) {
  // items уже нормализованы fa_bridge.py (type, pair_no, teacher, room, time)
  const dt = new Date(targetDate.replace(/\./g,'-')); // YYYY-MM-DD
  // костыль: date "YYYY.MM.DD" -> норм Date
  const [Y,M,D] = targetDate.split('.').map(Number);
  const d = new Date(Y, (M||1)-1, D||1);

  const header = `Расписание ${groupTitle} на ${ruDowTitle(d)} (${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}):`;

  if (!Array.isArray(items) || items.length === 0) {
    return `${header}\n\nПар не найдено.`;
  }

  // сортировка по началу
  const sorted = [...items].sort((a,b)=>parseStartMinutes(a.time)-parseStartMinutes(b.time));

  const out = [header, ""];
  for (let i=0;i<sorted.length;i++){
    const p = sorted[i];
    const no = p.pair_no || (i+1);
    const line1 = `${emojiNum(no)} ${String(p.time||"").replace(/\s*-\s*/,'-')}. ${p.teacher||"—"} — ${p.room||"—"}.`;
    const line2 = `${p.title||"—"} (${(p.type||"").replace(/ПАРА/i,"") || "Занятие"}).`.replace(/\s+\(\)\./, ".");
    out.push(line1);
    out.push(line2);

    // перерыв до следующей пары
    if (i < sorted.length - 1) {
      const curStart = parseStartMinutes(p.time);
      // берём конец текущей пары
      const m2 = String(p.time||"").match(/(\d{2}):(\d{2}).*?(\d{2}):(\d{2})/);
      const curEnd = m2 ? (Number(m2[3])*60 + Number(m2[4])) : curStart;
      const nextStart = parseStartMinutes(sorted[i+1].time);
      const br = diffMinutes(curEnd, nextStart);
      if (br >= 20) out.push(`Перерыв ${br} минут.`);
      out.push("");
    }
  }
  return out.join("\n").trim();
}

const NOTIFY_TZ = process.env.NOTIFY_TZ || "Europe/Moscow";

function nowPartsInTZ() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: NOTIFY_TZ,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false
  }).formatToParts(new Date());

  const get = (t) => parts.find(p => p.type === t)?.value;
  return {
    yyyy: get("year"),
    mm: get("month"),
    dd: get("day"),
    hh: get("hour"),
    mi: get("minute")
  };
}

function addDaysStr(ymdDot, add) {
  const [Y, M, D] = ymdDot.split('.').map(Number);
  const dt = new Date(Y, (M || 1) - 1, D || 1);
  dt.setDate(dt.getDate() + add);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, '0');
  const d = String(dt.getDate()).padStart(2, '0');
  return `${y}.${m}.${d}`;
}

function weekdayKeyForYmdDot(ymdDot) {
  const [Y, M, D] = String(ymdDot).split('.').map(Number);
  // берём полдень UTC, чтобы не словить DST-край
  const dt = new Date(Date.UTC(Y, (M || 1) - 1, D || 1, 12, 0, 0));
  const w = new Intl.DateTimeFormat("en-US", { timeZone: NOTIFY_TZ, weekday: "short" }).format(dt);
  const map = { Mon:"mon", Tue:"tue", Wed:"wed", Thu:"thu", Fri:"fri", Sat:"sat", Sun:"sun" };
  return map[w] || null;
}

async function notifyTick() {
  const p = nowPartsInTZ();
  const hhmm = `${p.hh}:${p.mi}`;

  const rows = db.prepare(`
    SELECT telegram_user_id, group_id, group_title, times_json, days_json, rules_json, weekdays_json
    FROM notify_settings
    WHERE enabled = 1
  `).all();

  for (const r of rows) {
    let times = [];
    let days = [];
    try { times = JSON.parse(r.times_json || "[]"); } catch {}
    try { days  = JSON.parse(r.days_json  || "[]"); } catch {}
    
    const hasRulesField = r.rules_json !== null && r.rules_json !== undefined && String(r.rules_json).trim() !== "";
    
    let rules = null;
    if (hasRulesField) {
      try {
        rules = JSON.parse(r.rules_json);
        if (!Array.isArray(rules)) rules = [];
      } catch {
        // ❗ если rules_json битый — считаем что правил нет, но legacy НЕ используем
        rules = [];
      }
    } else {
      // старые записи: конвертируем times/days -> rules
      rules = buildRulesFromLegacy(times, days);
    }
    
    // weekdays
    let weekdays = null;
    try { weekdays = r.weekdays_json ? JSON.parse(r.weekdays_json) : null; } catch { weekdays = null; }
    if (!Array.isArray(weekdays) || weekdays.length === 0) weekdays = ["mon","tue","wed","thu","fri","sat"];
    
    // ✅ ТЕПЕРЬ ВСЕГДА работаем через rules (даже если rules = [])
    for (const rule of rules) {
      const hhmmRule = String(rule?.time || "");
      const dayType = String(rule?.day || "");
    
      if (hhmmRule !== hhmm) continue;
      if (dayType !== "today" && dayType !== "tomorrow") continue;
    
      const todayYMD = `${p.yyyy}.${p.mm}.${p.dd}`;
      const target = dayType === "today" ? todayYMD : addDaysStr(todayYMD, 1);
    
      const sent = db.prepare(`
        SELECT 1 FROM notify_log
        WHERE telegram_user_id=? AND group_id=? AND day_type=? AND schedule_date=? AND hhmm=?
      `).get(r.telegram_user_id, r.group_id, String(dayType), target, hhmmRule);
      if (sent) continue;
    
      const wKey = weekdayKeyForYmdDot(target);
      if (wKey && !weekdays.includes(wKey)) continue;
    
      try {
        const py = await runPython('timetable_group', [Number(r.group_id), target, target]);
    
        const text = formatBotLikeSchedule({
          groupTitle: r.group_title,
          targetDate: target,
          items: py.items || []
        });
    
        await tgSendMessageToUser({ userId: r.telegram_user_id, text });
    
        db.prepare(`
          INSERT INTO notify_log (telegram_user_id, group_id, day_type, schedule_date, hhmm, sent_at)
          VALUES (?, ?, ?, ?, ?, ?)
        `).run(r.telegram_user_id, r.group_id, String(dayType), target, hhmmRule, Date.now());
    
        db.prepare(`
          UPDATE notify_settings
          SET last_error_at=NULL, last_error_text=NULL
          WHERE telegram_user_id=? AND group_id=?
        `).run(r.telegram_user_id, r.group_id);
    
      } catch (e) {
        const msg = String(e?.message || e);
        db.prepare(`
          UPDATE notify_settings
          SET last_error_at=?, last_error_text=?
          WHERE telegram_user_id=? AND group_id=?
        `).run(Date.now(), msg.slice(0, 400), r.telegram_user_id, r.group_id);
      }
    }
    
    // ✅ ВАЖНО: legacy блок ниже больше не нужен вообще
    continue;
  }
}

setInterval(() => { notifyTick().catch(()=>{}); }, 20000);

app.listen(8000, () => {
  console.log('Backend listening on http://localhost:8000');
});
