# Phase 11 — UX-полировка и баг-фиксы после beta-теста

## Статус реализации на 23.04.2026

Codex уже прошёл по блокам D, B, G, F, A, H, C — в коде это:

- `src/services/anti_abuse.py`, `anti_abuse_alerts.py`, миграция `0004_anti_abuse_fields.py`
  — блок G закрыт (rate_limit_events, strikes, shadow-ban, requires_manual_approval,
  reschedules_count; `attempt_booking_with_anti_abuse` и `attempt_reschedule_with_anti_abuse`
  подключены в `booking_flow.py` и `my_bookings.py`).
- `src/services/image_theme.py`, `price_image.py`, `bookings_image.py`,
  `schedule_image.py`, `client_card_image.py`, `src/bot/handlers/admin/backgrounds.py` —
  блок F закрыт (общее ядро, мульти-слот фоны, прайс-картинка).
- `src/bot/handlers/admin/all_bookings.py` — блок H закрыт (пагинация 14 дней,
  toggle отменённых, картинка периода).
- Блок A (перенос слота + календарь месяца) — в `admin/schedule.py`.
- Блок D (карточка админа-в-режиме-клиента) — в `admin/clients.py`, тест в
  `tests/test_admin_clients.py::test_open_card_for_admin_in_client_mode`.
- Блок C — прайс перед выбором услуги и post-booking CTA уже в `booking_flow.py`.

**Допущенные отклонения от ТЗ, принятые как эквивалент:**

- Вместо единого роутера `src/bot/handlers/admin/navigation.py` Codex сделал
  параметризованные `back_callback` в хендлерах (см. `admin/clients.py` и подобное).
  Функционально — то же самое: «⬅️ Назад» ведёт на родительский экран. Переделывать
  **не надо**, проверь только полноту покрытия по таблице из B1.
- В `src/bot/keyboards/admin.py` и `keyboards/client.py` уже используется
  `ButtonStyle.PRIMARY/SUCCESS/DANGER` из `aiogram.enums` — т.е. часть блока I2
  (цветные кнопки Bot API 9.4) уже стоит. В `pyproject.toml` бамп до
  `aiogram>=3.26.0,<4.0` сделан.

**Остался блок I полностью** — картинки на большинстве экранов, сверка `ButtonStyle`
по таблице I2, применение новых текстов из `PHASE11_TEXTS.md`. И блок E
(тесты/линт/ручная верификация) в конце.

**Критичные мелочи, которые НЕ забыть при следующем заходе:**

- Docstring `build_client_main_menu` в `keyboards/client.py` обновлён — новое описание
  ссылается на Bot API 9.4; убедись, что в других клавиатурах нет остатков старых
  docstring'ов «Bot API has no color field».
- Пройтись по `src/bot/keyboards/**/*.py` и допроставить `style=ButtonStyle.DANGER`
  на все «⬅️ Назад», «❌ Отмена», «🗑 Удалить», «🔕 Shadow-ban», «🚫 Заблокировать»,
  и `style=ButtonStyle.SUCCESS` на все «✅ Всё верно», «✅ Подтвердить», «Готово» —
  сейчас это не везде.
- Применить новые тексты из `PHASE11_TEXTS.md` (см. блок I4) — это основная работа
  следующего захода, там ~80 констант.
- Прогнать `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy src`.

---

## Контекст

Бот ANGELS NAIL SPACE (`aiogram 3.x`, `SQLAlchemy 2.x async`, `Pillow`, `pydantic-settings`,
`Alembic`). Phase 9 (MVP) и Phase 10 (картинка-расписание как альтернатива инлайн day-picker)
уже в main. Марк прогнал бота руками в режиме админа и в «🙈 Режиме клиента», прислал список
замечаний. Эта фаза закрывает эти замечания.

Техстек и инварианты, которые нельзя нарушать:
- aiogram 3 FSM c `StatesGroup`, payload через `state.update_data`/`get_data`.
- Все I/O в БД идут через репозитории (`src/db/repositories/*`), **без прямых запросов** в хендлерах.
- Таймзоны: `tz_name` берётся из runtime-настройки, не из `settings.tz` напрямую. Для UTC→local
  используем `src/services/booking.format_local_datetime`.
- Новые миграции — только `alembic revision --autogenerate`, затем ручной ревью.
- Каждая новая ветка логики закрыта unit-тестом. `pytest` обязан быть зелёным.
- Локальная проверка линта перед коммитом: `ruff check .`, `ruff format --check .`, `mypy src` (как в CI).

## Что уже сделано и это не надо трогать

- `src/bot/commands.py` уже настраивает scope-команды по ролям: `CLIENT_COMMANDS` через
  `BotCommandScopeAllPrivateChats`, `ADMIN_COMMANDS` через `BotCommandScopeChat` для каждого
  из `settings.admin_tg_ids`. То есть клиент физически не видит `/admin`, `/schedule` и т.п.
  в автодополнении команд. **Пункт B3 из обсуждения — уже работает**, нужна только проверка
  тестом, см. ниже.
- `src/services/client_card_image.py` уже рендерит «дарк»-карточку клиента — её мы
  используем как референс визуального стиля в блоке F.
- `src/services/schedule_image.py` (Phase 10) — админ-загрузка фона + hybrid-источник текста
  уже работают. В блоке F этот файл расширится до единого визуального ядра.

## Порядок выполнения

Делай строго по порядку, не перескакивай — последующие блоки опираются на предыдущие.

1. **Блок D** — критический баг (карточка клиента).
2. **Блок B** — навигация «Назад» по админке + покрытие scope-команд тестом.
3. **Блок G** — anti-abuse: rate-limits, cooldown, strikes, shadow-ban, approval-gated booking/reschedule.
4. **Блок F** — общее визуальное ядро `image_theme.py`, плюс миграция `schedule_image` и
   `client_card_image` на него, плюс новый `price_image`.
5. **Блок A** — редактирование слотов + календарь на месяц.
6. **Блок H** — админский просмотр всех записей (текст + картинка).
7. **Блок C** — клиентский флоу (прайс перед выбором услуги, CTA после записи, цвет кнопки).
8. **Блок I** — визуальная полировка: Bot API 9.4 `style` (красные/зелёные/синие кнопки),
   картинки на большинстве экранов, новый текстовый стиль из `PHASE11_TEXTS.md`.
9. **Блок E** — тесты + линт + ручная верификация.

Каждый блок закоммичен отдельно, сообщение коммита: `feat(phase11): <блок>: <короткое описание>`
или `fix(phase11): …` для D.

Phase 12 (геймификация) — отдельный раздел в конце документа, **в этой фазе не делаем**,
только фиксируем идеи.

---

## Блок D — баг: «Не нашла эту клиентку» после записи админа в режиме клиента

### Репро

1. `/admin` → «🙈 Режим клиента».
2. Пройти стандартный клиентский booking flow до «Записала тебя 🪄».
3. Вернуться в админку (`/admin`).
4. В чате приходит уведомление «NEW Новая запись … Открыть карточку клиентки».
5. Нажать «👀 Открыть карточку клиентки».
6. Бот отвечает: `Не нашла эту клиентку.` — воспроизводится стабильно.

### Задача

- `src/bot/handlers/admin/clients.py` — найти callback-хендлер на `admin_clients:open:<user_id>`.
  Посмотреть, через какой репозиторий идёт поиск клиента. Скорее всего, репозиторий фильтрует
  по `is_admin=False` или по `role != admin`, и «админ в режиме клиента» пролетает.
- `src/db/repositories/users.py` (или аналогичный) — тот метод, что вызывается из
  карточного хендлера. Разрешить находить любого `User`, включая `is_admin=True`.
- Если найдутся отдельные «user-card» и «admin-card» репо — открывать всех как обычную
  клиентку, но в тексте карточки (рендерер `client_card_image.py` и/или текстовый заголовок)
  пометить «👑 Админ в режиме клиента», если у пользователя выставлен флаг админа.

### Тест

`tests/test_admin_clients_open.py`:
- `test_open_card_for_admin_in_client_mode` — создаём `User(is_admin=True)`, который сделал
  `Booking`, зовём хендлер/репо — карточка возвращается, а не «не нашла».
- `test_open_card_for_normal_client` — регрессионный, что обычные клиенты открываются.

### Критерий готовности

Шаги репро выше больше не воспроизводят баг. Тесты зелёные.

---

## Блок B — двухуровневая навигация + покрытие scope-команд

### B1. Кнопки «⬅️ Назад» во всех подменю

**Правило навигации:**
- В любом подменю админки (глубже, чем главное админ-меню) должна быть кнопка
  `⬅️ Назад` — переход на один уровень выше.
- На уровнях глубже двух — также `🏠 Главное меню` рядом, чтобы не ломиться через три экрана.
- Кнопки — inline (`InlineKeyboardButton`), отдельной строкой в конце клавиатуры.

**Единый callback-протокол:**
- `admin_nav:back:<context>` — один уровень вверх (context идентифицирует, куда именно).
- `admin_nav:home` — в главное админ-меню.

Реализация: один общий роутер `src/bot/handlers/admin/navigation.py` с хендлерами на
`admin_nav:back:*` и `admin_nav:home`. В каждом подменю добавляем свой `back:<context>`.

**Разделы, где ДОЛЖНЫ быть кнопки (пройтись и добавить, если нет):**

| Раздел (файл)                          | Что добавить                                    |
| -------------------------------------- | ----------------------------------------------- |
| `admin/services_crud.py` (список услуг) | `⬅️ Назад` в админ-меню                         |
| `admin/services_crud.py` (карточка/edit)| `⬅️ Назад` к списку услуг + `🏠 Главное меню`   |
| `admin/templates_edit.py` (корень)      | `⬅️ Назад` в админ-меню                         |
| `admin/templates_edit.py` (подкатегория)| `⬅️ Назад` к корню шаблонов + `🏠 Главное меню` |
| `admin/settings_edit.py`                | `⬅️ Назад` в админ-меню                         |
| `admin/clients.py` (поиск и карточка)   | `⬅️ Назад` в админ-меню; в карточке — тоже     |
| `admin/broadcast.py`                    | `⬅️ Назад` в админ-меню                         |
| `admin/stats.py`                        | `⬅️ Назад` в админ-меню                         |
| `admin/schedule.py` (после «На неделю», после «Календарь месяца») | `⬅️ Назад` к меню расписания |
| `admin/schedule_image_edit.py`          | `⬅️ Назад` к меню расписания                    |

Кнопки главного админ-меню (reply-клавиатура `build_admin_main_menu`) **не трогаем** — это
корень, там «назад» не нужно.

### B2. Покрытие scope-команд тестом

`tests/test_bot_commands.py`:
- `test_register_bot_commands_sets_client_scope` — мокаем `Bot.set_my_commands`, проверяем
  что для `BotCommandScopeAllPrivateChats` отправляется `CLIENT_COMMANDS`.
- `test_register_bot_commands_sets_admin_scope` — для каждого `admin_tg_id` отправляется
  `ADMIN_COMMANDS` через `BotCommandScopeChat(chat_id=admin_tg_id)`.

### Критерий готовности

- Нажатие «Назад» на любом экране админки возвращает на предыдущий уровень, а не прыгает
  в корень.
- `tests/test_bot_commands.py` зелёный.
- Ручная проверка на втором Telegram-аккаунте (клиентом): команда `/admin` в автодополнении
  НЕ показывается.

---

## Блок G — защита от злоупотреблений и soft-UX

### Цель

Три профиля пользователя — честная невнимательная, ненадёжный, целенаправленный вредитель.
Для каждого — своя реакция, при этом клиент **никогда не видит формулировок про правила**:
нет «давно/недавно», «за 2.5 недели», «rate-limit», «strikes». Только нейтральные сообщения
вида «Отправила Ангеле на подтверждение, напишу как ответит 🤍». Все числовые пороги —
в `Settings`, editable из админки.

### G1. Миграция БД

`alembic revision --autogenerate -m "phase11_g_rate_limit_and_reputation"`:

- Новая таблица `rate_limit_events`:
  - `id` PK
  - `user_id` FK→users(id)
  - `kind` TEXT NOT NULL (`"proxy_message"`, `"ask_master"`, `"booking_attempt"`, `"cancel"`, `"late_cancel"`, `"no_show"`)
  - `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
  - `metadata` JSONB NULLABLE
  - INDEX `(user_id, kind, created_at DESC)` — для окна-выборок.
- Новые поля на `users`:
  - `is_shadow_banned BOOLEAN NOT NULL DEFAULT false`
  - `strikes INTEGER NOT NULL DEFAULT 0`
  - `requires_manual_approval BOOLEAN NOT NULL DEFAULT false`
  - `duplicate_phone_flag BOOLEAN NOT NULL DEFAULT false`
- Добавить в enum `ApprovalRequestKind` значения: `FREQUENT_BOOKING`, `LATE_RESCHEDULE`,
  `MANUAL_APPROVAL_REQUIRED`. Если enum — Python-enum на ORM-стороне, отразить в миграции
  через `ALTER TYPE ... ADD VALUE`.

### G2. Settings (admin-editable)

Расширить `src/services/admin_defaults.py::editable_setting_definitions`:

| Ключ                            | Тип  | Дефолт | Смысл                                           |
| ------------------------------- | ---- | ------ | ----------------------------------------------- |
| min_days_between_bookings       | int  | 17     | Интервал между записями клиента (дней)          |
| reschedule_min_hours_before     | int  | 48     | Минимум часов до целевого времени при переносе  |
| max_reschedules_per_booking     | int  | 2      | Сколько раз можно перенести одну запись         |
| cancel_cooldown_minutes         | int  | 30     | Пауза после отмены                              |
| late_cancel_hours               | int  | 4      | Окно «поздней отмены»                           |
| late_cancel_strike_limit        | int  | 3      | Strike-порог для requires_manual_approval       |
| no_show_strike_limit            | int  | 2      | 2 = flag, дальше — ручное решение               |
| proxy_messages_per_hour         | int  | 5      | Rate-limit proxy-chat                           |
| ask_master_per_day              | int  | 3      | Rate-limit ask-master                           |
| max_pending_approvals_per_user  | int  | 5      | Сколько approval-requests может висеть у юзера  |

Чтение — через `get_int_setting` (добавить по аналогии с `get_bool_setting`, если нет).

### G3. Бизнес-логика

#### Создание новой записи (client confirm)

Место: финальный хендлер подтверждения booking в `src/bot/handlers/client/booking_flow.py`.

Перед сохранением — проверки **строго в этом порядке**:

1. **Shadow-ban.** Если `user.is_shadow_banned == True`: ответить клиенту
   «Записала тебя 🪄» (стандартное confirmation-сообщение, как обычно), **ничего не создаём
   в БД**, notification админу — не шлём. Возвращаемся в меню. Клиент верит, что всё ок.
2. **Cancel cooldown.** Если у юзера есть `RateLimitEvent(kind="cancel")` за последние
   `cancel_cooldown_minutes` минут: клиенту «Давай чуть позже попробуем 🤍» и вернуть в
   шаг выбора. Без упоминания причины.
3. **Требование ручного approval** (flag `requires_manual_approval=True`):
   создать `ApprovalRequest(kind=MANUAL_APPROVAL_REQUIRED, payload=<desired booking>)`
   вместо прямой записи.
4. **Лимит pending approvals.** Если у юзера уже >= `max_pending_approvals_per_user`
   approval-requests в статусе pending: клиенту «У тебя уже есть ожидающие запросы,
   дождись, пожалуйста, ответа Ангелы 🤍». Новый approval НЕ создаём.
5. **Частотный лимит.** Считаем «последний релевантный визит»:
   - самая поздняя `Booking` у юзера со статусом `CONFIRMED`/`COMPLETED` И
   - самая ранняя будущая `Booking` у юзера в статусе `CONFIRMED`.

   Если **любая** из них укладывается в окно `±min_days_between_bookings` дней от
   целевой даты новой записи → создать `ApprovalRequest(kind=FREQUENT_BOOKING,
   payload=<desired booking>)` вместо прямой записи. Клиенту:
   **«Отправила Ангеле на подтверждение, напишу как ответит 🤍»** — без объяснений.
6. **Иначе** — стандартный прямой booking, как сейчас.

Все отказы/перенаправления пишутся в `RateLimitEvent(kind="booking_attempt",
metadata={"outcome": "shadow_banned"/"cooldown"/"manual_approval"/"frequent_booking"/…})` —
для видимости админу (блок G4) и отладки.

#### Перенос существующей записи

Место: хендлер переноса в `src/bot/handlers/client/my_bookings.py` (или где flow идёт).

1. **Shadow-ban** — тот же silent-noop.
2. Если `target_datetime - now() < reschedule_min_hours_before`: создать
   `ApprovalRequest(kind=LATE_RESCHEDULE, payload={booking_id, new_start_at})`. Клиенту —
   нейтральное сообщение «отправила Ангеле на подтверждение».
3. Если `booking.reschedules_count >= max_reschedules_per_booking`: то же, через approval,
   metadata `{reason: "too_many_reschedules"}`.
4. Иначе — стандартный перенос. По факту переноса: `booking.reschedules_count += 1`.

(Поле `reschedules_count` у `Booking` — добавить в миграцию G1.)

#### Отмена

Место: хендлер cancel в `src/bot/handlers/client/my_bookings.py`.

1. При отмене всегда пишем `RateLimitEvent(kind="cancel",
   metadata={"hours_before": <часов до визита>})`.
2. Если `hours_before < late_cancel_hours` → `user.strikes += 1`,
   `RateLimitEvent(kind="late_cancel")`. Если `strikes >= late_cancel_strike_limit`:
   выставить `requires_manual_approval=True`.
3. Пишем `RateLimitEvent(kind="cancel")` с `created_at=now()` — используется для cancel-cooldown.
4. Клиенту — стандартное «Отменила запись 🤍», никаких намёков на штрафы.
5. В «Мои записи» есть отмена — если до визита `< late_cancel_hours`, добавляем
   **предупреждающий шаг** (confirmation): «Осталось меньше N часов. Ангела может не успеть
   заполнить окошко. Точно отменить?». Это не штраф, просто дать шанс передумать.

#### No-show

Место: админская карточка booking в `admin/schedule.py` или новом файле.

- Добавить кнопку «⚠️ Не пришла» на админской карточке booked/прошедшего слота.
- По нажатию: `booking.status = NO_SHOW`, `user.strikes += 2`,
  `RateLimitEvent(kind="no_show")`. Если `strikes >= no_show_strike_limit * 2`:
  выставить `requires_manual_approval=True` и pushнуть админу «Клиент X: накопилось no-show,
  рассмотрите блокировку».

#### Rate-limit на proxy-chat и ask-master

- Перед пересылкой в админский чат считать `COUNT(*) FROM rate_limit_events
  WHERE user_id=? AND kind=? AND created_at > now() - <window>`.
- Если превышено:
  - Клиенту ответить, как обычно: «Передам Ангеле 🤍» — **не давать понять**, что лимит.
  - Сообщение в админский чат **НЕ пересылается**.
  - Пишем `RateLimitEvent(kind="<same>", metadata={"blocked": true})`.
  - Шлём админу агрегированный алерт (см. G4).
- Событие `RateLimitEvent` пишем в обоих случаях (и при пропуске, и при блоке).

#### Телефонный дубль при онбординге

- В `Onboarding.input_phone` после валидации номера — `UserRepository.find_by_phone(phone)`.
- Если найдено другого `User` с этим телефоном → `current_user.duplicate_phone_flag=True`.
- Не блокируем онбординг, не пишем клиенту. Админ увидит в карточке (G4).

### G4. Админский UX anti-abuse

- В карточке клиента (`admin/clients.py` + `client_card_image.py` если бейдж нужен на картинке):
  - Поля: `strikes`, `requires_manual_approval`, `is_shadow_banned`, `duplicate_phone_flag`.
  - Кнопки в `build_admin_client_card_keyboard`:
    - `🔕 Shadow-ban` / `🔔 Снять shadow-ban` (toggle)
    - `♻️ Сбросить strikes` (confirmation перед применением)
    - `🔓 Снять requires_manual_approval`
  - Если `duplicate_phone_flag=True` — рядом с телефоном подпись
    `📞 Совпадает с @<other_username>` и кнопка «Открыть того пользователя».
- Алерт о rate-limit нарушениях: **агрегированный**, не на каждое событие. Фоновая джоба
  (или в on-demand, раз в 60 минут при любом админском действии) — если за последний час
  >= 3 разных юзеров превысили rate-limit, push в админский чат: «🚨 За последний час
  rate-limit превысили: @u1 (N), @u2 (M), @u3 (K). [Открыть карточку] [Блок]».
  Без спама: один алерт в час.

### G5. Тесты

`tests/test_anti_abuse.py` — обязательные сценарии:

- `test_frequent_booking_triggers_approval_not_direct_confirm` — booking в пределах
  `min_days_between_bookings` от существующей.
- `test_booking_outside_window_confirms_directly`.
- `test_late_reschedule_creates_approval_request`.
- `test_reschedule_outside_window_direct`.
- `test_reschedule_count_limit_triggers_approval`.
- `test_cancel_cooldown_blocks_new_booking` — попытка записи через 5 минут после отмены.
- `test_late_cancel_increments_strikes`.
- `test_strike_limit_sets_requires_manual_approval`.
- `test_no_show_increments_strikes_double`.
- `test_shadow_banned_user_booking_is_silent_noop` — ответ клиенту тот же, что в обычном
  success-кейсе; в БД ничего нет; админу не приходит notification.
- `test_proxy_message_rate_limit_blocks_silently` — клиент видит success, админ не получает.
- `test_ask_master_daily_limit`.
- `test_duplicate_phone_sets_flag_without_blocking_onboarding`.
- `test_client_never_sees_rule_wording` — pytest-парсер всех текстов ответов клиенту в
  этих сценариях: проверяем, что нет слов «давно», «недавно», «17 дней», «2.5 недели»,
  «rate-limit», «strike», «лимит», «ограничение». Только нейтральные формулировки.

### G6. Критерий готовности блока G

- Миграция прокачалась на чистой БД и на копии prod-данных.
- Все 14 тестов зелёные.
- Ручная проверка в Telegram:
  - запись #1, попытка записи #2 на ту же неделю → клиент видит «отправила Ангеле на подтверждение»,
    Ангела видит approval;
  - late-reschedule → то же;
  - shadow-ban тестового аккаунта → записи «уходят в пустоту», Ангела ничего не видит;
  - 3 late-cancel подряд → четвёртая запись идёт через approval.
- Клиент ни в одном сценарии не слышит про правила.

---

## Блок F — общий визуальный стиль для картинок

### Цель

Три картинки (расписание, прайс, карточка клиента) сейчас живут каждая в своём файле и
визуально немного разные. Свести их к единому тёмно-элегантному стилю (как «КАРТОЧКА» клиента:
тёмный фон с мягкими размытыми «орбами», сериф, «звёздочки»-акценты) и дать админу возможность
менять фон у каждой из трёх картинок отдельно.

### F1. Новое общее ядро `src/services/image_theme.py`

Экспортирует:

```python
IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1350

PALETTE_DARK = {
    "bg_top": (24, 20, 28),
    "bg_bottom": (42, 32, 48),
    "text_primary": (245, 238, 252),
    "text_soft": (210, 195, 230),
    "accent": (214, 176, 245),
}

FONT_CANDIDATES_SERIF = [...]  # как сейчас в schedule_image
FONT_CANDIDATES_BODY = [...]

def load_theme_background(custom_path: Path | None) -> Image.Image: ...
    """Либо пользовательский фон (cover-fit + subtle dark wash), либо
    синтезированный dark-gradient с blurred soft orbs."""

def draw_soft_orbs(image: Image.Image, *, count: int = 6, seed: int = 0) -> None: ...
    """Добавляет мягкие размытые светлые пятна (как на «КАРТОЧКА»)."""

def draw_header_serif(draw, text, *, y, theme, max_width) -> tuple[int, int]:
    """Центрированный серифный заголовок с auto-shrink (перенос _fit_font из schedule_image)."""

def draw_footer_brand(draw, text, *, y_bottom_offset, theme) -> None: ...
```

Стиль должен совпадать с текущим дизайном «КАРТОЧКА клиента» по:
- тёмному фону + размытым световым акцентам,
- сериф-шрифту заголовка (тот же DejaVu Serif Bold, тот же auto-shrink),
- footer «ANGELS NAIL SPACE» малыми серыми капиталями.

### F2. Миграция `schedule_image.py` на `image_theme`

- Убрать локальные `PALETTE`-константы, `_synthesize_default_background`,
  `_load_font`, `_fit_font`, `_text_size` — они переезжают в `image_theme`.
- `load_background()` становится обёрткой вокруг `image_theme.load_theme_background(path)`.
- Рендер заголовка и футера — через `draw_header_serif` / `draw_footer_brand`.
- Перекрасить тело (day-rows) под тёмную палитру: `text_primary` для даты, `text_soft` для
  времени. Убедиться, что кириллические глифы сохраняют читаемость.
- Существующие тесты `tests/test_schedule_image.py` (если ещё нет — создать в блоке E) должны
  продолжать пройти: hybrid source (auto/override), валидный PNG, fallback при отсутствии фона.

### F3. Миграция `client_card_image.py` на `image_theme`

- По аналогии перевести на общее ядро. Поведение (layout, шаблон карточки) не меняем — только
  источник палитры/шрифтов/фона.
- Если в `client_card_image.py` был свой путь к фоновому файлу — сменить его на слот из
  нового background-хранилища (см. F5).

### F4. Новый файл `src/services/price_image.py`

Отвечает за рендер картинки прайс-листа.

```python
async def build_price_image_bytes(db_session: AsyncSession) -> bytes:
    """Рендерит картинку услуги+цены из Service-таблицы + текста-оверрайда."""
```

Структура картинки:
- Header (сериф): `«УСЛУГИ И ЦЕНЫ»` или кастомный, если есть template `price_image_header`.
- Блок base-услуг: `название — цена`.
- Разделительная линия (accent).
- Блок addon-услуг: `название — цена` мельче.
- Блок «Важно» (сноска): template `price_image_note`.
- Footer: «ANGELS NAIL SPACE».

Hybrid-источник текста (как в `schedule_image`):
- По умолчанию тянем услуги из БД через `ServiceRepository.list_for_admin()`.
- Если в template `price_image_text_override` есть непустой контент — рендерим как есть
  построчно.

### F5. Унификация загрузки фонов

Переиспользовать текущий `save_custom_background` / `reset_custom_background` /
`CURRENT_BACKGROUND_PATH` из `schedule_image.py`, **расширив их** до мультислота:

```python
BACKGROUND_KINDS = {"schedule", "price", "client_card"}

def background_path(kind: str) -> Path: ...
def save_custom_background(kind: str, content: bytes) -> Path: ...
def reset_custom_background(kind: str) -> bool: ...
```

Каталог: `assets/backgrounds/<kind>/current.jpg` (перенести существующий
`assets/schedule_backgrounds/current.jpg` → `assets/backgrounds/schedule/current.jpg`,
если такой файл реально есть у юзера; не стирать содержимое, если он там есть).

`Dockerfile` уже копирует `assets` целиком — менять не требуется.

### F6. Админский UI «🎨 Фоны»

В главном админ-меню добавить кнопку `🎨 Фоны` (рядом с «📝 Шаблоны» / «⚙️ Настройки»).

Подменю:
```
🎨 Фоны

Выбери, какой фон редактируем:
[🗓 Фон расписания]
[💰 Фон прайса]
[👤 Фон карточки клиента]
[⬅️ Назад в админ-меню]
```

Для каждого из трёх — стандартный подфлоу (переиспользуем код из Phase 10):
- текст с пояснением + inline-кнопки: `📤 Загрузить новый`, `🔄 Сбросить к стандартному`,
  `👁 Предпросмотр`, `⬅️ Назад`.
- FSM `AdminBackgroundUpload { kind, await_photo }` — при входе хранит `kind` в state-data,
  при получении фото зовёт `save_custom_background(kind, photo_bytes)`.

Существующий `AdminScheduleImage.await_background` из Phase 10 — заменяется на новый общий
`AdminBackgroundUpload`, старую запись в `states.py` можно удалить, если она больше нигде
не используется.

### F7. Критерии готовности блока F

- Три картинки визуально соответствуют стилю текущей «КАРТОЧКА клиента» (тёмный фон, мягкие
  орбы, сериф-заголовок, футер с брендом).
- Админ из одного места может сменить/сбросить фон любой из трёх картинок.
- Unit-тесты: `tests/test_image_theme.py` (загрузка фона, fallback-гра­диент), обновлённые
  `tests/test_schedule_image.py`, новые `tests/test_price_image.py`.
- Ручная проверка: сгенерировать все три картинки и открыть визуально — выглядят как семья.

---

## Блок A — расписание (админ)

### A1. Редактирование слотов (перенос)

- `src/bot/keyboards/admin.py`, `build_week_slot_keyboard`: для статусов `FREE` и `BLOCKED`
  добавить в первую строку кнопку `✏️ Перенести` → callback
  `admin_schedule:move:<slot_id>`. Для `BOOKED` — **не добавлять** (в этой фазе не трогаем
  записанные слоты).
- `src/bot/states.py`: новая группа

  ```python
  class AdminScheduleMove(StatesGroup):
      input_text = State()
  ```
- `src/bot/handlers/admin/schedule.py`:
  - Callback `admin_schedule:move:*` → выставляет state, сохраняет `slot_id` в
    `state_data`, просит прислать новое время одним сообщением в формате `ДД.ММ HH:MM`.
  - Сообщение в state: парсим через `src/services/schedule_parser.parse_schedule`
    (одна строка) + конверт в UTC через `parsed_slot_to_utc`.
  - Проверяем, что в БД нет слота на это время (`SlotRepository.get_by_start_at`
    или аналог — если нет, написать метод в репо). Если занято — ответить ошибкой
    «Это время уже в расписании. Пришли другое.» и оставаться в state.
  - Если свободно — `SlotRepository.update_start_at(slot, new_start_at_utc)` или
    эквивалент (написать, если нет). Закоммитить. Ответить `✅ Перенесла.` и показать
    обновлённую клавиатуру слота.
- `tests/test_admin_schedule_move.py`:
  - `test_move_free_slot_to_free_time_succeeds`,
  - `test_move_blocked_slot_to_free_time_succeeds`,
  - `test_move_rejects_collision_with_existing_slot`,
  - `test_move_for_booked_slot_is_not_offered` (проверка, что кнопки нет в клавиатуре).

### A2. Календарь на месяц с пагинацией

- Callback `admin_schedule:month` сейчас — placeholder. Реализовать:
  - Читаем слоты на 30 дней вперёд (`SlotRepository.list_for_next_days(tz_name=tz, days=30)`).
  - Группируем по локальному дню (используем существующую `group_slots_by_local_day` из
    `src/services/booking.py` — она уже сортирует хронологически).
  - Выводим страницу по 10 дней (`PAGE_SIZE = 10`). Если дней меньше 10 — одна страница.
  - Формат строки дня: `«DD.MM — 🟢 HH:MM, 🔴 HH:MM, ⚫️ HH:MM»` (иконки — те же, что в
    `render_week_slot_text`). Пустые дни в выводе пропускаем (не печатаем).
  - Под сообщением — inline-кнопки пагинации: `← Назад` (если не первая страница),
    `Дальше →` (если есть следующая), и `⬅️ К меню расписания`.
  - Callback: `admin_schedule:month:page:<offset>` — offset в днях (0, 10, 20).
- Константы текстов — в `src/bot/texts.py`: `ADMIN_SCHEDULE_MONTH_HEADER_TEXT`,
  `ADMIN_SCHEDULE_MONTH_EMPTY_TEXT`.
- Тесты: `tests/test_admin_schedule_month.py`:
  - `test_month_renders_days_with_slots_only`,
  - `test_month_paginates_correctly`,
  - `test_month_empty_message_when_no_slots`.

### Критерий готовности блока A

- Админ может перенести FREE/BLOCKED слот, BOOKED не предлагается.
- Календарь на месяц отображается с пагинацией, коллизии при переносе отлавливаются.
- Тесты зелёные.

---

## Блок H — админский просмотр всех записей

### Цель

Сейчас у админа нет единого экрана со всеми предстоящими записями — только «На неделю» в
разделе расписания, где записи и свободные слоты вперемешку. Нужен отдельный раздел,
который показывает именно записи (booked), с группировкой по дню, с возможностью скинуть
всё одной картинкой (для пересылки Ангелой себе в заметки / в сторис).

### H1. Текстовый вид со страницами по 14 дней

- В главном админ-меню (`build_admin_main_menu` в `src/bot/keyboards/admin.py`) добавить
  кнопку `📋 Все записи` рядом с `📅 Расписание` и `📨 Запросы`.
- Хендлер `admin/all_bookings.py` (новый файл), роутер подключить в `src/bot/handlers/admin/__init__.py`.
- Callback/текст на кнопку `📋 Все записи` → показать первую страницу (14 дней вперёд от «сегодня» в локальном TZ).
- Репозиторий `BookingRepository.list_for_range(start_utc, end_utc, *, include_cancelled: bool)`
  — вернуть booking-и с join-ом на `Slot`, `Service`, `User`; фильтр по статусам: по умолчанию
  `CONFIRMED`+`COMPLETED`+`NO_SHOW`, при `include_cancelled=True` добавить `CANCELLED_BY_CLIENT`/
  `CANCELLED_BY_ADMIN`. Если метода нет — написать. Сортировка по `start_at ASC`.
- Формат вывода (text):
  ```
  📋 Все записи · стр. 1/N
  Период: 22.04 – 05.05

  🗓 22.04, ср
    • 10:00 — Анна @anna_k — Маникюр комбинированный, 2500₽
    • 14:30 — Катя @kate_m — Педикюр, 3000₽

  🗓 23.04, чт
    • 11:00 — Лена @lena_v — Маникюр + покрытие, 2800₽

  …
  ```
  Дни без записей — пропускаем (не печатаем). Если на странице вообще пусто — «За этот
  период записей нет 🤍».
- Каждая строка `• HH:MM — …` — кликабельная (inline-кнопка поверх сообщения невозможна для
  длинного списка; поэтому под текстом выводим inline-клавиатуру с кнопками «HH:MM DD.MM»
  по каждой записи этой страницы — callback `admin_bookings:open:<booking_id>` → открывает
  карточку клиентки/слота через существующий флоу из блока D).
- Под списком — строка пагинации + toggle:
  - `← 14 дней назад` (только если есть что показать назад)
  - `14 дней вперёд →` (только если есть записи дальше)
  - `👁 Показать отменённые` / `🙈 Скрыть отменённые` (toggle, состояние хранится в state-data
    текущего админа, не в БД).
  - `🖼 Скинуть картинкой` — см. H2.
  - `⬅️ Назад` в главное админ-меню.
- Callback-протокол:
  - `admin_bookings:page:<offset_days>:<show_cancelled:0|1>`
  - `admin_bookings:toggle_cancelled:<offset_days>`
  - `admin_bookings:image:<offset_days>:<show_cancelled:0|1>`
  - `admin_bookings:open:<booking_id>`

### H2. Картинка на ту же страницу

- Новый файл `src/services/bookings_image.py`:
  ```python
  async def build_bookings_image_bytes(
      db_session: AsyncSession,
      *,
      start_local_date: date,
      end_local_date: date,
      tz_name: str,
      include_cancelled: bool,
  ) -> bytes: ...
  ```
- Использует `image_theme.py` (блок F) — тёмный фон, серифный заголовок, футер «ANGELS NAIL SPACE».
- Layout:
  - Header (сериф): `«ЗАПИСИ · 22.04 – 05.05»`.
  - Для каждого дня с записями: жирная дата («22.04, ср»), ниже — строки `HH:MM · Имя · Услуга · Цена`.
  - Отменённые (если включены) — курсивом, с зачёркиванием или с иконкой `✕`, приглушённым цветом.
  - Если слишком много — авто-уменьшение шрифта body до нижней границы `BODY_MIN_SIZE` (то же, что в `_fit_font`).
- Hybrid-override: если в template есть непустое `bookings_image_header` — использовать его вместо автогенерируемой даты-периода.
- Фон — из общего слота `image_theme.load_theme_background(kind="bookings")` (или переиспользовать
  `schedule`, чтобы не плодить слоты; решение за тобой, прокомментируй выбор).

### H3. Тесты

`tests/test_admin_all_bookings.py`:
- `test_all_bookings_first_page_shows_14_days` — seed 20 booking-ов в разные дни, первая страница содержит только первые 14 дней.
- `test_all_bookings_pagination_next_prev` — переход на вторую страницу и обратно.
- `test_all_bookings_hides_cancelled_by_default`.
- `test_all_bookings_shows_cancelled_when_toggled`.
- `test_all_bookings_empty_period_message` — когда на странице нет записей.
- `test_open_booking_callback_routes_to_existing_card_handler`.

`tests/test_bookings_image.py`:
- `test_bookings_image_renders_valid_png` — байты начинаются с PNG-сигнатуры.
- `test_bookings_image_includes_cancelled_when_flag_set`.
- `test_bookings_image_header_uses_override_when_template_set`.

### H4. Критерий готовности блока H

- Админ из главного меню нажимает `📋 Все записи` — видит ближайшие 2 недели списком,
  может пагинироваться вперёд/назад.
- Клик по записи открывает карточку клиентки (через фикс блока D).
- `🖼 Скинуть картинкой` возвращает картинку того же периода, пригодную для пересылки.
- Отменённые по умолчанию скрыты, открываются toggle-кнопкой.
- Тесты зелёные.

---

## Блок C — клиентский флоу

### C1. Прайс-картинка перед выбором услуги + dedupe caption

**Клиентский «Запись»:**

- `src/bot/handlers/client/booking_flow.py`, функция входа в state `Booking.choose_base_service`
  (`show_base_service_step` или как называется сейчас — надо найти).
- Перед отправкой инлайн-клавиатуры услуг — `message.answer_photo(photo=<price_png>,
  caption=texts.CLIENT_BOOKING_PRICE_INTRO_TEXT)`. PNG берётся из
  `price_image.build_price_image_bytes(db_session)` (блок F4).
- Текст caption: `«Актуальный прайс ✨ Выбери ниже, с чего начнём.»` — добавить
  константу в `texts.py`.

**Клиентский «Услуги и цены» (главное меню):**

- Сейчас в `src/bot/handlers/client/services_list.py` caption прайс-картинки содержит
  дубликаты «Дизайн — от 250₽», «Доплата за длину — от 200₽», хотя эти же цены уже
  нарисованы на самой картинке. Убрать эти строки из caption, оставив только блок «Важно».
- Если «Важно» сейчас тоже дублирует, проверить и оставить только один источник истины
  (прайс-картинка — главный источник; caption — только призыв «хочешь — пришли референс»).

**Тесты:**
- `tests/test_client_booking_price_intro.py` — при старте booking-flow отправляется
  `answer_photo` с прайсом.
- Обновить существующие тесты `services_list` / `booking_flow`, если там что-то ломается
  от нового answer_photo.

### C2. Пост-запись CTA

- `src/bot/handlers/client/booking_flow.py` — финальный хендлер, отправляющий
  «Записала тебя 🪄 … До встречи 🤍».
- В конце сообщения добавить **инлайн-клавиатуру** (не reply, чтобы не ломать главное
  меню клиента):
  ```
  [👋 Мои записи]
  [🏠 В меню]
  ```
- Callback: `client:to_my_bookings`, `client:to_menu`. Хендлеры зовут существующие
  `show_my_bookings` и `show_client_menu`.
- Тексты кнопок — в `texts.py`.
- Тест: `tests/test_post_booking_cta.py`.

### C3. Исследование «фиолетовой» кнопки

**Задача на разбирательство, не на слепое редактирование.**

1. Найти, где сейчас рендерится кнопка «Записаться» в главном клиентском меню
   (`src/bot/keyboards/client.py` → `build_client_main_menu` или аналог).
2. Посмотреть, есть ли у этой кнопки `web_app=WebAppInfo(...)`, `pay=True` или она — первая
   строка reply-клавиатуры.
3. В зависимости от результата:
   - Если у «Записаться» стоит `web_app=WebAppInfo(...)` и это реальный Mini App — то её
     цвет приходит от открытого web-app. Повторять это для «Мои записи» не имеет смысла,
     если нет соответствующего web-app. Оставить «Мои записи» как обычную серую кнопку
     с эмодзи.
   - Если «Записаться» — первая строка reply-клавиатуры и клиенты Telegram на iOS/macOS
     рендерят её акцентом — переместить «Мои записи» в первую строку тоже, рядом с
     «Записаться» (или чередовать в зависимости от дизайна).
   - Если `pay=True` или редкий вариант — задокументировать в комментарии и оставить без
     изменений.
4. Результат расследования зафиксировать комментарием в `src/bot/keyboards/client.py`
   над соответствующей функцией — чтобы в будущем было понятно, почему так.

**Важно:** в Telegram Bot API нет поля `style`/`color`/`primary` у `InlineKeyboardButton`.
Попытки передать такие поля — бессмысленны (см. комментарий в исходниках и
[документацию](https://core.telegram.org/bots/api#inlinekeyboardbutton)). Не используй их.

### Критерий готовности блока C

- Клиент при нажатии «Запись» видит красивую картинку с прайсом, потом выбор услуги.
- После успешной записи — две inline-кнопки «Мои записи» / «В меню».
- Кнопка «Мои записи» либо акцентирована (если удалось применить корректный механизм),
  либо явно оставлена серой с зафиксированным в комментарии обоснованием.

---

## Блок I — визуальная полировка (стиль Мориарти)

Марк вдохновился оформлением Moriarty VPN и хочет, чтобы бот выглядел так же аккуратно:
картинки на большинстве экранов, цветные кнопки (красные для отмены/возврата, зелёные
для подтверждения), и тексты в структурированном стиле с tree-буллетами. Тексты уже
переписаны — см. файл **`PHASE11_TEXTS.md`** в корне репозитория.

### I1. Обновление aiogram до Bot API 9.4

Поле `style` на `KeyboardButton` / `InlineKeyboardButton` добавлено в **Bot API 9.4
от 9 февраля 2026**. В aiogram поддержка появилась в **3.26.0**. У нас в `pyproject.toml`
сейчас `aiogram>=3.25.0,<4.0`.

- Обновить закреп: `aiogram>=3.26.0,<4.0`.
- Прогнать `pip install -e .` (или `uv sync` — что используется в проекте) и убедиться,
  что всё ставится и тесты проходят.
- Никаких breaking-changes в 3.26 по сравнению с 3.25 для нашего кода быть не должно,
  но если что-то упало — зафиксировать и починить точечно.

### I2. Цветные кнопки через `style`

**API-справка:**
- `style="danger"` → красная (отмена, возврат, деструктив).
- `style="success"` → зелёная (основное подтверждение, оплата — у нас только подтверждение).
- `style="primary"` → синяя (выделенное вторичное действие, навигация-акцент).
- Без `style` → стандартная серая (все обычные кнопки).

**Правила применения — единые для всего бота:**

| Эмодзи / смысл | `style` |
| -------------- | ------- |
| `⬅️ Назад`, `🏠 Главное меню`, `🏠 В меню`, `⬅️ К меню расписания` | `danger` |
| `❌ Отмена`, `❌ Не оформлять`, любой «cancel» | `danger` |
| `🗑 Удалить`, `❌ Удалить слот`, `🔕 Shadow-ban`, `🚫 Заблокировать` | `danger` |
| `✅ Подтвердить`, `✅ Всё верно`, `✅ Записать`, «Готово» в forms | `success` |
| `📤 Загрузить новый`, `✏️ Перенести`, `✏️ Изменить`, «primary-actions» | `primary` |
| «Мои записи», «Записаться» в главном меню клиента | `primary` |
| Выбор варианта (дни, время, услуги, подпункты) — **без `style`** | gray |

**Задача Codex:**

1. Написать хелпер в `src/bot/keyboards/_styled.py` (или добавить в `keyboards/common.py`):
   ```python
   def danger(text: str, callback_data: str) -> InlineKeyboardButton: ...
   def success(text: str, callback_data: str) -> InlineKeyboardButton: ...
   def primary(text: str, callback_data: str) -> InlineKeyboardButton: ...
   ```
   Аналогично для `KeyboardButton` (reply-клавиатуры) — если в версии aiogram этот
   параметр принимается как `style="danger"` напрямую, оборачиваем. Если имена полей в
   Python-обёртке другие, смотри типы в aiogram 3.26 (`from aiogram.types import
   InlineKeyboardButton`; поле, вероятно, называется `style`).
2. Пройтись по всем `src/bot/keyboards/**/*.py` и по местам в хендлерах, где клавиатуры
   строятся inline, и проставить стиль по таблице выше. Это в том числе кнопки из блока
   B (`admin_nav:back:*`, `admin_nav:home`).
3. Для reply-клавиатур админа (`build_admin_main_menu` и т.п.) — если у кнопок есть
   явные «опасные» действия (у нас таких в reply-меню нет, главное меню — все primary),
   не проставлять стиль, оставить стандартными. Для кнопок типа «🙈 Режим клиента»
   поставить `primary`, чтобы админ ясно их различала.
4. Graceful degradation: если клиент Telegram старый и не поддерживает `style`, кнопка
   рендерится обычной серой — это ок, ничего ломать не нужно.

### I3. Картинки на большинстве экранов

Marked добавил: «Почти везде есть Фото на всех функциях». Свой стиль у нас уже есть — те же
тёмные картинки из блока F. Расширяем применение:

| Экран | Картинка | Источник |
| ----- | -------- | -------- |
| Клиент: главное меню (`/start`) | 🤍 бренд-заставка «ANGELS NAIL SPACE» | `assets/hero/main_menu.jpg` (новый файл, админ может заменить через «🎨 Фоны» → новая kind `main_menu`) |
| Клиент: «Запись» → выбор услуги | прайс-картинка (блок C1) | `price_image.build_price_image_bytes` |
| Клиент: «Запись» → выбор дня | картинка расписания | `schedule_image.render_schedule_image` (уже есть) |
| Клиент: «Портфолио» | бренд-заставка или первая работа из канала | `assets/hero/portfolio.jpg` (admin editable) |
| Клиент: «Адрес» | картинка-карта/фото подъезда | `assets/hero/address.jpg` (admin editable) |
| Клиент: «Услуги и цены» | прайс-картинка | `price_image.build_price_image_bytes` |
| Клиент: «Мои записи» (карточка записи) | картинка слота: дата+время+услуга в стиле блока F | **новый** `src/services/booking_card_image.py` |
| Клиент: пост-booking «Записала тебя» | картинка подтверждения записи | тот же `booking_card_image` с badge «✨ ЗАПИСАНО» |
| Клиент: reminder 24h и 2h | картинка напоминания | `booking_card_image` с badge «⏰ НАПОМИНАНИЕ» |
| Клиент: post-visit, repeat-prompt | бренд-заставка | `assets/hero/afterglow.jpg` (admin editable) |
| Админ: главное меню | **без картинки** (там reply-клавиатура, картинку некуда встроить удобно) |
| Админ: «📋 Все записи» | картинка-список (блок H2) | `bookings_image.build_bookings_image_bytes` |
| Админ: карточка клиента | картинка-карточка | `client_card_image` (уже есть) |
| Админ: «📅 Календарь на месяц» | картинка-календарь | **новый, но стаб**: в блоке A2 реализуем текстовый вид, для Phase 11 этого достаточно. Картинку-месяц — в Phase 12. |
| Админ: любые confirm-экраны («Всё верно?», «Точно удалить?») | **без картинки** (быстрые диалоги) |
| Онбординг, Broadcast, Settings, Templates — служебные | **без картинки** (технические экраны) |

**Новый сервис `src/services/booking_card_image.py`:**

```python
async def build_booking_card_image_bytes(
    booking: Booking,
    *,
    tz_name: str,
    badge: Literal["CONFIRMED", "REMINDER_24H", "REMINDER_2H", "CANCELLED"],
) -> bytes: ...
```

- Использует `image_theme.py` (блок F).
- Layout: header — CAPS-бейдж по `badge`, потом tree-блок:
  ```
  📇 ТВОЯ ЗАПИСЬ
  ┣ 📆 {date}
  ┣ 🕑 {time}
  ┗ 💅 {service}
  ```
- Footer — «ANGELS NAIL SPACE».
- Фон — `image_theme.load_theme_background(kind="booking_card")` (добавь этот kind в
  `BACKGROUND_KINDS` из блока F5; тот же набор операций — upload/reset/preview).

**Расширение списка фонов (блок F5 → I3):**

Добавить в `BACKGROUND_KINDS` слоты: `main_menu`, `portfolio`, `address`, `afterglow`,
`booking_card`. В «🎨 Фоны» админ-меню — новые кнопки по одной на каждый kind.

### I4. Применение новых текстов

См. отдельный файл **`PHASE11_TEXTS.md`**. Он содержит готовые значения для ВСЕХ
ключевых констант из `src/bot/texts.py`, переписанных в tree-структуре с эмодзи-префиксами.

- Codex подставляет значения в `src/bot/texts.py` (имена констант и `{плейсхолдеры}` — не
  меняет).
- Для констант-шаблонов (с префиксом `DEFAULT_…`) — также обновляет дефолты в
  `src/services/admin_defaults.py::required_template_defaults()`.
- Старые значения в БД (`SettingsTemplate` и т.п.), уже сохранённые админом вручную, не
  трогает — миграция не нужна.
- Тесты, которые сравнивают полные строки ответов — обновить снепшоты.

### I5. Тесты

`tests/test_styled_buttons.py`:
- `test_back_button_is_danger_style` — на примере любого сгенерированного admin_nav keyboard.
- `test_confirm_button_is_success_style`.
- `test_regular_choice_button_has_no_style`.

`tests/test_booking_card_image.py`:
- `test_booking_card_renders_valid_png`.
- `test_booking_card_shows_badge_for_each_state`.
- `test_booking_card_uses_custom_background_when_set`.

Обновить существующие тесты `test_client_texts.py`/`test_admin_texts.py` (если есть) под
новые строки.

### I6. Критерий готовности блока I

- `aiogram` обновлён до 3.26+, `pip install -e .` проходит, тесты зелёные.
- Везде, где клиент/админ нажимает «Назад», «Отмена», «Удалить», «Shadow-ban» —
  кнопка красная.
- Везде, где «Подтвердить», «Всё верно», «Готово» — зелёная.
- Клиент видит картинку на: главном меню, записи (выбор услуги, выбор дня, подтверждение),
  напоминаниях, карточке своих записей, портфолио, адресе, прайсе, после визита.
- Админ видит картинку на: «Все записи», карточке клиентки.
- Тексты соответствуют `PHASE11_TEXTS.md`, tree-буллеты `┣`/`┗` рендерятся в Telegram корректно.
- Ручная проверка: пройти все основные флоу на двух аккаунтах (клиент + Ангела) и
  удостовериться, что ничего не выглядит «голым» без картинки, и что цветные кнопки
  есть там, где должны.

---

## Блок E — тесты, линт, ручная верификация

1. `pytest -q` — зелёный, покрытие новых модулей не ниже 80%.
2. `ruff check . && ruff format --check .` — зелёный.
3. `mypy src` — зелёный (если в проекте включён).
4. Ручная проверка в Telegram со второго аккаунта (клиент):
   - `/start` → видит полный флоу записи, картинку-прайс, CTA после записи.
   - В автодополнении команд НЕТ `/admin`, `/schedule`, `/requests`, `/clients`.
5. Ручная проверка на аккаунте Ангелы (админ):
   - Открыть каждый раздел и на каждом экране убедиться, что есть понятная «⬅️ Назад».
   - В «🎨 Фоны» загрузить тестовый фон для каждой из трёх картинок, сбросить, убедиться
     что всё красиво и картинки visually в одной семье.
   - Перенести тестовый слот из одного времени в другое, проверить коллизии.
   - Открыть «📅 На месяц», пролистать пагинацию.
   - Записаться в «🙈 Режиме клиента», вернуться в админку, открыть карточку — не должно
     быть «не нашла эту клиентку».

---

## Phase 12 (геймификация) — заморожено, только фиксируем идеи

**В этой фазе НЕ делаем**, но держим в голове при проектировании моделей в Phase 11.
Когда Phase 11 стабилизируется и anti-abuse обкатается на реальных клиентах, откроем Phase 12.

Идеи:
- Расширить рейтинг/репутацию клиента (используем поле `strikes` и вводим обратное — `loyalty_score` или аналог).
- Очки за хорошее поведение:
  - +N за посещение (`Booking.status = COMPLETED`);
  - −M за `late_cancel`, −K за `NO_SHOW`.
- Триггеры уровня: при достижении порога — пуш клиенту «🌸 Ангела подарит тебе …».
- Каталог подарков (editable в админке): кремы для рук, масочки, маленькие скидки на следующий сеанс.
- Уведомление Ангелы: «У клиентки X накоплено N очков, можешь предложить подарок».
- Клиентский раздел «🤍 Мой уровень» в главном меню (опциональный, по флагу юзера или глобально).
- Opt-out: клиент может отключить уведомления о прогрессе, если не хочет.
- В разделе «О боте» / «Что я умею» — короткое описание программы лояльности.

Ограничения-напоминания на будущее:
- Геймификация не должна превращаться в давление («вы отменили запись, −10 очков» — так НЕ делать,
  продолжаем скрывать внутренние правила от клиента).
- Подарки выдаёт Ангела лично, бот только подсказывает и трекает. Не рассылать автоматически
  сообщения вроде «вам положен подарок».

## Коммиты и PR

- По одному коммиту на блок, сообщения:
  - `fix(phase11): unblock admin-as-client card lookup (block D)`
  - `feat(phase11): two-level back navigation + bot commands test (block B)`
  - `feat(phase11): anti-abuse — rate limits, shadow-ban, approval-gated booking/reschedule (block G)`
  - `feat(phase11): shared image_theme + price_image + backgrounds menu (block F)`
  - `feat(phase11): slot reschedule + month calendar (block A)`
  - `feat(phase11): admin view of all bookings — text + image (block H)`
  - `feat(phase11): price image in booking + post-booking CTA (block C)`
  - `feat(phase11): Bot API 9.4 styled buttons + pictures + new text style (block I)`
  - `chore(phase11): tests and lint pass (block E)`

Одним PR, title `Phase 11: UX polish + bug fixes + anti-abuse + Moriarty-style visual pass`,
тело — краткое резюме каждого блока с галочками acceptance criteria.
