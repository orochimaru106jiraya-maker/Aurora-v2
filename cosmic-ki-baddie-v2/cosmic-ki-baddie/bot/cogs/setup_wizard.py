"""Interactive Discord Configuration Dashboard (`/setup`, `!setup`) for Project Nova.

Implements:
- Discord Embeds displaying live server configuration across 3 paginated pages.
- Select Menus to jump to any of the 15 configuration areas.
- Modals for editing Prefix, Language, Welcome/Goodbye templates, Ticket limits/formats,
  AI provider/endpoint/model, Music volume/timeout, and AutoMod thresholds without code changes.
- Channel Select & Role Select menus.
- Pagination buttons (Previous / Next Page) and Confirmation dialog for resetting configuration.
- Persistent Views so buttons and menus continue working after bot restarts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import discord
from discord.ext import commands

from bot.services.permission_service import require_tier
from bot.utils.formatting import make_embed


class GeneralSetupModal(discord.ui.Modal, title="Configure Prefix & Language"):
    """Modal for editing prefix and language."""

    prefix_input = discord.ui.TextInput(
        label="Command Prefix (1-10 chars)",
        placeholder="!",
        default="!",
        min_length=1,
        max_length=10,
    )
    language_input = discord.ui.TextInput(
        label="Server Language (en, es, hi, fr, de)",
        placeholder="en",
        default="en",
        min_length=2,
        max_length=5,
    )

    def __init__(self, bot: commands.Bot, guild_id: int, current_cfg: Dict[str, Any]) -> None:
        super().__init__(custom_id="nova:setup:modal:general")
        self.bot = bot
        self.guild_id = guild_id
        self.prefix_input.default = str(current_cfg.get("prefix", "!"))
        self.language_input.default = str(current_cfg.get("language", "en"))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        new_prefix = self.prefix_input.value.strip() or "!"
        new_lang = self.language_input.value.strip().lower() or "en"
        await self.bot.guild_config_repo.set_prefix(self.guild_id, new_prefix)
        cfg = await self.bot.guild_config_repo.update_fields(self.guild_id, language=new_lang)
        emb = make_embed(
            "✅ Prefix & Language Saved",
            f"• **Prefix:** `{cfg['prefix']}`\n• **Language:** `{cfg['language']}`",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)


class WelcomeGoodbyeModal(discord.ui.Modal, title="Configure Welcome & Goodbye"):
    """Modal for editing welcome and goodbye messages and toggles."""

    welcome_enabled = discord.ui.TextInput(
        label="Enable Welcome? (true / false)",
        default="true",
        max_length=5,
    )
    welcome_msg = discord.ui.TextInput(
        label="Welcome Message ({user}, {server})",
        style=discord.TextStyle.paragraph,
        default="Welcome {user} to **{server}**!",
        max_length=500,
    )
    goodbye_enabled = discord.ui.TextInput(
        label="Enable Goodbye? (true / false)",
        default="true",
        max_length=5,
    )
    goodbye_msg = discord.ui.TextInput(
        label="Goodbye Message ({user_name}, {server})",
        style=discord.TextStyle.paragraph,
        default="Goodbye **{user_name}**, we will miss you!",
        max_length=500,
    )

    def __init__(self, bot: commands.Bot, guild_id: int, current_cfg: Dict[str, Any]) -> None:
        super().__init__(custom_id="nova:setup:modal:welcome")
        self.bot = bot
        self.guild_id = guild_id
        self.welcome_enabled.default = "true" if current_cfg.get("welcome_enabled") else "false"
        self.welcome_msg.default = str(current_cfg.get("welcome_message", "Welcome {user}!"))
        self.goodbye_enabled.default = "true" if current_cfg.get("goodbye_enabled") else "false"
        self.goodbye_msg.default = str(current_cfg.get("goodbye_message", "Goodbye {user_name}!"))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        w_on = 1 if self.welcome_enabled.value.strip().lower() in ("1", "true", "yes", "on") else 0
        g_on = 1 if self.goodbye_enabled.value.strip().lower() in ("1", "true", "yes", "on") else 0
        await self.bot.guild_config_repo.update_fields(
            self.guild_id,
            welcome_enabled=w_on,
            welcome_message=self.welcome_msg.value.strip(),
            goodbye_enabled=g_on,
            goodbye_message=self.goodbye_msg.value.strip(),
        )
        emb = make_embed(
            "✅ Welcome & Goodbye Saved",
            f"• **Welcome Enabled:** `{'Yes' if w_on else 'No'}`\n• **Goodbye Enabled:** `{'Yes' if g_on else 'No'}`",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)


class ModerationSetupModal(discord.ui.Modal, title="Configure AutoMod & Moderation"):
    """Modal for configuring AutoMod toggles and thresholds."""

    automod_enabled = discord.ui.TextInput(
        label="Enable AutoMod? (true / false)",
        default="true",
        max_length=5,
    )
    max_mentions = discord.ui.TextInput(
        label="Max Mentions Per Message",
        default="5",
        max_length=3,
    )
    anti_invite = discord.ui.TextInput(
        label="Block Discord Invites? (true / false)",
        default="true",
        max_length=5,
    )
    spam_threshold = discord.ui.TextInput(
        label="Anti-Spam Max Messages in 5s",
        default="6",
        max_length=3,
    )

    def __init__(self, bot: commands.Bot, guild_id: int, current_cfg: Dict[str, Any]) -> None:
        super().__init__(custom_id="nova:setup:modal:automod")
        self.bot = bot
        self.guild_id = guild_id
        self.automod_enabled.default = "true" if current_cfg.get("automod_enabled") else "false"
        self.max_mentions.default = str(current_cfg.get("automod_max_mentions", 5))
        self.anti_invite.default = "true" if current_cfg.get("automod_anti_invite") else "false"
        self.spam_threshold.default = str(current_cfg.get("automod_spam_threshold", 6))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        am_on = 1 if self.automod_enabled.value.strip().lower() in ("1", "true", "yes", "on") else 0
        inv_on = 1 if self.anti_invite.value.strip().lower() in ("1", "true", "yes", "on") else 0
        mentions = int(self.max_mentions.value.strip()) if self.max_mentions.value.strip().isdigit() else 5
        spam = int(self.spam_threshold.value.strip()) if self.spam_threshold.value.strip().isdigit() else 6
        await self.bot.guild_config_repo.update_fields(
            self.guild_id,
            automod_enabled=am_on,
            automod_max_mentions=max(2, mentions),
            automod_anti_invite=inv_on,
            automod_spam_threshold=max(3, spam),
        )
        emb = make_embed(
            "✅ Moderation & AutoMod Saved",
            f"• **AutoMod:** `{'Enabled' if am_on else 'Disabled'}`\n"
            f"• **Max Mentions:** `{mentions}` | **Block Invites:** `{'Yes' if inv_on else 'No'}`",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)


class AISetupModal(discord.ui.Modal, title="Configure AI Assistant"):
    """Modal for configuring AI endpoint, model, and cooldown."""

    ai_enabled = discord.ui.TextInput(
        label="Enable AI Assistant? (true / false)",
        default="false",
        max_length=5,
    )
    ai_provider = discord.ui.TextInput(
        label="Provider (local, openai_compatible, none)",
        default="local",
        max_length=30,
    )
    ai_endpoint = discord.ui.TextInput(
        label="Model HTTP Endpoint URL",
        default="http://127.0.0.1:11434/api/generate",
        max_length=200,
    )
    ai_model = discord.ui.TextInput(
        label="Model Name",
        default="llama3",
        max_length=60,
    )

    def __init__(self, bot: commands.Bot, guild_id: int, current_cfg: Dict[str, Any]) -> None:
        super().__init__(custom_id="nova:setup:modal:ai")
        self.bot = bot
        self.guild_id = guild_id
        self.ai_enabled.default = "true" if current_cfg.get("ai_enabled") else "false"
        self.ai_provider.default = str(current_cfg.get("ai_provider", "local"))
        self.ai_endpoint.default = str(
            current_cfg.get("ai_endpoint", "http://127.0.0.1:11434/api/generate")
        )
        self.ai_model.default = str(current_cfg.get("ai_model", "llama3"))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        enabled = 1 if self.ai_enabled.value.strip().lower() in ("1", "true", "yes", "on") else 0
        await self.bot.guild_config_repo.update_fields(
            self.guild_id,
            ai_enabled=enabled,
            ai_provider=self.ai_provider.value.strip().lower(),
            ai_endpoint=self.ai_endpoint.value.strip(),
            ai_model=self.ai_model.value.strip(),
        )
        emb = make_embed(
            "✅ AI Assistant Configuration Saved",
            f"• **Enabled:** `{'Yes' if enabled else 'No'}`\n"
            f"• **Provider:** `{self.ai_provider.value.strip()}`\n"
            f"• **Model:** `{self.ai_model.value.strip()}`",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)


class MusicAndJTCModal(discord.ui.Modal, title="Configure Music & Join-to-Create"):
    """Modal for configuring default music volume, idle timeout, and JTC room template."""

    music_volume = discord.ui.TextInput(
        label="Default Music Volume (1-100)",
        default="80",
        max_length=3,
    )
    music_timeout = discord.ui.TextInput(
        label="Music Idle Disconnect Timeout (seconds)",
        default="180",
        max_length=5,
    )
    jtc_name = discord.ui.TextInput(
        label="JTC Room Naming Format ({username})",
        default="{username}'s Room",
        max_length=60,
    )
    jtc_limit = discord.ui.TextInput(
        label="JTC Default User Limit (0 = unlimited)",
        default="0",
        max_length=2,
    )

    def __init__(self, bot: commands.Bot, guild_id: int, current_cfg: Dict[str, Any]) -> None:
        super().__init__(custom_id="nova:setup:modal:music_jtc")
        self.bot = bot
        self.guild_id = guild_id
        self.music_volume.default = str(current_cfg.get("music_default_volume", 80))
        self.music_timeout.default = str(current_cfg.get("music_idle_timeout_sec", 180))
        self.jtc_name.default = str(current_cfg.get("jtc_default_name", "{username}'s Room"))
        self.jtc_limit.default = str(current_cfg.get("jtc_default_limit", 0))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        vol = int(self.music_volume.value.strip()) if self.music_volume.value.strip().isdigit() else 80
        timeout = int(self.music_timeout.value.strip()) if self.music_timeout.value.strip().isdigit() else 180
        limit = int(self.jtc_limit.value.strip()) if self.jtc_limit.value.strip().isdigit() else 0
        await self.bot.guild_config_repo.update_fields(
            self.guild_id,
            music_default_volume=max(1, min(100, vol)),
            music_idle_timeout_sec=max(30, timeout),
            jtc_default_name=self.jtc_name.value.strip() or "{username}'s Room",
            jtc_default_limit=max(0, min(99, limit)),
        )
        emb = make_embed(
            "✅ Music & Join-to-Create Saved",
            f"• **Music Default Volume:** `{vol}%` (Idle Timeout: `{timeout}s`)\n"
            f"• **JTC Format:** `{self.jtc_name.value.strip()}` (Default Limit: `{limit}`)",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)


class SetupResetConfirmView(discord.ui.View):
    """Confirmation dialog before resetting server configuration to defaults."""

    def __init__(self, bot: commands.Bot, guild_id: int) -> None:
        super().__init__(timeout=60.0)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(
        label="Confirm Factory Reset",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
        custom_id="nova:setup:confirm_reset",
    )
    async def confirm_reset(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.bot.guild_config_repo.update_fields(
            self.guild_id,
            prefix=self.bot.config.default_prefix,
            language="en",
            welcome_enabled=0,
            goodbye_enabled=0,
            automod_enabled=0,
            ai_enabled=0,
            music_default_volume=80,
        )
        emb = make_embed(
            "♻️ Configuration Reset Complete",
            "Server configuration has been restored to factory defaults.",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=emb, view=None)

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
        custom_id="nova:setup:cancel_reset",
    )
    async def cancel_reset(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        emb = make_embed(
            "✅ Reset Cancelled",
            "Your server configuration was not modified.",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=emb, view=None)


class SetupDashboardView(discord.ui.View):
    """Persistent interactive `/setup` dashboard view with select menus, modals, pagination, and reset confirmation."""

    def __init__(self, bot: commands.Bot, page: int = 1) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.page = page

    async def _check_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Server only.", ephemeral=True)
            return False
        if not await self.bot.permission_service.has_tier(interaction.user, "administrator"):
            await interaction.response.send_message(
                "🚫 Only Server Administrators can modify `/setup` configuration.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.select(
        placeholder="Choose a configuration module to edit...",
        custom_id="nova:setup:module_select",
        options=[
            discord.SelectOption(
                label="1. Prefix & Language",
                value="general",
                emoji="🔤",
                description="Configure server command prefix and language.",
            ),
            discord.SelectOption(
                label="2. Welcome & Goodbye Messages",
                value="welcome",
                emoji="👋",
                description="Toggle and customize welcome/goodbye messages.",
            ),
            discord.SelectOption(
                label="3. Moderation & AutoMod",
                value="automod",
                emoji="🛡️",
                description="Configure AutoMod, mention limits, invite blocker, and anti-spam.",
            ),
            discord.SelectOption(
                label="4. AI Assistant Settings",
                value="ai",
                emoji="🤖",
                description="Configure optional AI provider, local endpoint, and model.",
            ),
            discord.SelectOption(
                label="5. Music & Join-to-Create (JTC)",
                value="music_jtc",
                emoji="🎵",
                description="Configure default volume, idle disconnect, and JTC room templates.",
            ),
            discord.SelectOption(
                label="6. Tickets, Roles & Automation Guide",
                value="guide",
                emoji="🎫",
                description="Quick reference for ticket panels, RBAC, activity/reaction roles.",
            ),
        ],
        row=0,
    )
    async def select_module(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        if not await self._check_admin(interaction):
            return
        assert interaction.guild is not None
        cfg = await self.bot.guild_config_repo.ensure_guild(interaction.guild.id)
        choice = select.values[0]
        if choice == "general":
            await interaction.response.send_modal(
                GeneralSetupModal(self.bot, interaction.guild.id, cfg)
            )
        elif choice == "welcome":
            await interaction.response.send_modal(
                WelcomeGoodbyeModal(self.bot, interaction.guild.id, cfg)
            )
        elif choice == "automod":
            await interaction.response.send_modal(
                ModerationSetupModal(self.bot, interaction.guild.id, cfg)
            )
        elif choice == "ai":
            await interaction.response.send_modal(
                AISetupModal(self.bot, interaction.guild.id, cfg)
            )
        elif choice == "music_jtc":
            await interaction.response.send_modal(
                MusicAndJTCModal(self.bot, interaction.guild.id, cfg)
            )
        else:
            emb = make_embed(
                "🎛️ Interactive Module Configuration Commands",
                (
                    "Use the select menu and channel selectors on the `/setup` panel, or use these direct module wizards:\n"
                    "• **Welcome/Goodbye/Log Channels:** Use the Channel Selector below or `/logging`, `/welcome`, `/goodbye`\n"
                    "• **Tickets & Categories:** `/ticket panel`, `/ticket addcategory`, `/ticket config`\n"
                    "• **Staff Roles & Permissions:** `/permissions addrole`, `/permissions setcommand`\n"
                    "• **Activity Roles:** `/activityrole add`, `/activityrole list`\n"
                    "• **Reaction Roles:** `/reactionrole create`, `/reactionrole additem`\n"
                    "• **Join-to-Create Trigger:** `/jtc setup`\n"
                    "• **Auto-Responder:** `/autoresponder add`, `/autoresponder list`"
                ),
                color=discord.Color.blurple(),
            )
            await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(
        label="◀ Prev Page",
        style=discord.ButtonStyle.secondary,
        custom_id="nova:setup:prev_page",
        row=1,
    )
    async def prev_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_admin(interaction):
            return
        self.page = 3 if self.page <= 1 else self.page - 1
        cog: Optional["SetupWizardCog"] = self.bot.get_cog("SetupWizardCog")  # type: ignore
        if cog and interaction.guild:
            emb = await cog.build_dashboard_embed(interaction.guild, page=self.page)
            await interaction.response.edit_message(embed=emb, view=self)

    @discord.ui.button(
        label="🔄 Refresh",
        style=discord.ButtonStyle.primary,
        custom_id="nova:setup:refresh",
        row=1,
    )
    async def refresh_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_admin(interaction):
            return
        cog: Optional["SetupWizardCog"] = self.bot.get_cog("SetupWizardCog")  # type: ignore
        if cog and interaction.guild:
            emb = await cog.build_dashboard_embed(interaction.guild, page=self.page)
            await interaction.response.edit_message(embed=emb, view=self)

    @discord.ui.button(
        label="Next Page ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="nova:setup:next_page",
        row=1,
    )
    async def next_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_admin(interaction):
            return
        self.page = 1 if self.page >= 3 else self.page + 1
        cog: Optional["SetupWizardCog"] = self.bot.get_cog("SetupWizardCog")  # type: ignore
        if cog and interaction.guild:
            emb = await cog.build_dashboard_embed(interaction.guild, page=self.page)
            await interaction.response.edit_message(embed=emb, view=self)

    @discord.ui.button(
        label="Reset Defaults",
        style=discord.ButtonStyle.danger,
        emoji="♻️",
        custom_id="nova:setup:reset_btn",
        row=1,
    )
    async def reset_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_admin(interaction):
            return
        assert interaction.guild is not None
        emb = make_embed(
            "⚠️ Confirm Configuration Reset",
            "Are you sure you want to reset core server configuration settings to factory defaults?",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(
            embed=emb,
            view=SetupResetConfirmView(self.bot, interaction.guild.id),
            ephemeral=True,
        )


class SetupWizardCog(commands.Cog, name="SetupWizardCog"):
    """Interactive Discord Server Configuration Dashboard (`/setup`, `!setup`)."""

    CATEGORY = "Configuration"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(SetupDashboardView(self.bot))

    async def build_dashboard_embed(
        self, guild: discord.Guild, page: int = 1
    ) -> discord.Embed:
        """Build a paginated overview of all 15 configuration areas for `guild`."""
        cfg = await self.bot.guild_config_repo.ensure_guild(guild.id)
        staff_roles = await self.bot.rbac_repo.list_staff_roles(guild.id)
        ticket_cats = await self.bot.ticket_repo.ensure_default_categories(guild.id)
        activity_rules = await self.bot.activity_repo.list_rules(guild.id)
        rr_panels = await self.bot.reaction_role_repo.list_panels(guild.id)
        responders = await self.bot.automation_repo.list_autoresponders(guild.id)
        perm_rules = await self.bot.rbac_repo.list_permission_rules(guild.id)

        def _ch(cid: Any) -> str:
            return f"<#{cid}>" if cid else "*Not Set*"

        def _role(rid: Any) -> str:
            return f"<@&{rid}>" if rid else "*Not Set*"

        if page == 1:
            emb = make_embed(
                f"🎛️ Project Nova Setup Dashboard — {guild.name} (Page 1/3)",
                "Use the dropdown menu below to edit settings via interactive modals, or paginate through all 15 configuration modules.",
                color=discord.Color.blurple(),
            )
            emb.add_field(
                name="1. Prefix & 2. Language",
                value=f"• **Prefix:** `{cfg['prefix']}`\n• **Language:** `{cfg['language']}`",
                inline=True,
            )
            emb.add_field(
                name="3. Welcome & 4. Goodbye Channels",
                value=(
                    f"• **Welcome:** {'🟢' if cfg['welcome_enabled'] else '⚪'} {_ch(cfg['welcome_channel_id'])}\n"
                    f"• **Goodbye:** {'🟢' if cfg['goodbye_enabled'] else '⚪'} {_ch(cfg['goodbye_channel_id'])}\n"
                    f"• **Auto-Role:** {_role(cfg['auto_role_id'])}"
                ),
                inline=True,
            )
            emb.add_field(
                name="5. Logging Channels",
                value=(
                    f"• **Server Logs:** {_ch(cfg['log_channel_id'])}\n"
                    f"• **Mod Logs:** {_ch(cfg['mod_log_channel_id'])}"
                ),
                inline=False,
            )
            emb.add_field(
                name="6. Moderation & AutoMod Settings",
                value=(
                    f"• **AutoMod:** `{'Enabled' if cfg['automod_enabled'] else 'Disabled'}`\n"
                    f"• **Max Mentions:** `{cfg['automod_max_mentions']}` | **Anti-Invite:** `{'Yes' if cfg['automod_anti_invite'] else 'No'}`\n"
                    f"• **Spam Threshold:** `{cfg['automod_spam_threshold']} msgs / {cfg['automod_spam_window_sec']}s`"
                ),
                inline=False,
            )
        elif page == 2:
            emb = make_embed(
                f"🎛️ Project Nova Setup Dashboard — {guild.name} (Page 2/3)",
                "Tickets, RBAC Staff Roles, Activity Roles, Reaction Roles & Join-to-Create.",
                color=discord.Color.blurple(),
            )
            emb.add_field(
                name="7. Ticket Categories & Settings",
                value=(
                    f"• **Categories ({len(ticket_cats)}):** {', '.join(c['name'] for c in ticket_cats[:6])}\n"
                    f"• **Ticket Parent Category:** {_ch(cfg['ticket_category_id'])}\n"
                    f"• **Transcript Log:** {_ch(cfg['ticket_log_channel_id'])} | **Limit/User:** `{cfg['ticket_limit_per_member']}`"
                ),
                inline=False,
            )
            emb.add_field(
                name="8. Staff Roles & 15. Permissions",
                value=(
                    f"• **Configured Staff Roles:** `{len(staff_roles)}` role mapping(s)\n"
                    f"• **Command/Category Overrides:** `{len(perm_rules)}` custom rule(s)"
                ),
                inline=False,
            )
            emb.add_field(
                name="9. Activity Roles & 10. Reaction Roles",
                value=(
                    f"• **Activity Role Rules:** `{len(activity_rules)}` active rule(s)\n"
                    f"• **Reaction/Button/Select Panels:** `{len(rr_panels)}` panel(s)"
                ),
                inline=False,
            )
            emb.add_field(
                name="11. Join-to-Create (JTC) Settings",
                value=(
                    f"• **Trigger Voice Channel:** {_ch(cfg['jtc_trigger_channel_id'])}\n"
                    f"• **Parent Category:** {_ch(cfg['jtc_category_id'])}\n"
                    f"• **Naming Format:** `{cfg['jtc_default_name']}` (Limit: `{cfg['jtc_default_limit']}`)"
                ),
                inline=False,
            )
        else:
            emb = make_embed(
                f"🎛️ Project Nova Setup Dashboard — {guild.name} (Page 3/3)",
                "AI Assistant, Voice Music System & Keyword Auto-Responder.",
                color=discord.Color.blurple(),
            )
            emb.add_field(
                name="12. AI Assistant Settings",
                value=(
                    f"• **Status:** `{'Enabled' if cfg['ai_enabled'] else 'Disabled'}`\n"
                    f"• **Provider:** `{cfg['ai_provider']}` | **Model:** `{cfg['ai_model']}`\n"
                    f"• **Endpoint:** `{cfg['ai_endpoint']}`\n"
                    f"• **Per-User Cooldown:** `{cfg['ai_cooldown_sec']}s`"
                ),
                inline=False,
            )
            emb.add_field(
                name="13. Music Settings",
                value=(
                    f"• **Default Volume:** `{cfg['music_default_volume']}%`\n"
                    f"• **Idle Disconnect:** `{cfg['music_idle_timeout_sec']}s`\n"
                    f"• **DJ Role:** {_role(cfg['music_dj_role_id'])}"
                ),
                inline=False,
            )
            emb.add_field(
                name="14. Auto-Responder Settings",
                value=f"• **Configured Keyword Triggers:** `{len(responders)}` trigger(s)",
                inline=False,
            )
        return emb

    @commands.hybrid_command(
        name="setup",
        aliases=["dashboard", "config"],
        description="Launch the interactive Project Nova server configuration dashboard.",
    )
    @commands.guild_only()
    @require_tier("administrator")
    async def setup_command(self, ctx: commands.Context) -> None:
        """Open the interactive server configuration wizard."""
        assert ctx.guild is not None
        emb = await self.build_dashboard_embed(ctx.guild, page=1)
        view = SetupDashboardView(self.bot, page=1)
        await ctx.send(embed=emb, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupWizardCog(bot))
