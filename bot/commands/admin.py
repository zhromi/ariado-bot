from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import get_db
from bot.timeutils import format_almaty

log = logging.getLogger(__name__)

BROADCAST_COOLDOWN = 300
_last_broadcast = 0.0


def _is_admin(interaction: discord.Interaction) -> bool:
    settings = getattr(interaction.client, "settings", None)
    return bool(settings and interaction.user.id in settings.admin_ids)


class BroadcastView(discord.ui.View):
    def __init__(self, author_id: int, text: str):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.text = text
        self.finished = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Не твоя кнопка.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Отправить всем в ЛС", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.finished = True
        global _last_broadcast
        _last_broadcast = time.monotonic()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Отправляю…", view=self)
        db = get_db()
        sent = 0
        failed = 0
        for discord_id in await db.broadcast_targets():
            try:
                user = interaction.client.get_user(discord_id) or await interaction.client.fetch_user(discord_id)
                await user.send(self.text)
                await db.set_dm_blocked(discord_id, False)
                sent += 1
                await asyncio.sleep(1)
            except discord.Forbidden:
                await db.set_dm_blocked(discord_id, True)
                failed += 1
            except discord.HTTPException:
                failed += 1
        await interaction.followup.send(f"Доставлено: {sent}. Не дошло: {failed}.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.finished = True
        self.stop()
        await interaction.response.edit_message(content="Отменено.", view=None)


class AdminCog(commands.Cog):
    async def _guard(self, interaction: discord.Interaction) -> bool:
        if _is_admin(interaction):
            return True
        await interaction.response.send_message("Эта команда только для админов бота.", ephemeral=True)
        return False

    @app_commands.command(name="admin_users", description="Кто подключил календарь, без задач и без ссылок")
    @app_commands.default_permissions(administrator=True)
    async def admin_users(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        rows = await get_db().admin_overview()
        if not rows:
            await interaction.followup.send("Пока никто не пользовался ботом.", ephemeral=True)
            return
        lines = []
        for row in rows:
            linked = "да" if row["has_calendar"] else "нет"
            ok = "—" if row["last_sync_ok"] is None else ("ок" if row["last_sync_ok"] else "ошибка")
            when = format_almaty(row["last_sync_at"]) if row["last_sync_at"] else "нет"
            name = row["username"] or str(row["discord_id"])
            lines.append(
                f"{name} — календарь: {linked}, синк: {ok}, {when}, событий: {row['event_count']}"
            )
        text = "\n".join(lines)
        if len(text) > 3900:
            text = text[:3900] + "\n…"
        await interaction.followup.send(text, ephemeral=True)

    @app_commands.command(name="admin_broadcast", description="Написать всем пользователям бота в личку")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(text="Текст сообщения")
    async def admin_broadcast(self, interaction: discord.Interaction, text: str) -> None:
        if not await self._guard(interaction):
            return
        clean = text.strip()
        if not clean or len(clean) > 1500:
            await interaction.response.send_message("Текст нужен, и он короче 1500 символов.", ephemeral=True)
            return
        global _last_broadcast
        wait = BROADCAST_COOLDOWN - (time.monotonic() - _last_broadcast)
        if _last_broadcast and wait > 0:
            await interaction.response.send_message(
                f"Рассылку можно раз в 5 минут. Подожди {int(wait)} с.", ephemeral=True
            )
            return
        view = BroadcastView(interaction.user.id, clean)
        await interaction.response.send_message(
            f"Отправить это всем, кто уже запускал бота?\n\n{clean}",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if not view.finished:
            try:
                await interaction.edit_original_response(content="Время вышло, ничего не отправил.", view=None)
            except discord.HTTPException:
                log.info("broadcast confirmation expired")