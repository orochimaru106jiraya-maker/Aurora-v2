"""Administration Cog: Prefix/Language config, Logging, Announcements, Polls, Giveaways, Temp Roles, and Backups."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
import logging
import random
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.services.permission_service import require_tier
from bot.utils.formatting import format_duration, make_embed, parse_duration

logger = logging.getLogger("project_nova.cogs.administration")


class PollView(discord.ui.View):
    """Persistent view for interactive server polls."""

    def __init__(self, bot: commands.Bot, poll_id: int, options: List[str]) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.poll_id = poll_id
        for idx, opt in enumerate(options[:5]):
            btn = discord.ui.Button(
                label=f"{idx + 1}. {opt[:60]}",
                style=discord.ButtonStyle.primary,
                custom_id=f"nova:poll:{poll_id}:{idx}",
            )
            btn.callback = self._make_vote_callback(idx)  # type: ignore
            self.add_item(btn)

    def _make_vote_callback(self, option_idx: int):
        async def _cb(interaction: discord.Interaction) -> None:
            if not interaction.user:
                return
            updated = await self.bot.mod_repo.record_poll_vote(
                self.poll_id, interaction.user.id, option_idx
            )
            options: List[str] = updated["options"]
            votes: Dict[str, int] = updated["votes"]
            total = len(votes)
            lines = []
            for i, opt in enumerate(options):
                cnt = sum(1 for v in votes.values() if int(v) == i)
                pct = round((cnt / total) * 100) if total > 0 else 0
                lines.append(f"**{i + 1}. {opt}** — `{cnt}` votes (`{pct}%`)")
            emb = make_embed(
                f"📊 Poll: {updated['question']}",
                "\n".join(lines) + f"\n\n*Total votes: {total}*",
                color=discord.Color.blurple(),
            )
            await interaction.response.edit_message(embed=emb, view=self)

        return _cb


class GiveawayView(discord.ui.View):
    """Persistent view allowing members to enter giveaways."""

    def __init__(self, bot: commands.Bot, giveaway_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.giveaway_id = giveaway_id
        btn = discord.ui.Button(
            label="🎉 Enter Giveaway",
            style=discord.ButtonStyle.success,
            custom_id=f"nova:giveaway:enter:{giveaway_id}",
        )
        btn.callback = self._on_enter  # type: ignore
        self.add_item(btn)

    async def _on_enter(self, interaction: discord.Interaction) -> None:
        if not interaction.user:
            return
        joined, count = await self.bot.mod_repo.toggle_giveaway_entrant(
            self.giveaway_id, interaction.user.id
        )
        status = (
            f"✅ You have entered the giveaway! (Total entrants: **{count}**)"
            if joined
            else f"📤 You have left the giveaway. (Total entrants: **{count}**)"
        )
        await interaction.response.send_message(status, ephemeral=True)


class AdministrationCog(commands.Cog, name="AdministrationCog"):
    """Server Administration, Backups, Logging, Announcements, Polls, Giveaways & Temp Roles."""

    CATEGORY = "Administration"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.temp_role_cleanup_loop.start()

    async def cog_unload(self) -> None:
        self.temp_role_cleanup_loop.cancel()

    @tasks.loop(seconds=30)
    async def temp_role_cleanup_loop(self) -> None:
        """Background task that removes expired temporary roles."""
        if not self.bot.db.is_connected:
            return
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        expired = await self.bot.mod_repo.get_expired_temp_roles(now_iso)
        for row in expired:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild:
                member = guild.get_member(int(row["user_id"]))
                role = guild.get_role(int(row["role_id"]))
                if member and role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Temporary role expired")
                    except Exception:
                        pass
            await self.bot.mod_repo.remove_temp_role(
                int(row["guild_id"]), int(row["user_id"]), int(row["role_id"])
            )

    @commands.hybrid_command(
        name="setprefix",
        aliases=["prefix"],
        description="Change the bot command prefix for this server.",
    )
    @app_commands.describe(new_prefix="The new prefix (1 to 10 characters, e.g. !, ?, $)")
    @commands.guild_only()
    @require_tier("administrator")
    async def setprefix(self, ctx: commands.Context, new_prefix: str) -> None:
        """Configure a custom command prefix for this server."""
        assert ctx.guild is not None
        try:
            await self.bot.guild_config_repo.set_prefix(ctx.guild.id, new_prefix)
        except ValueError as exc:
            raise commands.BadArgument(str(exc))
        emb = make_embed(
            "✅ Server Prefix Updated",
            f"The command prefix for **{ctx.guild.name}** is now **`{new_prefix.strip()}`**.\n"
            f"Both `{new_prefix.strip()}help` and `/help` are active.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="setlang",
        aliases=["language"],
        description="Configure the primary language for this server.",
    )
    @app_commands.describe(language="Language code (en, es, hi, fr, de)")
    @commands.guild_only()
    @require_tier("administrator")
    async def setlang(self, ctx: commands.Context, language: str) -> None:
        """Set the server's preferred language code."""
        assert ctx.guild is not None
        clean = language.lower().strip()
        if clean not in ("en", "es", "hi", "fr", "de", "pt", "ja"):
            raise commands.BadArgument(
                "Supported language codes: `en`, `es`, `hi`, `fr`, `de`, `pt`, `ja`."
            )
        await self.bot.guild_config_repo.update_fields(ctx.guild.id, language=clean)
        emb = make_embed(
            "🌐 Language Updated",
            f"Server language set to **`{clean}`**.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="logging",
        aliases=["setlogs"],
        description="Configure the server event log and moderation audit log channels.",
    )
    @app_commands.describe(
        log_channel="General server log channel",
        mod_log_channel="Moderation audit log channel (defaults to log_channel)",
    )
    @commands.guild_only()
    @require_tier("administrator")
    async def configure_logging(
        self,
        ctx: commands.Context,
        log_channel: discord.TextChannel,
        mod_log_channel: Optional[discord.TextChannel] = None,
    ) -> None:
        """Set the channels used for general server logs and moderation audit logs."""
        assert ctx.guild is not None
        mod_ch = mod_log_channel or log_channel
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id,
            log_channel_id=log_channel.id,
            mod_log_channel_id=mod_ch.id,
        )
        emb = make_embed(
            "📋 Logging Channels Configured",
            f"• **Server Logs:** {log_channel.mention}\n• **Moderation Logs:** {mod_ch.mention}",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="announce",
        aliases=["announcement"],
        description="Publish an official server announcement embed to a channel.",
    )
    @app_commands.describe(
        channel="Target text channel for the announcement",
        message="Announcement content (supports Markdown)",
    )
    @commands.guild_only()
    @require_tier("management")
    async def announce(
        self, ctx: commands.Context, channel: discord.TextChannel, *, message: str
    ) -> None:
        """Send a styled announcement embed to the chosen channel."""
        emb = make_embed(
            f"📢 Server Announcement — {ctx.guild.name if ctx.guild else ''}",
            message,
            color=discord.Color.gold(),
        )
        emb.set_author(
            name=str(ctx.author),
            icon_url=str(ctx.author.display_avatar) if ctx.author else None,
        )
        sent = await channel.send(embed=emb)
        confirm = make_embed(
            "✅ Announcement Published",
            f"Announcement posted in {channel.mention} ([Jump to Message]({sent.jump_url})).",
            color=discord.Color.green(),
        )
        await ctx.send(embed=confirm)

    @commands.hybrid_command(
        name="poll",
        description="Create an interactive button poll (separate options with '|').",
    )
    @app_commands.describe(
        question="The poll question",
        options="Poll options separated by '|' (e.g. Option A | Option B | Option C)",
    )
    @commands.guild_only()
    @require_tier("moderator")
    async def poll(self, ctx: commands.Context, question: str, *, options: str) -> None:
        """Create a persistent interactive button poll."""
        assert ctx.guild is not None and ctx.channel is not None
        parsed_opts = [o.strip() for o in options.split("|") if o.strip()]
        if len(parsed_opts) < 2 or len(parsed_opts) > 5:
            raise commands.BadArgument("Please provide between 2 and 5 options separated by `|`.")

        lines = [f"**{i + 1}. {opt}** — `0` votes (`0%`)" for i, opt in enumerate(parsed_opts)]
        emb = make_embed(
            f"📊 Poll: {question}",
            "\n".join(lines) + "\n\n*Total votes: 0*",
            color=discord.Color.blurple(),
        )
        placeholder_msg = await ctx.send(embed=emb)
        poll_id = await self.bot.mod_repo.create_poll(
            ctx.guild.id,
            ctx.channel.id,
            placeholder_msg.id,
            ctx.author.id,
            question,
            parsed_opts,
        )
        view = PollView(self.bot, poll_id, parsed_opts)
        self.bot.add_view(view)
        await placeholder_msg.edit(embed=emb, view=view)

    @commands.hybrid_group(
        name="giveaway",
        aliases=["gcreate"],
        description="Create and manage server giveaways.",
        fallback="start",
    )
    @app_commands.describe(
        channel="Channel to host the giveaway",
        duration="Duration (e.g. 10m, 2h, 1d)",
        winners="Number of winners",
        prize="Prize description",
    )
    @commands.guild_only()
    @require_tier("management")
    async def giveaway_group(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        duration: str,
        winners: int,
        *,
        prize: str,
    ) -> None:
        """Start an interactive giveaway in the specified channel."""
        assert ctx.guild is not None
        secs = parse_duration(duration)
        if not secs or secs < 10:
            raise commands.BadArgument("Duration must be at least `10s` (e.g. `10m`, `2h`, `1d`).")
        winners = max(1, min(20, int(winners)))
        ends_dt = datetime.now(timezone.utc) + timedelta(seconds=secs)
        ends_iso = ends_dt.strftime("%Y-%m-%d %H:%M:%S")

        emb = make_embed(
            f"🎉 GIVEAWAY: {prize}",
            (
                f"Click the button below to enter!\n\n"
                f"• **Hosted By:** {ctx.author.mention}\n"
                f"• **Winners:** `{winners}`\n"
                f"• **Ends:** {discord.utils.format_dt(ends_dt, 'R')} ({format_duration(secs)})"
            ),
            color=discord.Color.gold(),
        )
        msg = await channel.send(embed=emb)
        giveaway_id = await self.bot.mod_repo.create_giveaway(
            ctx.guild.id,
            channel.id,
            msg.id,
            ctx.author.id,
            prize,
            winners,
            ends_iso,
        )
        view = GiveawayView(self.bot, giveaway_id)
        self.bot.add_view(view)
        await msg.edit(embed=emb, view=view)
        await ctx.send(
            embed=make_embed(
                "✅ Giveaway Started",
                f"Giveaway **`#{giveaway_id}`** for **{prize}** started in {channel.mention}.",
                color=discord.Color.green(),
            )
        )

    @giveaway_group.command(
        name="end",
        description="End an active giveaway by its message ID and pick winners.",
    )
    @app_commands.describe(message_id="The Discord message ID of the giveaway")
    @require_tier("management")
    async def giveaway_end(self, ctx: commands.Context, message_id: str) -> None:
        """Draw winners and close an active giveaway."""
        if not message_id.strip().isdigit():
            raise commands.BadArgument("Please provide a valid numeric message ID.")
        record = await self.bot.mod_repo.get_giveaway_by_message(int(message_id.strip()))
        if not record:
            raise commands.BadArgument("No giveaway found with that message ID.")

        entrants: List[int] = record["entrants"]
        await self.bot.mod_repo.close_giveaway(int(record["giveaway_id"]))

        if not entrants:
            emb = make_embed(
                "🎉 Giveaway Ended",
                f"Giveaway for **{record['prize']}** ended with no entrants.",
                color=discord.Color.orange(),
            )
            await ctx.send(embed=emb)
            return

        winners_cnt = min(len(entrants), int(record["winners_count"]))
        chosen = random.sample(entrants, k=winners_cnt)
        mentions = ", ".join(f"<@{uid}>" for uid in chosen)
        emb = make_embed(
            f"🏆 Giveaway Winners — {record['prize']}",
            f"Congratulations {mentions}! You won **{record['prize']}**!",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="temprole",
        description="Assign a temporary role to a member for a specified duration.",
    )
    @app_commands.describe(
        member="Member to receive the temporary role",
        role="Role to assign",
        duration="Duration (e.g. 30m, 2h, 7d)",
        reason="Optional audit reason",
    )
    @commands.guild_only()
    @require_tier("management")
    async def temprole(
        self,
        ctx: commands.Context,
        member: discord.Member,
        role: discord.Role,
        duration: str,
        *,
        reason: str = "Temporary role assignment",
    ) -> None:
        """Grant a role to a member and automatically revoke it after `duration`."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        secs = parse_duration(duration)
        if not secs or secs < 5:
            raise commands.BadArgument("Invalid duration. Use formats like `10m`, `2h`, `1d`.")

        ok, err = self.bot.permission_service.validate_role_assignment(ctx.guild, role, ctx.author)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy check failed.")

        expires_dt = datetime.now(timezone.utc) + timedelta(seconds=secs)
        expires_iso = expires_dt.strftime("%Y-%m-%d %H:%M:%S")
        await member.add_roles(role, reason=f"TempRole ({duration}): {reason}")
        await self.bot.mod_repo.add_temp_role(
            ctx.guild.id, member.id, role.id, expires_iso, reason
        )
        emb = make_embed(
            "⏳ Temporary Role Assigned",
            (
                f"• **Member:** {member.mention}\n"
                f"• **Role:** {role.mention}\n"
                f"• **Duration:** `{format_duration(secs)}` (expires {discord.utils.format_dt(expires_dt, 'R')})\n"
                f"• **Reason:** {reason}"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_group(
        name="backup",
        description="Export or restore server configuration backups.",
        fallback="export",
    )
    @commands.guild_only()
    @require_tier("administrator")
    async def backup_group(self, ctx: commands.Context) -> None:
        """Export a complete JSON backup of this server's Project Nova configuration."""
        assert ctx.guild is not None
        gid = ctx.guild.id
        cfg = dict(await self.bot.guild_config_repo.ensure_guild(gid))
        # Never expose API keys in exported backups
        cfg["ai_api_key"] = None
        payload: Dict[str, Any] = {
            "version": "2.0.0",
            "guild_id": gid,
            "guild_name": ctx.guild.name,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "guild_config": cfg,
            "rbac_staff_roles": await self.bot.rbac_repo.list_staff_roles(gid),
            "rbac_permissions": await self.bot.rbac_repo.list_permission_rules(gid),
            "ticket_categories": await self.bot.ticket_repo.ensure_default_categories(gid),
            "activity_role_rules": await self.bot.activity_repo.list_rules(gid),
            "autoresponders": await self.bot.automation_repo.list_autoresponders(gid),
            "embed_templates": await self.bot.embed_repo.list_templates(gid),
        }
        raw_bytes = json.dumps(payload, indent=2).encode("utf-8")
        discord_file = discord.File(
            io.BytesIO(raw_bytes), filename=f"nova_backup_{gid}.json"
        )
        emb = make_embed(
            "💾 Server Configuration Backup",
            f"Exported configuration backup for **{ctx.guild.name}** (`{len(raw_bytes)} bytes`).\n"
            f"All sensitive credentials (such as AI API keys) are automatically scrubbed.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb, file=discord_file)

    @backup_group.command(
        name="restore",
        description="Restore server configuration settings from a JSON backup string.",
    )
    @app_commands.describe(json_data="JSON backup object to restore")
    @require_tier("administrator")
    async def backup_restore(self, ctx: commands.Context, *, json_data: str) -> None:
        """Restore guild configuration and rules from a JSON backup string."""
        assert ctx.guild is not None
        try:
            data = json.loads(json_data)
        except Exception as exc:
            raise commands.BadArgument(f"Invalid JSON backup payload: {exc}")

        guild_cfg = data.get("guild_config", {})
        safe_fields = {
            k: v
            for k, v in guild_cfg.items()
            if k in ("prefix", "language", "welcome_enabled", "welcome_message", "goodbye_enabled", "goodbye_message", "ticket_limit_per_member")
        }
        if safe_fields:
            await self.bot.guild_config_repo.update_fields(ctx.guild.id, **safe_fields)

        emb = make_embed(
            "✅ Backup Restored",
            f"Successfully restored configuration settings for **{ctx.guild.name}**.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdministrationCog(bot))
