"""Core `ProjectNovaBot` (`commands.Bot` subclass) for Cosmic ki baddie V2."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple
import discord
from discord.ext import commands

from bot.core.command_registry import CommandRegistryInspector
from bot.core.command_sync import CommandSyncManager
from bot.core.config import BotConfig
from bot.core.error_handler import handle_prefix_command_error, register_error_handlers
from bot.core.health import HealthMonitor
from bot.core.loader import COG_EXTENSIONS, CogLoader
from bot.database import (
    ActivityRoleRepository,
    AutomationRepository,
    DatabaseManager,
    EmbedTemplateRepository,
    GuildConfigRepository,
    JTCRepository,
    ModerationRepository,
    RBACRepository,
    ReactionRoleRepository,
    TicketRepository,
)
from bot.services.permission_service import PermissionService

logger = logging.getLogger("project_nova.core.bot")


async def _dynamic_prefix_resolver(bot: "ProjectNovaBot", message: discord.Message) -> List[str]:
    """Resolve per-guild configurable prefix from SQLite + mention prefixes."""
    guild_id = message.guild.id if message.guild else None
    prefix = await bot.guild_config_repo.get_prefix(guild_id)
    prefixes = [prefix]
    if bot.user is not None:
        prefixes.extend([f"<@{bot.user.id}> ", f"<@!{bot.user.id}> "])
    return prefixes


class ProjectNovaBot(commands.Bot):
    """Production Discord bot class for Cosmic ki baddie V2 (Project Nova)."""

    def __init__(
        self,
        config: Optional[BotConfig] = None,
        *,
        extensions: Tuple[str, ...] = COG_EXTENSIONS,
    ) -> None:
        self.config = config or BotConfig.from_env()
        self._target_extensions = extensions

        intents = discord.Intents.default()
        # Privileged and required intents (must also be toggled in Discord Developer Portal)
        intents.message_content = True
        intents.members = True
        intents.presences = True
        intents.voice_states = True
        intents.guilds = True
        intents.messages = True
        intents.reactions = True

        super().__init__(
            command_prefix=_dynamic_prefix_resolver,
            help_command=None,  # Disable default discord.py HelpCommand; use custom HelpCog
            intents=intents,
            owner_ids=self.config.owner_ids if self.config.owner_ids else None,
        )

        # Centralized Database & Repositories
        self.db = DatabaseManager(self.config.database_path)
        self.guild_config_repo = GuildConfigRepository(self.db, self.config.default_prefix)
        self.rbac_repo = RBACRepository(self.db, self.guild_config_repo)
        self.ticket_repo = TicketRepository(self.db, self.guild_config_repo)
        self.mod_repo = ModerationRepository(self.db, self.guild_config_repo)
        self.jtc_repo = JTCRepository(self.db, self.guild_config_repo)
        self.activity_repo = ActivityRoleRepository(self.db, self.guild_config_repo)
        self.reaction_role_repo = ReactionRoleRepository(self.db, self.guild_config_repo)
        self.automation_repo = AutomationRepository(self.db, self.guild_config_repo)
        self.embed_repo = EmbedTemplateRepository(self.db, self.guild_config_repo)

        # Centralized RBAC Service
        self.permission_service = PermissionService(self.rbac_repo, self.config.owner_ids)

        # Core Managers
        self.cog_loader = CogLoader(self)
        self.sync_manager = CommandSyncManager(self)
        self.registry_inspector = CommandRegistryInspector(self)
        self.health = HealthMonitor(self, port=self.config.health_port)

        # Register global centralized RBAC check and error handlers
        self.add_check(self._global_rbac_check)
        register_error_handlers(self)

    async def _global_rbac_check(self, ctx: commands.Context) -> bool:
        """Enforce centralized RBAC permissions on every prefix and hybrid command."""
        if ctx.command is None:
            return True
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            allowed, reason = await self.permission_service.check_command_access(
                ctx.author, ctx.command.qualified_name, None
            )
            if not allowed:
                raise commands.CheckFailure(reason)
            return True

        cat_name = getattr(ctx.cog, "CATEGORY", None) if ctx.cog else None
        allowed, reason = await self.permission_service.check_command_access(
            ctx.author, ctx.command.qualified_name, cat_name
        )
        if not allowed:
            raise commands.CheckFailure(reason)
        return True

    async def setup_hook(self) -> None:
        """Initialize database, run migrations, load all Cogs once, and sync slash commands."""
        logger.info("Starting Project Nova (Cosmic ki baddie V2) setup_hook...")
        await self.db.connect()
        await self.cog_loader.load_all(self._target_extensions)
        stats = self.registry_inspector.verify_integrity()
        logger.info(
            "Command registry verified: %d Cogs, %d prefix commands, %d slash commands.",
            stats["cogs"],
            stats["prefix_commands"],
            stats["slash_commands"],
        )
        await self.health.start_server_if_configured()

        if self.config.sync_commands_on_startup:
            if self.config.dev_guild_id:
                await self.sync_manager.sync_guild(self.config.dev_guild_id)
            await self.sync_manager.sync_global()

    async def on_ready(self) -> None:
        logger.info(
            "Cosmic ki baddie V2 is online as %s (ID: %s) in %d guild(s).",
            self.user,
            self.user.id if self.user else "unknown",
            len(self.guilds),
        )
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="/help | !help • Project Nova",
            ),
            status=discord.Status.online,
        )

    async def on_message(self, message: discord.Message) -> None:
        """Primary message handler ensuring `process_commands(message)` is always called."""
        if message.author.bot:
            return
        # Check if AutoMod flagged and deleted the message before command processing
        automod_cog = self.get_cog("ModerationCog")
        if automod_cog is not None and hasattr(automod_cog, "check_automod_message"):
            blocked = await automod_cog.check_automod_message(message)
            if blocked:
                return
        await self.process_commands(message)

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        await handle_prefix_command_error(ctx, error)

    async def close(self) -> None:
        logger.info("Shutting down Project Nova (Cosmic ki baddie V2)...")
        await self.health.stop()
        await self.db.close()
        await super().close()
