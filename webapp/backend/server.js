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

function getUserIdFromInitData(initData) {
  const token = requireToken();

  const init = String(initData ?? '').trim();
  if (!init) throw new Error('initData missing or empty');

  // validate() иногда кидает "The string did not match the expected pattern."
  // если строка не того формата/пустая/с мусором.
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
    const script = path.join(__dirname, 'fa_bridge.py');
    const pythonPath = path.join(__dirname, '.venv', 'bin', 'python');

    const py = spawn(pythonPath, [script, cmd, ...args.map(String)], { stdio: ['ignore', 'pipe', 'pipe'] });

    let out = '';
    let err = '';

    py.stdout.on('data', (d) => (out += d.toString('utf-8')));
    py.stderr.on('data', (d) => (err += d.toString('utf-8')));

    py.on('close', (code) => {
      if (code !== 0) return reject(new Error(err || `python exit code ${code}`));
      try {
        const json = JSON.parse(out);
        if (!json.ok) return reject(new Error(json.error || 'python error'));
        resolve(json);
      } catch (e) {
        reject(new Error(`bad python json: ${String(e)}`));
      }
    });
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


// -------- existing endpoints --------
app.get('/api/ping', (req, res) => {
  res.json({ ok: true, ts: Date.now() });
});

app.post('/api/auth/telegram', (req, res) => {
  try {
    const { initData } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    requireToken();
    validate(initData, process.env.BOT_TOKEN);
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
      const abs = path.join(UPLOAD_ROOT, String(removed.rel_path));
      safeUnlink(abs);
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
          AND (pair_time IS NULL OR pair_time = ?)
          AND (pair_no  IS NULL OR pair_no  = ?)
        ORDER BY created_at DESC
      `).all(
        sel.target_type,
        sel.target_id,
        String(date),
        String(p.title || ''),
        p.time ? String(p.time) : null,
        p.pair_no != null ? Number(p.pair_no) : null
      );
    
      return { ...p, homeworks: hws };
    });
    
    return res.json({
      ok: true,
      items,
      count: Number(py.count || 0),
    });

  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e?.message || e) });
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
    const { initData, pair_date, pair_title, pair_time, pair_no } = req.body || {};
    if (!initData) return res.status(400).json({ ok: false, error: 'initData missing' });
    if (!pair_date || !pair_title) return res.status(400).json({ ok: false, error: 'pair_date/pair_title required' });

    const userId = getUserIdFromInitData(initData);
    const sel = getSelectionForUser(userId);
    if (!sel) return res.status(404).json({ ok: false, error: 'No selection' });

    const now = Date.now();

    const info = db.prepare(`
      INSERT INTO homework_drafts (
        telegram_user_id, target_type, target_id, target_title,
        pair_date, pair_title, pair_time, pair_no,
        text, deadline_date, files_json,
        created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', NULL, '[]', ?, ?)
    `).run(
      userId,
      sel.target_type, sel.target_id, sel.target_title,
      String(pair_date), String(pair_title),
      pair_time ? String(pair_time) : null,
      pair_no != null ? Number(pair_no) : null,
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
    const { initData, draft_id, text, deadline_date } = req.body || {};
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

// Подтвердить (перенос draft -> homework)
app.post('/api/hw/draft/submit', (req, res) => {
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

    const info = db.prepare(`
      INSERT INTO homework (
        target_type, target_id, target_title,
        pair_date, pair_title, pair_time, pair_no,
        created_by_telegram_user_id,
        text, deadline_date, files_json,
        created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      d.target_type, d.target_id, d.target_title,
      d.pair_date, d.pair_title, d.pair_time, d.pair_no,
      userId,
      text,
      d.deadline_date,
      d.files_json || '[]',
      now
    );

    db.prepare(`DELETE FROM homework_drafts WHERE id = ? AND telegram_user_id = ?`)
      .run(Number(draft_id), userId);

    return res.json({ ok: true, homework_id: Number(info.lastInsertRowid) });
  } catch (e) {
    return res.status(401).json({ ok: false, error: String(e?.message || e) });
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

app.listen(8000, () => {
  console.log('Backend listening on http://localhost:8000');
});