GENERIC_ERROR_TEXT = "Что-то пошло не так — попробуй ещё раз 🤍"
GOOGLE_TEST_SUCCESS_TEXT = """Google интеграция работает ✅

Таблица: {sheet_title}
Диапазон: {updated_range}
Файл: {drive_file_name}
Drive ID: {drive_file_id}"""
GOOGLE_TEST_FAILED_TEXT = "Google проверка упала: {error}"
SAVE_PHOTO_USAGE_TEXT = (
    "отправь фото с подписью /save_photo или ответь командой /save_photo на сообщение с фото"
)
SAVE_PHOTO_SUCCESS_TEXT = """Фото загружено ✅

Папка: {folder_path}
Файл: {file_name}
Drive ID: {file_id}"""
SAVE_PHOTO_FAILED_TEXT = "Не удалось загрузить фото: {error}"
CALENDAR_TEST_SUCCESS_TEXT = """Google Calendar работает ✅

Календарь: {calendar_summary}
Событие: {event_summary}
Начало: {start_at}
Конец: {end_at}
Event ID: {event_id}"""
CALENDAR_TEST_FAILED_TEXT = "Google Calendar проверка упала: {error}"
GOOGLE_TEST_LOADING_TEXT = "Секунду, проверяю Google Sheets и Drive ✨"
SAVE_PHOTO_LOADING_TEXT = "Сохраняю фото в Google Drive ✨"
CALENDAR_TEST_LOADING_TEXT = "Проверяю календарь и собираю тестовое событие ✨"

MENU_HEADER = """🌸 Привет, я бот Ангелы

Помогу записаться, напомню о визите и подскажу, как добраться — спокойно и без лишней суеты.

Что можно здесь:

┣ 📅 Посмотреть окошки и записаться
┣ 💰 Открыть актуальный прайс
┣ 📍 Узнать адрес и построить маршрут
┣ 🌸 Познакомиться с Ангелой и посмотреть работы
┗ 💬 Написать Ангеле напрямую

Выбирай раздел ниже 👇"""

GREETING_LAPSED_ADDON = (
    "🌸 С возвращением, {display_name}! Давно не виделись — рада, что снова здесь.\n\n"
)

PORTFOLIO_INTRO = """📸 РАБОТЫ И НАСТРОЕНИЕ

Свежие дизайны и новые работы Ангела выкладывает в Telegram-канале.

Открой кнопку ниже — загляни, там все последние дизайны. ✨"""

DEFAULT_ABOUT_MASTER_TEMPLATE = """🌸 Знакомься — это Ангела

Ангела делает аккуратный, чистый маникюр в спокойной атмосфере — без спешки и лишнего шума.

Любит мягкие формы, носибельные оттенки и чтобы тебе было по-настоящему комфортно в кресле.

Если хочешь посмотреть свежие работы — открой канал ниже.
Если удобнее сначала уточнить детали — можно сразу написать Ангеле напрямую ✨"""

DEFAULT_ADDRESS_PUBLIC_TEMPLATE = (
    "📍 АДРЕС И КАК ДОБРАТЬСЯ\n\n"
    "Очаковское шоссе, 5к3, подъезд 2\n\n"
    "Маршрут откроется по кнопке ниже.\n\n"
    "Если захочешь уточнить дорогу заранее — можно сразу написать Ангеле 🌸"
)

DEFAULT_ADDRESS_POST_CONFIRM = (
    "📍 АДРЕС\n\n"
    "Очаковское шоссе, 5к3, подъезд 2\n\n"
    "Маршрут откроется по кнопке ниже.\n\n"
    "Если что-то по дороге пойдёт не так — просто напиши, Ангела поможет 🌸"
)

DEFAULT_RULES = """🤍 ПРАВИЛА ВИЗИТА

┣ 💬 Если планы поменялись — напиши заранее
┣ ⏰ Постарайся не опаздывать
┗ ✨ О важных деталях по рукам или покрытию — предупреди

Всё простое, чтобы нам обеим было комфортно 🤍"""

DEFAULT_VACATION_NOTICE = """🌸 ЗАПИСЬ ВРЕМЕННО ЗАКРЫТА

Сейчас окошек нет, но скоро Ангела откроет новые.

Как только появятся — бот покажет их здесь ✨"""

DEFAULT_BOOKING_CONFIRM_TEMPLATE = """<b>Записала тебя ✨</b>

────────────

<b>📅 {date} · {time}</b>
💅 <b>{service}</b>
💳 <b>{payment}</b>

────────────

{address_block}

────────────

✨ Напомню за сутки и за 2 часа.

Если вдруг задержишься больше чем на 15 минут —
запись может отмениться 🤍

Если что-то изменится —
жми «Мои записи» в меню 🤍

До встречи 🌸"""

DEFAULT_REMINDER_24H_TEMPLATE = """🌸 Привет 🤍

Напоминаю о записи:

┣ 📅 {date}, в {time}
┣ 💅 {service}
┗ 📍 {address_short}

Если вдруг задержишься больше чем на 15 минут —
запись может отмениться 🤍

Всё в силе?"""

DEFAULT_REMINDER_2H_TEMPLATE = """⏰ ЧЕРЕЗ ПАРУ ЧАСОВ

Сегодня в {time} — жду тебя 🤍

Если вдруг задержишься больше чем на 15 минут —
запись может отмениться 🤍

Если вдруг не успеваешь, напиши."""

DEFAULT_LATE_NOTICE_INTRO_TEMPLATE = """⏰ ОПОЗДАНИЕ

Если понимаешь, что не успеваешь, предупреди здесь — я быстро передам Ангеле.

Выбери, на сколько минут задерживаешься 👇"""

DEFAULT_POSTVISIT_TEMPLATE = """🌸 Спасибо, что сегодня пришла

Очень рада была тебя видеть 🫶

Надеюсь, тебе понравился результат и атмосфера 🤍

Если будет минутка — расскажи, всё ли тебе понравилось.

Мне важно, чтобы каждая девочка чувствовала себя комфортно 🫂"""

DEFAULT_REPEAT_PROMPT_TEMPLATE = """🌸 Привет 🤍

Прошло немного времени с нашей встречи.

Если захочешь снова — я буду рада тебя видеть ✨"""

DEFAULT_REPAIR_INTRO_TEMPLATE = """🛠 РЕМОНТ / ГАРАНТИЯ

Если после визита что-то скололось, треснуло или отошло — здесь можно оставить заявку на ремонт.

Ангела смотрит каждую ситуацию отдельно.
По гарантии обычно рассматриваются до 2 ноготков в течение 14 дней после визита 🤍"""

DEFAULT_REPAIR_REQUEST_RECEIVED_TEMPLATE = """🛠 ЗАЯВКУ ПРИНЯЛА

Передала всё Ангеле: фото, описание и детали.

Она посмотрит, что случилось, и вернётся с решением или предложит время ✨"""

DEFAULT_REPAIR_WARRANTY_OFFER_TEMPLATE = """🌸 АНГЕЛА ПРЕДЛАГАЕТ РЕМОНТ

📅 {date}
🕐 {time}
💅 {service}

Тебе подходит это время?"""

DEFAULT_REPAIR_NOT_WARRANTY_TEMPLATE = """🤍 Ангела посмотрела заявку.

Похоже, случай не попадает под гарантию, но она свяжется и поможет согласовать ремонт вручную.

Если повреждено 3+ ноготков, ориентир может быть около 200 ₽ за ноготь.
Точнее Ангела подскажет после просмотра."""

DEFAULT_REPAIR_DECLINED_TEMPLATE = """🤍 Ангела посмотрела заявку,
но пока не может подтвердить ремонт в таком формате.

Если нужно, она уточнит детали отдельно и предложит, как лучше поступить."""

NO_BOOKINGS_YET_TEXT = """🤍 ПОКА НИ ОДНОЙ ЗАПИСИ

Когда запишешься — она появится здесь ✨"""
NO_ACTIVE_SERVICES_TEXT = "Список услуг ещё не настроен. Попробуй чуть позже 🤍"

ONBOARDING_NAME_CONFIRM_TEXT = """🤍 ЗАПИСЫВАЕМСЯ

Это нужно заполнить один раз — дальше всё будет быстро.

Я вижу тебя в Telegram как «{first_name}».

Так обращаться?"""
ONBOARDING_NAME_INPUT_TEXT = """👤 Как к тебе обращаться?

Напиши имя одним сообщением ✨"""
ONBOARDING_NAME_INVALID_TEXT = "Имя должно быть от 1 до 40 символов. Попробуем ещё раз 🤍"
ONBOARDING_PHONE_TEXT = """📱 ТЕЛЕФОН

Сохраним номер один раз, чтобы Ангела могла быстро связаться, если что-то поменяется.

Нажми кнопку ниже или выбери ручной ввод 👇"""
ONBOARDING_PHONE_MANUAL_INPUT_TEXT = """📱 Напиши номер одним сообщением.

Пример: +7 900 000 00 00"""
ONBOARDING_PHONE_SAVED_TEXT = "Супер, сохранила номер ✨"
ONBOARDING_PHONE_INVALID_TEXT = """😔 Не смогла распознать номер.

Пришли его в формате +7… или поделись контактом кнопкой."""
ONBOARDING_PHONE_DUPLICATE_TEXT = """😔 Этот номер уже есть в базе.

Если это твой номер, но запись раньше оформлялась не через тебя,
лучше напиши Ангеле напрямую — она поможет аккуратно объединить карточки 🤍"""
ONBOARDING_CONTACT_FOREIGN_TEXT = (
    "Лучше отправь свой контакт кнопкой ниже или напиши номер вручную 🤍"
)
BUTTON_CHOICE_HINT_TEXT = "Здесь лучше нажать одну из кнопок ниже 👇"
BOOKING_CHOOSE_DAY_TEXT = """📆 ВЫБЕРИ ДЕНЬ

Ниже — свободные дни на ближайшее время 👇"""
BOOKING_CHOOSE_TIME_TEXT = """🕑 ТЕПЕРЬ ВРЕМЯ

Выбери удобный час 👇"""
BOOKING_CHOOSE_PAYMENT_TEXT = """💳 КАК УДОБНЕЕ ОПЛАТИТЬ?

Наличными Ангеле предпочтительнее, но перевод тоже можно выбрать.

Выбери способ оплаты 👇"""
BOOKING_NO_SLOTS_TEXT = """😔 Жаль, окошек пока нет

Свободные часы разобрали. Бывает.

Можно дождаться новых — Ангела открывает их регулярно.
Или написать ей напрямую: вдруг получится найти что-то под тебя 🤍"""
BOOKING_REFERENCE_PROMPT_TEXT = """📸 РЕФЕРЕНСЫ

Хочешь приложить фото дизайна, который нравится?

Можно до 5 штук."""
BOOKING_REFERENCE_WAITING_TEXT = """Пришли до 5 фото.

После каждого можно добавить комментарий или сразу нажать «Готово» ✨"""
BOOKING_REFERENCE_LIMIT_TEXT = "Можно приложить до 5 фото. Если всё готово — нажми «Готово»."
BOOKING_REFERENCE_COMMENT_INPUT_TEXT = "💬 Напиши комментарий к референсам одним сообщением."
BOOKING_REFERENCE_COMMENT_SAVED_TEXT = "Сохранила комментарий ✨"
BOOKING_CONFIRM_SLOT_TAKEN_TEXT = """😔 Это окошко только что заняли

Бывает — пока ты выбирала, его кто-то успел забронировать.

Не страшно, ниже свободные часы на этот же день 🤍"""
BOOKING_CONFIRM_SLOT_TAKEN_FOLLOWUP_TEXT = "Вот что осталось на этот день 👇"
BOOKING_CANCELLED_TEXT = "Хорошо, запись не оформляю 🤍"
BOOKING_STALE_DATA_TEXT = """Не получилось собрать запись: данные уже изменились.

Попробуй выбрать услугу и время ещё раз 🤍"""
BOOKING_RETRY_LATER_TEXT = (
    "Подождём ещё {minutes} мин и попробуем снова 🤍\n\nЕсли хочешь — напиши Ангеле напрямую."
)
BOOKING_BLOCKED_TEXT = """К сожалению, запись через бота сейчас недоступна.

Если хочешь обсудить — напиши Ангеле напрямую 🤍"""
BOOKING_ACTIVE_LIMIT_TEXT = """🤍 У тебя уже есть активная запись

Новую запись удобнее создать после завершения текущей.

Если планы изменились — открой «Мои записи» или напиши Ангеле напрямую."""
BOOKING_ATTEMPT_LIMIT_TEXT = (
    "Сейчас было слишком много попыток записи подряд. "
    "Давай сделаем небольшую паузу и попробуем позже 🤍"
)
BOOKING_PENDING_APPROVALS_LIMIT_TEXT = (
    "У тебя уже есть ожидающие запросы, дождись, пожалуйста, ответа Ангелы 🤍"
)
POST_BOOKING_MY_BOOKINGS_BUTTON_TEXT = "🙋‍♀️ Мои записи"
POST_BOOKING_MENU_BUTTON_TEXT = "🏠 В меню"
POST_BOOKING_REFERENCE_BUTTON_TEXT = "📸 Приложить референсы"
BOOKING_POST_REFERENCE_DONE_TEXT = "Референсы добавлены ✨"
BOOKING_CUSTOM_TIME_NEW_BOOKING_PROMPT_TEXT = """💬 ДРУГОЕ ВРЕМЯ

Напиши, когда тебе было бы удобно для новой записи — я передам Ангеле 🌸

Можно конкретно: «22.04 в 13:00»

Или общо: «после работы, после 19, кроме вторника»"""
BOOKING_CUSTOM_TIME_RESCHEDULE_PROMPT_TEXT = """💬 ДРУГОЕ ВРЕМЯ ДЛЯ ПЕРЕНОСА

Напиши, когда тебе было бы удобно перенести текущую запись — я передам Ангеле 🌸

Можно конкретно: «22.04 в 13:00»

Или общо: «после работы, после 19, кроме вторника»"""
APPROVAL_NEW_BOOKING_SENT_TEXT = """✨ ОТПРАВИЛА АНГЕЛЕ ЗАПРОС НА ЗАПИСЬ

Как только она посмотрит варианты, я сюда вернусь с ответом 🌸"""
APPROVAL_RESCHEDULE_SENT_TEXT = """✨ ОТПРАВИЛА АНГЕЛЕ ЗАПРОС НА ПЕРЕНОС

Как только она посмотрит варианты, я сюда вернусь с ответом 🌸"""
APPROVAL_CUSTOM_TIME_SENT_TEXT = """✨ ПЕРЕДАЛА АНГЕЛЕ ТВОИ ПОЖЕЛАНИЯ ПО ВРЕМЕНИ

Как только она посмотрит варианты, я сюда вернусь с ответом 🌸"""
ASK_MASTER_PROMPT_TEXT = """💬 ВОПРОС АНГЕЛЕ

Напиши сообщение — можно текстом, фото или голосовым ✨"""
ASK_MASTER_SENT_TEXT = """✨ Передала сообщение Ангеле

Как только она ответит, я напишу сюда 🌸"""
ASK_MASTER_LIMIT_TEXT = (
    "Я уже передала Ангеле твои сообщения за сегодня 🌸\n\n"
    "Если что-то срочное — попробуй завтра, а пока загляни в «Мои записи»."
)
DESIGN_PHOTO_OUTSIDE_FLOW_TEXT = """📸 Красивый дизайн 🤍

Я не умею оценивать его сама — передам Ангеле,
как только ты оформишь запись или попросишь.

Что делаем дальше?"""
DESIGN_PHOTO_CANCELLED_TEXT = "Хорошо, ничего не отправляю 🤍"
CLIENT_FALLBACK_TEXT = """🌸 Не совсем поняла тебя

Я бот-помощник Ангелы — могу записать на маникюр,
напомнить о визите или передать сообщение мастеру.

Выбери, что подходит 👇"""
PROXY_REPLY_PROMPT_TEXT = "💬 Напиши сообщение для Ангелы одним сообщением."
PROXY_REPLY_SENT_TEXT = "Передала сообщение Ангеле ✨"
PROXY_MESSAGE_LIMIT_TEXT = (
    "Передала Ангеле всё, что было за этот час 🤍\n\nПодожди немного, она прочитает и ответит."
)
CLIENT_RESCUE_SLOT_TEXT = """🌸 Освободилось окошко у Ангелы

📅 {date}
🕑 {time}

Если тебе подходит, можно быстро выбрать услугу и забрать это время ✨"""
CLIENT_RESCUE_SLOT_EXPIRED_TEXT = """😔 Это окошко уже забрали

Если хочешь, покажу актуальные свободные варианты ниже 🌸"""
CLIENT_RESCUE_SLOT_DISMISSED_TEXT = "Хорошо, не буду отвлекать этим окошком 🌸"

REMINDER_24H_TEXT = """🌸 Привет, {display_name} 🤍

Напоминаю о записи:

┣ 📅 {date}, в {time}
┣ 💅 {service_name}
┗ 📍 {address_short}

Если вдруг задержишься больше чем на 15 минут —
запись может отмениться 🤍

Всё в силе?"""
REMINDER_2H_TEXT = """⏰ ЧЕРЕЗ ~2 ЧАСА ЖДУ ТЕБЯ 🤍

┣ 🕑 {time}
┗ 💅 {service_name}

Если вдруг задержишься больше чем на 15 минут —
запись может отмениться 🤍

Если вдруг не успеваешь — напиши."""
LATE_POLICY_CONFIRMATION_NOTICE_TEXT = (
    "Если вдруг задержишься больше чем на 15 минут —\n"
    "запись может отмениться 🤍"
)
REMINDER_CONFIRMED_TEXT = "Супер, жду тебя 🤍"
REMINDER_ACK_NOTICE_TEXT = "Отметила 🤍"
REMINDER_STALE_TEXT = "Эта кнопка уже неактуальна 🤍"
REMINDER_MANAGE_BOOKING_TEXT = """🌸 Здесь можно быстро перенести или отменить именно эту запись.

Если планы поменялись — выбери нужное действие ниже."""
LATE_NOTICE_REASON_PROMPT_TEXT = """⏰ ПОНЯЛА

Теперь выбери причину или пропусти 👇"""
LATE_NOTICE_OTHER_REASON_PROMPT_TEXT = "✏️ Напиши коротко, что случилось одним сообщением."
LATE_NOTICE_OTHER_REASON_INVALID_TEXT = "Нужен один короткий комментарий одним сообщением 🤍"
LATE_NOTICE_UPDATED_TOAST = "Передала Ангеле ✨"
LATE_NOTICE_ACKNOWLEDGED_TOAST = "Учла 🤍"
LATE_NOTICE_CLIENT_SENT_DEFAULT_TEXT = """⏰ Передала Ангеле,
что ты задерживаешься на {minutes} мин.

Если что-то изменится, можешь отправить обновление ещё раз из карточки записи."""
LATE_NOTICE_CLIENT_RISKY_DEFAULT_TEXT = """⏰ Передала Ангеле,
что ты задерживаешься на {minutes} мин.

Если опоздание будет большим, часть услуги может сократиться или может понадобиться перенос 🤍"""
LATE_NOTICE_CLIENT_UPDATED_TEXT = "Обновила информацию для Ангелы ✨"
LATE_NOTICE_NEED_ACTIVE_BOOKING_TEXT = (
    "Сейчас для этой записи предупредить об опоздании уже нельзя 🤍"
)
LATE_NOTICE_PHOTO_HINT_TEXT = "Здесь нужен выбор кнопкой или короткий текст, без фото 🤍"
LATE_NOTICE_ADMIN_NOT_FOUND_TEXT = "Это опоздание уже неактуально 🤍"
POSTVISIT_RATE_ACK_NOTICE_TEXT = "Спасибо 🤍"
POSTVISIT_PROMPT_TEXT = """✨ КАК ВСЁ ПРОШЛО?

Поставь оценку ниже — это помогает Ангеле расти 🤍"""
POSTVISIT_THANK_YOU_TEXT = "Спасибо большое за оценку 🤍"

DEFAULT_POSTVISIT_RATING_5_TEMPLATE = """🌸 Спасибо большое!

Очень рада, что всё понравилось.
Если будет минутка — оставь, пожалуйста, отзыв или расскажи знакомым:
для меня это лучшая поддержка."""

DEFAULT_POSTVISIT_RATING_MID_TEMPLATE = """🤍 Спасибо за оценку

Расскажи, пожалуйста, что можно сделать лучше — постараюсь учесть в следующий раз.
Просто напиши пару слов следующим сообщением, я прочитаю."""

DEFAULT_POSTVISIT_RATING_LOW_TEMPLATE = """🤍 Жаль, что так получилось

Очень хочу разобраться.
Напиши, пожалуйста, что не так — отвечу лично и постараюсь исправить ситуацию."""

POSTVISIT_FEEDBACK_THANK_YOU_TEXT = "Спасибо, передала Ангеле 🤍"
REPEAT_PROMPT_TEXT = """🌸 {display_name}, привет 🤍

Уже почти три недельки прошло с твоего визита — если захочешь, можно быстро повторить запись 🌸

Ниже — свободные окошки у Ангелы ✨"""
REPEAT_PROMPT_LATER_TEXT = "Хорошо, пока не трогаю. Напомню позже 🌸"
REPEAT_PROMPT_SNOOZE_1W_TEXT = "Хорошо, напомню через неделю 🌸"
REPEAT_PROMPT_SNOOZE_2W_TEXT = "Хорошо, напомню через две недели 🌸"
REPEAT_PROMPT_STOP_TEXT = "Поняла, пока больше не напоминаю 🌸"

DEFAULT_WINBACK_TEMPLATE = """🌸 {display_name}, соскучились!

Давно тебя не было — больше двух месяцев. Всё в порядке?

Если готова вернуться — вот свободные окошки у Ангелы ✨"""

MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT = (
    "Похоже, по этой записи всё уже изменилось. Открой актуальную карточку ещё раз 🤍"
)
MY_BOOKINGS_CANCEL_PRE_CONFIRM_TEXT = """❓ Точно отменить запись?

Это действие нельзя отменить 🤍"""
MY_BOOKINGS_CANCEL_REASON_TEXT = """💬 Что случилось?

Напиши причину — ничего страшного, это просто для статистики 🤍"""
MY_BOOKINGS_CANCEL_WARNING_TEXT = """⚠️ ДО ВИЗИТА ОСТАЛОСЬ МАЛО ВРЕМЕНИ

Меньше {hours} ч — Ангела может не успеть заполнить окошко.

Точно отменить?"""
MY_BOOKINGS_CANCEL_OTHER_REASON_TEXT = "💬 Напиши причину одним сообщением."
MY_BOOKINGS_CANCEL_OTHER_REASON_INVALID_TEXT = "Напиши причину одним сообщением, пожалуйста 🤍"
MY_BOOKINGS_CANCEL_DONE_TEXT = "Записала отмену 🤍"
MY_BOOKINGS_CANCEL_LT24H_TEXT = """Записала отмену 🤍

Маленькая просьба: в следующий раз постарайся предупредить заранее —
так мне проще передать окошко другой девочке.

Спасибо за понимание ✨"""
MY_BOOKINGS_CARD_MISSING_TEXT = "Похоже, эта запись уже изменилась или исчезла 🤍"
MY_BOOKINGS_RESCHEDULE_DAY_TEXT = """📆 ПЕРЕНОС ЗАПИСИ

Выбери новый день 👇"""
MY_BOOKINGS_RESCHEDULE_TIME_TEXT = """🕑 НОВОЕ ВРЕМЯ

Выбери удобный час 👇"""
MY_BOOKINGS_RESCHEDULE_NO_SLOTS_TEXT = "Свободных окошек для переноса пока нет 🤍"
MY_BOOKINGS_RESCHEDULED_TEXT = "Перенесла запись ✨"
ADMIN_CLIENT_RESCHEDULED_TEXT = """🔁 Клиентка перенесла запись

{name} ({username})

Было: {old_date}, {old_time}
Стало: {new_date}, {new_time}

💅 {service}"""
MY_BOOKINGS_REPAIR_PHOTO_PROMPT_TEXT = """🛠 РЕМОНТ / ГАРАНТИЯ

Пришли 1-3 фото, чтобы Ангела могла понять, что случилось.

После фото попросим коротко описать ситуацию ✨"""
MY_BOOKINGS_REPAIR_PHOTO_PROGRESS_TEXT = (
    "📸 Фото добавлены: {count}/3\n\nКогда всё готово — нажми «Готово»."
)
MY_BOOKINGS_REPAIR_NEED_PHOTO_TEXT = "Сначала пришли хотя бы одно фото 🤍"
MY_BOOKINGS_REPAIR_DESCRIPTION_PROMPT_TEXT = (
    "✏️ Теперь коротко опиши, что случилось одним сообщением."
)
MY_BOOKINGS_REPAIR_DESCRIPTION_INVALID_TEXT = "Нужен один короткий текст с описанием ситуации 🤍"
MY_BOOKINGS_REPAIR_UNAVAILABLE_TEXT = "Для этой записи сейчас нельзя отправить заявку на ремонт 🤍"

ADMIN_MENU_TEXT = """👋 Привет, Ангела

👑 АДМИН-МЕНЮ
────────────
📥 Запросов: {pending_approvals}
📅 Записей на сегодня: {today_bookings}
────────────
Выбери раздел ниже 👇"""
ADMIN_ONLY_TEXT = "Этот раздел доступен только Ангеле 🤍"
ADMIN_EMOJI_ID_PROMPT_TEXT = """✨ EMOJI ID

Пришли одним сообщением premium/custom emoji, который хочешь использовать в кнопке.

Я верну его `custom_emoji_id`, чтобы потом можно было подставить в `icon_custom_emoji_id`."""
ADMIN_EMOJI_ID_EMPTY_TEXT = (
    "Не вижу здесь premium/custom emoji 🤍\n\n"
    "Пришли именно Telegram Premium emoji, а не обычный символ."
)
ADMIN_APPROVALS_EMPTY_TEXT = """📨 ЗАПРОСЫ

Пока чисто — новых запросов нет ✨"""
ADMIN_APPROVALS_HEADER_TEXT = """📨 ЗАПРОСЫ

Ниже все pending-запросы от клиенток 👇"""
ADMIN_APPROVAL_CONFIRM_TEXT = """🗓 ПОДБЕРИ ВРЕМЯ

Выбери подходящее окошко 👇"""
ADMIN_APPROVAL_OFFER_TIME_TEXT = """🗓 ПРЕДЛОЖИ ДРУГОЕ ВРЕМЯ

Выбери подходящее окошко 👇"""
ADMIN_APPROVAL_CONFIRM_DAY_TEXT = """🗓 ПОДБЕРИ ВРЕМЯ

Сначала выбери день 👇"""
ADMIN_APPROVAL_OFFER_DAY_TEXT = """🗓 ПРЕДЛОЖИ ДРУГОЕ ВРЕМЯ

Сначала выбери день 👇"""
ADMIN_APPROVAL_CHOOSE_TIME_TEXT = """🕰 ВЫБЕРИ ВРЕМЯ

{date} 👇"""
ADMIN_REPAIR_CUSTOM_OFFER_PROMPT_TEXT = """🕰 СВОЁ ВРЕМЯ ДЛЯ РЕМОНТА

Пришли дату и время одним сообщением.

Формат: 25.04 17:00"""
ADMIN_REPAIR_CUSTOM_OFFER_INVALID_TEXT = "Не смогла разобрать дату и время. Формат: 25.04 17:00"
ADMIN_REPAIR_WARRANTY_MARKED_TEXT = "Гарантийный случай отметила ✨ Теперь можно предложить время."
ADMIN_REPAIR_PAID_MARKED_TEXT = "Отметила как платный ремонт ✨ Теперь можно предложить время."
ADMIN_REPAIR_ACCEPTANCE_REQUIRED_TEXT = "Сначала отметь: по гарантии или платно 🤍"
ADMIN_REPAIR_WARRANTY_LIMIT_CONFIRM_TEXT = """⚠️ Это больше лимита {nails_limit} ноготка.

Точно делаем по гарантии? Если да — нажми ещё раз."""
ADMIN_REPAIR_DECLINE_CONFIRM_TEXT = """⚠️ Точно отказать по гарантии?

Клиентка получит сообщение, что случай не принят по гарантии.

Это действие нельзя отменить."""
ADMIN_APPROVAL_REPLY_PROMPT_TEXT = """💬 ОТВЕТ КЛИЕНТКЕ

Пришли ответ одним сообщением.

Можно текстом, фото или голосовым ✨"""
ADMIN_APPROVAL_DECLINE_PROMPT_TEXT = """😔 ОТКАЗ

Выбери готовую причину или напиши свою — я передам клиентке мягко."""
ADMIN_APPROVAL_DECLINE_CONFIRM_TEXT = """⚠️ Точно отказать клиентке?

Причина: {reason}

Это действие нельзя отменить."""
ADMIN_APPROVAL_PROCESSED_TEXT = "Готово ✨"
ADMIN_APPROVAL_READ_TEXT = "Отметила как прочитанное 🤍"
ADMIN_APPROVAL_QUIET_CLOSE_TEXT = "Запрос тихо закрыт — клиентке ничего не отправляла 🤍"
ADMIN_APPROVAL_SLOT_UNAVAILABLE_TEXT = "Это окошко уже недоступно 🤍"
ADMIN_APPROVAL_CONFIRM_FAILED_TEXT = (
    "Не получилось подтвердить запрос. Проверь запрос и попробуй ещё раз 🤍"
)
ADMIN_APPROVAL_REPLY_SENT_TEXT = "Ответ отправлен клиентке ✨"
ADMIN_APPROVAL_QUICK_REPLY_AFTER_19_TEXT = (
    "После 19:00 у меня обычно получается только в отдельные дни 🌸 "
    "Если хочешь, я подберу ближайший вечерний вариант."
)
ADMIN_APPROVAL_QUICK_REPLY_WEEKDAYS_BUSY_TEXT = (
    "В будни у меня сейчас очень плотно 🌸 "
    "Если хочешь, посмотрю ближайшее вечернее окно или выходной вариант."
)
ADMIN_APPROVAL_QUICK_REPLY_TWO_VARIANTS_TEXT = (
    "Могу предложить 2 ближайших варианта 🌸 "
    "Напиши, что удобнее по дню или времени, и я подберу точнее."
)
ADMIN_RESCUE_SLOT_PROMPT_TEXT = """✨ Освободилось окошко

📅 {date}
🕑 {time}

Если хочешь, можно быстро предложить его постоянным клиенткам 🌸"""
ADMIN_RESCUE_SLOT_SENT_TEXT = """✨ Разослала оффер на освободившееся окошко

📅 {date}
🕑 {time}

Отправлено чатов: {count} 🌸"""
ADMIN_RESCUE_SLOT_NONE_TEXT = """🤍 Подходящих клиенток для быстрого оффера сейчас не нашлось.

Можно попробовать позже или открыть окошко обычным способом."""
ADMIN_RESCUE_SLOT_UNAVAILABLE_TEXT = "Это окошко уже нельзя быстро разослать 🌸"
DEFAULT_REPEAT_BOOKING_DECLINE_REASON = (
    "Сейчас не могу подтвердить ещё одну запись так близко друг к другу. "
    "Давай чуть позже подберём следующее окошко спокойно 🤍"
)

ADMIN_ALL_BOOKINGS_EMPTY_TEXT = "За этот период записей нет 🤍"
ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT = "Не нашла эту запись 🤍"
ADMIN_ALL_BOOKINGS_DELETE_PERIOD_CONFIRM_TEXT = """🗑 УДАЛИТЬ ЗАПИСИ ЗА ПЕРИОД?

Период: {period}
Сейчас в списке: {count}

Это удалит записи из текущего списка и освободит связанные слоты.
Действие нельзя отменить."""
ADMIN_ALL_BOOKINGS_DELETE_PERIOD_DONE_TEXT = "🗑 Удалила {count} записей за период {period}."
ADMIN_ALL_BOOKINGS_DELETE_PERIOD_EMPTY_TEXT = "За этот период сейчас нечего удалять 🤍"
ADMIN_SCHEDULE_MENU_TEXT = """📅 РАСПИСАНИЕ

Выбери, что сделать дальше 👇"""
ADMIN_SCHEDULE_DELETE_MENU_TEXT = """🗑 УДАЛИТЬ ОКОШКИ

Выбери период, за который нужно убрать свободные или заблокированные окошки.

Активные записи бот не тронет 👇"""
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
ADMIN_SCHEDULE_PREVIEW_EMPTY_TEXT = "Не получилось распознать ни одного окошка 🤍"
ADMIN_SCHEDULE_ADDED_TEXT = "Готово ✨ Добавила {created} окошек."
ADMIN_SCHEDULE_ADDED_WITH_SKIPS_TEXT = (
    "Готово ✨ Добавила {created}, пропустила дубликаты: {skipped}."
)
ADMIN_SCHEDULE_ALL_DUPLICATES_TEXT = "Всё уже добавлено 🤍"
ADMIN_SCHEDULE_WEEK_EMPTY_TEXT = "На ближайшую неделю окошек пока нет 🤍"
ADMIN_SCHEDULE_BOOKED_DELETE_FORBIDDEN_TEXT = "Нельзя удалить слот с активной записью 🤍"
ADMIN_SCHEDULE_SLOT_DELETED_TEXT = "Окошко удалено ✨"
ADMIN_SCHEDULE_DELETE_PERIOD_CONFIRM_TEXT = """🗑 УДАЛИТЬ ОКОШКИ ЗА ПЕРИОД?

Период: {period}
Удалю окошек: {count}

Записанные слоты останутся как есть.
Действие нельзя отменить."""
ADMIN_SCHEDULE_DELETE_PERIOD_DONE_TEXT = "🗑 Удалила {count} окошек за период {period}."
ADMIN_SCHEDULE_DELETE_PERIOD_EMPTY_TEXT = (
    "За этот период сейчас нет свободных окошек для удаления 🤍"
)
ADMIN_SCHEDULE_SLOT_BLOCKED_TEXT = "Окошко заблокировано 🤍"
ADMIN_SCHEDULE_SLOT_UNBLOCKED_TEXT = "Окошко снова открыто ✨"
ADMIN_SCHEDULE_NO_SHOW_MARKED_TEXT = "Отметила no-show и обновила риски клиентки."
ADMIN_SCHEDULE_MOVE_PROMPT_TEXT = """✏️ ПЕРЕНОС ОКОШКА

Пришли новую дату и время одним сообщением.

📇 Формат: 25.04 17:00"""
ADMIN_SCHEDULE_MOVE_INVALID_TEXT = "Не смогла разобрать дату и время. Формат: 25.04 17:00"
ADMIN_SCHEDULE_MOVE_COLLISION_TEXT = "Это время уже в расписании. Пришли другое 🤍"
ADMIN_SCHEDULE_MOVE_BOOKED_FORBIDDEN_TEXT = "Записанное окошко нельзя перенести отсюда 🤍"
ADMIN_SCHEDULE_MOVE_DONE_TEXT = "✨ Перенесла"
ADMIN_SCHEDULE_MONTH_HEADER_TEXT = """📅 РАСПИСАНИЕ НА 30 ДНЕЙ

Ниже — все окошки, сгруппированные по дням 👇"""
ADMIN_SCHEDULE_MONTH_EMPTY_TEXT = "На ближайшие 30 дней окошек пока нет 🤍"
ADMIN_RATE_LIMIT_ALERT_TEXT = """🚨 RATE-LIMIT ПРЕВЫШЕН

За последний час:

{lines}"""

ADMIN_UNCONFIRMED_ALERT_TEXT = """⚠️ Клиентка не подтвердила запись

{name} — запись на {time}, до записи {hours_left}.
Я отправила напоминание {minutes_ago} мин назад, ответа нет.

Что делаем?"""
ADMIN_UNCONFIRMED_24H_ALERT_TEXT = """⚠️ Клиентка не нажала подтверждение за сутки

{name} — запись на {time}, до записи {hours_left}.
Я отправила напоминание {minutes_ago} мин назад, кнопка «✅ Буду» не нажата.

Лучше заранее уточнить, всё ли в силе 🤍"""
ADMIN_UNCONFIRMED_ALERT_CONFIRMED_TEXT = """✅ Клиентка подтвердила запись

{name} — запись на {time}.
Подтвердила в {confirmed_at}.

Теперь всё в силе 🤍"""
ADMIN_UNCONFIRMED_NO_SHOW_DONE_TEXT = "Отметила запись как отмену 🤍"
ADMIN_UNCONFIRMED_NO_SHOW_NOT_FOUND_TEXT = "Запись уже изменена 🤍"
NO_SHOW_CLIENT_NOTICE_TEXT = """🤍 Запись отметила как не состоявшуюся.

Если планы меняются, лучше написать заранее — так бот не будет ужесточать условия записи.

Текущий риск по записям: {strikes}/{strike_limit}.
{manual_approval_hint}"""

FORCE_MAJEURE_CHOOSE_DAY_TEXT = """🌷 Форс-мажор

Выбери день, для которого нужно отменить все записи 👇"""
FORCE_MAJEURE_INPUT_REASON_TEXT = """Напиши текст для клиентов — объяснение и извинение.

Они получат это сообщение + кнопку «Выбрать новое время»."""
FORCE_MAJEURE_CONFIRM_TEXT = """Готово отправить {count} клиентам на {date}?

Текст уведомления:
{reason}

⚠️ Отменить это действие нельзя."""
FORCE_MAJEURE_FINAL_CONFIRM_TEXT = """⚠️ Точно отменить {count} записей на {date}?

Это действие нельзя отменить."""
FORCE_MAJEURE_NO_BOOKINGS_TEXT = "На этот день нет активных записей 🤍"
FORCE_MAJEURE_DONE_TEXT = "✅ Готово. Уведомила {sent} из {total} клиентов, записи отменены."
FORCE_MAJEURE_CLIENT_NOTICE_PREFIX = "🌷 Важное сообщение от Ангелы\n\n"

DEFAULT_FORCE_MAJEURE_TEMPLATE = """🌷 Извини, пожалуйста

К сожалению, мне пришлось отменить запись на этот день — возникли непредвиденные обстоятельства.

Очень жаль, что так получилось.
Запишись на удобное время — постараюсь тебя принять как можно скорее 🌸"""

ADMIN_MANUAL_BOOKING_START_TEXT = """➕ Ручная запись

Найди клиента — введи имя или номер телефона.

Если клиента нет в базе — можно создать гостевую запись (напиши имя)."""
ADMIN_MANUAL_BOOKING_NOT_FOUND_CREATE_TEXT = (
    "Клиент не найден. Создать гостевую запись для «{name}»?"
)
ADMIN_MANUAL_BOOKING_CHOOSE_SERVICE_TEXT = "Выбери услугу для записи 👇"
ADMIN_MANUAL_BOOKING_CHOOSE_DAY_TEXT = "Выбери день 👇"
ADMIN_MANUAL_BOOKING_CHOOSE_TIME_TEXT = "Выбери время 👇"
ADMIN_MANUAL_BOOKING_CONFIRM_TEXT = """Подтверди ручную запись:

👤 {client_name}
📅 {date}
⏰ {time}
💅 {service}"""
ADMIN_MANUAL_BOOKING_DONE_TEXT = "✅ Запись создана. Уведомление клиенту не отправлялось."
ADMIN_MANUAL_BOOKING_SLOT_TAKEN_TEXT = "Это время уже занято 🤍"

# Time-offer confirmation flow
APPROVAL_TIME_OFFER_CLIENT_TEXT = (
    "Ангела предлагает тебе другое время:\n\n"
    "📅 {date}\n"
    "🕐 {time}\n"
    "💅 {service}\n\n"
    "Тебе подходит? 🌸"
)
APPROVAL_TIME_OFFER_SENT_ADMIN_TEXT = "Предложила клиентке время — ждём подтверждения 🌸"
APPROVAL_OFFER_ACCEPTED_ADMIN_TEXT = "✅ Клиентка подтвердила время {date} {time}"
APPROVAL_OFFER_DECLINED_ADMIN_TEXT = "❌ Клиентка хочет другое время — запрос снова в очереди"
APPROVAL_OFFER_EXPIRED_TEXT = "Похоже, это предложение уже успело измениться 🤍"
APPROVAL_OFFER_ACCEPT_TOAST = "Отлично, записала тебя 🌸"
APPROVAL_OFFER_DECLINE_TOAST = "Хорошо, сообщила Ангеле ✨"
APPROVAL_REPAIR_OFFER_ACCEPTED_ADMIN_TEXT = "✅ Клиентка подтвердила время ремонта {date} {time}"
APPROVAL_REPAIR_OFFER_DECLINED_ADMIN_TEXT = (
    "❌ Клиентке не подошло время ремонта — заявка снова в очереди"
)

ADMIN_SERVICES_HEADER_TEXT = """💼 УСЛУГИ

Ниже все услуги, включая скрытые 👇"""
ADMIN_SERVICES_EMPTY_TEXT = "Услуг пока нет. Можно добавить первую ✨"
ADMIN_SERVICE_ADD_NAME_TEXT = """✏️ НОВАЯ УСЛУГА

Как она называется?"""
ADMIN_SERVICE_ADD_PRICE_TEXT = """💰 Цена в рублях.

Если цена плавающая — введи 0."""
ADMIN_SERVICE_ADD_DURATION_TEXT = "🕑 Сколько минут закладывать по умолчанию?"
ADMIN_SERVICE_ADD_KIND_TEXT = "💅 Это базовая услуга или дополнение?"
ADMIN_SERVICE_ADD_VARIABLE_TEXT = "💰 Цена плавающая?"
ADMIN_SERVICE_ADD_CONFIRM_TEXT = """✨ НОВАЯ УСЛУГА

📇 Проверим:

┣ Название: {name}
┣ Цена: {price}₽
┣ Длительность: {duration_min} мин
┣ Тип: {kind}
┗ Плавающая цена: {price_variable}

Всё верно?"""
ADMIN_SERVICE_CREATED_TEXT = "Услуга добавлена ✨"
ADMIN_SERVICE_UPDATED_TEXT = "Изменение сохранено 🤍"
ADMIN_SERVICE_VISIBILITY_TEXT = "Видимость обновила ✨"
ADMIN_SERVICE_DELETE_FORBIDDEN_TEXT = (
    "Эту услугу уже используют записи или запросы, поэтому лучше скрыть её, а не удалять 🤍"
)
ADMIN_SERVICE_DELETED_TEXT = "Услуга удалена ✨"
ADMIN_SERVICE_EDIT_FIELD_TEXT = "Что меняем?"
ADMIN_SERVICE_EDIT_NAME_TEXT = "✏️ Введи новое название."
ADMIN_SERVICE_EDIT_PRICE_TEXT = "💰 Введи новую цену в рублях."
ADMIN_SERVICE_EDIT_DURATION_TEXT = "🕑 Введи новую длительность в минутах."
ADMIN_SERVICE_EDIT_INVALID_TEXT = "Не смогла принять это значение. Попробуй ещё раз 🤍"

ADMIN_CLIENTS_HOME_TEXT = """👥 КЛИЕНТЫ

Можно быстро найти клиентку по имени или открыть полный список 👇"""
ADMIN_CLIENTS_PROMPT_TEXT = """🔍 ПОИСК КЛИЕНТКИ

Напиши имя или @username одним сообщением ✨"""
ADMIN_CLIENTS_EMPTY_TEXT = "Никого не нашла 🤍 Попробуй другой запрос."
ADMIN_CLIENTS_PICK_TEXT = "Нашла несколько совпадений. Открой нужную карточку 👇"
ADMIN_CLIENTS_LIST_EMPTY_TEXT = "Пока нет ни одной клиентки 🤍"
ADMIN_CLIENTS_LIST_TEXT = """👥 КЛИЕНТЫ

📇 Навигация:

┣ Страница: {page} из {pages}
┗ Всего клиенток: {total}"""
ADMIN_CLIENT_NOTE_PROMPT_TEXT = """✏️ ЗАМЕТКА

Пришли новую заметку одним сообщением.

Если хочешь очистить, отправь `-`."""
ADMIN_CLIENT_NOTE_SAVED_TEXT = "Заметку сохранила ✨"
ADMIN_CLIENT_MESSAGE_PROMPT_TEXT = """💬 СООБЩЕНИЕ КЛИЕНТКЕ

Пришли одно сообщение — текстом, фото или голосовым ✨"""
ADMIN_CLIENT_MESSAGE_SENT_TEXT = "Сообщение отправлено клиентке ✨"
ADMIN_BOOKING_CARD_RESCHEDULE_PROMPT_TEXT = """🕐 ПЕРЕНЕСТИ ЗАПИСЬ

Пришли новую дату и время одним сообщением.

Пример: `25.05 18:30`"""
ADMIN_BOOKING_CARD_RESCHEDULE_INVALID_TEXT = (
    "Не смогла разобрать дату и время. Пришли один вариант в формате `25.05 18:30` 🤍"
)
ADMIN_BOOKING_CARD_RESCHEDULE_PAST_TEXT = "Это время уже прошло. Пришли будущую дату 🤍"
ADMIN_BOOKING_CARD_RESCHEDULE_COLLISION_TEXT = "Это время уже занято. Пришли другое 🌸"
ADMIN_BOOKING_CARD_RESCHEDULE_DONE_TEXT = "✨ Перенесла запись"
ADMIN_BOOKING_CARD_CANCELLED_TEXT = "❌ Отменила запись"
ADMIN_BOOKING_CARD_REPAIR_INFO_TEXT = """🛠 Гарантия / ремонт

Сейчас по этой записи можно ориентироваться так:

• гарантия: {days} дн.
• лимит: до {nails} ногтя(ей)
• окно заявки: {request_days} дн.

Если клиентке понадобится ремонт, она сможет открыть его со своей стороны через «Мои записи» 🌸"""
ADMIN_CLIENT_BLOCKED_TEXT = "Клиентка заблокирована 🤍"
ADMIN_CLIENT_UNBLOCKED_TEXT = "Клиентка разблокирована ✨"
ADMIN_CLIENT_SHADOW_BANNED_TEXT = "🔕 Shadow-ban включён"
ADMIN_CLIENT_SHADOW_UNBANNED_TEXT = "🔔 Shadow-ban снят"
ADMIN_CLIENT_STRIKES_RESET_TEXT = "♻️ Strikes сброшены"
ADMIN_CLIENT_MANUAL_APPROVAL_SET_TEXT = "✋ Ручное подтверждение включено"
ADMIN_CLIENT_MANUAL_APPROVAL_CLEARED_TEXT = "🔓 Ручное подтверждение снято"

ADMIN_STATS_TITLE_TEXT = """📊 СТАТИСТИКА

Ниже основные цифры за выбранный период 👇"""

ADMIN_BROADCAST_PROMPT_TEXT = """✉️ РАССЫЛКА

📇 Отправим на {count} клиенток.

Пришли текст рассылки — можно использовать Telegram MarkdownV2."""
ADMIN_BROADCAST_INVALID_TEXT = (
    "Не смогла показать превью с MarkdownV2. Проверь текст и попробуй ещё раз 🤍"
)
ADMIN_BROADCAST_STARTED_TEXT = "Рассылка запущена. Отправляю аккуратно, без спама ✨"
ADMIN_BROADCAST_CANCELLED_TEXT = "Рассылку отменила 🤍"
ADMIN_BROADCAST_REPORT_TEXT = """✨ РАССЫЛКА ЗАВЕРШЕНА

📇 Итог:

┣ Доставлено: {delivered}
┣ Заблокировали / удалили: {blocked}
┗ Ошибки: {failed}"""

ADMIN_TEMPLATES_HOME_TEXT = """📝 ШАБЛОНЫ

Выбери раздел 👇"""
ADMIN_TEMPLATE_DETAIL_TEXT = """✏️ {title}

🌿 Что это
{description}

━━━━━━━━━━━━━━
📌 Состояние
{meta_line}

━━━━━━━━━━━━━━
📝 Текущий текст
{content}

━━━━━━━━━━━━━━
{variables_block}

{image_block}"""
ADMIN_TEMPLATE_SAVED_TEXT = "Шаблон обновила ✨"
ADMIN_TEMPLATE_IMAGE_SAVED_TEXT = "Картинку шаблона сохранила ✨"
ADMIN_TEMPLATE_IMAGE_MISSING_ALERT_TEXT = "У этого шаблона пока нет картинки."
ADMIN_TEMPLATE_IMAGE_ALREADY_VISIBLE_TEXT = "Картинка уже показана в карточке 👆"
ADMIN_TEMPLATE_IMAGE_NOT_PHOTO_TEXT = "Нужна именно картинка: отправь фото или файл с изображением."
ADMIN_TEMPLATE_TOO_SHORT_TEXT = "Нужен осмысленный текст хотя бы от 10 символов 🤍"
ADMIN_TEMPLATE_IMAGE_TOO_LARGE_TEXT = "Картинка слишком большая. Лучше до 5 MB 🤍"

ADMIN_SETTINGS_HEADER_TEXT = """⚙️ НАСТРОЙКИ

Ниже редактируемые параметры бота 👇"""
ADMIN_SETTINGS_VALUE_PROMPT_TEXT = "Пришли новое значение одним сообщением."
ADMIN_SETTINGS_EDIT_PROMPT_TEXT = """⚙️ {title}

{prompt}"""
ADMIN_SETTINGS_INVALID_TZ_TEXT = "Не нашла такой часовой пояс. Пример: Europe/Moscow 🤍"
ADMIN_SETTINGS_INVALID_INT_TEXT = "Нужно целое число больше нуля 🤍"

DEFAULT_SCHEDULE_CAPTION_TEXT = "Свободные окошки на ближайшие дни · Ангела"
DEFAULT_PRICE_TEMPLATE = """💅 АКТУАЛЬНЫЙ ПРАЙС

Сюда можно добавить актуальный прайс, описание услуг и важные пояснения.

Если нужен сложный дизайн или расчёт под конкретную длину, Ангела подскажет стоимость отдельно 🤍

Смотри на актуальные кнопки ниже: старые картинки в истории могут уже устареть 🌸"""
BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT = """📅 СВОБОДНЫЕ ОКОШКИ

На картинке — ближайшие дни. Ориентируйся на кнопки ниже: они всегда актуальнее старых сообщений 🌸

Выбери удобный день ниже 👇"""

SERVICES_CAPTION_TEXT = """🤍 Важно

Картинка выше — основной прайс.

Если хочешь сложный дизайн или сомневаешься по длине —
пришли референс перед записью, Ангела подскажет точнее ✨"""
