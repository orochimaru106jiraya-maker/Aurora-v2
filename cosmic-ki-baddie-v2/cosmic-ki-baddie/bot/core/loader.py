"""Idempotent Cog extension loader for Project Nova."""

from __future__ import annotations

import logging
from typing import List, Tuple
from discord.ext import commands

logger = logging.getLogger("project_nova.core.loader")

# Ordered list of all production Cog modules
COG_EXTENSIONS: Tuple[str, ...] = (
    "bot.cogs.help",
    "bot.cogs.utility",
    "bot.cogs.permissions",
    "bot.cogs.administration",
    "bot.cogs.tickets",
    "bot.cogs.setup_wizard",
    "bot.cogs.moderation",
    "bot.cogs.jtc",
    "bot.cogs.activity_roles",
    "bot.cogs.reaction_roles",
    "bot.cogs.automation",
    "bot.cogs.music",
    "bot.cogs.ai_assistant",
    "bot.cogs.embeds",
)


class CogLoader:
    """Ensures every Cog extension is loaded exactly once without duplicates."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._loaded: set[str] = set()

    async def load_all(self, extensions: Tuple[str, ...] = COG_EXTENSIONS) -> List[str]:
        """Load all specified Cog extensions once."""
        loaded_now: List[str] = []
        for ext in extensions:
            if ext in self.bot.extensions or ext in self._loaded:
                logger.debug("Skipping already-loaded extension %s", ext)
                continue
            logger.info("Loading extension: %s", ext)
            await self.bot.load_extension(ext)
            self._loaded.add(ext)
            loaded_now.append(ext)
        logger.info("Loaded %d/%d Cog extensions.", len(self.bot.extensions), len(extensions))
        return loaded_now
