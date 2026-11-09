"""Application command synchronization service for Project Nova."""

from __future__ import annotations

import logging
from typing import List, Optional
import discord
from discord.ext import commands

logger = logging.getLogger("project_nova.core.command_sync")


class CommandSyncManager:
    """Synchronizes registered `app_commands` with Discord safely."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def sync_global(self) -> int:
        """Synchronize global slash commands."""
        try:
            synced = await self.bot.tree.sync()
            logger.info("Synchronized %d global application commands.", len(synced))
            return len(synced)
        except Exception as exc:
            logger.error("Failed to sync global application commands: %s", exc)
            return 0

    async def sync_guild(self, guild_id: int) -> int:
        """Copy global commands to a specific development guild and sync immediately."""
        try:
            guild_obj = discord.Object(id=int(guild_id))
            self.bot.tree.copy_global_to(guild=guild_obj)
            synced = await self.bot.tree.sync(guild=guild_obj)
            logger.info("Synchronized %d application commands to guild %d.", len(synced), guild_id)
            return len(synced)
        except Exception as exc:
            logger.error("Failed to sync application commands to guild %d: %s", guild_id, exc)
            return 0
