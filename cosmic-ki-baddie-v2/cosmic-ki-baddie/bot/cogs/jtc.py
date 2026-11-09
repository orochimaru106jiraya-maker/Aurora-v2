"""Complete Join-to-Create (JTC) Temporary Voice Channel System (`bot/cogs/jtc.py`).

Features:
- Configurable trigger voice channel & parent category.
- Automatic creation of temporary voice channel when a user joins the trigger channel, moving them inside.
- Persistent UI control panel (`JTCControlView`) + `/vc` (`!vc`) commands for:
  - Rename channel
  - Change user limit
  - Lock / Unlock channel
  - Hide / Unhide channel
  - Transfer ownership
  - Allow / Deny specific members
- Automatic cleanup when the channel becomes empty.
- Recovery after bot restart (prunes orphaned/empty channels and preserves active ones).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.permission_service import require_tier
from bot.utils.formatting import make_embed

logger = logging.getLogger("project_nova.cogs.jtc")


class JTCRenameModal(discord.ui.Modal, title="Rename Voice Channel"):
    new_name = discord.ui.TextInput(
        label="New Channel Name",
        placeholder="Cosmic Lounge",
        min_length=1,
        max_length=90,
    )

    def __init__(self, cog: "JTCCog", channel: discord.VoiceChannel) -> None:
        super().__init__(custom_id="nova:jtc:modal:rename")
        self.cog = cog
        self.channel = channel
        self.new_name.default = channel.name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.new_name.value.strip()[:90]
        await self.channel.edit(name=name, reason=f"JTC Owner Rename by {interaction.user}")
        await self.cog.bot.jtc_repo.update_channel(self.channel.id, name=name)
        await interaction.response.send_message(
            embed=make_embed("✅ Channel Renamed", f"Renamed voice channel to **{name}**.", color=discord.Color.green()),
            ephemeral=True,
        )


class JTCLimitModal(discord.ui.Modal, title="Set Voice Channel User Limit"):
    limit_input = discord.ui.TextInput(
        label="User Limit (0 for unlimited, max 99)",
        placeholder="0",
        min_length=1,
        max_length=2,
    )

    def __init__(self, cog: "JTCCog", channel: discord.VoiceChannel) -> None:
        super().__init__(custom_id="nova:jtc:modal:limit")
        self.cog = cog
        self.channel = channel
        self.limit_input.default = str(channel.user_limit or 0)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.limit_input.value.strip()
        if not raw.isdigit():
            await interaction.response.send_message("Please enter a number between 0 and 99.", ephemeral=True)
            return
        lim = max(0, min(99, int(raw)))
        await self.channel.edit(user_limit=lim, reason=f"JTC Limit set by {interaction.user}")
        await self.cog.bot.jtc_repo.update_channel(self.channel.id, user_limit=lim)
        await interaction.response.send_message(
            embed=make_embed(
                "👥 User Limit Updated",
                f"Channel user limit set to **`{lim if lim > 0 else 'Unlimited'}`**.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class JTCAccessModal(discord.ui.Modal, title="Allow or Deny Member Access"):
    action_input = discord.ui.TextInput(
        label="Action (allow / deny / transfer)",
        placeholder="allow",
        default="allow",
        max_length=10,
    )
    user_id_input = discord.ui.TextInput(
        label="Target Member ID",
        placeholder="123456789012345678",
        max_length=25,
    )

    def __init__(self, cog: "JTCCog", channel: discord.VoiceChannel) -> None:
        super().__init__(custom_id="nova:jtc:modal:access")
        self.cog = cog
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        act = self.action_input.value.strip().lower()
        uid_str = self.user_id_input.value.strip().strip("<@!>")
        if not uid_str.isdigit():
            await interaction.response.send_message("Invalid Member ID.", ephemeral=True)
            return
        member = interaction.guild.get_member(int(uid_str))
        if member is None:
            await interaction.response.send_message("Member not found in this server.", ephemeral=True)
            return

        if act == "transfer":
            await self.cog.transfer_channel_ownership(self.channel, member)
            await interaction.response.send_message(
                embed=make_embed("👑 Ownership Transferred", f"Transferred room ownership to {member.mention}.", color=discord.Color.green()),
                ephemeral=True,
            )
        elif act == "deny":
            await self.cog.set_member_access(self.channel, member, allow=False)
            await interaction.response.send_message(
                embed=make_embed("🚫 Member Denied", f"Denied {member.mention} from joining {self.channel.mention}.", color=discord.Color.orange()),
                ephemeral=True,
            )
        else:
            await self.cog.set_member_access(self.channel, member, allow=True)
            await interaction.response.send_message(
                embed=make_embed("✅ Member Allowed", f"Permitted {member.mention} to join {self.channel.mention}.", color=discord.Color.green()),
                ephemeral=True,
            )


class JTCControlView(discord.ui.View):
    """Persistent owner control panel for Join-to-Create temporary voice channels."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    async def _resolve_owned_channel(
        self, interaction: discord.Interaction
    ) -> Optional[ Tuple["JTCCog", discord.VoiceChannel, Dict[str, Any]] ]:
        cog: Optional["JTCCog"] = self.bot.get_cog("JTCCog")  # type: ignore
        if cog is None or interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return None
        # Check the channel where button was clicked or the voice channel the user is currently in
        target_vc: Optional[discord.VoiceChannel] = None
        if isinstance(interaction.channel, discord.VoiceChannel):
            target_vc = interaction.channel
        elif interaction.user.voice and isinstance(interaction.user.voice.channel, discord.VoiceChannel):
            target_vc = interaction.user.voice.channel

        if target_vc is None:
            await interaction.response.send_message(
                "You must be inside your temporary voice channel to use these controls.",
                ephemeral=True,
            )
            return None

        record = await self.bot.jtc_repo.get_channel(target_vc.id)
        if record is None:
            await interaction.response.send_message(
                "This voice channel is not a managed Join-to-Create room.",
                ephemeral=True,
            )
            return None

        is_admin = await self.bot.permission_service.has_tier(interaction.user, "moderator")
        if int(record["owner_id"]) != interaction.user.id and not is_admin:
            await interaction.response.send_message(
                f"🚫 Only the room owner (<@{record['owner_id']}>) can use these controls.",
                ephemeral=True,
            )
            return None
        return cog, target_vc, record

    @discord.ui.button(
        label="Rename",
        style=discord.ButtonStyle.primary,
        emoji="✏️",
        custom_id="nova:jtc:rename",
        row=0,
    )
    async def rename_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        resolved = await self._resolve_owned_channel(interaction)
        if not resolved:
            return
        cog, vc, _ = resolved
        await interaction.response.send_modal(JTCRenameModal(cog, vc))

    @discord.ui.button(
        label="User Limit",
        style=discord.ButtonStyle.secondary,
        emoji="👥",
        custom_id="nova:jtc:limit",
        row=0,
    )
    async def limit_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        resolved = await self._resolve_owned_channel(interaction)
        if not resolved:
            return
        cog, vc, _ = resolved
        await interaction.response.send_modal(JTCLimitModal(cog, vc))

    @discord.ui.button(
        label="Lock / Unlock",
        style=discord.ButtonStyle.secondary,
        emoji="🔒",
        custom_id="nova:jtc:lock_toggle",
        row=0,
    )
    async def lock_toggle_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        resolved = await self._resolve_owned_channel(interaction)
        if not resolved:
            return
        cog, vc, record = resolved
        new_locked = not bool(record.get("is_locked"))
        await cog.set_channel_locked(vc, new_locked)
        state = "🔒 Locked" if new_locked else "🔓 Unlocked"
        await interaction.response.send_message(
            embed=make_embed(
                f"{state} Voice Channel",
                f"{vc.mention} is now **{state}**.",
                color=discord.Color.orange() if new_locked else discord.Color.green(),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Hide / Unhide",
        style=discord.ButtonStyle.secondary,
        emoji="👁️",
        custom_id="nova:jtc:hide_toggle",
        row=1,
    )
    async def hide_toggle_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        resolved = await self._resolve_owned_channel(interaction)
        if not resolved:
            return
        cog, vc, record = resolved
        new_hidden = not bool(record.get("is_hidden"))
        await cog.set_channel_hidden(vc, new_hidden)
        state = "🙈 Hidden" if new_hidden else "👁️ Visible"
        await interaction.response.send_message(
            embed=make_embed(
                f"{state} Voice Channel",
                f"{vc.mention} is now **{state}** to `@everyone`.",
                color=discord.Color.blurple(),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Allow / Deny / Transfer",
        style=discord.ButtonStyle.success,
        emoji="🔑",
        custom_id="nova:jtc:access",
        row=1,
    )
    async def access_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        resolved = await self._resolve_owned_channel(interaction)
        if not resolved:
            return
        cog, vc, _ = resolved
        await interaction.response.send_modal(JTCAccessModal(cog, vc))


class JTCCog(commands.Cog, name="JTCCog"):
    """Join-to-Create Temporary Voice Channel Manager."""

    CATEGORY = "Voice Channels"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(JTCControlView(self.bot))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.recover_jtc_channels()

    async def recover_jtc_channels(self) -> int:
        """Clean up orphaned or empty temporary voice channels after a bot restart."""
        if not self.bot.db.is_connected:
            return 0
        rows = await self.bot.jtc_repo.list_all_channels()
        cleaned = 0
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                continue
            ch = guild.get_channel(int(row["channel_id"]))
            if ch is None or not isinstance(ch, discord.VoiceChannel):
                await self.bot.jtc_repo.delete_channel(int(row["channel_id"]))
                cleaned += 1
            elif len(ch.members) == 0:
                try:
                    await ch.delete(reason="JTC Recovery: Empty temporary voice channel")
                except Exception:
                    pass
                await self.bot.jtc_repo.delete_channel(ch.id)
                cleaned += 1
        return cleaned

    async def create_temp_voice_channel(
        self, member: discord.Member, cfg: Dict[str, Any]
    ) -> discord.VoiceChannel:
        """Create a temporary voice channel for `member`, move them in, and send persistent controls."""
        guild = member.guild
        name_fmt = str(cfg.get("jtc_default_name") or "{username}'s Room")
        ch_name = name_fmt.replace("{username}", member.display_name)[:90]
        limit = int(cfg.get("jtc_default_limit") or 0)

        category: Optional[discord.CategoryChannel] = None
        if cfg.get("jtc_category_id"):
            cand = guild.get_channel(int(cfg["jtc_category_id"]))
            if isinstance(cand, discord.CategoryChannel):
                category = cand

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
            member: discord.PermissionOverwrite(
                connect=True,
                view_channel=True,
                manage_channels=True,
                move_members=True,
            ),
            guild.me: discord.PermissionOverwrite(
                connect=True,
                view_channel=True,
                manage_channels=True,
                move_members=True,
            ),
        }

        new_vc = await guild.create_voice_channel(
            name=ch_name,
            category=category,
            user_limit=limit,
            overwrites=overwrites,
            reason=f"Join-to-Create room for {member}",
        )
        await member.move_to(new_vc, reason="Moved to Join-to-Create channel")

        ctrl_embed = make_embed(
            f"🔊 {ch_name} — Voice Controls",
            (
                f"Welcome {member.mention}! You are the owner of this temporary voice room.\n"
                f"Use the buttons below or `/vc` commands to customize your room. "
                f"This channel will automatically delete when everyone leaves."
            ),
            color=discord.Color.blurple(),
        )
        view = JTCControlView(self.bot)
        ctrl_msg = await new_vc.send(embed=ctrl_embed, view=view)
        await self.bot.jtc_repo.register_channel(
            new_vc.id,
            guild.id,
            member.id,
            ch_name,
            user_limit=limit,
            control_message_id=ctrl_msg.id,
        )
        return new_vc

    async def set_channel_locked(
        self, vc: discord.VoiceChannel, locked: bool
    ) -> None:
        await vc.set_permissions(
            vc.guild.default_role,
            connect=not locked,
            reason="JTC Lock Toggle",
        )
        await self.bot.jtc_repo.update_channel(vc.id, is_locked=1 if locked else 0)

    async def set_channel_hidden(
        self, vc: discord.VoiceChannel, hidden: bool
    ) -> None:
        await vc.set_permissions(
            vc.guild.default_role,
            view_channel=not hidden,
            reason="JTC Hide Toggle",
        )
        await self.bot.jtc_repo.update_channel(vc.id, is_hidden=1 if hidden else 0)

    async def transfer_channel_ownership(
        self, vc: discord.VoiceChannel, new_owner: discord.Member
    ) -> None:
        await vc.set_permissions(
            new_owner,
            connect=True,
            view_channel=True,
            manage_channels=True,
            move_members=True,
            reason="JTC Ownership Transfer",
        )
        await self.bot.jtc_repo.update_channel(vc.id, owner_id=new_owner.id)

    async def set_member_access(
        self, vc: discord.VoiceChannel, target: discord.Member, allow: bool
    ) -> None:
        record = await self.bot.jtc_repo.get_channel(vc.id)
        if not record:
            return
        allowed_ids = set(record.get("allowed_user_ids", []))
        denied_ids = set(record.get("denied_user_ids", []))
        if allow:
            allowed_ids.add(target.id)
            denied_ids.discard(target.id)
            await vc.set_permissions(target, connect=True, view_channel=True)
        else:
            denied_ids.add(target.id)
            allowed_ids.discard(target.id)
            await vc.set_permissions(target, connect=False)
            if target in vc.members:
                try:
                    await target.move_to(None, reason="Removed by JTC owner")
                except Exception:
                    pass
        await self.bot.jtc_repo.update_channel(
            vc.id,
            allowed_user_ids=sorted(allowed_ids),
            denied_user_ids=sorted(denied_ids),
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Handle Join-to-Create channel creation and automatic empty channel cleanup."""
        if member.bot or member.guild is None:
            return
        cfg = await self.bot.guild_config_repo.ensure_guild(member.guild.id)
        trigger_id = cfg.get("jtc_trigger_channel_id")

        # 1. Check if member joined the trigger voice channel
        if (
            trigger_id
            and after.channel is not None
            and after.channel.id == int(trigger_id)
            and (before.channel is None or before.channel.id != int(trigger_id))
        ):
            try:
                await self.create_temp_voice_channel(member, cfg)
            except Exception as exc:
                logger.error("Failed to create JTC voice channel: %s", exc)

        # 2. Check if member left a managed JTC channel that is now empty
        if before.channel is not None and (
            after.channel is None or after.channel.id != before.channel.id
        ):
            record = await self.bot.jtc_repo.get_channel(before.channel.id)
            if record is not None and len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="JTC temporary voice channel empty")
                except Exception:
                    pass
                await self.bot.jtc_repo.delete_channel(before.channel.id)

    @commands.hybrid_group(
        name="jtc",
        description="Configure the server's Join-to-Create temporary voice channel system.",
        fallback="setup",
    )
    @app_commands.describe(
        trigger_channel="Voice channel members join to create their own room",
        category="Category where temporary voice rooms are created",
        default_limit="Default user limit (0 = unlimited)",
    )
    @commands.guild_only()
    @require_tier("management")
    async def jtc_group(
        self,
        ctx: commands.Context,
        trigger_channel: discord.VoiceChannel,
        category: Optional[discord.CategoryChannel] = None,
        default_limit: int = 0,
    ) -> None:
        """Configure the Join-to-Create trigger voice channel and parent category."""
        assert ctx.guild is not None
        cat_id = category.id if category else (trigger_channel.category.id if trigger_channel.category else None)
        lim = max(0, min(99, int(default_limit)))
        await self.bot.guild_config_repo.update_fields(
            ctx.guild.id,
            jtc_trigger_channel_id=trigger_channel.id,
            jtc_category_id=cat_id,
            jtc_default_limit=lim,
        )
        emb = make_embed(
            "🔊 Join-to-Create Configured",
            (
                f"• **Trigger Channel:** {trigger_channel.mention}\n"
                f"• **Parent Category:** {f'<#{cat_id}>' if cat_id else 'None'}\n"
                f"• **Default User Limit:** `{lim if lim > 0 else 'Unlimited'}`"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @commands.hybrid_group(
        name="vc",
        description="Control your active Join-to-Create temporary voice channel.",
        fallback="panel",
    )
    @commands.guild_only()
    async def vc_group(self, ctx: commands.Context) -> None:
        """Send the interactive voice channel control panel."""
        assert isinstance(ctx.author, discord.Member)
        if not ctx.author.voice or not isinstance(ctx.author.voice.channel, discord.VoiceChannel):
            raise commands.BadArgument("You must be inside a Join-to-Create voice channel.")
        vc = ctx.author.voice.channel
        record = await self.bot.jtc_repo.get_channel(vc.id)
        if not record:
            raise commands.BadArgument("Your current voice channel is not a Join-to-Create room.")
        emb = make_embed(
            f"🔊 Voice Controls — {vc.name}",
            f"• **Owner:** <@{record['owner_id']}>\n• **Locked:** `{'Yes' if record['is_locked'] else 'No'}`\n• **Hidden:** `{'Yes' if record['is_hidden'] else 'No'}`",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb, view=JTCControlView(self.bot))

    async def _require_owned_vc(self, ctx: commands.Context) -> Tuple[discord.VoiceChannel, Dict[str, Any]]:
        assert isinstance(ctx.author, discord.Member)
        if not ctx.author.voice or not isinstance(ctx.author.voice.channel, discord.VoiceChannel):
            raise commands.BadArgument("You must be in your temporary voice channel.")
        vc = ctx.author.voice.channel
        record = await self.bot.jtc_repo.get_channel(vc.id)
        if not record:
            raise commands.BadArgument("This voice channel is not a Join-to-Create room.")
        if int(record["owner_id"]) != ctx.author.id and not await self.bot.permission_service.has_tier(ctx.author, "moderator"):
            raise commands.CheckFailure("Only the voice room owner can modify this channel.")
        return vc, record

    @vc_group.command(name="rename", description="Rename your temporary voice channel.")
    @app_commands.describe(name="New channel name")
    async def vc_rename(self, ctx: commands.Context, *, name: str) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        clean = name.strip()[:90]
        await vc.edit(name=clean)
        await self.bot.jtc_repo.update_channel(vc.id, name=clean)
        await ctx.send(embed=make_embed("✅ Room Renamed", f"Renamed voice room to **{clean}**.", color=discord.Color.green()))

    @vc_group.command(name="limit", description="Set the user limit for your temporary voice channel.")
    @app_commands.describe(limit="User limit (0 to 99)")
    async def vc_limit(self, ctx: commands.Context, limit: int) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        lim = max(0, min(99, int(limit)))
        await vc.edit(user_limit=lim)
        await self.bot.jtc_repo.update_channel(vc.id, user_limit=lim)
        await ctx.send(embed=make_embed("👥 Limit Updated", f"User limit set to `{lim}`.", color=discord.Color.green()))

    @vc_group.command(name="lock", description="Lock your temporary voice channel.")
    async def vc_lock(self, ctx: commands.Context) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        await self.set_channel_locked(vc, True)
        await ctx.send(embed=make_embed("🔒 Room Locked", f"{vc.mention} is now locked.", color=discord.Color.orange()))

    @vc_group.command(name="unlock", description="Unlock your temporary voice channel.")
    async def vc_unlock(self, ctx: commands.Context) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        await self.set_channel_locked(vc, False)
        await ctx.send(embed=make_embed("🔓 Room Unlocked", f"{vc.mention} is now unlocked.", color=discord.Color.green()))

    @vc_group.command(name="hide", description="Hide your temporary voice channel from @everyone.")
    async def vc_hide(self, ctx: commands.Context) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        await self.set_channel_hidden(vc, True)
        await ctx.send(embed=make_embed("🙈 Room Hidden", f"{vc.mention} is now hidden.", color=discord.Color.blurple()))

    @vc_group.command(name="unhide", description="Make your temporary voice channel visible to @everyone.")
    async def vc_unhide(self, ctx: commands.Context) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        await self.set_channel_hidden(vc, False)
        await ctx.send(embed=make_embed("👁️ Room Visible", f"{vc.mention} is now visible.", color=discord.Color.green()))

    @vc_group.command(name="transfer", description="Transfer ownership of your voice channel to another member.")
    @app_commands.describe(member="New owner")
    async def vc_transfer(self, ctx: commands.Context, member: discord.Member) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        await self.transfer_channel_ownership(vc, member)
        await ctx.send(embed=make_embed("👑 Ownership Transferred", f"{member.mention} is now the owner of {vc.mention}.", color=discord.Color.green()))

    @vc_group.command(name="allow", description="Allow a specific member to join your locked/hidden voice channel.")
    @app_commands.describe(member="Member to allow")
    async def vc_allow(self, ctx: commands.Context, member: discord.Member) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        await self.set_member_access(vc, member, allow=True)
        await ctx.send(embed=make_embed("✅ Member Allowed", f"{member.mention} can now join {vc.mention}.", color=discord.Color.green()))

    @vc_group.command(name="deny", description="Deny and disconnect a member from your temporary voice channel.")
    @app_commands.describe(member="Member to deny")
    async def vc_deny(self, ctx: commands.Context, member: discord.Member) -> None:
        vc, _ = await self._require_owned_vc(ctx)
        await self.set_member_access(vc, member, allow=False)
        await ctx.send(embed=make_embed("🚫 Member Denied", f"{member.mention} is denied from {vc.mention}.", color=discord.Color.orange()))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JTCCog(bot))
