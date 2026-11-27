from __future__ import annotations

import logging
from datetime import timedelta

import discord

from bot.db import Database, get_db
from bot.timeutils import format_almaty, human_left, newly_crossed, parse_iso, parse_remind_hours, utcnow

log = logging.getLogger(__name__)


def reminder_text(summary: str, course: str | None, dtstart: str, left: timedelta) -> str:
    subject = f" ({course})" if course else ""
    return (
        f"Через {human_left(left)}: {summary}{subject}\n"
        f"{format_almaty(dtstart)} по времени Астаны."
    )


async def run_reminders(bot: discord.Client) -> None:
    db = get_db()
    now = utcnow()
    horizon = now + timedelta(days=31)
    rows = await db.upcoming_for_reminders(now.isoformat(), horizon.isoformat())
    for row in rows:
        if row["dm_blocked"]:
            continue
        thresholds = parse_remind_hours(row["remind_hours"] or "") or [24.0, 1.0]
        start = parse_iso(row["dtstart"])
        left = start - now
        hours_left = left.total_seconds() / 3600
        already = set(row["reminded"])
        crossed = newly_crossed(hours_left, thresholds, already)
        if not crossed:
            continue
        text = reminder_text(row["summary"], row["course"], row["dtstart"], left)
        try:
            user = bot.get_user(int(row["discord_id"])) or await bot.fetch_user(int(row["discord_id"]))
            await user.send(text)
        except discord.Forbidden:
            await db.set_dm_blocked(int(row["discord_id"]), True)
            log.info("dm closed for %s", row["discord_id"])
            continue
        except discord.HTTPException:
            log.warning("dm failed for %s", row["discord_id"])
            continue
        await db.mark_reminded(int(row["id"]), crossed)


async def send_dm(db: Database, user: discord.abc.User, content: str | None = None, **kwargs) -> bool:
    try:
        await user.send(content, **kwargs)
    except discord.Forbidden:
        await db.set_dm_blocked(user.id, True)
        return False
    except discord.HTTPException:
        log.warning("dm failed for %s", user.id)
        return False
    await db.set_dm_blocked(user.id, False)
    return True
