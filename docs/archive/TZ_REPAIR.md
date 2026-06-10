# ТЗ: Функция гарантийного ремонта ноготков

Дата: 22.04.2026

---

## Суть функции

После маникюра у клиентки может сломаться ноготок. Ангела даёт гарантию: **бесплатный ремонт до 2 ноготков в течение 3 недель** после визита.

Сейчас это делается вручную — клиентка пишет в личку, они договариваются. Задача — перенести этот процесс в бот: клиентка оформляет запрос, Ангела видит его в очереди запросов и согласует время.

---

## Бизнес-правила

| Правило | Значение |
|---|---|
| Срок гарантии | 21 день с момента визита (дата слота) |
| Лимит ноготков | До 2 штук включительно |
| Стоимость | Бесплатно (в рамках гарантии) |
| Применимость | Только к `Booking.status = 'completed'` |
| Повторный запрос | Один активный запрос на запись (нельзя создать второй, пока первый pending/approved) |

---

## Изменения в БД

### 1. Миграция: новый вид запроса

**Файл:** `alembic/versions/0002_add_repair_support.py`

```python
# В enum ApprovalRequestKind добавить значение
"repair"  # к existing: new_booking, reschedule, question

# В таблицу approval_request добавить колонку
repair_nails_count: Integer, nullable=True  # 1 или 2
```

**Модель (`models.py`):**

```python
class ApprovalRequestKind(str, Enum):
    NEW_BOOKING = "new_booking"
    RESCHEDULE = "reschedule"
    QUESTION = "question"
    REPAIR = "repair"           # ← НОВОЕ
```

```python
class ApprovalRequest(Base):
    ...
    repair_nails_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ← НОВОЕ
```

**Уже есть и подходит:**
- `related_booking_id` → ссылка на оригинальную запись ✅
- `design_photos` → можно хранить фото сломанного ноготка ✅
- `requested_text` → текст с пожеланиями по времени ✅
- `status` (PENDING / APPROVED / DECLINED) → покрывает жизненный цикл ✅

### 2. Seed: новый шаблон

Добавить в `build_template_seed()` в `scripts/seed.py`:

```python
"repair_confirm": texts.DEFAULT_REPAIR_CONFIRM_TEMPLATE,
```

В `texts.py` добавить:

```python
DEFAULT_REPAIR_CONFIRM_TEMPLATE = """Ангела подтвердила ремонт 🔧

📆 {date}, {time}

{address}

До встречи 🤍"""
```

---

## Клиентская часть

### Точки входа

**Основная — карточка записи в "Мои записи":**

Для каждого `Booking.status == completed`, если с момента визита прошло менее 21 дня:

```
┌─────────────────────────────────────┐
│ Покрытие гель-лак                   │
│ 18 апреля, 15:00 · 2 400 ₽ · ✅    │
│                                     │
│ [✏️ Перенести]  [❌ Отменить]       │
│ [🔧 Запросить ремонт]               │  ← показывается если eligible
└─────────────────────────────────────┘
```

Если ремонт уже запрошен и в ожидании:
```
[🔧 Ремонт на рассмотрении]   ← кнопка-заглушка, без действия
```

Если ремонт подтверждён Ангелой:
```
[🔧 Ремонт: 25 апр, 16:00]   ← кнопка-заглушка, информационная
```

Если 21 день прошёл — кнопка не показывается совсем.

**Вспомогательная — пост-визитное сообщение:**

В шаблон `postvisit` добавить (в конец):
```
P.S. Если вдруг ноготок сломается — даю гарантию: ремонт 2 ноготков в течение 3 недель. Жми «Мои записи» в любой момент 🫶
```

Это направляет клиентку в нужное место и объясняет гарантию сразу после визита.

### FSM: RepairRequest

**Файл:** `src/bot/states.py` — добавить:

```python
class RepairRequest(StatesGroup):
    """Repair guarantee request flow."""
    choose_nails_count = State()
    await_photo = State()
    input_preferred_time = State()
    confirm = State()
```

### Флоу клиентки (шаг за шагом)

**Шаг 1. Выбор количества ноготков**

Триггер: `my_bookings:repair:{booking_id}`

```
🔧 Ремонт ноготков

Гарантия распространяется на 2 ноготка в течение 3 недель после визита.

Сколько ноготков сломалось?

[1 ноготок]  [2 ноготка]
[⬅️ Назад]
```

**Шаг 2. Фото (опционально)**

```
Можешь прислать фото — Ангела поймёт, что произошло.
Или пропусти, если фото нет.

[⏭ Пропустить]
```

Клиентка присылает фото → сохраняется в `design_photos`.
При пропуске — пустой список.

**Шаг 3. Удобное время (опционально)**

```
Когда тебе удобно прийти? 

Можно написать примерно: «после 18», «в выходные», «в среду утром».
Или пропусти — Ангела сама предложит.

[⏭ Пропустить]
```

Текст сохраняется в `requested_text`.

**Шаг 4. Подтверждение**

```
Всё верно?

Сломала: 2 ноготка
Удобное время: после 18, кроме среды

[✅ Отправить запрос]  [⬅️ Отмена]
```

`✅ Отправить запрос` → SUCCESS стиль
`⬅️ Отмена` → DANGER стиль

**Шаг 5. Результат**

```
Передала Ангеле! 🤍

Она скоро напишет и согласует время. 
Обычно отвечает в течение нескольких часов.
```

Кнопка `⬅️ К записям` — возврат в "Мои записи".

### Проверка eligibility

**Файл:** `src/services/booking.py` — добавить функцию:

```python
def is_repair_eligible(booking: Booking) -> bool:
    """Check if a booking is within the repair guarantee window."""
    if booking.status != BookingStatus.COMPLETED:
        return False
    if booking.slot is None:
        return False
    elapsed = utcnow() - booking.slot.start_at
    return elapsed <= timedelta(weeks=3)

def has_pending_repair(booking: Booking) -> bool:
    """Check if there's already an active repair request for this booking."""
    for req in booking.approval_requests:
        if req.kind == ApprovalRequestKind.REPAIR and req.status in (
            ApprovalRequestStatus.PENDING,
            ApprovalRequestStatus.APPROVED,
        ):
            return True
    return False
```

---

## Административная часть

### Уведомление Ангеле о новом запросе ремонта

Приходит в раздел "📥 Запросы" (как обычные запросы):

```
🔧 Запрос на ремонт

Матвей (@l1XLEB)
Запись: 18 апреля — Покрытие гель-лак (4 дня назад)

Сломала: 2 ноготка
Удобное время: после 18, кроме среды

[фото если есть]

[✅ Согласовать время]  [💬 Написать]
[❌ Отклонить]
```

### Клавиатура для ремонта (в `admin.py`)

Новая функция `build_admin_repair_actions_keyboard(approval_id: int)`:

```python
InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(
            text="✅ Согласовать время",
            callback_data=f"approval:repair_confirm:{approval_id}",
            style=ButtonStyle.SUCCESS,
        ),
    ],
    [
        InlineKeyboardButton(
            text="💬 Написать",
            callback_data=f"approval:reply:{approval_id}",
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=f"approval:repair_decline:{approval_id}",
            style=ButtonStyle.DANGER,
        ),
    ],
])
```

### Флоу "Согласовать время"

**Вариант А — через слот:**

Ангела нажимает "✅ Согласовать время" → бот показывает ближайшие свободные слоты (как в обычном потоке подтверждения запроса). Ангела выбирает → бот:
1. Создаёт `Booking` с `status=confirmed` и `slot.status=booked`, помечает как repair (см. ниже)
2. Отправляет клиентке уведомление из шаблона `repair_confirm`
3. Переводит `ApprovalRequest.status = APPROVED`

**Вариант Б — через прокси-чат:**

Ангела нажимает "💬 Написать" → обычный прокси-чат. Договариваются в переписке. Ангела вручную фиксирует слот. Клиентка получает сообщение напрямую.

**Для MVP:** реализовать только вариант Б (прокси-чат уже есть в архитектуре). Вариант А — следующая итерация.

### Флоу "Отклонить"

Ангела нажимает "❌ Отклонить" → пикер причины:

```
[⌛ Гарантийный срок истёк]
[💔 Нет свободного времени сейчас]
[✏️ Другое]
```

"Другое" → Ангела вводит текст.

Клиентке приходит:
```
К сожалению, Ангела не может сделать ремонт в рамках гарантии.

{причина}

Если хочешь записаться — жми «Записаться» в меню 💅
```

### Отображение в очереди запросов

В списке запросов добавить маркер типа:

```
🔧 РЕМОНТ · Матвей · 2 ноготка · 4 дня назад
📋 ЗАПИСЬ · Алина · Покрытие гель-лак · 2 часа назад
💬 ВОПРОС · Катя · 1 час назад
```

---

## Интеграция с существующим функционалом

### "Мои записи" — изменения в build_booking_card_keyboard

Добавить параметры в функцию:

```python
def build_booking_card_keyboard(
    booking_id: int,
    *,
    can_reschedule: bool,
    can_cancel: bool,
    cancel_label: str,
    can_request_repair: bool,    # ← НОВОЕ
    repair_status: str | None,   # ← НОВОЕ: None / "pending" / "approved"
    repair_label: str | None,    # ← НОВОЕ: текст кнопки если approved
) -> InlineKeyboardMarkup:
```

Логика кнопки ремонта:
- `can_request_repair=True` → кнопка "🔧 Запросить ремонт" (без стиля — вторичное действие)
- `repair_status="pending"` → кнопка "🔧 Ремонт на рассмотрении" (без callback, info-only)
- `repair_status="approved"` → кнопка "🔧 Ремонт: {repair_label}" (без callback, info-only)
- Иначе → кнопка не показывается

### Шаблон postvisit — дополнение

В конец шаблона `DEFAULT_POSTVISIT_TEMPLATE` добавить абзац:

```
P.S. Если вдруг ноготок сломается — даю гарантию: ремонт 2 ноготков в течение 3 недель. Жми «Мои записи» в любой момент 🫶
```

Это нужно добавить как в константу в `texts.py`, так и в seed (обновить существующую запись).

### Карточка клиентки (admin) — дополнение

Добавить в статистику клиентки:

```
Ремонтов использовала: N
```

Запрос: `COUNT(approval_requests WHERE kind='repair' AND status='approved' AND client_id=X)`

### Статистика — дополнение

В раздел "📊 Статистика" добавить строку:

```
Запросов на ремонт: N (из них выполнено: M)
```

---

## Файловая структура (новые файлы)

```
src/bot/handlers/client/repair_flow.py      ← FSM флоу ремонта
src/bot/handlers/admin/approvals.py         ← уже есть, дополнить repair_confirm/decline
alembic/versions/0002_add_repair_support.py ← миграция
```

### Что добавить в существующие файлы

| Файл | Что добавить |
|---|---|
| `models.py` | `ApprovalRequestKind.REPAIR`, `ApprovalRequest.repair_nails_count` |
| `states.py` | `class RepairRequest(StatesGroup)` |
| `texts.py` | `DEFAULT_REPAIR_CONFIRM_TEMPLATE`, `REPAIR_DECLINED_TEXT`, `REPAIR_SUBMITTED_TEXT` |
| `keyboards/client.py` | Обновить `build_booking_card_keyboard` (параметры repair), добавить `build_repair_flow_keyboards` |
| `keyboards/admin.py` | `build_admin_repair_actions_keyboard`, `build_admin_repair_decline_keyboard` |
| `scripts/seed.py` | Добавить `repair_confirm` в `build_template_seed()` |
| `bot/app.py` | Подключить `repair_flow` router |
| `services/booking.py` | `is_repair_eligible()`, `has_pending_repair()` |

---

## UX-детали и граничные случаи

| Случай | Поведение |
|---|---|
| Запись не завершена (confirmed) | Кнопка ремонта не показывается |
| Прошло больше 21 дня | Кнопка не показывается |
| Уже есть pending-запрос | Показывается "🔧 Ремонт на рассмотрении" |
| Уже есть approved-запрос | Показывается "🔧 Ремонт: {дата}" |
| Клиентка пытается открыть ремонт через URL/callback вручную | Проверяем eligibility, если не eligible — дружелюбный отказ |
| Ангела отклонила | Клиентка получает сообщение с причиной + предложение записаться |

---

## Пользовательские тексты

Добавить в `texts.py`:

```python
REPAIR_INTRO_TEXT = """🔧 Ремонт ноготков

Гарантия распространяется на 2 ноготка в течение 3 недель после визита.

Сколько ноготков сломалось?"""

REPAIR_PHOTO_PROMPT_TEXT = """Можешь прислать фото — Ангела поймёт, что произошло.
Или пропусти, если фото нет."""

REPAIR_TIME_PROMPT_TEXT = """Когда тебе удобно прийти?

Можно написать примерно: «после 18», «в выходные», «в среду утром».
Или пропусти — Ангела сама предложит."""

REPAIR_CONFIRM_TEXT = """Всё верно?

Сломала: {nails_count}
Удобное время: {preferred_time}"""

REPAIR_CONFIRM_NO_TIME_TEXT = """Всё верно?

Сломала: {nails_count}
Время: Ангела предложит сама"""

REPAIR_SUBMITTED_TEXT = """Передала Ангеле! 🤍

Она скоро напишет и согласует время."""

REPAIR_DECLINED_TEXT = """К сожалению, Ангела не может сделать ремонт.

{reason}

Если хочешь записаться — жми «Записаться» в меню 💅"""

ADMIN_REPAIR_NOTIFICATION_TEXT = """🔧 Запрос на ремонт

{name} (@{username})
Запись: {original_date} — {service}

Сломала: {nails_count}
{preferred_time_line}"""
```

---

## Приоритет реализации

| # | Шаг | Зависимости |
|---|---|---|
| 1 | Миграция DB (`repair_nails_count`, `REPAIR` kind) | Ничего |
| 2 | Добавить в `models.py` | Миграция |
| 3 | Добавить `RepairRequest` FSM в `states.py` | Ничего |
| 4 | Функции `is_repair_eligible` и `has_pending_repair` в `services/booking.py` | Модели |
| 5 | Обновить `build_booking_card_keyboard` в `keyboards/client.py` | Функции eligibility |
| 6 | Реализовать `repair_flow.py` (клиентский FSM) | Keyboards, FSM states |
| 7 | Обновить хендлер "Мои записи" — передавать repair-параметры в keyboard | repair_flow.py |
| 8 | Добавить `build_admin_repair_actions_keyboard` | admin.py keyboards |
| 9 | Дополнить `admin/approvals.py` — обработка repair запросов | Keyboards admin |
| 10 | Добавить тексты и шаблон `repair_confirm` в seed | texts.py |
| 11 | Подключить router в `app.py` | repair_flow.py |
| 12 | Обновить шаблон `postvisit` — упомянуть гарантию | seed.py |

Весь функционал независим от нереализованных частей (планировщик, рассылка и т.д.) и может быть добавлен в любой момент.
