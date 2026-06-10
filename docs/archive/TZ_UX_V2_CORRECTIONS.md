# Правки к TZ_UX_V2 — после анализа кода

Дата: 22.04.2026

После изучения реального кода оказалось, что несколько пунктов из TZ_UX_V2 уже реализованы или требуют корректировки формулировок.

---

## Раздел 2 — Быстрые команды: УЖЕ РЕАЛИЗОВАНО

`commands.py` и `common.py` содержат полную реализацию — как объявление команд, так и хендлеры:

| Команда | Статус |
|---|---|
| `/start` | ✅ реализован |
| `/book` | ✅ реализован (`command_book` → `start_booking_entry`) |
| `/mybookings` | ✅ реализован (`command_my_bookings` → `show_my_bookings_entry`) |
| `/schedule` | ✅ реализован (только для admin) |
| `/requests` | ✅ реализован (только для admin) |
| `/clients` | ✅ реализован (только для admin) |

**Единственное, что проверить:** вызывается ли `register_bot_commands()` из `main.py` при старте. Если нет — добавить вызов в `main.py` на этапе инициализации бота. Это одна строка, не задача на реализацию.

---

## Раздел 3 — Шаблоны: константы ЕСТЬ, в сид НЕ ДОБАВЛЕНЫ

`texts.py` уже содержит правильные дефолтные тексты:

| Константа в texts.py | Нужный ключ в Template | Статус в seed |
|---|---|---|
| `DEFAULT_BOOKING_CONFIRM_TEMPLATE` | `booking_confirm` | ❌ не посеян |
| `DEFAULT_REMINDER_24H_TEMPLATE` | `reminder_24h` | ❌ не посеян |
| `DEFAULT_REMINDER_2H_TEMPLATE` | `reminder_2h` | ❌ не посеян |
| `DEFAULT_POSTVISIT_TEMPLATE` | `postvisit` | ❌ не посеян |
| `DEFAULT_REPEAT_PROMPT_TEMPLATE` | `repeat_prompt` | ❌ не посеян |

Тексты шаблонов из TZ_UX_V2 раздела 3 заменить на уже написанные константы из `texts.py`.

**Что нужно сделать:**
Добавить в `build_template_seed()` в `scripts/seed.py`:
```python
"booking_confirm": texts.DEFAULT_BOOKING_CONFIRM_TEMPLATE,
"reminder_24h": texts.DEFAULT_REMINDER_24H_TEMPLATE,
"reminder_2h": texts.DEFAULT_REMINDER_2H_TEMPLATE,
"postvisit": texts.DEFAULT_POSTVISIT_TEMPLATE,
"repeat_prompt": texts.DEFAULT_REPEAT_PROMPT_TEMPLATE,
```

Также нужны шаблоны картинки расписания (если они используются как Template, а не hardcoded):
```python
"schedule_image_header": "Свободные окошки",
"schedule_image_footer": "ANGELS NAIL SPACE",
"schedule_image_text_override": "",
```

---

## Раздел 3 — FSM редактирования шаблона: УЖЕ ЕСТЬ

`AdminTemplateEdit` в `states.py` уже объявлен с состоянием `input_content`. Хендлер в `templates_edit.py` пустой — это и есть задача на реализацию. ТЗ корректно описывает что нужно, просто FSM объявлять заново не нужно.

---

## Раздел 3 — Переменные в шаблонах: УТОЧНЕНИЕ

`texts.py` использует Python `.format()` с ключами `{date}`, `{time}`, `{service}`, `{address}`. Это уже установленный формат. Реализовывать другой (например, Jinja2) не нужно — продолжать использовать `.format()`.

---

## Разделы 4, 5, 6, 7, 8 — без правок

Описание корректное, всё требует реализации.

---

## Раздел 9 — Кнопки "На месяц" и "Заблокировать период"

Из аудита: показывают алерт "Этот раздел подключу в одной из следующих админских фаз ✨". Это уже более мягко чем crash, но всё равно вводит в заблуждение.

**Уточнение:** "Заблокировать период" — это важная функция (блокировать несколько дней за раз), её нужно не удалять а реализовывать. Убрать только "📅 На месяц" — этот вид расписания менее критичен.

---

## Раздел 12 — Greeting header: НЕ НУЖНА ПРАВКА

`texts.MENU_HEADER` уже содержит корректный текст — "💅 ANGELS NAIL SPACE...". На скриншоте в Шаблонах видно "greeting_header" жирным — это только лейбл карточки в админке (ключ шаблона), не часть контента. Содержимое чистое.

---

## Раздел 13 — client_card.py: ФАЙЛ СУЩЕСТВУЕТ

`src/bot/handlers/client/client_card.py` — файл есть. По аудиту его содержимое неизвестно, но это может быть уже частичная реализация карточки. Перед редизайном прочитать и сверить.
