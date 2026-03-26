# FINdz

FINdz это единый проект для студентов Финансового университета, который состоит из двух частей:

- Telegram-бота на Python;
- Telegram Mini App на React + Node.js.

Обе части работают с расписанием, домашними заданиями, избранными группами и уведомлениями. После объединения веток в репозитории сохранены и серверная логика бота, и более развитый `webapp`.

## Что умеет проект

### Telegram-бот

Бот запускается из `main.py` и умеет:

- проверять подписку на обязательный Telegram-канал;
- показывать расписание групп;
- показывать расписание преподавателей;
- хранить избранные группы в `favorites.json`;
- отправлять уведомления по расписанию через `JobQueue`;
- показывать и добавлять домашние задания;
- подтверждать корпоративную почту `@edu.fa.ru`;
- проверять подключённые почтовые ящики по IMAP и присылать уведомления о новых письмах.

### Telegram Mini App

Mini App находится в папке `webapp/` и уже умеет:

- валидировать `initData` Telegram Mini App;
- проверять подписку на канал;
- искать группу или преподавателя;
- сохранять текущий выбор пользователя;
- хранить историю последних выборов;
- показывать расписание на выбранную дату;
- работать с избранными группами;
- настраивать уведомления по времени и дням недели;
- создавать, редактировать и удалять домашние задания;
- прикреплять файлы к домашним заданиям;
- отправлять файлы в чат через Bot API;
- хранить данные в SQLite.

## Структура репозитория

```text
.
├─ main.py
├─ schedule.py
├─ schedule_groups.py
├─ teachers_schedule.py
├─ homework.py
├─ mail_check.py
├─ settings.py
├─ favorites.json
├─ webapp/
│  ├─ src/
│  ├─ public/
│  ├─ vite.config.js
│  └─ backend/
│     ├─ server.js
│     ├─ fa_bridge.py
│     └─ fa_bridge.sh
└─ README.md
```

## Технологии

### Python-часть

Основные библиотеки:

- `python-telegram-bot`
- `fa_api`
- `gspread`
- `oauth2client`

Также используются стандартные модули Python: `sqlite3`, `imaplib`, `smtplib`, `json`, `asyncio`, `logging`.

### Frontend

- React
- Vite
- ESLint

### Backend Mini App

- Node.js
- Express
- better-sqlite3
- multer
- `@tma.js/init-data-node`

## Какие данные и файлы используются

### Обязательные локальные файлы для Telegram-бота

Рядом с `main.py` должны быть подготовлены:

- `token.txt` — токен Telegram-бота;
- `required_chanel_link.txt` — ссылка на обязательный канал;
- `required_chaned_id.txt` — username или id канала для `get_chat_member`;
- `password_mail.txt` — пароль почты `finashkadzbot@gmail.com`;
- `finashkadzbot-d8415e20cc18.json` — сервисный Google JSON для резервного копирования ДЗ.

### Файлы, создаваемые во время работы

- `favorites.json` — избранные группы и настройки уведомлений бота;
- `mail_accounts.json` — подключённые почтовые аккаунты пользователей;
- `data/homework.db` — база домашних заданий бота;
- `webapp/backend/miniapp.sqlite` — база данных Mini App.

### Игнорируемые runtime-артефакты Mini App

В `webapp` не должны попадать в git:

- `webapp/backend/.cache/`
- `webapp/backend/uploads/`
- `*.sqlite-wal`
- `*.sqlite-shm`

## Запуск Telegram-бота

### 1. Подготовьте Python-окружение

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install python-telegram-bot gspread oauth2client fa_api
```

Если `fa_api` ставится нестандартно, убедитесь, что он доступен в том же окружении, из которого запускается бот.

### 2. Подготовьте секреты

Создайте файлы:

- `token.txt`
- `required_chanel_link.txt`
- `required_chaned_id.txt`
- `password_mail.txt`
- `finashkadzbot-d8415e20cc18.json`

### 3. Запустите бота

```powershell
python main.py
```

Бот работает через polling.

## Запуск Mini App

Mini App состоит из двух процессов: frontend и backend.

### 1. Frontend

```powershell
cd webapp
npm install
npm run dev
```

По умолчанию Vite поднимется на `http://localhost:5173`.

В `vite.config.js` уже настроен proxy:

- `/api` -> `http://localhost:8000`

### 2. Backend

Создайте файл `webapp/backend/.env`:

```env
REQUIRED_CHANNEL=@your_channel
NOTIFY_TZ=Europe/Moscow
```

Токен Telegram backend теперь берёт из корневого `token.txt`.
Опционально можно переопределить путь через `TOKEN_FILE`.

Установите зависимости и запустите backend:

```powershell
cd webapp\backend
npm install
node server.js
```

Backend слушает `http://localhost:8000`.

## Запуск в одном Docker-контейнере

В репозитории добавлены:

- `Dockerfile` — один контейнер для bot + Mini App backend;
- `docker-compose.yml` — один сервис `findz`;
- `.env.example` — единый пример переменных окружения.

Что делает контейнер:

- собирает frontend `webapp` в `dist`;
- поднимает Node.js backend;
- одновременно запускает Telegram-бота на Python;
- хранит runtime-данные в `/app/data`.

### Быстрый старт через Docker Compose

1. Скопируйте `.env.example` в `.env`.
2. Убедитесь, что в корне проекта есть `token.txt` с токеном Telegram-бота.
3. Заполните обязательные переменные:

- `REQUIRED_CHANNEL`
- `REQUIRED_CHANNEL_LINK`
- `REQUIRED_CHANNEL_ID`

4. При необходимости заполните дополнительные переменные:

- `MAIL_PASSWORD`
- `GOOGLE_CREDS_JSON_B64`
- `NOTIFY_TZ`
- `ENABLE_BOT`
- `ENABLE_WEBAPP`
- `FA_TIMEOUT_SEC`

5. Запустите:

```powershell
docker compose up -d --build
```

Если `ENABLE_WEBAPP=1`, в `.env` должен быть заполнен `REQUIRED_CHANNEL`.
Если `ENABLE_BOT=1`, в `.env` должны быть заполнены `REQUIRED_CHANNEL_LINK` и `REQUIRED_CHANNEL_ID`.

После старта:

- Mini App backend и собранный frontend будут доступны на `http://localhost:8000`;
- Telegram-бот будет запущен в этом же контейнере;
- данные будут сохраняться в docker volume `findz_data`.

### Полезные переменные контейнера

- `PORT=8000` — порт backend внутри контейнера;
- `ENABLE_BOT=1` — запускать бота;
- `ENABLE_WEBAPP=1` — запускать backend Mini App;
- `NOTIFY_TZ=Europe/Moscow` — таймзона уведомлений;
- `FA_PY=/usr/bin/python3` — Python для `fa_bridge.sh`;
- `FA_TIMEOUT_SEC=8` — таймаут вызовов `fa_api`.

### Что означает каждая переменная из `.env`

- `REQUIRED_CHANNEL` — канал для проверки подписки в backend Mini App через `getChatMember`.
- `REQUIRED_CHANNEL_LINK` — ссылка на канал, которую бот показывает пользователю.
- `REQUIRED_CHANNEL_ID` — username или id канала, который бот использует для проверки подписки.
- `MAIL_PASSWORD` — пароль приложения для почты `finashkadzbot@gmail.com`.
- `GOOGLE_CREDS_JSON_B64` — base64-представление файла `finashkadzbot-d8415e20cc18.json`; entrypoint внутри контейнера восстановит из него JSON-файл.
- `ENABLE_BOT` — если `0`, контейнер поднимет только Mini App backend.
- `ENABLE_WEBAPP` — если `0`, контейнер поднимет только Telegram-бота.
- `NOTIFY_TZ` — таймзона для уведомлений backend Mini App.
- `FA_PY` — путь к Python, который должен использовать `fa_bridge.sh`.
- `FA_TIMEOUT_SEC` — лимит времени на вызовы `fa_api`.

### Где теперь хранится токен Telegram

Во всех основных сценариях токен хранится в корневом файле `token.txt`.

Это относится к:

- Telegram-боту на Python;
- backend Mini App;
- Docker-контейнеру.

Для Docker `docker-compose.yml` монтирует:

```yaml
./token.txt:/app/token.txt:ro
```

### Как передать Google credentials в Docker

Если нужен backup в Google Sheets, закодируйте JSON-файл в base64 и положите строку в `GOOGLE_CREDS_JSON_B64`.

Пример для PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("finashkadzbot-d8415e20cc18.json"))
```

## Важная особенность backend

`webapp/backend/server.js` вызывает Python через `sh` и `fa_bridge.sh`.

Это означает:

- в системе должен быть доступен POSIX-совместимый `sh`;
- для Windows вне Docker обычно нужен Git Bash, MSYS2 или WSL;
- backend должен уметь найти Python-интерпретатор с установленным `fa_api`.

`fa_bridge.sh` ищет Python:

- через переменную окружения `FA_PY`;
- в `.venv` и `venv` текущей папки и родительских каталогов;
- затем через системные `python3` и `python`.

Если хотите задать интерпретатор явно:

```sh
export FA_PY=/abs/path/to/python
```

Дополнительно поддерживается:

- `FA_TIMEOUT_SEC` — таймаут запросов к `fa_api`;
- `NOTIFY_TZ` — таймзона уведомлений Mini App backend.

## Основные API Mini App

В `webapp/backend/server.js` есть маршруты для:

- аутентификации и проверки подписки;
- текущего выбора пользователя и истории выбора;
- избранных групп;
- настроек уведомлений;
- поиска групп и преподавателей;
- получения расписания на день;
- создания draft домашнего задания;
- загрузки и удаления файлов;
- публикации, редактирования и удаления ДЗ.

## Основные сценарии использования

### Расписание

- выбрать группу или преподавателя;
- посмотреть пары на нужную дату;
- переключаться между днями;
- сохранять группы в избранное;
- получать уведомления по расписанию.

### Домашние задания

- добавить ДЗ к паре;
- задать дедлайн;
- приложить файл;
- редактировать и удалять существующие задания;
- хранить черновики перед публикацией.

### Уведомления

- выбрать несколько времён отправки;
- выбрать режим "на сегодня" или "на завтра";
- выбрать дни недели;
- отключить уведомления для группы.

## Ограничения и замечания

- В репозитории пока нет общего `requirements.txt` для Python-части.
- Имена файлов `required_chanel_link.txt` и `required_chaned_id.txt` содержат опечатки, но в коде используются именно они.
- В репозитории остаётся `main-backup.py`, это резервная копия, а не основной entrypoint.
- Для работы Mini App backend нужен доступ к Bot API Telegram и рабочее окружение с `sh` + Python + `fa_api`.
- Для локального запуска Telegram Mini App внутри Telegram обычно нужен внешний HTTPS-домен или туннель.

## Рекомендуемый порядок локального запуска

1. Запустить backend Mini App на `8000`.
2. Запустить frontend Vite в `webapp`.
3. Убедиться, что Python-окружение содержит `fa_api`.
4. Отдельно, если нужен бот, запустить `python main.py`.

## Текущее состояние

Это уже не два разрозненных прототипа, а один общий репозиторий:

- в корне лежит рабочий Telegram-бот;
- в `webapp/` лежит более развитый интерфейс Mini App;
- обе части используют одну предметную область: расписание, избранное, ДЗ и уведомления.

Если нужен следующий шаг, логично:

- собрать `requirements.txt`;
- добавить инструкции по деплою;
- унифицировать хранение данных между ботом и Mini App.

## Production Domain

Mini App и backend теперь ориентированы на домен:

- `https://finunischedule.allspace.com.ru`

Что уже подготовлено в репозитории:

- в [`webapp/vite.config.js`](./webapp/vite.config.js) добавлен `allowedHosts` для `finunischedule.allspace.com.ru`;
- в [`docker-compose.yml`](./docker-compose.yml) контейнер слушает только `127.0.0.1:8000`, чтобы наружу его отдавал reverse proxy;
- в [`deploy/nginx/finunischedule.allspace.com.ru.conf`](./deploy/nginx/finunischedule.allspace.com.ru.conf) лежит готовый Nginx-конфиг для домена.

Рекомендуемая прод-схема:

1. Запустить проект через Docker Compose на сервере.
2. Подключить Nginx на `finunischedule.allspace.com.ru`.
3. Проксировать HTTPS-трафик на `127.0.0.1:8000`.
4. В `@BotFather` указать Mini App URL:
   `https://finunischedule.allspace.com.ru`

На сервере важно:

- DNS домена должен указывать на сервер;
- сертификат TLS должен быть выпущен для `finunischedule.allspace.com.ru`;
- порт `8000` не должен публиковаться наружу напрямую, только через Nginx.
