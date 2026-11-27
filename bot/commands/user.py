from __future__ import annotations

import time as monotonic_clock
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.calendar_sync import sync_user, validate_calendar_url
from bot.db import get_db
from bot.reminders import send_dm
from bot.timeutils import (
    almaty_day_bounds,
    format_almaty,
    iso_utc,
    parse_remind_hours,
    parse_user_deadline,
    today_almaty,
    utcnow,
)

_cooldown: dict[tuple[int, str], float] = {}


def _ready(user_id: int, action: str, seconds: float = 20) -> bool:
    now = monotonic_clock.monotonic()
    key = (user_id, action)
    if now - _cooldown.get(key, 0) < seconds:
        return False
    _cooldown[key] = now
    return True


def _line(event: dict) -> str:
    course = f" · {event['course']}" if event.get("course") else ""
    origin = "своё" if event["source"] == "manual" else "Moodle"
    return f"`{event['id']}` {format_almaty(event['dtstart'])} — {event['summary']}{course} ({origin})"


def _chunks(lines: list[str], limit: int = 3500) -> list[str]:
    if not lines:
        return ["На эти дни ничего нет."]
    chunks: list[str] = []
    buf = ""
    for line in lines:
        piece = line if len(line) <= limit else line[: limit - 1] + "…"
        if buf and len(buf) + len(piece) + 1 > limit:
            chunks.append(buf)
            buf = piece
        else:
            buf = f"{buf}\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)
    return chunks


def _embed(title: str, body: str) -> discord.Embed:
    return discord.Embed(title=title, description=body[:4096], color=0x1F6FEB)


async def deliver(interaction: discord.Interaction, title: str, lines: list[str]) -> None:
    db = get_db()
    embeds = [_embed(title if index == 0 else f"{title} ({index + 1})", body) for index, body in enumerate(_chunks(lines))]
    opened = await send_dm(db, interaction.user, embed=embeds[0])
    if opened:
        for embed in embeds[1:]:
            await send_dm(db, interaction.user, embed=embed)
        await interaction.followup.send("Отправил в личные сообщения.", ephemeral=True)
        return
    for embed in embeds:
        await interaction.followup.send(embed=embed, ephemeral=True)
    await interaction.followup.send(
        "Личные сообщения закрыты, поэтому список виден только тебе здесь. "
        "Напоминания придут после того, как откроешь ЛС от участников сервера.",
        ephemeral=True,
    )


class UserCog(commands.Cog):
    def __init__(self) -> None:
        pass

    async def _user(self, interaction: discord.Interaction):
        db = get_db()
        await db.touch_user(interaction.user.id, interaction.user.display_name)
        return db

    @app_commands.command(name="help", description="Что умеет бот")
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "\n".join(
                [
                    "Календарь и дедлайны приходят только тебе в личку.",
                    "/setcalendar — вставить ссылку календаря Moodle",
                    "/sync — обновить сейчас",
                    "/deadlines — ближайшие дедлайны",
                    "/today и /tomorrow — день по времени Астаны",
                    "/add — своё задание",
                    "/remove — удалить своё задание",
                    "/hide — скрыть событие из Moodle",
                    "/reminders — за сколько часов писать, например 24,1",
                    "/status — привязан ли календарь",
                    "/unset — отвязать календарь и удалить свои события",
                ]
            ),
            ephemeral=True,
        )

    @app_commands.command(name="setcalendar", description="Привязать свою ссылку календаря Moodle")
    @app_commands.describe(url="Секретная https-ссылка из Moodle calendar export")
    async def setcalendar(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        error = validate_calendar_url(url)
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return
        if not _ready(interaction.user.id, "sync"):
            await interaction.followup.send("Подожди несколько секунд и повтори.", ephemeral=True)
            return
        previous = await db.get_user(interaction.user.id)
        await db.set_calendar_url(interaction.user.id, url.strip())
        result = await sync_user(db, interaction.user.id, url.strip())
        if not result.ok:
            old_url = (previous or {}).get("calendar_url")
            if old_url and old_url != url.strip():
                await db.set_calendar_url(interaction.user.id, old_url)
                await db.set_sync_status(interaction.user.id, bool(previous.get("last_sync_ok")), previous.get("last_error"))
            elif not old_url:
                await db.set_calendar_url(interaction.user.id, None)
            await interaction.followup.send(
                f"Ссылка не сработала: {result.error} Старый календарь не заменил.",
                ephemeral=True,
            )
            return
        end = iso_utc(utcnow() + timedelta(days=14))
        rows = await db.events_between(interaction.user.id, utcnow().isoformat(), end)
        await deliver(interaction, "Календарь подключён", [_line(row) for row in rows] or ["Календарь пустой на ближайшие 14 дней."])
        await interaction.followup.send(
            f"Сохранил календарь. Событий в ближайшие 14 дней: {len(rows)}. Ссылку больше не показываю.",
            ephemeral=True,
        )

    @app_commands.command(name="sync", description="Обновить свой календарь сейчас")
    async def sync_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        if not _ready(interaction.user.id, "sync"):
            await interaction.followup.send("Подожди несколько секунд и повтори.", ephemeral=True)
            return
        user = await db.get_user(interaction.user.id)
        url = (user or {}).get("calendar_url") or ""
        if not url:
            await interaction.followup.send("Сначала /setcalendar.", ephemeral=True)
            return
        result = await sync_user(db, interaction.user.id, url)
        if not result.ok:
            await interaction.followup.send(f"Не обновил: {result.error} Старые события оставил.", ephemeral=True)
            return
        await interaction.followup.send(f"Обновил. В календаре событий: {result.count}.", ephemeral=True)

    @app_commands.command(name="deadlines", description="Ближайшие дедлайны в личку")
    @app_commands.describe(days="На сколько дней вперёд, от 1 до 60")
    async def deadlines(self, interaction: discord.Interaction, days: app_commands.Range[int, 1, 60] = 14) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        start = utcnow()
        rows = await db.events_between(interaction.user.id, start.isoformat(), iso_utc(start + timedelta(days=int(days))))
        await deliver(interaction, f"Дедлайны на {int(days)} дн.", [_line(row) for row in rows])

    @app_commands.command(name="today", description="Что сегодня по времени Астаны")
    async def today(self, interaction: discord.Interaction) -> None:
        await self._day(interaction, today_almaty(), "Сегодня")

    @app_commands.command(name="tomorrow", description="Что завтра по времени Астаны")
    async def tomorrow(self, interaction: discord.Interaction) -> None:
        await self._day(interaction, today_almaty() + timedelta(days=1), "Завтра")

    async def _day(self, interaction: discord.Interaction, day, title: str) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        start, end = almaty_day_bounds(day)
        rows = await db.events_between(interaction.user.id, start, end)
        await deliver(interaction, title, [_line(row) for row in rows])

    @app_commands.command(name="add", description="Добавить своё задание")
    @app_commands.rename(time_text="time")
    @app_commands.describe(
        course="Предмет",
        title="Что сделать",
        date="Дата в формате ГГГГ-ММ-ДД",
        time_text="Время ЧЧ:ММ. Если пусто — 23:59",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        course: str,
        title: str,
        date: str,
        time_text: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        when = parse_user_deadline(date, time_text)
        if when is None:
            await interaction.followup.send("Дата как 2026-11-20, время как 18:30.", ephemeral=True)
            return
        course_clean = course.strip()[:80]
        title_clean = title.strip()[:200]
        if not course_clean or not title_clean:
            await interaction.followup.send("Нужны предмет и текст задания.", ephemeral=True)
            return
        event_id = await db.add_manual(interaction.user.id, title_clean, course_clean, when.isoformat())
        await interaction.followup.send(
            f"Добавил `{event_id}`: {format_almaty(when)} — {title_clean} · {course_clean}.",
            ephemeral=True,
        )

    @app_commands.command(name="remove", description="Удалить своё задание по номеру")
    @app_commands.describe(event_id="Номер из списка")
    async def remove(self, interaction: discord.Interaction, event_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        event = await db.get_event(interaction.user.id, event_id)
        if event is None:
            await interaction.followup.send("Такого номера у тебя нет.", ephemeral=True)
            return
        if event["source"] != "manual":
            await interaction.followup.send("Это событие из Moodle. Скрой его командой /hide.", ephemeral=True)
            return
        await db.delete_manual(interaction.user.id, event_id)
        await interaction.followup.send(f"Удалил `{event_id}`.", ephemeral=True)

    @app_commands.command(name="hide", description="Скрыть событие только у себя")
    @app_commands.describe(event_id="Номер из списка")
    async def hide(self, interaction: discord.Interaction, event_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        event = await db.get_event(interaction.user.id, event_id)
        if event is None:
            await interaction.followup.send("Такого номера у тебя нет.", ephemeral=True)
            return
        await db.hide_event(interaction.user.id, event_id)
        await interaction.followup.send(f"Скрыл `{event_id}`. Напоминаний по нему больше не будет.", ephemeral=True)

    @app_commands.command(name="reminders", description="За сколько часов напоминать")
    @app_commands.describe(hours="Например 24,1 или 48,12,1")
    async def reminders(self, interaction: discord.Interaction, hours: str) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        parsed = parse_remind_hours(hours)
        if not parsed:
            await interaction.followup.send("Напиши числа через запятую, например 24,1.", ephemeral=True)
            return
        stored = ",".join(str(int(item)) if item == int(item) else str(item) for item in parsed)
        await db.set_remind_hours(interaction.user.id, stored)
        await interaction.followup.send(f"Буду писать за {stored} ч.", ephemeral=True)

    @app_commands.command(name="status", description="Привязан ли календарь и когда был синк")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        user = await db.get_user(interaction.user.id)
        if user is None or not user.get("calendar_url"):
            await interaction.followup.send("Календарь не привязан. Команда: /setcalendar.", ephemeral=True)
            return
        raw_when = user.get("last_sync_at")
        when = format_almaty(raw_when) if raw_when else "ещё не было"
        ok = "да" if user.get("last_sync_ok") else "нет"
        count = await db.count_events(interaction.user.id)
        error = user.get("last_error")
        extra = f"\nПоследняя ошибка: {error}" if error else ""
        dm = "закрыты" if user.get("dm_blocked") else "открыты"
        await interaction.followup.send(
            f"Календарь привязан.\nПоследний синк: {when}. Успешно: {ok}.\n"
            f"Видимых событий: {count}. ЛС: {dm}.{extra}",
            ephemeral=True,
        )

    @app_commands.command(name="unset", description="Отвязать календарь и удалить свои события")
    async def unset(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        db = await self._user(interaction)
        await db.clear_user_data(interaction.user.id)
        await interaction.followup.send(
            "Отвязал календарь. Удалил события Moodle и твои ручные задания.",
            ephemeral=True,
        )
