# Инструкция по деплою и обновлению бота

## Коротко

- Продовый запуск делается через `docker-compose.prod.yml`.
- На сервере нужно сохранять четыре вещи: код проекта, `.env`, папку `secrets/` и папку `data/`.
- При старте контейнер сам выполняет `alembic upgrade head`.
- `scripts/seed.py` нельзя запускать на каждом релизе: он перезаписывает часть данных в БД.
- Бота нужно держать в одном экземпляре: здесь `long polling` и встроенный scheduler.

## Как устроен прод

В проде контейнер получает:

- `.env` с токенами и настройками
- `./secrets:/app/secrets:ro` с Google JSON-ключами
- `./data:/app/data` с SQLite-базой `data/bot.db`

Это значит:

- код можно обновлять отдельно
- `.env`, `secrets/` и `data/` нельзя затирать обычной заливкой кода
- после рестарта данные не теряются, потому что они лежат на хосте, а не внутри контейнера

## Что важно помнить до первого деплоя

- Примеры ниже рассчитаны на Linux-сервер и путь `/opt/angel-nail-bot`.
- Этот проект работает через `long polling`, а не через webhook.
- Для работы не нужны `Nginx`, домен и открытые `80/443`.
- Серверу нужны только SSH-доступ для вас, исходящий доступ в интернет, Docker и Docker Compose.

## Первый запуск на сервере

### 1. Подготовить папку проекта

На сервере:

```bash
mkdir -p /opt/angel-nail-bot
mkdir -p /opt/angel-nail-bot/data
mkdir -p /opt/angel-nail-bot/secrets
```

### 2. Залить код без секретов и базы

С локальной машины:

```bash
rsync -av \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude 'data' \
  --exclude 'secrets' \
  --exclude '.env' \
  /Users/mark/Angel-nail-bot/ \
  root@<SERVER_IP>:/opt/angel-nail-bot/
```

### 3. Создать `.env` на сервере

На сервере:

```bash
cd /opt/angel-nail-bot
cp .env.example .env
```

После этого заполнить `.env` минимум такими значениями:

```env
BOT_TOKEN=
ADMIN_TG_IDS=12345678
TZ=Europe/Moscow
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db
```

Если используются Google Calendar / Sheets / Drive, нужно также заполнить:

- `GCAL_ENABLED`
- `GCAL_CALENDAR_ID`
- `GCAL_CREDENTIALS_PATH`
- `GOOGLE_SERVICE_ACCOUNT_PATH`
- `GOOGLE_OAUTH_CLIENT_PATH`
- `GOOGLE_OAUTH_TOKEN_PATH`
- `GSHEETS_SPREADSHEET_ID`
- `GDRIVE_FOLDER_ID`

### 4. Положить секреты на сервер

В папке `/opt/angel-nail-bot/secrets/` должны лежать нужные JSON-файлы:

- `google_service_account.json`
- `google_oauth_client.json`
- `google_oauth_token.json`
- `gcal_service_account.json`, если включён Google Calendar

Рекомендуемые права:

```bash
chmod 600 /opt/angel-nail-bot/.env
chmod 600 /opt/angel-nail-bot/secrets/*.json
```

### 5. Инициализировать базу и стартовые данные

Первый запуск на пустой базе:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml build bot
docker compose -f docker-compose.prod.yml run --rm bot python scripts/seed.py
docker compose -f docker-compose.prod.yml up -d bot
```

Что здесь происходит:

- `build` собирает образ
- `run --rm bot python scripts/seed.py` поднимает одноразовый контейнер, автоматически применяет миграции и затем заполняет стартовые данные
- `up -d bot` запускает постоянный контейнер

### 6. Проверить, что бот поднялся

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml logs -f bot
```

Нормальные признаки:

- нет ошибок `BOT_TOKEN is not configured`
- нет ошибок Alembic
- бот уходит в polling без падений

## Безопасный порядок обновления

### 1. Локально проверить код

Перед заливкой желательно прогнать хотя бы:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

### 2. Сделать бэкап перед важным релизом

Особенно важно перед:

- изменениями БД
- изменениями логики записи и расписания
- изменениями интеграций Google

Самый простой безопасный вариант для SQLite:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml stop bot
mkdir -p backups
cp data/bot.db backups/bot.db.$(date +%F-%H%M%S)
cp .env backups/.env.$(date +%F-%H%M%S)
docker compose -f docker-compose.prod.yml up -d bot
```

Если менялись Google-ключи, отдельно сохраните и папку `secrets/`.

### 3. Залить обновлённый код

Обычный апдейт:

```bash
rsync -av \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude 'data' \
  --exclude 'secrets' \
  --exclude '.env' \
  /Users/mark/Angel-nail-bot/ \
  root@<SERVER_IP>:/opt/angel-nail-bot/
```

Если директория на сервере хранит только код этого проекта и в ней нет ручных файлов, можно использовать более строгий вариант, чтобы не накапливались удалённые из проекта файлы:

```bash
rsync -av --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude 'data' \
  --exclude 'secrets' \
  --exclude '.env' \
  /Users/mark/Angel-nail-bot/ \
  root@<SERVER_IP>:/opt/angel-nail-bot/
```

### 4. Пересобрать и перезапустить контейнер

На сервере:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml logs -f bot
```

Этого достаточно для большинства релизов:

- новые зависимости попадут в образ
- миграции применятся автоматически
- контейнер перезапустится с новым кодом

## Когда достаточно просто перезапуска

Если код не менялся, а нужно только перезапустить процесс:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml restart bot
docker compose -f docker-compose.prod.yml logs -f bot
```

## Когда нужен `force-recreate`

Если меняли `.env`, лучше не ограничиваться `restart`, а пересоздать контейнер:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml up -d --force-recreate bot
docker compose -f docker-compose.prod.yml logs -f bot
```

Это важно, потому что `env_file` подхватывается при создании контейнера, а не всегда при обычном `restart`.

## Когда запускать `seed.py`

`scripts/seed.py` нужно запускать только в таких случаях:

- первый запуск проекта на пустой БД
- осознанное восстановление стартовых значений
- контролируемый сброс тестового стенда

### Почему нельзя гонять `seed.py` на каждом деплое

Скрипт делает `upsert` и обновляет:

- стандартные услуги
- шаблоны текстов
- runtime-настройки

В этом проекте часть этих данных редактируется через админку и хранится в `data/bot.db`. Повторный `seed.py` может затереть изменения, уже сделанные на проде.

## Что нельзя затирать при деплое

Обычный релиз не должен копировать на сервер:

- `data/`
- `secrets/`
- `.env`

Почему это важно:

- в `data/bot.db` лежат записи клиентов, настройки, шаблоны и другие runtime-данные
- в `secrets/` лежат доступы к Google
- в `.env` лежит `BOT_TOKEN` и продовые параметры

## Что особенно важно учитывать

- Держите только один экземпляр бота. Если поднять два контейнера с одним `BOT_TOKEN`, можно получить конфликты polling и двойной запуск scheduler jobs.
- После каждого релиза смотрите логи хотя бы 2-5 минут.
- Перед миграциями всегда делайте бэкап `data/bot.db`.
- Не храните бэкапы внутри папки, которую потом синхронизируете `rsync --delete`.
- Если меняли только Python-код, используйте `up --build -d`, а не ручной запуск контейнера.
- Если меняли `.env`, делайте `force-recreate`.
- Если меняли JSON-ключи в `secrets/`, после замены перезапустите контейнер.

## Полезные команды после деплоя

Проверить статус:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml ps
```

Посмотреть последние логи:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml logs --tail=200 bot
```

Проверить Google Calendar:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml exec bot python scripts/calendar_smoke_test.py
```

Проверить Google Sheets / Drive:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml exec bot python scripts/check_google_access.py
```

## Если нужно откатиться

Минимально безопасный сценарий:

1. Остановить контейнер.
2. Вернуть предыдущую рабочую версию кода.
3. При необходимости восстановить `data/bot.db` из бэкапа.
4. Поднять контейнер заново и проверить логи.

Команды:

```bash
cd /opt/angel-nail-bot
docker compose -f docker-compose.prod.yml stop bot
cp backups/<BACKUP_FILE> data/bot.db
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml logs -f bot
```

Если миграция уже изменила структуру БД, откат без бэкапа может быть сложным. Поэтому бэкап перед релизом с миграциями обязателен.
