# Ariado

**English** | [Русский](#русский)

Discord bot for AITU students. It syncs your personal Moodle calendar and sends deadlines and reminders as **private DMs**.

Unofficial student project. Not affiliated with Astana IT University. It never asks for your Moodle password.

## Features

- Pulls events from your Moodle calendar and refreshes them every 45 minutes.
- Shows upcoming deadlines, plus today's and tomorrow's events. Times are shown in Astana time (UTC+5).
- Sends reminders by DM ahead of time. Default: 24 hours and 1 hour before, thresholds are configurable.
- Lets you add your own tasks that are missing from Moodle and hide events you don't need.

## Getting started

1. Open the [Moodle calendar export](https://lms.astanait.edu.kz/calendar/export.php).
2. **Events to export:** "Events related to courses". **Time period:** "Custom range" or "Recent and next 60 days".
3. Click **Get calendar URL** and copy the link.
4. On the server with the bot, run `/setcalendar` and paste the link. Your upcoming events will arrive by DM.
5. Allow direct messages from server members (right-click the server → Privacy Settings). Without this, reminders cannot be delivered.

Your calendar link is a secret. Don't share it. If it leaks, generate a new one in Moodle.

## Commands

| Command | What it does |
|---|---|
| `/setcalendar url` | Link your Moodle calendar |
| `/sync` | Refresh your calendar now |
| `/deadlines days` | Deadlines for the next N days (1–60, default 14) |
| `/today`, `/tomorrow` | Events for today and tomorrow |
| `/add course title date time` | Add your own task. Date `YYYY-MM-DD`, time `HH:MM` (default 23:59) |
| `/remove event_id` | Delete your own task |
| `/hide event_id` | Hide a Moodle event for yourself only |
| `/reminders hours` | How many hours ahead to remind, e.g. `24,1` or `48,12,1` |
| `/status` | Whether a calendar is linked and when it last synced |
| `/unset` | Unlink the calendar and delete your data, including manual tasks |
| `/help` | List of commands |

## Privacy

- Deadlines, lists and reminders are sent only to you, by DM.
- Command replies are visible only to you.
- The bot never posts anything in public channels.
- It does not ask for or store your Moodle login or password, does not log in to Moodle, and does not scrape private pages.
- The bot admin can only see your nickname, whether a calendar is linked, the time of the last sync and the number of events. They cannot see your link or task titles.
- The bot needs your calendar link to keep syncing, so it is stored in the bot's database. It is never sent to chat or written to logs. `/unset` deletes it together with your events.

## Limitations

- Data is refreshed every 45 minutes, not instantly.
- If your DMs are closed, reminders can't be delivered. The bot tells you once in its reply to a command.
- Only calendar links from `lms.astanait.edu.kz` are accepted.

## Tech

Python 3.11, discord.py, httpx, icalendar, SQLite (aiosqlite), APScheduler.

## License

[MIT](LICENSE) © 2026 ariatolize

---

# Русский

[English](#ariado) | **Русский**

Discord-бот для студентов AITU. Подключает твой календарь Moodle и присылает дедлайны и напоминания **в личные сообщения**.

Неофициальный студенческий проект. Не связан с Astana IT University и не требует пароль от Moodle.

## Что умеет

- Подтягивает события из твоего календаря Moodle и обновляет их каждые 45 минут.
- Показывает ближайшие дедлайны, события на сегодня и завтра. Время по Астане (UTC+5).
- Напоминает в личку заранее. По умолчанию за 24 часа и за 1 час, пороги можно менять.
- Позволяет добавить своё задание, если его нет в Moodle, и скрыть ненужное событие.

## Как начать

1. Открой [экспорт календаря Moodle](https://lms.astanait.edu.kz/calendar/export.php).
2. **Events to export:** «Events related to courses». **Time period:** «Custom range» или «Recent and next 60 days».
3. Нажми **Get calendar URL** и скопируй ссылку.
4. На сервере с ботом напиши `/setcalendar` и вставь ссылку. Список ближайших событий придёт в личные сообщения.
5. Разреши личные сообщения от участников сервера (правый клик по серверу → Настройки конфиденциальности). Без этого напоминания не придут.

Ссылка календаря секретная, не отправляй её другим. Если она попала не туда, создай новую в Moodle.

## Команды

| Команда | Что делает |
|---|---|
| `/setcalendar url` | Привязать календарь Moodle |
| `/sync` | Обновить календарь сейчас |
| `/deadlines days` | Дедлайны на N дней вперёд (1–60, по умолчанию 14) |
| `/today`, `/tomorrow` | События за сегодня и завтра |
| `/add course title date time` | Своё задание. Дата `ГГГГ-ММ-ДД`, время `ЧЧ:ММ` (по умолчанию 23:59) |
| `/remove event_id` | Удалить своё задание |
| `/hide event_id` | Скрыть событие Moodle только у себя |
| `/reminders hours` | За сколько часов напоминать, например `24,1` или `48,12,1` |
| `/status` | Привязан ли календарь и когда был последний синк |
| `/unset` | Отвязать календарь и удалить свои данные, включая ручные задания |
| `/help` | Список команд |

## Приватность

- Дедлайны, списки и напоминания приходят только тебе в личные сообщения.
- Ответы бота на команды видишь только ты.
- В общие каналы бот ничего не пишет.
- Бот не просит и не хранит логин и пароль Moodle, не заходит в Moodle и не парсит закрытые страницы.
- Админ бота видит только ник, подключён ли календарь, время последнего синка и число событий. Ссылку и названия задач он видеть не может.
- Ссылка календаря нужна боту для обновлений, поэтому хранится в его базе данных. В логи и в чат она не попадает. Команда `/unset` удаляет её вместе с твоими событиями.

## Ограничения

- Данные обновляются не мгновенно, а раз в 45 минут.
- Если личные сообщения закрыты, напоминания не придут. Бот один раз скажет об этом в ответе на команду.
- Принимаются только ссылки календаря с `lms.astanait.edu.kz`.

## Технологии

Python 3.11, discord.py, httpx, icalendar, SQLite (aiosqlite), APScheduler.

## Лицензия

[MIT](LICENSE) © 2026 ariatolize
