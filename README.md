# ANGELS NAIL SPACE Bot

Telegram-бот для студии ANGELS NAIL SPACE: запись, перенос и отмена визитов, админское расписание, approval-запросы, напоминания и синхронизация с Google Calendar.

## Что умеет MVP

- клиентское меню с витриной, услугами, адресом, портфолио и связью с мастером
- онбординг клиента: имя, телефон, заметка
- запись на свободные слоты с аддонами и референсами
- `Мои записи`: просмотр, перенос, отмена с причиной
- approval-флоу для нестандартного времени и свободных вопросов
- прокси-чат между Ангелой и клиенткой
- админские разделы: расписание, услуги, клиенты, статистика, рассылка, шаблоны, настройки
- Google Calendar lifecycle: create, patch, delete, pull-sync внешних блокировок
- фоновые jobs: 24h/2h reminders, `mark_completed`, post-visit, repeat-prompt, `gcal_pull`

## Требования

- Python `3.11+`
- SQLite для локального запуска
- Telegram bot token
- при включённом Google Calendar: service-account JSON с доступом к календарю

## Быстрый старт

1. Скопируй `.env.example` в `.env`.
2. Заполни обязательные переменные:
   - `BOT_TOKEN`
   - `ADMIN_TG_IDS`
   - `DATABASE_URL` при необходимости
3. Создай виртуальное окружение и установи зависимости:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

4. Примени миграции:

```bash
alembic upgrade head
```

5. Залей стартовые данные:

```bash
python scripts/seed.py
```

6. Запусти бота:

```bash
python -m src.main
```

## Переменные окружения

Минимальный набор:

```env
BOT_TOKEN=
ADMIN_TG_IDS=12345678
TZ=Europe/Moscow
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db
```

Google Calendar:

```env
GCAL_ENABLED=true
GCAL_CALENDAR_ID=
GCAL_CREDENTIALS_PATH=./secrets/gcal_service_account.json
```

Google Sheets / Drive:

```env
GOOGLE_SERVICE_ACCOUNT_PATH=./secrets/google_service_account.json
GOOGLE_OAUTH_CLIENT_PATH=./secrets/google_oauth_client.json
GOOGLE_OAUTH_TOKEN_PATH=./secrets/google_oauth_token.json
GSHEETS_SPREADSHEET_ID=
GDRIVE_FOLDER_ID=
```

Фичи:

```env
FEATURE_REPEAT_PROMPT=true
FEATURE_POSTVISIT_FEEDBACK=true
FEATURE_REMINDER_2H=true
```

## Настройка Google Calendar

Используется service-account.

1. Создай service account в Google Cloud.
2. Включи Google Calendar API.
3. Скачай JSON-ключ и положи его в `secrets/gcal_service_account.json`.
4. Возьми email service account из JSON.
5. Расшарь календарь Ангелы на этот email с правом редактирования событий.
6. Укажи `GCAL_ENABLED=true` и `GCAL_CALENDAR_ID` в `.env`.

После этого бот сможет:

- создавать события при подтверждении записи
- обновлять их при переносе
- удалять их при отмене
- каждые 15 минут подтягивать внешние busy-события и блокировать соответствующие слоты

## Smoke-checks

Проверка Google Calendar:

```bash
.venv/bin/python scripts/calendar_smoke_test.py
```

Проверка Google Sheets / Drive:

```bash
.venv/bin/python scripts/check_google_access.py
```

Проверка из Telegram:

- `/google_test`
- `/calendar_test`
- `/save_photo`

Эти команды доступны только админу.

## Тесты

Полный прогон:

```bash
.venv/bin/python -m pytest
```

Ключевые группы тестов:

- `tests/test_schedule_parser.py`
- `tests/test_booking_flow.py`
- `tests/test_approvals.py`
- `tests/test_reminders.py`
- `tests/test_admin_phase7.py`
- `tests/test_calendar_pull.py`
- `tests/test_phase9_acceptance.py`
- `tests/test_anti_abuse.py`
- `tests/test_admin_all_bookings.py`
- `tests/test_client_booking_price_intro.py`
- `tests/test_post_booking_cta.py`

Линт и форматирование:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

## Docker

Production автоматически разворачивается Railway из подключённой ветки GitHub.
Актуальная инструкция: [docs/railway_deploy.md](docs/railway_deploy.md).

Локальный запуск:

```bash
docker compose up --build
```

Теперь контейнер сам делает `alembic upgrade head` через `entrypoint.sh`, поэтому отдельный ручной шаг для миграций внутри контейнера не нужен.

Если хочешь подготовить БД и сиды через Docker, удобный порядок такой:

```bash
docker compose run --rm bot python scripts/seed.py
docker compose up --build
```

`seed.py` рассчитан в первую очередь на первый запуск пустой БД. На проде его не стоит гонять на каждом обновлении: он обновляет стартовые услуги, шаблоны и runtime-настройки в базе.

Для Railway обязательно:

- подключить persistent volume к `/app/data`;
- задать `DATABASE_URL=sqlite+aiosqlite:////app/data/bot.db`;
- хранить токены и Google credentials только в Railway Variables;
- держать один экземпляр сервиса из-за long polling и встроенного scheduler;
- включить резервные копии volume.

Railway использует корневой `Dockerfile`. При старте `entrypoint.sh` применяет миграции
и заполняет seed-данные только на действительно новой базе. Код дополнительно
проверяет, что SQLite находится внутри Railway volume, поэтому ошибочная конфигурация
не сможет незаметно создать временную production-базу.

## Структура проекта

- `src/bot/` — handlers, keyboards, middlewares, texts, states
- `src/db/` — модели, session factory, repositories
- `src/services/` — бизнес-логика, reminders, approvals, calendar sync
- `scripts/` — сиды и smoke-checks
- `alembic/` — миграции
- `tests/` — unit и acceptance-style тесты

## Ручная приёмка MVP

Перед релизом полезно руками пройти:

- клиентский `/start`, онбординг и happy-path записи
- `Мои записи`: перенос и отмена
- approval на нестандартное время
- вопрос Ангеле и прокси-чат
- админские `Расписание`, `Услуги`, `Клиенты`, `Рассылка`, `Шаблоны`, `Настройки`
- `send_due_reminders`, `postvisit`, `repeat_prompt`
- create/update/delete события в Google Calendar
- pull-sync внешней блокировки из календаря

## Ручная приёмка Phase 11

Клиентский аккаунт:

- `/start` → запись показывает прайс-картинку перед выбором услуги.
- Happy-path записи завершается CTA-кнопками `Мои записи` и `В меню`.
- В автодополнении команд клиента нет админских команд: `/admin`, `/schedule`, `/requests`, `/clients`.

Аккаунт Ангелы:

- Открыть каждый админ-раздел и убедиться, что на экранах есть понятная кнопка назад.
- В `🎨 Фоны` проверить фоны расписания, прайса, карточки клиента и записей: загрузить тестовый фон, посмотреть превью, сбросить.
- В `📅 Расписание` перенести свободный/заблокированный слот и проверить, что занятое время не принимается.
- Открыть `📅 На месяц` и проверить пагинацию.
- Открыть `📋 Все записи`, проверить 14-дневные страницы, toggle отменённых и отправку картинки.
- В `🙈 Режиме клиента` записаться, вернуться в админку и открыть карточку клиентки без ошибки `Не нашла эту клиентку`.
- Проверить anti-abuse на тестовой клиентке: no-show добавляет риск, ручное подтверждение можно снять из карточки клиента.

## Полезные команды

```bash
alembic upgrade head
python scripts/seed.py
python -m src.main
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python scripts/calendar_smoke_test.py
docker compose up --build
docker compose -f docker-compose.prod.yml up --build -d
```
