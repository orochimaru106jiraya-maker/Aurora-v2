"""Moderation & AutoMod Cog (`ban`, `unban`, `kick`, `timeout`, `untimeout`, `warn`, `warnings`, `clearwarnings`, `purge`, `slowmode`, `lock`, `unlock`, `snipe`, `modlogs`, `automod`)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import json
import logging
import re
import time
from typing import Any, Callable, Coroutine, Deque, Dict, List, Optional, Tuple
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.permission_service import require_tier
from bot.utils.formatting import format_duration, make_embed, parse_duration

logger = logging.getLogger("project_nova.cogs.moderation")

INVITE_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discordapp\.com/invite|discord\.com/invite)/[a-zA-Z0-9-]+",
    re.IGNORECASE,
)
URL_REGEX = re.compile(r"https?://[^\s/$.?#].[^\s]*", re.IGNORECASE)
SNIPE_TTL_SECONDS = 300  # 5-minute privacy expiration for snipe cache
SAFE_PURGE_MAX = 100


class DestructiveActionConfirmView(discord.ui.View):
    """Confirmation dialog for destructive moderation actions."""

    def __init__(
        self,
        author_id: int,
        action_label: str,
        on_confirm_coro: Callable[[discord.Interaction], Coroutine[Any, Any, None]],
    ) -> None:
        super().__init__(timeout=60.0)
        self.author_id = author_id
        self.on_confirm_coro = on_confirm_coro
        self.confirmed = False

        confirm_btn = discord.ui.Button(
            label=f"Confirm {action_label}",
            style=discord.ButtonStyle.danger,
            emoji="⚠️",
            custom_id="nova:mod:confirm",
        )
        confirm_btn.callback = self._confirm  # type: ignore
        self.add_item(confirm_btn)

        cancel_btn = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            emoji="✖️",
            custom_id="nova:mod:cancel",
        )
        cancel_btn.callback = self._cancel  # type: ignore
        self.add_item(cancel_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the moderator who initiated this command can confirm it.",
                ephemeral=True,
            )
            return False
        return True

    async def _confirm(self, interaction: discord.Interaction) -> None:
        self.confirmed = True
        await self.on_confirm_coro(interaction)
        self.stop()

    async def _cancel(self, interaction: discord.Interaction) -> None:
        emb = make_embed(
            "✖️ Action Cancelled",
            "The moderation action was cancelled.",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=emb, view=None)
        self.stop()


class ModerationCog(commands.Cog, name="ModerationCog"):
    """Comprehensive Server Moderation, Audit Logging & Automatic Moderation."""

    CATEGORY = "Moderation"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Limited, temporary in-memory store for deleted messages per channel_id
        # Stores (author_name, author_id, content, deleted_timestamp_monotonic, deleted_dt)
        self._snipe_cache: Dict[int, Tuple[str, int, str, float, datetime]] = {}
        # Anti-spam sliding window per (guild_id, user_id) -> deque of timestamps
        self._spam_buckets: Dict[Tuple[int, int], Deque[float]] = {}

    async def _dispatch_mod_log(
        self,
        guild: discord.Guild,
        action: str,
        target_str: str,
        target_id: int,
        moderator: discord.abc.User,
        reason: str,
        details: Optional[str] = None,
    ) -> None:
        """Persist moderation action in SQLite and post to the configured mod-log channel."""
        await self.bot.mod_repo.log_mod_action(
            guild.id, action, target_id, moderator.id, reason, details
        )
        cfg = await self.bot.guild_config_repo.ensure_guild(guild.id)
        log_ch_id = cfg.get("mod_log_channel_id") or cfg.get("log_channel_id")
        if log_ch_id:
            ch = guild.get_channel(int(log_ch_id))
            if isinstance(ch, discord.TextChannel):
                emb = make_embed(
                    f"🛡️ Mod Log — {action.upper()}",
                    (
                        f"• **Target:** {target_str} (`{target_id}`)\n"
                        f"• **Moderator:** {moderator.mention} (`{moderator.id}`)\n"
                        f"• **Reason:** {reason}"
                        + (f"\n• **Details:** {details}" if details else "")
                    ),
                    color=discord.Color.orange(),
                )
                try:
                    await ch.send(embed=emb)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Store a single temporary, privacy-respecting snipe record per channel."""
        if not message.guild or not message.channel or not message.author:
            return
        if message.author.bot or not message.content:
            return
        # Limit content length and overwrite previous entry for this channel
        self._snipe_cache[message.channel.id] = (
            str(message.author),
            int(message.author.id),
            message.content[:500],
            time.monotonic(),
            datetime.now(timezone.utc),
        )

    async def check_automod_message(self, message: discord.Message) -> bool:
        """Evaluate incoming guild messages against AutoMod rules. Returns True if blocked."""
        if message.guild is None or not isinstance(message.author, discord.Member):
            return False
        if message.author.bot:
            return False
        # Staff (moderator+) bypass AutoMod
        if await self.bot.permission_service.has_tier(message.author, "moderator"):
            return False

        cfg = await self.bot.guild_config_repo.ensure_guild(message.guild.id)
        if not cfg.get("automod_enabled"):
            return False

        content = message.content or ""
        violation_reason: Optional[str] = None

        # 1. Bad words check
        bad_words: List[str] = json.loads(cfg.get("automod_bad_words") or "[]")
        lower_content = content.lower()
        for word in bad_words:
            if word and word.lower() in lower_content:
                violation_reason = f"AutoMod: Prohibited word (`{word}`)"
                break

        # 2. Anti-invite check
        if not violation_reason and cfg.get("automod_anti_invite"):
            if INVITE_REGEX.search(content):
                violation_reason = "AutoMod: Unauthorized Discord server invite link"

        # 3. Anti-link check
        if not violation_reason and cfg.get("automod_anti_links"):
            if URL_REGEX.search(content):
                violation_reason = "AutoMod: External links are restricted"

        # 4. Mass mentions check
        max_mentions = int(cfg.get("automod_max_mentions") or 5)
        if not violation_reason and len(getattr(message, "mentions", [])) >= max_mentions:
            violation_reason = f"AutoMod: Mass mention limit exceeded ({len(message.mentions)}/{max_mentions})"

        # 5. Anti-spam rate check
        if not violation_reason:
            threshold = int(cfg.get("automod_spam_threshold") or 6)
            window = int(cfg.get("automod_spam_window_sec") or 5)
            now = time.monotonic()
            key = (message.guild.id, message.author.id)
            bucket = self._spam_buckets.setdefault(key, deque())
            while bucket and now - bucket[0] > window:
                bucket.popleft()
            bucket.append(now)
            if len(bucket) >= threshold:
                violation_reason = f"AutoMod: Message spam detected ({len(bucket)} msgs in {window}s)"

        if not violation_reason:
            return False

        try:
            await message.delete()
        except Exception:
            pass

        await self.bot.mod_repo.add_warning(
            message.guild.id,
            message.author.id,
            message.guild.me.id if message.guild.me else 0,
            violation_reason,
        )
        await self._dispatch_mod_log(
            message.guild,
            "automod",
            message.author.mention,
            message.author.id,
            message.guild.me or self.bot.user,
            violation_reason,
        )
        if message.channel:
            warn_emb = make_embed(
                "🤖 AutoMod Intervention",
                f"{message.author.mention}, your message was removed: **{violation_reason}**.",
                color=discord.Color.red(),
            )
            try:
                await message.channel.send(embed=warn_emb)
            except Exception:
                pass
        return True

    @commands.hybrid_command(
        name="ban",
        description="Ban a member from the server with hierarchy validation and audit logging.",
    )
    @app_commands.describe(
        member="The member to ban",
        reason="Reason for the ban",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(ban_members=True)
    @require_tier("moderator")
    async def ban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Ban a member from the server after validating role hierarchy."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        ok, err = self.bot.permission_service.validate_moderation_hierarchy(ctx.author, member)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy check failed.")

        await member.ban(reason=f"Banned by {ctx.author} ({ctx.author.id}): {reason}")
        await self._dispatch_mod_log(
            ctx.guild, "ban", str(member), member.id, ctx.author, reason
        )
        emb = make_embed(
            "🔨 Member Banned",
            f"• **Member:** {member.mention} (`{member.id}`)\n"
            f"• **Moderator:** {ctx.author.mention}\n"
            f"• **Reason:** {reason}",
            color=discord.Color.red(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="unban",
        description="Unban a user from the server by their Discord user ID.",
    )
    @app_commands.describe(user_id="The Discord user ID to unban", reason="Audit reason")
    @commands.guild_only()
    @commands.bot_has_permissions(ban_members=True)
    @require_tier("moderator")
    async def unban(
        self,
        ctx: commands.Context,
        user_id: str,
        *,
        reason: str = "Unbanned by moderator",
    ) -> None:
        """Unban a previously banned user by ID."""
        assert ctx.guild is not None
        clean_id = user_id.strip("<@!>")
        if not clean_id.isdigit():
            raise commands.BadArgument("Please provide a valid numeric Discord user ID.")
        uid = int(clean_id)
        try:
            await ctx.guild.unban(discord.Object(id=uid), reason=f"{ctx.author}: {reason}")
        except discord.NotFound:
            raise commands.BadArgument(f"User ID `{uid}` is not currently banned.")

        await self._dispatch_mod_log(
            ctx.guild, "unban", f"<@{uid}>", uid, ctx.author, reason
        )
        emb = make_embed(
            "🔓 User Unbanned",
            f"• **User ID:** `{uid}` (<@{uid}>)\n• **Moderator:** {ctx.author.mention}\n• **Reason:** {reason}",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="kick",
        description="Kick a member from the server with role hierarchy validation.",
    )
    @app_commands.describe(member="The member to kick", reason="Reason for the kick")
    @commands.guild_only()
    @commands.bot_has_permissions(kick_members=True)
    @require_tier("moderator")
    async def kick(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Kick a member from the server."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        ok, err = self.bot.permission_service.validate_moderation_hierarchy(ctx.author, member)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy check failed.")

        await member.kick(reason=f"Kicked by {ctx.author} ({ctx.author.id}): {reason}")
        await self._dispatch_mod_log(
            ctx.guild, "kick", str(member), member.id, ctx.author, reason
        )
        emb = make_embed(
            "👢 Member Kicked",
            f"• **Member:** {member.mention} (`{member.id}`)\n"
            f"• **Moderator:** {ctx.author.mention}\n"
            f"• **Reason:** {reason}",
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="timeout",
        aliases=["mute"],
        description="Timeout (mute) a member for a specified duration (e.g. 10m, 1h, 1d).",
    )
    @app_commands.describe(
        member="The member to timeout",
        duration="Duration (e.g. 10m, 1h, 1d; max 28d)",
        reason="Reason for the timeout",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(moderate_members=True)
    @require_tier("moderator")
    async def timeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: str = "10m",
        *,
        reason: str = "No reason provided",
    ) -> None:
        """Apply a Discord communication timeout to a member."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        ok, err = self.bot.permission_service.validate_moderation_hierarchy(ctx.author, member)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy check failed.")

        secs = parse_duration(duration)
        if not secs or secs < 5 or secs > 28 * 86400:
            raise commands.BadArgument(
                "Invalid duration. Specify between `5s` and `28d` (e.g. `10m`, `2h`, `1d`)."
            )

        await member.timeout(timedelta(seconds=secs), reason=f"{ctx.author}: {reason}")
        await self._dispatch_mod_log(
            ctx.guild,
            "timeout",
            str(member),
            member.id,
            ctx.author,
            reason,
            details=f"Duration: {format_duration(secs)}",
        )
        emb = make_embed(
            "🔇 Member Timed Out",
            (
                f"• **Member:** {member.mention} (`{member.id}`)\n"
                f"• **Duration:** `{format_duration(secs)}`\n"
                f"• **Moderator:** {ctx.author.mention}\n"
                f"• **Reason:** {reason}"
            ),
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="untimeout",
        aliases=["unmute", "removetimeout"],
        description="Remove an active timeout from a member.",
    )
    @app_commands.describe(member="The member whose timeout to remove", reason="Reason")
    @commands.guild_only()
    @commands.bot_has_permissions(moderate_members=True)
    @require_tier("moderator")
    async def untimeout(
        self,
        ctx: commands.Context,
        member: discord.Member,
        *,
        reason: str = "Timeout removed by moderator",
    ) -> None:
        """Clear a member's communication timeout."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        ok, err = self.bot.permission_service.validate_moderation_hierarchy(ctx.author, member)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy check failed.")

        await member.timeout(None, reason=f"{ctx.author}: {reason}")
        await self._dispatch_mod_log(
            ctx.guild, "untimeout", str(member), member.id, ctx.author, reason
        )
        emb = make_embed(
            "🔊 Timeout Removed",
            f"• **Member:** {member.mention}\n• **Moderator:** {ctx.author.mention}\n• **Reason:** {reason}",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="warn",
        description="Issue an official warning to a member and record it in SQLite.",
    )
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    @commands.guild_only()
    @require_tier("moderator")
    async def warn(
        self, ctx: commands.Context, member: discord.Member, *, reason: str
    ) -> None:
        """Warn a member and persist the warning in the server database."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        ok, err = self.bot.permission_service.validate_moderation_hierarchy(ctx.author, member)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy check failed.")

        warn_id = await self.bot.mod_repo.add_warning(
            ctx.guild.id, member.id, ctx.author.id, reason
        )
        history = await self.bot.mod_repo.get_warnings(ctx.guild.id, member.id)
        await self._dispatch_mod_log(
            ctx.guild,
            "warn",
            str(member),
            member.id,
            ctx.author,
            reason,
            details=f"Warning #{warn_id} (Total: {len(history)})",
        )
        try:
            await member.send(
                embed=make_embed(
                    f"⚠️ Warning Received in {ctx.guild.name}",
                    f"• **Reason:** {reason}\n• **Total Warnings:** `{len(history)}`",
                    color=discord.Color.orange(),
                )
            )
        except Exception:
            pass

        emb = make_embed(
            f"⚠️ Member Warned (#{warn_id})",
            (
                f"• **Member:** {member.mention} (`{member.id}`)\n"
                f"• **Moderator:** {ctx.author.mention}\n"
                f"• **Reason:** {reason}\n"
                f"• **Total Active Warnings:** `{len(history)}`"
            ),
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="warnings",
        aliases=["warnhistory", "warns"],
        description="Display the warning history for a member.",
    )
    @app_commands.describe(member="The member whose warning history to view")
    @commands.guild_only()
    @require_tier("support")
    async def warnings(self, ctx: commands.Context, member: discord.Member) -> None:
        """Inspect all recorded warnings for a member."""
        assert ctx.guild is not None
        rows = await self.bot.mod_repo.get_warnings(ctx.guild.id, member.id)
        if not rows:
            emb = make_embed(
                f"📋 Warnings — {member}",
                f"{member.mention} has a clean record (**0** warnings).",
                color=discord.Color.green(),
            )
            await ctx.send(embed=emb)
            return

        lines = [
            f"• **`#{r['warn_id']}`** ({r['created_at']}) by <@{r['moderator_id']}>: {r['reason']}"
            for r in rows[:15]
        ]
        emb = make_embed(
            f"📋 Warning History — {member} ({len(rows)})",
            "\n".join(lines),
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="clearwarnings",
        aliases=["clearwarns"],
        description="Clear all recorded warnings for a member (includes confirmation dialog).",
    )
    @app_commands.describe(member="Member whose warnings should be cleared")
    @commands.guild_only()
    @require_tier("moderator")
    async def clearwarnings(
        self, ctx: commands.Context, member: discord.Member
    ) -> None:
        """Clear all warnings for a member."""
        assert ctx.guild is not None
        count = await self.bot.mod_repo.clear_warnings(ctx.guild.id, member.id)
        await self._dispatch_mod_log(
            ctx.guild,
            "clearwarnings",
            str(member),
            member.id,
            ctx.author,
            f"Cleared {count} warning(s)",
        )
        emb = make_embed(
            "🧹 Warnings Cleared",
            f"Cleared **{count}** warning(s) for {member.mention}.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="purge",
        aliases=["clear", "prune"],
        description="Bulk delete between 1 and 100 messages in the current text channel.",
    )
    @app_commands.describe(amount="Number of messages to delete (1 to 100)")
    @commands.guild_only()
    @commands.bot_has_permissions(manage_messages=True)
    @require_tier("moderator")
    async def purge(self, ctx: commands.Context, amount: int) -> None:
        """Delete up to 100 recent messages in the channel."""
        assert ctx.guild is not None and isinstance(ctx.channel, discord.TextChannel)
        if amount < 1 or amount > SAFE_PURGE_MAX:
            raise commands.BadArgument(
                f"Safe purge limit: Please specify an amount between **1** and **{SAFE_PURGE_MAX}**."
            )
        deleted = await ctx.channel.purge(limit=amount)
        await self._dispatch_mod_log(
            ctx.guild,
            "purge",
            f"#{ctx.channel.name}",
            ctx.channel.id,
            ctx.author,
            f"Purged {len(deleted)} message(s)",
        )
        emb = make_embed(
            "🧹 Channel Purged",
            f"Deleted **{len(deleted)}** message(s) in {ctx.channel.mention}.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb, ephemeral=True)

    @commands.hybrid_command(
        name="slowmode",
        description="Set the slowmode delay (in seconds) for the current text channel.",
    )
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to 21600)")
    @commands.guild_only()
    @commands.bot_has_permissions(manage_channels=True)
    @require_tier("moderator")
    async def slowmode(self, ctx: commands.Context, seconds: int = 0) -> None:
        """Configure channel slowmode between 0 and 21600 seconds."""
        assert ctx.guild is not None and isinstance(ctx.channel, discord.TextChannel)
        if seconds < 0 or seconds > 21600:
            raise commands.BadArgument("Slowmode must be between **0** and **21600** seconds (6 hours).")
        await ctx.channel.edit(slowmode_delay=seconds, reason=f"Slowmode set by {ctx.author}")
        await self._dispatch_mod_log(
            ctx.guild,
            "slowmode",
            f"#{ctx.channel.name}",
            ctx.channel.id,
            ctx.author,
            f"Slowmode set to {seconds}s",
        )
        emb = make_embed(
            "⏱️ Slowmode Updated",
            f"Slowmode for {ctx.channel.mention} is now **`{seconds}s`**."
            if seconds > 0
            else f"Slowmode disabled for {ctx.channel.mention}.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="lock",
        description="Lock a text channel so @everyone cannot send messages.",
    )
    @app_commands.describe(
        channel="Channel to lock (defaults to current)",
        reason="Reason for locking",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(manage_channels=True)
    @require_tier("moderator")
    async def lock(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel] = None,
        *,
        reason: str = "Channel locked by moderator",
    ) -> None:
        """Prevent `@everyone` from sending messages in the channel."""
        assert ctx.guild is not None
        target = channel or ctx.channel
        assert isinstance(target, discord.TextChannel)
        await target.set_permissions(
            ctx.guild.default_role,
            send_messages=False,
            reason=f"Locked by {ctx.author}: {reason}",
        )
        await self._dispatch_mod_log(
            ctx.guild, "lock", f"#{target.name}", target.id, ctx.author, reason
        )
        emb = make_embed(
            "🔒 Channel Locked",
            f"{target.mention} has been locked.\n• **Reason:** {reason}",
            color=discord.Color.red(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="unlock",
        description="Unlock a previously locked text channel for @everyone.",
    )
    @app_commands.describe(
        channel="Channel to unlock (defaults to current)",
        reason="Reason for unlocking",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(manage_channels=True)
    @require_tier("moderator")
    async def unlock(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel] = None,
        *,
        reason: str = "Channel unlocked by moderator",
    ) -> None:
        """Restore `@everyone` send permissions in the channel."""
        assert ctx.guild is not None
        target = channel or ctx.channel
        assert isinstance(target, discord.TextChannel)
        await target.set_permissions(
            ctx.guild.default_role,
            send_messages=None,
            reason=f"Unlocked by {ctx.author}: {reason}",
        )
        await self._dispatch_mod_log(
            ctx.guild, "unlock", f"#{target.name}", target.id, ctx.author, reason
        )
        emb = make_embed(
            "🔓 Channel Unlocked",
            f"{target.mention} has been unlocked.\n• **Reason:** {reason}",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="snipe",
        description="View the most recently deleted message in this channel (5-minute privacy window).",
    )
    @commands.guild_only()
    @require_tier("moderator")
    async def snipe(self, ctx: commands.Context) -> None:
        """Retrieve the temporary in-memory record of the last deleted message in this channel."""
        assert ctx.channel is not None
        entry = self._snipe_cache.get(ctx.channel.id)
        if entry is None:
            emb = make_embed(
                "🔍 Nothing to Snipe",
                "No recently deleted messages are stored for this channel.",
                color=discord.Color.blurple(),
            )
            await ctx.send(embed=emb, ephemeral=True)
            return

        author_name, author_id, content, mono_ts, deleted_dt = entry
        if time.monotonic() - mono_ts > SNIPE_TTL_SECONDS:
            self._snipe_cache.pop(ctx.channel.id, None)
            emb = make_embed(
                "🔍 Snipe Expired",
                "The temporary deleted message cache for this channel has expired for privacy.",
                color=discord.Color.blurple(),
            )
            await ctx.send(embed=emb, ephemeral=True)
            return

        emb = make_embed(
            f"🎯 Sniped Message in #{ctx.channel.name}",
            content,
            color=discord.Color.orange(),
        )
        emb.add_field(name="Author", value=f"{author_name} (<@{author_id}>)", inline=True)
        emb.add_field(
            name="Deleted",
            value=discord.utils.format_dt(deleted_dt, "R"),
            inline=True,
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="modlogs",
        aliases=["auditlogs"],
        description="View recent moderation audit log entries for the server or a specific member.",
    )
    @app_commands.describe(member="Optional member to filter logs by")
    @commands.guild_only()
    @require_tier("moderator")
    async def modlogs(
        self, ctx: commands.Context, member: Optional[discord.Member] = None
    ) -> None:
        """Display recent moderation actions from SQLite."""
        assert ctx.guild is not None
        rows = await self.bot.mod_repo.get_mod_logs(
            ctx.guild.id, target_id=member.id if member else None, limit=15
        )
        if not rows:
            emb = make_embed(
                "📜 Moderation Audit Logs",
                "No moderation log entries found.",
                color=discord.Color.blurple(),
            )
            await ctx.send(embed=emb)
            return

        lines = [
            f"• **`#{r['log_id']}` [{r['action'].upper()}]** Target: `<@{r['target_id']}>` | Mod: <@{r['moderator_id']}> — {r['reason'] or 'N/A'}"
            for r in rows
        ]
        emb = make_embed(
            f"📜 Moderation Audit Logs ({len(rows)})",
            "\n".join(lines),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_group(
        name="automod",
        description="Configure server Automatic Moderation filters and blocked words.",
        fallback="status",
    )
    @commands.guild_only()
    @require_tier("management")
    async def automod_group(self, ctx: commands.Context) -> None:
        """Display the current AutoMod configuration."""
        assert ctx.guild is not None
        cfg = await self.bot.guild_config_repo.ensure_guild(ctx.guild.id)
        words = json.loads(cfg.get("automod_bad_words") or "[]")
        emb = make_embed(
            f"🤖 AutoMod Configuration — {ctx.guild.name}",
            (
                f"• **Enabled:** `{'Yes' if cfg['automod_enabled'] else 'No'}`\n"
                f"• **Block Invites:** `{'Yes' if cfg['automod_anti_invite'] else 'No'}`\n"
                f"• **Block External Links:** `{'Yes' if cfg['automod_anti_links'] else 'No'}`\n"
                f"• **Max Mentions / Message:** `{cfg['automod_max_mentions']}`\n"
                f"• **Anti-Spam Threshold:** `{cfg['automod_spam_threshold']} msgs / {cfg['automod_spam_window_sec']}s`\n"
                f"• **Filtered Words ({len(words)}):** {', '.join(f'`{w}`' for w in words) if words else '*None*'}"
            ),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb)

    @automod_group.command(
        name="toggle",
        description="Enable or disable Automatic Moderation for this server.",
    )
    @app_commands.describe(enabled="True to enable AutoMod, False to disable")
    @require_tier("management")
    async def automod_toggle(self, ctx: commands.Context, enabled: bool) -> None:
        """Toggle AutoMod on or off."""
        assert ctx.guild is not None
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id, automod_enabled=1 if enabled else 0
        )
        emb = make_embed(
            "🤖 AutoMod Updated",
            f"Automatic Moderation is now **{'Enabled' if enabled else 'Disabled'}**.",
            color=discord.Color.green() if enabled else discord.Color.orange(),
        )
        await ctx.send(embed=emb)

    @automod_group.command(
        name="addword",
        description="Add a prohibited word or phrase to the AutoMod filter.",
    )
    @app_commands.describe(word="Word or phrase to block")
    @require_tier("management")
    async def automod_addword(self, ctx: commands.Context, *, word: str) -> None:
        """Add a blocked word to AutoMod."""
        assert ctx.guild is not None
        clean = word.strip().lower()
        cfg = await self.bot.guild_config_repo.ensure_guild(ctx.guild.id)
        words: List[str] = json.loads(cfg.get("automod_bad_words") or "[]")
        if clean not in words:
            words.append(clean)
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id, automod_bad_words=json.dumps(words)
        )
        emb = make_embed(
            "✅ Filtered Word Added",
            f"Added `{clean}` to AutoMod blocked words ({len(words)} total).",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @automod_group.command(
        name="removeword",
        description="Remove a word or phrase from the AutoMod filter.",
    )
    @app_commands.describe(word="Word or phrase to unblock")
    @require_tier("management")
    async def automod_removeword(self, ctx: commands.Context, *, word: str) -> None:
        """Remove a word from the AutoMod filter."""
        assert ctx.guild is not None
        clean = word.strip().lower()
        cfg = await self.bot.guild_config_repo.ensure_guild(ctx.guild.id)
        words: List[str] = json.loads(cfg.get("automod_bad_words") or "[]")
        if clean in words:
            words.remove(clean)
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id, automod_bad_words=json.dumps(words)
        )
        emb = make_embed(
            "🗑️ Filtered Word Removed",
            f"Removed `{clean}` from AutoMod blocked words.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
