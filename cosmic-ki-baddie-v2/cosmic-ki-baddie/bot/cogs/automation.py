"""Automation Module: Keyword Autoresponder, Welcome/Goodbye Messages, Auto-Role & Scheduled Announcements."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.services.permission_service import require_tier
from bot.utils.formatting import make_embed

logger = logging.getLogger("project_nova.cogs.automation")


class AutomationCog(commands.Cog, name="AutomationCog"):
    """Keyword Auto-Responder, Welcome/Goodbye, Auto-Role & Scheduled Announcements."""

    CATEGORY = "Automation"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Cooldown tracking: (guild_id, responder_id, user_id) -> monotonic timestamp
        self._responder_cooldowns: Dict[Tuple[int, int, int], float] = {}

    async def cog_load(self) -> None:
        self.scheduled_announcements_loop.start()

    async def cog_unload(self) -> None:
        self.scheduled_announcements_loop.cancel()

    def _format_template(
        self, template: str, member: discord.abc.User, guild: discord.Guild, channel: Any = None
    ) -> str:
        return (
            template.replace("{user}", member.mention)
            .replace("{user_name}", str(member))
            .replace("{server}", guild.name)
            .replace("{member_count}", str(guild.member_count))
            .replace("{channel}", getattr(channel, "mention", ""))
        )

    @tasks.loop(seconds=60)
    async def scheduled_announcements_loop(self) -> None:
        """Background task executing scheduled announcements when their interval elapses."""
        if not self.bot.db.is_connected:
            return
        rows = await self.bot.automation_repo.list_scheduled_announcements()
        now = datetime.now(timezone.utc)
        for row in rows:
            if not row.get("enabled"):
                continue
            guild = self.bot.get_guild(int(row["guild_id"]))
            if not guild:
                continue
            ch = guild.get_channel(int(row["channel_id"]))
            if not isinstance(ch, discord.TextChannel):
                continue
            last_str = row.get("last_run_at")
            should_run = False
            if not last_str:
                should_run = True
            else:
                try:
                    last_dt = datetime.fromisoformat(str(last_str)).replace(tzinfo=timezone.utc)
                    elapsed_min = (now - last_dt).total_seconds() / 60.0
                    if elapsed_min >= int(row.get("interval_minutes") or 60):
                        should_run = True
                except Exception:
                    should_run = True
            if should_run:
                try:
                    emb = make_embed(
                        "📣 Scheduled Announcement",
                        str(row["message_text"]),
                        color=discord.Color.blurple(),
                    )
                    await ch.send(embed=emb)
                    await self.bot.db.execute(
                        "UPDATE scheduled_announcements SET last_run_at = ? WHERE schedule_id = ?;",
                        (now.isoformat(), int(row["schedule_id"])),
                    )
                except Exception as exc:
                    logger.debug("Scheduled announcement error: %s", exc)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Handle Welcome message and automatic role assignment when a member joins."""
        if member.bot or member.guild is None:
            return
        guild = member.guild
        cfg = await self.bot.guild_config_repo.ensure_guild(guild.id)

        # 1. Automatic Role Assignment
        auto_role_id = cfg.get("auto_role_id")
        if auto_role_id:
            role = guild.get_role(int(auto_role_id))
            if role:
                ok, _ = self.bot.permission_service.validate_role_assignment(guild, role)
                if ok:
                    try:
                        await member.add_roles(role, reason="Project Nova Auto-Role on Join")
                    except Exception:
                        pass

        # 2. Welcome Message
        if cfg.get("welcome_enabled") and cfg.get("welcome_channel_id"):
            ch = guild.get_channel(int(cfg["welcome_channel_id"]))
            if isinstance(ch, discord.TextChannel):
                text = self._format_template(
                    str(cfg.get("welcome_message") or "Welcome {user} to **{server}**!"),
                    member,
                    guild,
                    ch,
                )
                emb = make_embed(f"👋 Welcome to {guild.name}!", text, color=discord.Color.green())
                emb.set_thumbnail(url=str(member.display_avatar))
                try:
                    await ch.send(content=member.mention, embed=emb)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Handle Goodbye message when a member leaves the server."""
        if member.bot or member.guild is None:
            return
        guild = member.guild
        cfg = await self.bot.guild_config_repo.ensure_guild(guild.id)
        if cfg.get("goodbye_enabled") and cfg.get("goodbye_channel_id"):
            ch = guild.get_channel(int(cfg["goodbye_channel_id"]))
            if isinstance(ch, discord.TextChannel):
                text = self._format_template(
                    str(cfg.get("goodbye_message") or "Goodbye **{user_name}**!"),
                    member,
                    guild,
                    ch,
                )
                emb = make_embed(f"👋 Member Left — {member}", text, color=discord.Color.orange())
                try:
                    await ch.send(embed=emb)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Non-blocking keyword autoresponder listener.

        Never blocks or prevents `bot.process_commands(message)` in `ProjectNovaBot.on_message`.
        """
        if message.author.bot or message.guild is None or not message.content:
            return
        prefix = await self.bot.guild_config_repo.get_prefix(message.guild.id)
        if message.content.startswith(prefix) or message.content.startswith("/"):
            return

        rules = await self.bot.automation_repo.list_autoresponders(message.guild.id)
        if not rules:
            return

        member_role_ids = {r.id for r in getattr(message.author, "roles", [])}
        now = time.monotonic()

        for rule in rules:
            if not rule.get("enabled"):
                continue

            # Check channel restriction
            allowed_channels = rule.get("allowed_channel_ids", [])
            if allowed_channels and message.channel.id not in allowed_channels:
                continue

            # Check role restriction
            allowed_roles = rule.get("allowed_role_ids", [])
            if allowed_roles and not member_role_ids.intersection(set(allowed_roles)):
                continue

            trigger = str(rule["trigger_text"])
            content = message.content
            if not rule.get("case_sensitive"):
                trigger_cmp = trigger.lower()
                content_cmp = content.lower()
            else:
                trigger_cmp = trigger
                content_cmp = content

            matched = (
                content_cmp.strip() == trigger_cmp
                if rule.get("match_mode") == "exact"
                else trigger_cmp in content_cmp
            )
            if not matched:
                continue

            # Enforce per-user cooldown for this trigger
            cd_sec = int(rule.get("cooldown_sec") or 0)
            cd_key = (message.guild.id, int(rule["responder_id"]), message.author.id)
            last_used = self._responder_cooldowns.get(cd_key, 0.0)
            if cd_sec > 0 and (now - last_used) < cd_sec:
                continue

            self._responder_cooldowns[cd_key] = now
            reply_text = self._format_template(
                str(rule["response_text"]), message.author, message.guild, message.channel
            )
            try:
                await message.channel.send(reply_text)
            except Exception:
                pass
            break

    @commands.hybrid_group(
        name="autoresponder",
        aliases=["ar", "triggers"],
        description="Configure keyword-based autoresponder triggers and responses.",
        fallback="list",
    )
    @commands.guild_only()
    @require_tier("management")
    async def autoresponder_group(self, ctx: commands.Context) -> None:
        """List all configured keyword autoresponders for this server."""
        assert ctx.guild is not None
        rows = await self.bot.automation_repo.list_autoresponders(ctx.guild.id)
        if not rows:
            emb = make_embed(
                "⚙️ Keyword Auto-Responders",
                "No autoresponders configured. Use `/autoresponder add` to create one.",
                color=discord.Color.blurple(),
            )
            await ctx.send(embed=emb)
            return

        lines = [
            f"• **`{r['trigger_text']}`** ({r['match_mode']}, CaseSensitive: `{'Yes' if r['case_sensitive'] else 'No'}`, CD: `{r['cooldown_sec']}s`, Status: `{'ON' if r['enabled'] else 'OFF'}`) → {r['response_text'][:60]}"
            for r in rows
        ]
        emb = make_embed(
            f"⚙️ Keyword Auto-Responders — {ctx.guild.name} ({len(rows)})",
            "\n".join(lines),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb)

    @autoresponder_group.command(
        name="add",
        description="Add or update a keyword autoresponder trigger.",
    )
    @app_commands.describe(
        trigger="Keyword or phrase that triggers the response",
        match_mode="Matching mode: exact or partial",
        case_sensitive="Whether matching is case-sensitive",
        cooldown="Cooldown in seconds per user",
        response="Response message (supports {user}, {server})",
    )
    @require_tier("management")
    async def ar_add(
        self,
        ctx: commands.Context,
        trigger: str,
        match_mode: str = "exact",
        case_sensitive: bool = False,
        cooldown: int = 5,
        *,
        response: str,
    ) -> None:
        """Create or update an autoresponder rule."""
        assert ctx.guild is not None
        mode = match_mode.lower().strip()
        if mode not in ("exact", "partial"):
            raise commands.BadArgument("`match_mode` must be `exact` or `partial`.")
        await self.bot.automation_repo.upsert_autoresponder(
            ctx.guild.id,
            trigger,
            response,
            match_mode=mode,
            case_sensitive=case_sensitive,
            cooldown_sec=max(0, int(cooldown)),
            enabled=True,
        )
        emb = make_embed(
            "✅ Auto-Responder Saved",
            (
                f"• **Trigger:** `{trigger}`\n"
                f"• **Mode:** `{mode}` (Case-Sensitive: `{case_sensitive}`)\n"
                f"• **Cooldown:** `{cooldown}s`\n"
                f"• **Response:** {response}"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @autoresponder_group.command(
        name="remove",
        description="Delete an autoresponder trigger.",
    )
    @app_commands.describe(trigger="The trigger keyword to remove")
    @require_tier("management")
    async def ar_remove(self, ctx: commands.Context, *, trigger: str) -> None:
        """Delete a keyword autoresponder."""
        assert ctx.guild is not None
        deleted = await self.bot.automation_repo.delete_autoresponder(ctx.guild.id, trigger)
        await ctx.send(
            embed=make_embed(
                "🗑️ Auto-Responder Removed" if deleted else "❓ Trigger Not Found",
                f"Removed trigger `{trigger}`." if deleted else f"Trigger `{trigger}` not found.",
                color=discord.Color.green() if deleted else discord.Color.orange(),
            )
        )

    @autoresponder_group.command(
        name="toggle",
        description="Enable or disable an existing autoresponder trigger.",
    )
    @app_commands.describe(trigger="Trigger keyword", enabled="True to enable, False to disable")
    @require_tier("management")
    async def ar_toggle(
        self, ctx: commands.Context, enabled: bool, *, trigger: str
    ) -> None:
        """Enable or disable a keyword autoresponder."""
        assert ctx.guild is not None
        updated = await self.bot.automation_repo.toggle_autoresponder(
            ctx.guild.id, trigger, enabled
        )
        if not updated:
            raise commands.BadArgument(f"Autoresponder trigger `{trigger}` was not found.")
        await ctx.send(
            embed=make_embed(
                "⚙️ Auto-Responder Toggled",
                f"Trigger `{trigger}` is now **{'Enabled' if enabled else 'Disabled'}**.",
                color=discord.Color.green(),
            )
        )

    @commands.hybrid_command(
        name="welcome",
        description="Configure the server's welcome channel and welcome message.",
    )
    @app_commands.describe(
        channel="Channel where welcome messages are sent",
        enabled="Enable or disable welcome messages",
        message="Welcome template ({user}, {user_name}, {server})",
    )
    @commands.guild_only()
    @require_tier("management")
    async def welcome_config(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        enabled: bool = True,
        *,
        message: str = "Welcome {user} to **{server}**!",
    ) -> None:
        """Configure automatic welcome messages."""
        assert ctx.guild is not None
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id,
            welcome_enabled=1 if enabled else 0,
            welcome_channel_id=channel.id,
            welcome_message=message,
        )
        await ctx.send(
            embed=make_embed(
                "👋 Welcome Configuration Updated",
                f"• **Status:** `{'Enabled' if enabled else 'Disabled'}`\n• **Channel:** {channel.mention}\n• **Message:** {message}",
                color=discord.Color.green(),
            )
        )

    @commands.hybrid_command(
        name="goodbye",
        description="Configure the server's goodbye channel and goodbye message.",
    )
    @app_commands.describe(
        channel="Channel where goodbye messages are sent",
        enabled="Enable or disable goodbye messages",
        message="Goodbye template ({user_name}, {server})",
    )
    @commands.guild_only()
    @require_tier("management")
    async def goodbye_config(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        enabled: bool = True,
        *,
        message: str = "Goodbye **{user_name}**, we will miss you!",
    ) -> None:
        """Configure automatic goodbye messages."""
        assert ctx.guild is not None
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id,
            goodbye_enabled=1 if enabled else 0,
            goodbye_channel_id=channel.id,
            goodbye_message=message,
        )
        await ctx.send(
            embed=make_embed(
                "👋 Goodbye Configuration Updated",
                f"• **Status:** `{'Enabled' if enabled else 'Disabled'}`\n• **Channel:** {channel.mention}\n• **Message:** {message}",
                color=discord.Color.green(),
            )
        )

    @commands.hybrid_command(
        name="autorole",
        description="Configure the automatic role assigned to new members when they join.",
    )
    @app_commands.describe(role="Role to automatically grant on join")
    @commands.guild_only()
    @require_tier("management")
    async def autorole_config(
        self, ctx: commands.Context, role: discord.Role
    ) -> None:
        """Set the auto-role granted to new members upon joining."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        ok, err = self.bot.permission_service.validate_role_assignment(ctx.guild, role, ctx.author)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy validation failed.")
        await self.bot.guild_config_repo.update_fields(ctx.guild.id, auto_role_id=role.id)
        await ctx.send(
            embed=make_embed(
                "✅ Auto-Role Configured",
                f"New members joining **{ctx.guild.name}** will automatically receive {role.mention}.",
                color=discord.Color.green(),
            )
        )

    @commands.hybrid_group(
        name="schedule",
        description="Configure recurring scheduled announcements.",
        fallback="list",
    )
    @commands.guild_only()
    @require_tier("management")
    async def schedule_group(self, ctx: commands.Context) -> None:
        """List all scheduled announcements for this server."""
        assert ctx.guild is not None
        rows = await self.bot.automation_repo.list_scheduled_announcements(ctx.guild.id)
        if not rows:
            await ctx.send(
                embed=make_embed(
                    "⏰ Scheduled Announcements",
                    "No scheduled announcements configured. Use `/schedule add`.",
                    color=discord.Color.blurple(),
                )
            )
            return
        lines = [
            f"• **`#{r['schedule_id']}`** in <#{r['channel_id']}> (every `{r['interval_minutes']}m`): {r['message_text'][:60]}"
            for r in rows
        ]
        await ctx.send(
            embed=make_embed(
                f"⏰ Scheduled Announcements ({len(rows)})",
                "\n".join(lines),
                color=discord.Color.blurple(),
            )
        )

    @schedule_group.command(
        name="add",
        description="Create a recurring scheduled announcement.",
    )
    @app_commands.describe(
        channel="Target text channel",
        interval_minutes="Interval in minutes (minimum 1)",
        message="Announcement message content",
    )
    @require_tier("management")
    async def schedule_add(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        interval_minutes: int,
        *,
        message: str,
    ) -> None:
        """Add a recurring scheduled announcement."""
        assert ctx.guild is not None
        sid = await self.bot.automation_repo.add_scheduled_announcement(
            ctx.guild.id, channel.id, message, max(1, int(interval_minutes))
        )
        await ctx.send(
            embed=make_embed(
                f"✅ Scheduled Announcement #{sid} Created",
                f"Will post in {channel.mention} every **`{max(1, int(interval_minutes))}m`**.",
                color=discord.Color.green(),
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutomationCog(bot))
