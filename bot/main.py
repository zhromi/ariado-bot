from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from bot.calendar_sync import sync_all
from bot.commands.admin import AdminCog
from bot.commands.user import UserCog
from bot.config import Settings, load_settings
from bot.db import get_db, init_db
from bot.reminders import run_reminders

log = logging.getLogger("deadline-bot")


class DeadlineBot(commands.Bot):
    def __init__(self, settings: Settings):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.settings = settings
        self.scheduler: AsyncIOScheduler | None = None
        self._jobs_started = False

    async def setup_hook(self) -> None:
        await init_db(self.settings.db_path)
        await self.add_cog(UserCog())
        await self.add_cog(AdminCog())
        try:
            if self.settings.guild_id:
                guild = discord.Object(id=self.settings.guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("synced %s commands to guild %s", len(synced), self.settings.guild_id)
            else:
                synced = await self.tree.sync()
                log.info("synced %s global commands", len(synced))
        except discord.HTTPException:
            log.exception("command sync failed")

    async def on_ready(self) -> None:
        log.info("logged in as %s", self.user)
        if self._jobs_started:
            return
        self._jobs_started = True

        async def sync_job() -> None:
            await sync_all(get_db())

        async def remind_job() -> None:
            await run_reminders(self)

        first = datetime.now(timezone.utc) + timedelta(seconds=20)
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(sync_job, "interval", minutes=45, next_run_time=first, id="sync")
        scheduler.add_job(remind_job, "interval", minutes=5, next_run_time=first, id="remind")
        scheduler.start()
        self.scheduler = scheduler
        log.info("scheduler started")


async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
    log.exception("command failed", exc_info=error)
    text = "Команда сломалась. Попробуй ещё раз."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        log.warning("could not report command error to user")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO, which would leak the calendar token
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = load_settings()
    if not settings.token:
        print("Нет DISCORD_TOKEN. Скопируй .env.example в .env и вставь токен бота.")
        raise SystemExit(2)
    if not settings.admin_ids:
        log.warning("ADMIN_USER_IDS is empty, admin commands will be unavailable")
    bot = DeadlineBot(settings)
    bot.tree.on_error = on_app_command_error
    bot.run(settings.token, log_handler=None)
