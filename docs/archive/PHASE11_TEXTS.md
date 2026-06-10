# Phase 11 — Переписанные тексты в структурированном стиле

Марк вдохновился форматом Moriarty VPN (чёткая структура, дерево-буллеты `┣`/`┗`,
CAPS-заголовки с эмодзи, короткие блоки через пустую строку) и хочет, чтобы все служебные
тексты бота выглядели так же аккуратно, но в нашей интонации — тёплой, «соло-мастер»,
на «ты», с 🤍 как подписью.

Этот файл — готовый материал для Codex: копируй значение константы в `src/bot/texts.py`
(и, где указано, в дефолты шаблонов в `src/services/admin_defaults.py`). Плейсхолдеры
`{…}` оставляй как есть, они уже совпадают по имени с текущим кодом.

---

## Философия

Moriarty делает так:
- заголовок CAPS-ом, префикс-эмодзи (💎, 📦, 📱);
- блок фактов деревом `┣` / `┗`;
- между смысловыми блоками — пустая строка;
- один эмодзи = один смысл (📇 личные данные, 💎 оплата, 📱 устройства, 🌍 локации).

Мы делаем так же по структуре, но:
- тёплая палитра эмодзи: 🤍 ✨ 🪄 🌷 🌸 💅 📅 📆 🕑 📸 📍 💰 👑 👋 🙈 ⏰ 💬 👀;
- обращение на «ты», «напишу», «жду», «передала»;
- подпись 🤍 или ✨ в конце важных сообщений — это наш «жест»;
- длинные параграфы ломаем на короткие блоки по 1–3 строки;
- числа/факты — деревом; эмоциональные сообщения (приветы, спасибки) — прозой.

Запрещено (повторяю из блока G):
- формулировки про «правила», «лимит», «2.5 недели», «ограничение», «strike/rate-limit»
  в клиентских текстах. Клиенту говорим мягко: «отправила Ангеле на подтверждение,
  напишу как ответит 🤍».

---

## Визуальный словарь

| Символ | Где использовать |
| ------ | ---------------- |
| `┣` | средняя строка списка |
| `┗` | последняя строка списка |
| `·` | подпункт или перечисление внутри одной строки |
| пустая строка | разделитель между смысловыми блоками |
| CAPS-заголовок + эмодзи слева | начало сообщения или новый блок внутри |
| 🤍 в конце абзаца | «подпись» / signoff |
| ✨ в конце короткого уведомления | лёгкий акцент успеха |

Эмодзи-карта по смыслам:

| Смысл | Эмодзи |
| ----- | ------ |
| запись/сеанс | 🪄 💅 |
| дата | 📆 |
| время | 🕑 ⏰ |
| услуга | 💅 |
| адрес | 📍 |
| прайс/деньги | 💰 |
| фото/портфолио | 📸 |
| сообщение в чат | 💬 |
| клиентка/карточка | 👤 👋 |
| админ / Ангела | 👑 |
| режим клиента | 🙈 |
| ошибка / не получилось | 😔 (мягче, чем ❌) |
| успех | ✨ 🤍 |
| предупреждение | ⚠️ |

---

## Главное меню и навигация

```python
MENU_HEADER = """🤍 ANGELS NAIL SPACE

Маникюрная студия Ангелы — уютное место, где делают красиво и без спешки.

✨ Что можно здесь:
┣ 📅 Посмотреть окошки и записаться
┣ 💰 Открыть актуальный прайс
┣ 📍 Узнать адрес и как дойти
┣ 📸 Заглянуть в портфолио
┗ 💬 Написать Ангеле напрямую

Выбирай раздел ниже 👇"""
```

```python
PORTFOLIO_INTRO = """📸 ПОРТФОЛИО

Свежие работы Ангела выкладывает у себя в Telegram-канале —
загляни, там все последние дизайны и настроения.

Тапни кнопку ниже, чтобы открыть ✨"""
```

```python
DEFAULT_ADDRESS_POST_CONFIRM = """📍 АДРЕС И НАВИГАЦИЯ

┣ 🏠 Адрес: [Ангела напишет]
┣ 🚪 Подъезд и код: [Ангела напишет]
┣ 🛗 Этаж: [Ангела напишет]
┗ 🗺 Ориентир: [Ангела напишет]

Если что-то не найдёшь — напиши, помогу 🤍"""
```

```python
DEFAULT_RULES = """🤍 ПРАВИЛА ВИЗИТА

┣ 💬 Если планы поменялись — напиши заранее
┣ ⏰ Постарайся не опаздывать
┗ ✨ О важных деталях по рукам или покрытию — предупреди

Всё простое, чтобы нам обеим было комфортно 🤍"""
```

```python
DEFAULT_VACATION_NOTICE = """🌷 ЗАПИСЬ ВРЕМЕННО ЗАКРЫТА

Сейчас окошек нет, но скоро Ангела откроет новые.

Как только появятся — бот покажет их здесь ✨"""
```

---

## Онбординг

```python
ONBOARDING_NAME_CONFIRM_TEXT = """🤍 ЗАПИСЫВАЕМСЯ

Это нужно заполнить один раз — дальше всё будет быстро.

Я вижу тебя в Telegram как «{first_name}».
Так обращаться?"""
```

```python
ONBOARDING_NAME_INPUT_TEXT = """👤 Как к тебе обращаться?

Напиши имя одним сообщением ✨"""
```

```python
ONBOARDING_NAME_INVALID_TEXT = "Имя должно быть от 1 до 40 символов. Попробуем ещё раз 🤍"
```

```python
ONBOARDING_PHONE_TEXT = """📱 ТЕЛЕФОН

Остался последний шаг — пришли номер одной кнопкой ниже 👇"""
```

```python
ONBOARDING_PHONE_MANUAL_HINT_TEXT = """Если удобнее — можно ввести номер вручную."""
```

```python
ONBOARDING_PHONE_MANUAL_INPUT_TEXT = """📱 Напиши номер одним сообщением.

Пример: +7 900 000 00 00"""
```

```python
ONBOARDING_PHONE_INVALID_TEXT = """😔 Не смогла распознать номер.

Пришли его в формате +7… или поделись контактом кнопкой."""
```

```python
ONBOARDING_CONTACT_FOREIGN_TEXT = (
    "Лучше отправь свой контакт кнопкой ниже или напиши номер вручную 🤍"
)
```

```python
ONBOARDING_NOTE_TEXT = """✏️ ПАРУ СЛОВ О СЕБЕ

Если есть аллергии, предпочтения или ник в инсте — черкни одним сообщением.
Или просто пропусти этот шаг ✨"""
```

---

## Клиентская запись (booking flow)

```python
CLIENT_BOOKING_PRICE_INTRO_TEXT = """💰 АКТУАЛЬНЫЙ ПРАЙС

Посмотри цены на картинке выше, и выбери ниже, с чего начнём ✨"""
```

```python
BOOKING_CHOOSE_BASE_SERVICE_TEXT = """💅 С ЧЕГО НАЧНЁМ?

Выбери основную услугу 👇"""
```

```python
BOOKING_CHOOSE_DAY_TEXT = """📆 ВЫБЕРИ ДЕНЬ

Ниже — свободные дни на ближайшее время 👇"""
```

```python
BOOKING_CHOOSE_TIME_TEXT = """🕑 ТЕПЕРЬ ВРЕМЯ

Выбери удобный час 👇"""
```

```python
BOOKING_NO_SLOTS_TEXT = """😔 ОКОШЕК ПОКА НЕТ

Все разобрали. Хочешь, напишу, как только откроются новые?"""
```

```python
BOOKING_WAITLIST_PLACEHOLDER_TEXT = (
    "Лист ожидания добавлю в одной из следующих фаз. Пока можно вернуться в меню 🤍"
)
```

```python
BOOKING_REFERENCE_PROMPT_TEXT = """📸 РЕФЕРЕНСЫ

Хочешь приложить фото дизайна, который нравится?
Можно до 5 штук."""
```

```python
BOOKING_REFERENCE_WAITING_TEXT = """Пришли до 5 фото.

После каждого можно добавить комментарий или сразу нажать «Готово» ✨"""
```

```python
BOOKING_REFERENCE_LIMIT_TEXT = "Можно приложить до 5 фото. Если всё готово — нажми «Готово»."
```

```python
BOOKING_REFERENCE_COMMENT_INPUT_TEXT = "💬 Напиши комментарий к референсам одним сообщением."
```

```python
BOOKING_REFERENCE_COMMENT_SAVED_TEXT = "Сохранила комментарий ✨"
```

```python
BOOKING_CONFIRM_SLOT_TAKEN_TEXT = """😔 ОЙ, ЭТО ОКОШКО УЖЕ ЗАНЯЛИ

Пока ты выбирала — его кто-то забронировал."""
```

```python
BOOKING_CONFIRM_SLOT_TAKEN_FOLLOWUP_TEXT = "Вот что осталось на этот день 👇"
```

```python
BOOKING_CANCELLED_TEXT = "Хорошо, запись не оформляю 🤍"
```

```python
BOOKING_RETRY_LATER_TEXT = "Давай чуть позже попробуем 🤍"
```

```python
BOOKING_PENDING_APPROVALS_LIMIT_TEXT = (
    "У тебя уже есть ожидающие запросы, дождись, пожалуйста, ответа Ангелы 🤍"
)
```

```python
BOOKING_CUSTOM_TIME_PROMPT_TEXT = """💬 ДРУГОЕ ВРЕМЯ

Напиши, когда тебе было бы удобно — передам Ангеле.

Можно конкретно: «22.04 в 13:00»
Или общо: «после работы, после 19, кроме вторника»"""
```

```python
APPROVAL_REQUEST_SENT_TEXT = """✨ ОТПРАВИЛА АНГЕЛЕ НА ПОДТВЕРЖДЕНИЕ

Напишу, как только ответит — обычно в течение нескольких часов 🤍"""
```

```python
ASK_MASTER_PROMPT_TEXT = """💬 ВОПРОС АНГЕЛЕ

Напиши сообщение — можно текстом, фото или голосовым ✨"""
```

```python
CLIENT_CARD_CAPTION_TEXT = "Твоя карточка в ANGELS NAIL SPACE 🤍"
```

```python
DESIGN_PHOTO_OUTSIDE_FLOW_TEXT = """📸 Красивый дизайн 🤍

Я не умею оценивать его сама — передам Ангеле,
как только ты оформишь запись или попросишь.

Что делаем дальше?"""
```

```python
DESIGN_PHOTO_CANCELLED_TEXT = "Хорошо, ничего не отправляю 🤍"
```

```python
PROXY_REPLY_PROMPT_TEXT = "💬 Напиши сообщение для Ангелы одним сообщением."
```

```python
PROXY_REPLY_SENT_TEXT = "Передала сообщение Ангеле ✨"
```

```python
PROXY_CLIENT_REPLY_BUTTON_TEXT = "💬 Ответить"
```

### Пост-запись CTA

```python
POST_BOOKING_MY_BOOKINGS_BUTTON_TEXT = "👋 Мои записи"
POST_BOOKING_MENU_BUTTON_TEXT = "🏠 В меню"
```

### Шаблон подтверждения записи (идёт в `templates_defaults`)

```python
DEFAULT_BOOKING_CONFIRM_TEMPLATE = """🪄 ЗАПИСАЛА ТЕБЯ

📇 Твоя запись:
┣ 📆 Дата: {date}
┣ 🕑 Время: {time}
┗ 💅 Услуга: {service}

{address}

✨ Напомню за сутки и за пару часов.
Если что-то изменится — жми «Мои записи» в меню.

До встречи 🤍"""
```

---

## Напоминания и post-visit

```python
DEFAULT_REMINDER_24H_TEMPLATE = """🌷 Привет 🤍

Напоминаю о завтрашней записи:

┣ 📆 Дата: {date}
┣ 🕑 Время: {time}
┗ 💅 Услуга: {service}

💌 До встречи — будет красиво ✨"""
```

```python
DEFAULT_REMINDER_2H_TEMPLATE = """⏰ ЧЕРЕЗ ПАРУ ЧАСОВ

Сегодня в {time} — жду тебя 🤍

Если вдруг не успеваешь, напиши."""
```

```python
DEFAULT_POSTVISIT_TEMPLATE = """🌷 Спасибо, что сегодня пришла

Очень рада была тебя видеть 🫶
Надеюсь, тебе понравился результат и атмосфера 🤍

Если будет минутка — расскажи, всё ли тебе понравилось.
Мне важно, чтобы каждая девочка чувствовала себя комфортно 🫂"""
```

```python
DEFAULT_REPEAT_PROMPT_TEMPLATE = """🌷 Привет 🤍

Прошло немного времени с нашей встречи.
Если захочешь снова — я буду рада тебя видеть ✨"""
```

### Рантайм-тексты напоминаний (те же шаблоны из `texts.py`)

```python
REMINDER_24H_TEXT = """🌷 Привет, {display_name} 🤍

Напоминаю о записи завтра:

┣ 🕑 Время: {time}
┗ 💅 Услуга: {service_name}

{address_text}

Всё в силе?"""
```

```python
REMINDER_2H_TEXT = """⏰ ЧЕРЕЗ ~2 ЧАСА ЖДУ ТЕБЯ 🤍

┣ 🕑 {time}
┗ 💅 {service_name}

Если вдруг не успеваешь — напиши."""
```

```python
REMINDER_CONFIRMED_TEXT = "Супер, жду тебя 🤍"
```

```python
POSTVISIT_PROMPT_TEXT = """✨ КАК ВСЁ ПРОШЛО?

Поставь оценку ниже — это помогает Ангеле расти 🤍"""
```

```python
POSTVISIT_THANK_YOU_TEXT = "Спасибо большое за оценку 🤍"
```

```python
REPEAT_PROMPT_TEXT = """🌷 {display_name}, привет 🤍

Уже почти три недельки прошло с твоего визита — пора обновить?

Ниже — свободные окошки у Ангелы ✨"""
```

```python
REPEAT_PROMPT_LATER_TEXT = "Хорошо, напомнюсь позже, когда ты сама заглянешь ✨"
```

---

## Мои записи (клиент)

```python
NO_BOOKINGS_YET_TEXT = """🤍 ПОКА НИ ОДНОЙ ЗАПИСИ

Когда запишешься — она появится здесь ✨"""
```

```python
MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT = "Сейчас это действие уже недоступно 🤍"
```

```python
MY_BOOKINGS_CANCEL_REASON_TEXT = """💬 Что случилось?

Напиши причину — ничего страшного, это просто для статистики 🤍"""
```

```python
MY_BOOKINGS_CANCEL_WARNING_TEXT = """⚠️ ДО ВИЗИТА ОСТАЛОСЬ МАЛО ВРЕМЕНИ

Меньше {hours} ч — Ангела может не успеть заполнить окошко.

Точно отменить?"""
```

```python
MY_BOOKINGS_CANCEL_OTHER_REASON_TEXT = "💬 Напиши причину одним сообщением."
```

```python
MY_BOOKINGS_CANCEL_OTHER_REASON_INVALID_TEXT = "Напиши причину одним сообщением, пожалуйста 🤍"
```

```python
MY_BOOKINGS_CANCEL_DONE_TEXT = "Записала отмену 🤍"
```

```python
MY_BOOKINGS_CANCEL_LT24H_TEXT = """Записала отмену 🤍

Маленькая просьба: в следующий раз постарайся предупредить заранее —
так мне проще передать окошко другой девочке.

Спасибо за понимание ✨"""
```

```python
MY_BOOKINGS_CARD_MISSING_TEXT = "Эта запись уже недоступна 🤍"
```

```python
MY_BOOKINGS_RESCHEDULE_DAY_TEXT = """📆 ПЕРЕНОС ЗАПИСИ

Выбери новый день 👇"""
```

```python
MY_BOOKINGS_RESCHEDULE_TIME_TEXT = """🕑 НОВОЕ ВРЕМЯ

Выбери удобный час 👇"""
```

```python
MY_BOOKINGS_RESCHEDULE_NO_SLOTS_TEXT = "Свободных окошек для переноса пока нет 🤍"
```

```python
MY_BOOKINGS_RESCHEDULED_TEXT = "Перенесла запись ✨"
```

---

## Услуги (клиентский список)

```python
SERVICES_CAPTION_TEXT = """🤍 Важно

Картинка выше — основной прайс.

Если хочешь сложный дизайн или сомневаешься по длине —
пришли референс перед записью, Ангела подскажет точнее ✨"""
```

```python
NO_ACTIVE_SERVICES_TEXT = "Список услуг ещё не настроен. Попробуй чуть позже 🤍"
```

---

## Админ — главное меню и общие

```python
ADMIN_MENU_TEXT = """👋 Привет, Ангела

👑 АДМИН-МЕНЮ

📇 Ожидают действий:
┣ 📨 Запросов: {pending_approvals}
┗ 📅 Записей на сегодня: {today_bookings}

Выбери раздел ниже 👇"""
```

```python
ADMIN_PLACEHOLDER_TEXT = "Этот раздел подключу в одной из следующих админских фаз ✨"
```

```python
ADMIN_ONLY_TEXT = "Этот раздел доступен только Ангеле 🤍"
```

---

## Админ — запросы (approvals)

```python
ADMIN_APPROVALS_EMPTY_TEXT = """📨 ЗАПРОСЫ

Пока чисто — новых запросов нет ✨"""
```

```python
ADMIN_APPROVALS_HEADER_TEXT = """📨 ЗАПРОСЫ

Ниже все pending-запросы от клиенток 👇"""
```

```python
ADMIN_APPROVAL_CONFIRM_TEXT = "Выбери, как подтвердить запрос 👇"
```

```python
ADMIN_APPROVAL_REPLY_PROMPT_TEXT = """💬 ОТВЕТ КЛИЕНТКЕ

Пришли ответ одним сообщением.
Можно текстом, фото или голосовым ✨"""
```

```python
ADMIN_APPROVAL_DECLINE_PROMPT_TEXT = """😔 ОТКАЗ

Напиши причину одним сообщением — я передам клиентке мягко."""
```

```python
ADMIN_APPROVAL_PROCESSED_TEXT = "Готово ✨"
```

```python
ADMIN_APPROVAL_READ_TEXT = "Отметила как прочитанное 🤍"
```

```python
ADMIN_APPROVAL_SLOT_UNAVAILABLE_TEXT = "Это окошко уже недоступно 🤍"
```

```python
ADMIN_APPROVAL_CONFIRM_FAILED_TEXT = (
    "Не получилось подтвердить запрос. Проверь данные и попробуй ещё раз 🤍"
)
```

```python
ADMIN_APPROVAL_REPLY_SENT_TEXT = "Ответ отправлен клиентке ✨"
```

---

## Админ — расписание

```python
ADMIN_SCHEDULE_MENU_TEXT = """📅 РАСПИСАНИЕ

Выбери, что сделать дальше 👇"""
```

```python
ADMIN_SCHEDULE_INSTRUCTION_TEXT = """📅 ДОБАВИТЬ ОКОШКИ

Скинь расписание одним сообщением. Формат:

┣ 07.04 17:00 19:00 21:00
┣ 08.04 17 19 21
┗ 09.04 18:00, 20:00

📇 Правила:
┣ Одна строка — один день
┣ Даты — ДД.ММ (год поставлю сама)
┣ Время — часы или часы:минуты
┗ Разделители: пробел, запятая, «/»"""
```

```python
ADMIN_SCHEDULE_PREVIEW_EMPTY_TEXT = "Не получилось распознать ни одного окошка 🤍"
```

```python
ADMIN_SCHEDULE_ADDED_TEXT = "Готово ✨ Добавила {created} окошек."
```

```python
ADMIN_SCHEDULE_ADDED_WITH_SKIPS_TEXT = (
    "Готово ✨ Добавила {created}, пропустила дубликаты: {skipped}."
)
```

```python
ADMIN_SCHEDULE_ALL_DUPLICATES_TEXT = "Всё уже добавлено 🤍"
```

```python
ADMIN_SCHEDULE_WEEK_EMPTY_TEXT = "На ближайшую неделю окошек пока нет 🤍"
```

```python
ADMIN_SCHEDULE_BOOKING_PLACEHOLDER_TEXT = "Карточку записи подключу в следующей фазе ✨"
```

```python
ADMIN_SCHEDULE_BOOKED_DELETE_FORBIDDEN_TEXT = "Нельзя удалить слот с активной записью 🤍"
```

```python
ADMIN_SCHEDULE_SLOT_DELETED_TEXT = "Окошко удалено ✨"
```

```python
ADMIN_SCHEDULE_SLOT_BLOCKED_TEXT = "Окошко заблокировано 🤍"
```

```python
ADMIN_SCHEDULE_SLOT_UNBLOCKED_TEXT = "Окошко снова открыто ✨"
```

```python
ADMIN_SCHEDULE_NO_SHOW_MARKED_TEXT = "Отметила no-show и обновила риски клиентки."
```

```python
ADMIN_SCHEDULE_MOVE_PROMPT_TEXT = """✏️ ПЕРЕНОС ОКОШКА

Пришли новую дату и время одним сообщением.

📇 Формат: 25.04 17:00"""
```

```python
ADMIN_SCHEDULE_MOVE_INVALID_TEXT = (
    "Не смогла разобрать дату и время. Формат: 25.04 17:00"
)
```

```python
ADMIN_SCHEDULE_MOVE_COLLISION_TEXT = "Это время уже в расписании. Пришли другое 🤍"
```

```python
ADMIN_SCHEDULE_MOVE_BOOKED_FORBIDDEN_TEXT = "Записанное окошко нельзя перенести отсюда 🤍"
```

```python
ADMIN_SCHEDULE_MOVE_DONE_TEXT = "✨ Перенесла"
```

```python
ADMIN_SCHEDULE_MONTH_HEADER_TEXT = """📅 РАСПИСАНИЕ НА 30 ДНЕЙ

Ниже — все окошки, сгруппированные по дням 👇"""
```

```python
ADMIN_SCHEDULE_MONTH_EMPTY_TEXT = "На ближайшие 30 дней окошек пока нет 🤍"
```

```python
ADMIN_RATE_LIMIT_ALERT_TEXT = """🚨 RATE-LIMIT ПРЕВЫШЕН

За последний час:

{lines}"""
```

---

## Админ — все записи (новый блок H)

```python
ADMIN_ALL_BOOKINGS_EMPTY_TEXT = "За этот период записей нет 🤍"
```

```python
ADMIN_ALL_BOOKINGS_IMAGE_CAPTION_TEXT = "🖼 Картинка записей за выбранный период 👆"
```

```python
ADMIN_ALL_BOOKINGS_IMAGE_FAILED_TEXT = "Не удалось собрать картинку записей: {error}"
```

```python
ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT = "Не нашла эту запись 🤍"
```

```python
# Заголовок страницы (рендерит хендлер, вставляет {page}/{pages} и период)
ADMIN_ALL_BOOKINGS_HEADER_TEXT = """📋 ВСЕ ЗАПИСИ · стр. {page}/{pages}

📇 Период: {period}

{body}"""
```

---

## Админ — фоны

```python
ADMIN_BACKGROUNDS_HOME_TEXT = """🎨 ФОНЫ

Выбери, какой фон редактируем 👇"""
```

```python
ADMIN_BACKGROUND_KIND_TEXT = """🎨 {title}

Можно:
┣ 📤 загрузить новый фон
┣ 🔄 сбросить к стандартному
┗ 👁 посмотреть предпросмотр"""
```

```python
ADMIN_BACKGROUND_UPLOAD_PROMPT_TEXT = """📤 НОВЫЙ ФОН

Пришли одно фото — оно станет новым фоном для «{title}» ✨"""
```

```python
ADMIN_BACKGROUND_UPLOAD_SAVED_TEXT = "Фон обновила ✨"
```

```python
ADMIN_BACKGROUND_UPLOAD_NO_PHOTO_TEXT = "Это не фото. Пришли изображение из галереи 🤍"
```

```python
ADMIN_BACKGROUND_UPLOAD_FAILED_TEXT = "Не удалось сохранить фон: {error}"
```

```python
ADMIN_BACKGROUND_RESET_TEXT = "Фон сбросила — вернулась к стандартному 🤍"
```

```python
ADMIN_BACKGROUND_PREVIEW_CAPTION_TEXT = "👁 Предпросмотр фона: {title}"
```

---

## Админ — услуги (services CRUD)

```python
ADMIN_SERVICES_HEADER_TEXT = """💼 УСЛУГИ

Ниже все услуги, включая скрытые 👇"""
```

```python
ADMIN_SERVICES_EMPTY_TEXT = "Услуг пока нет. Можно добавить первую ✨"
```

```python
ADMIN_SERVICE_ADD_NAME_TEXT = """✏️ НОВАЯ УСЛУГА

Как она называется?"""
```

```python
ADMIN_SERVICE_ADD_PRICE_TEXT = """💰 Цена в рублях.

Если цена плавающая — введи 0."""
```

```python
ADMIN_SERVICE_ADD_DURATION_TEXT = "🕑 Сколько минут закладывать по умолчанию?"
```

```python
ADMIN_SERVICE_ADD_KIND_TEXT = "💅 Это базовая услуга или дополнение?"
```

```python
ADMIN_SERVICE_ADD_VARIABLE_TEXT = "💰 Цена плавающая?"
```

```python
ADMIN_SERVICE_ADD_CONFIRM_TEXT = """✨ НОВАЯ УСЛУГА

📇 Проверим:
┣ Название: {name}
┣ Цена: {price}₽
┣ Длительность: {duration_min} мин
┣ Тип: {kind}
┗ Плавающая цена: {price_variable}

Всё верно?"""
```

```python
ADMIN_SERVICE_CREATED_TEXT = "Услуга добавлена ✨"
```

```python
ADMIN_SERVICE_UPDATED_TEXT = "Изменение сохранено 🤍"
```

```python
ADMIN_SERVICE_VISIBILITY_TEXT = "Видимость обновила ✨"
```

```python
ADMIN_SERVICE_DELETE_FORBIDDEN_TEXT = (
    "Эту услугу уже используют записи или запросы, поэтому лучше скрыть её, а не удалять 🤍"
)
```

```python
ADMIN_SERVICE_DELETED_TEXT = "Услуга удалена ✨"
```

```python
ADMIN_SERVICE_EDIT_FIELD_TEXT = "Что меняем?"
```

```python
ADMIN_SERVICE_EDIT_NAME_TEXT = "✏️ Введи новое название."
```

```python
ADMIN_SERVICE_EDIT_PRICE_TEXT = "💰 Введи новую цену в рублях."
```

```python
ADMIN_SERVICE_EDIT_DURATION_TEXT = "🕑 Введи новую длительность в минутах."
```

```python
ADMIN_SERVICE_EDIT_INVALID_TEXT = "Не смогла принять это значение. Попробуй ещё раз 🤍"
```

---

## Админ — клиенты

```python
ADMIN_CLIENTS_HOME_TEXT = """👥 КЛИЕНТЫ

Можно быстро найти клиентку по имени или открыть полный список 👇"""
```

```python
ADMIN_CLIENTS_PROMPT_TEXT = """🔍 ПОИСК КЛИЕНТКИ

Напиши имя или @username одним сообщением ✨"""
```

```python
ADMIN_CLIENTS_EMPTY_TEXT = "Никого не нашла 🤍 Попробуй другой запрос."
```

```python
ADMIN_CLIENTS_PICK_TEXT = "Нашла несколько совпадений. Открой нужную карточку 👇"
```

```python
ADMIN_CLIENTS_LIST_EMPTY_TEXT = "Пока нет ни одной клиентки 🤍"
```

```python
ADMIN_CLIENTS_LIST_TEXT = """👥 КЛИЕНТЫ

📇 Навигация:
┣ Страница: {page} из {pages}
┗ Всего клиенток: {total}"""
```

```python
ADMIN_CLIENT_NOTE_PROMPT_TEXT = """✏️ ЗАМЕТКА

Пришли новую заметку одним сообщением.
Если хочешь очистить, отправь `-`."""
```

```python
ADMIN_CLIENT_NOTE_SAVED_TEXT = "Заметку сохранила ✨"
```

```python
ADMIN_CLIENT_MESSAGE_PROMPT_TEXT = """💬 СООБЩЕНИЕ КЛИЕНТКЕ

Пришли одно сообщение — текстом, фото или голосовым ✨"""
```

```python
ADMIN_CLIENT_MESSAGE_SENT_TEXT = "Сообщение отправлено клиентке ✨"
```

```python
ADMIN_CLIENT_BLOCKED_TEXT = "Клиентка заблокирована 🤍"
```

```python
ADMIN_CLIENT_UNBLOCKED_TEXT = "Клиентка разблокирована ✨"
```

```python
ADMIN_CLIENT_SHADOW_BANNED_TEXT = "🔕 Shadow-ban включён"
```

```python
ADMIN_CLIENT_SHADOW_UNBANNED_TEXT = "🔔 Shadow-ban снят"
```

```python
ADMIN_CLIENT_STRIKES_RESET_TEXT = "♻️ Strikes сброшены"
```

```python
ADMIN_CLIENT_MANUAL_APPROVAL_CLEARED_TEXT = "🔓 Ручное подтверждение снято"
```

---

## Админ — статистика

```python
ADMIN_STATS_TITLE_TEXT = """📊 СТАТИСТИКА

Ниже основные цифры за выбранный период 👇"""
```

---

## Админ — рассылка

```python
ADMIN_BROADCAST_PROMPT_TEXT = """✉️ РАССЫЛКА

📇 Отправим на {count} клиенток.

Пришли текст рассылки — можно использовать Telegram MarkdownV2."""
```

```python
ADMIN_BROADCAST_PREVIEW_TEXT = "👁 Превью рассылки 👇"
```

```python
ADMIN_BROADCAST_INVALID_TEXT = (
    "Не смогла показать превью с MarkdownV2. Проверь текст и попробуй ещё раз 🤍"
)
```

```python
ADMIN_BROADCAST_STARTED_TEXT = "Рассылка запущена. Отправляю аккуратно, без спама ✨"
```

```python
ADMIN_BROADCAST_CANCELLED_TEXT = "Рассылку отменила 🤍"
```

```python
ADMIN_BROADCAST_REPORT_TEXT = """✨ РАССЫЛКА ЗАВЕРШЕНА

📇 Итог:
┣ Доставлено: {delivered}
┣ Заблокировали / удалили: {blocked}
┗ Ошибки: {failed}"""
```

---

## Админ — шаблоны текстов

```python
ADMIN_TEMPLATES_HEADER_TEXT = """📝 ШАБЛОНЫ

Ниже все редактируемые тексты бота 👇"""
```

```python
ADMIN_TEMPLATES_HOME_TEXT = """📝 ШАБЛОНЫ

Выбери раздел 👇"""
```

```python
ADMIN_TEMPLATES_CATEGORY_TEXT = """📝 ШАБЛОНЫ · {category_title}

{items_text}"""
```

```python
ADMIN_TEMPLATES_VARIABLES_TEXT = """📇 Доступные переменные:

{variables}"""
```

```python
ADMIN_TEMPLATES_NO_VARIABLES_TEXT = "Без переменных."
```

```python
ADMIN_TEMPLATE_DETAIL_TEXT = """✏️ {title}

📇 Когда отправляется:
{description}

📇 Текущий текст:
{content}

{variables_block}

Пришли новый текст — он заменит этот 🤍"""
```

```python
ADMIN_TEMPLATE_EDIT_PROMPT_TEXT = "✏️ Пришли новый текст шаблона одним сообщением."
```

```python
ADMIN_TEMPLATE_EDIT_CANCEL_TEXT = "Редактирование шаблона отменила 🤍"
```

```python
ADMIN_TEMPLATE_SAVED_TEXT = "Шаблон обновила ✨"
```

---

## Админ — настройки

```python
ADMIN_SETTINGS_HEADER_TEXT = """⚙️ НАСТРОЙКИ

Ниже редактируемые параметры бота 👇"""
```

```python
ADMIN_SETTINGS_VALUE_PROMPT_TEXT = "Пришли новое значение одним сообщением."
```

```python
ADMIN_SETTINGS_EDIT_PROMPT_TEXT = """⚙️ {title}

{prompt}"""
```

```python
ADMIN_SETTINGS_SAVED_TEXT = "Настройку сохранила ✨"
```

```python
ADMIN_SETTINGS_INVALID_TZ_TEXT = "Не нашла такой часовой пояс. Пример: Europe/Moscow 🤍"
```

```python
ADMIN_SETTINGS_INVALID_INT_TEXT = "Нужно целое число больше нуля 🤍"
```

---

## Картинки — заголовки и подписи

```python
# Дефолты шаблонов (src/services/admin_defaults.py)
DEFAULT_SCHEDULE_IMAGE_HEADER = "СВОБОДНЫЕ ОКОШКИ"
DEFAULT_SCHEDULE_IMAGE_FOOTER = "ANGELS NAIL SPACE"
DEFAULT_PRICE_IMAGE_HEADER = "УСЛУГИ И ЦЕНЫ"
DEFAULT_PRICE_IMAGE_NOTE = (
    "Дизайн и длина считаются отдельно — итоговую стоимость "
    "Ангела подскажет после референса или на месте 🤍"
)
DEFAULT_BOOKINGS_IMAGE_HEADER = "ЗАПИСИ"
```

```python
BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT = """📅 СВОБОДНЫЕ ОКОШКИ

На картинке — ближайшие дни.
Выбери удобный день ниже 👇"""
```

---

## Картинка-расписание — админский раздел

```python
ADMIN_SCHEDULE_IMAGE_MENU_TEXT = """🖼 КАРТИНКА РАСПИСАНИЯ

Бот может присылать клиенту красивое расписание картинкой перед выбором дня.

📇 Что можно здесь:
┣ 📤 загрузить фон (одно фото из галереи)
┣ 👁 посмотреть превью
┗ 🔘 включить / выключить показ"""
```

```python
ADMIN_SCHEDULE_IMAGE_UPLOAD_PROMPT_TEXT = """📤 НОВЫЙ ФОН

Пришли одно фото — оно станет фоном.
Отправлять не сжимая не обязательно ✨"""
```

```python
ADMIN_SCHEDULE_IMAGE_UPLOAD_SAVED_TEXT = "Фон обновила ✨"
```

```python
ADMIN_SCHEDULE_IMAGE_UPLOAD_FAILED_TEXT = "Не удалось сохранить фон: {error}"
```

```python
ADMIN_SCHEDULE_IMAGE_UPLOAD_NO_PHOTO_TEXT = "Это не фото. Пришли изображение из галереи 🤍"
```

```python
ADMIN_SCHEDULE_IMAGE_BACKGROUND_RESET_TEXT = (
    "Фон сбросила — бот снова сгенерирует мягкий градиент по умолчанию 🤍"
)
```

```python
ADMIN_SCHEDULE_IMAGE_BACKGROUND_CUSTOM_TEXT = "🖼 Фон: загружено своё фото ✅"
```

```python
ADMIN_SCHEDULE_IMAGE_BACKGROUND_DEFAULT_TEXT = "🖼 Фон: мягкий градиент по умолчанию"
```

```python
ADMIN_SCHEDULE_IMAGE_PREVIEW_CAPTION_TEXT = "👁 Превью текущей картинки расписания 👆"
```

```python
ADMIN_SCHEDULE_IMAGE_PREVIEW_FAILED_TEXT = "Не удалось собрать превью: {error}"
```

```python
ADMIN_SCHEDULE_IMAGE_PREVIEW_NO_SLOTS_TEXT = (
    "Свободных окошек пока нет — на картинке будет только заголовок и подпись 🤍"
)
```

```python
ADMIN_SCHEDULE_IMAGE_ENABLED_TEXT = "🖼 Картинка расписания: сейчас клиенты её видят ✅"
```

```python
ADMIN_SCHEDULE_IMAGE_DISABLED_TEXT = "🖼 Картинка расписания: сейчас клиентам не показывается"
```

```python
ADMIN_SCHEDULE_IMAGE_OVERRIDE_HINT_TEXT = (
    "Если нужно переписать текст вручную — шаблон «schedule_image_text_override» "
    "в разделе 📝 Шаблоны. Пустой шаблон = авто из слотов 🤍"
)
```

---

## Что НЕ трогаем (служебно-технические)

Эти константы оставляем как есть — их видит только Ангела как dev-инструмент:

- `BOT_IS_ALIVE_TEXT`
- `GOOGLE_TEST_*`, `SAVE_PHOTO_*`, `CALENDAR_TEST_*`
- `GOOGLE_TEST_LOADING_TEXT`, `SAVE_PHOTO_LOADING_TEXT`, `CALENDAR_TEST_LOADING_TEXT`

---

## Что делать Codex'у с этим файлом

1. Открой `src/bot/texts.py`, пройди константы по этому файлу сверху вниз,
   замени значения. Имена констант и `{плейсхолдеры}` НЕ меняй.
2. Для констант с префиксом `DEFAULT_…_TEMPLATE` / `DEFAULT_…_HEADER` / `DEFAULT_…_NOTE` —
   обнови также `src/services/admin_defaults.py::required_template_defaults()` и все
   сопутствующие дефолт-маппинги. Уже сохранённые в БД админские оверрайды не перезаписывай —
   миграция не нужна, просто обнови дефолты для новых инсталляций.
3. Если в ходе изменений наткнёшься на константу из `texts.py`, которой нет в этом файле —
   она либо служебная (см. раздел «Что НЕ трогаем»), либо её забыли здесь. В спорных случаях
   оставляй текущий текст как есть и добавь комментарий `# TODO: phase11 texts review`.
4. Прогони `ruff format` — длинные многострочные триплет-строки надо оставить как в этом файле.
5. Обнови/добавь снепшоты тестов, если сейчас тесты сравнивают полные строки —
   перепиши их под новые.

После этого визуально пройди клиентский и админский флоу — проверь, что tree-буллеты
`┣` и `┗` рендерятся в Telegram нормально (они Unicode, проблем быть не должно).
