import 'dotenv/config';
import express from 'express';
import { validate } from '@tma.js/init-data-node';
import Database from 'better-sqlite3';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const app = express();
app.use(express.json());

// -------- helpers --------
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function requireToken() {
  const token = process.env.BOT_TOKEN;
  if (!token) throw new Error('BOT_TOKEN not set');
  return token;
}

function getUserIdFromInitData(initData) {
  const token = requireToken();
  validate(initData, token);
  const params = new URLSearchParams(initData);
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

app.listen(8000, () => {
  console.log('Backend listening on http://localhost:8000');
});