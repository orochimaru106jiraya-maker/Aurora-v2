"""Reaction Roles, Button Roles & Select-Menu Self-Role System (`bot/cogs/reaction_roles.py`).

Supports:
- Reaction role panels (`reaction`)
- Button role panels (`button`)
- Select-menu role panels (`select`)
- Multiple role selection & exclusive role groups
- Automatic role removal on deselection / toggle
- Persistent views reloaded from SQLite across restarts
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.permission_service import require_tier
from bot.utils.formatting import make_embed

logger = logging.getLogger("project_nova.cogs.reaction_roles")


class ButtonRolePanelView(discord.ui.View):
    """Persistent button-based self-role panel view."""

    def __init__(self, bot: commands.Bot, panel: Dict[str, Any]) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.panel_id = int(panel["panel_id"])
        self.exclusive = bool(panel.get("exclusive"))
        self.items_data: List[Dict[str, Any]] = list(panel.get("items", []))

        style_map = {
            "primary": discord.ButtonStyle.primary,
            "secondary": discord.ButtonStyle.secondary,
            "success": discord.ButtonStyle.success,
            "danger": discord.ButtonStyle.danger,
        }
        for idx, item in enumerate(self.items_data[:20]):
            role_id = int(item["role_id"])
            btn = discord.ui.Button(
                label=str(item["label"])[:80],
                emoji=str(item.get("emoji") or "⭐"),
                style=style_map.get(str(item.get("style", "primary")).lower(), discord.ButtonStyle.primary),
                custom_id=f"nova:rr:btn:{self.panel_id}:{role_id}",
                row=idx // 5,
            )
            btn.callback = self._make_toggle_callback(role_id)  # type: ignore
            self.add_item(btn)

    def _make_toggle_callback(self, role_id: int):
        async def _cb(interaction: discord.Interaction) -> None:
            cog: Optional["ReactionRolesCog"] = self.bot.get_cog("ReactionRolesCog")  # type: ignore
            if cog is not None:
                await cog.handle_button_role_toggle(
                    interaction, self.panel_id, role_id, self.exclusive, self.items_data
                )

        return _cb


class SelectRoleDropdown(discord.ui.Select):
    """Persistent select-menu dropdown for multi-select or exclusive self-roles."""

    def __init__(self, bot: commands.Bot, panel: Dict[str, Any]) -> None:
        self.bot = bot
        self.panel_id = int(panel["panel_id"])
        self.exclusive = bool(panel.get("exclusive"))
        self.items_data: List[Dict[str, Any]] = list(panel.get("items", []))

        options: List[discord.SelectOption] = []
        for item in self.items_data[:25]:
            options.append(
                discord.SelectOption(
                    label=str(item["label"])[:100],
                    value=str(item["role_id"]),
                    emoji=str(item.get("emoji") or "⭐"),
                    description=(str(item.get("description") or "")[:100]) or None,
                )
            )
        max_vals = 1 if self.exclusive else max(1, min(len(options), int(panel.get("max_Select") or len(options))))
        super().__init__(
            placeholder="Select your roles (deselect to remove)...",
            min_values=0,
            max_values=max_vals,
            options=options,
            custom_id=f"nova:rr:select:{self.panel_id}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: Optional["ReactionRolesCog"] = self.bot.get_cog("ReactionRolesCog")  # type: ignore
        if cog is not None:
            selected_ids = {int(v) for v in self.values}
            await cog.handle_select_role_sync(
                interaction, self.panel_id, selected_ids, self.items_data
            )


class SelectRolePanelView(discord.ui.View):
    """Persistent wrapper view for `SelectRoleDropdown`."""

    def __init__(self, bot: commands.Bot, panel: Dict[str, Any]) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        if panel.get("items"):
            self.add_item(SelectRoleDropdown(bot, panel))


class ReactionRolesCog(commands.Cog, name="ReactionRolesCog"):
    """Self-Role Panels via Buttons, Select Menus, and Reactions."""

    CATEGORY = "Reaction Roles"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Reload all saved button and select-menu role panels as persistent views."""
        if not self.bot.db.is_connected:
            return
        panels = await self.bot.reaction_role_repo.list_panels()
        for p in panels:
            if not p.get("items"):
                continue
            if p["mode"] == "button":
                self.bot.add_view(ButtonRolePanelView(self.bot, p))
            elif p["mode"] == "select":
                self.bot.add_view(SelectRolePanelView(self.bot, p))

    async def handle_button_role_toggle(
        self,
        interaction: discord.Interaction,
        panel_id: int,
        role_id: int,
        exclusive: bool,
        items_data: List[Dict[str, Any]],
    ) -> None:
        """Toggle a role when a button on a reaction-role panel is clicked."""
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        role = guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message("Role no longer exists.", ephemeral=True)
            return

        ok, err = self.bot.permission_service.validate_role_assignment(guild, role)
        if not ok:
            await interaction.response.send_message(err or "Hierarchy error.", ephemeral=True)
            return

        if role in member.roles:
            await member.remove_roles(role, reason=f"Self-role button deselected (Panel #{panel_id})")
            await interaction.response.send_message(
                f"➖ Removed role {role.mention}.", ephemeral=True
            )
            return

        removed_others: List[str] = []
        if exclusive:
            for item in items_data:
                other_id = int(item["role_id"])
                if other_id != role_id:
                    other_role = guild.get_role(other_id)
                    if other_role and other_role in member.roles:
                        await member.remove_roles(
                            other_role, reason=f"Exclusive role group swap (Panel #{panel_id})"
                        )
                        removed_others.append(other_role.mention)

        await member.add_roles(role, reason=f"Self-role button selected (Panel #{panel_id})")
        extra = f" (Replaced {', '.join(removed_others)})" if removed_others else ""
        await interaction.response.send_message(
            f"➕ Added role {role.mention}{extra}.", ephemeral=True
        )

    async def handle_select_role_sync(
        self,
        interaction: discord.Interaction,
        panel_id: int,
        selected_role_ids: set[int],
        items_data: List[Dict[str, Any]],
    ) -> None:
        """Synchronize a member's roles for a select-menu panel (adding selected & removing deselected)."""
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        added: List[str] = []
        removed: List[str] = []
        panel_role_ids = {int(i["role_id"]) for i in items_data}

        for rid in panel_role_ids:
            role = guild.get_role(rid)
            if role is None:
                continue
            ok, _ = self.bot.permission_service.validate_role_assignment(guild, role)
            if not ok:
                continue
            if rid in selected_role_ids and role not in member.roles:
                await member.add_roles(role, reason=f"Self-role menu selection (Panel #{panel_id})")
                added.append(role.mention)
            elif rid not in selected_role_ids and role in member.roles:
                await member.remove_roles(role, reason=f"Self-role menu deselection (Panel #{panel_id})")
                removed.append(role.mention)

        parts = []
        if added:
            parts.append(f"➕ **Added:** {', '.join(added)}")
        if removed:
            parts.append(f"➖ **Removed:** {', '.join(removed)}")
        if not parts:
            parts.append("No role changes needed.")
        await interaction.response.send_message("\n".join(parts), ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: Any) -> None:
        """Assign role when a user reacts to a `reaction`-mode role panel."""
        if not getattr(payload, "guild_id", None) or getattr(payload, "user_id", 0) == (self.bot.user.id if self.bot.user else 0):
            return
        panel = await self.bot.reaction_role_repo.get_panel_by_message(int(payload.message_id))
        if not panel or panel["mode"] != "reaction":
            return
        guild = self.bot.get_guild(int(payload.guild_id))
        if not guild:
            return
        member = guild.get_member(int(payload.user_id))
        if not member or member.bot:
            return
        emoji_str = str(payload.emoji)
        for item in panel.get("items", []):
            if str(item.get("emoji")) == emoji_str:
                role = guild.get_role(int(item["role_id"]))
                if role:
                    ok, _ = self.bot.permission_service.validate_role_assignment(guild, role)
                    if ok:
                        await member.add_roles(role, reason=f"Reaction Role Panel #{panel['panel_id']}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: Any) -> None:
        """Remove role when a user removes their reaction from a `reaction`-mode role panel."""
        if not getattr(payload, "guild_id", None):
            return
        panel = await self.bot.reaction_role_repo.get_panel_by_message(int(payload.message_id))
        if not panel or panel["mode"] != "reaction":
            return
        guild = self.bot.get_guild(int(payload.guild_id))
        if not guild:
            return
        member = guild.get_member(int(payload.user_id))
        if not member or member.bot:
            return
        emoji_str = str(payload.emoji)
        for item in panel.get("items", []):
            if str(item.get("emoji")) == emoji_str:
                role = guild.get_role(int(item["role_id"]))
                if role and role in member.roles:
                    await member.remove_roles(role, reason=f"Reaction Role Removed #{panel['panel_id']}")

    @commands.hybrid_group(
        name="reactionrole",
        aliases=["rr", "selfroles"],
        description="Create and manage interactive button, select-menu, and reaction role panels.",
        fallback="list",
    )
    @commands.guild_only()
    @require_tier("management")
    async def rr_group(self, ctx: commands.Context) -> None:
        """List all reaction/button/select role panels in this server."""
        assert ctx.guild is not None
        panels = await self.bot.reaction_role_repo.list_panels(ctx.guild.id)
        if not panels:
            emb = make_embed(
                "🎭 Self-Role Panels",
                "No reaction/button/select role panels exist yet.\nUse `/reactionrole create` to create one.",
                color=discord.Color.blurple(),
            )
            await ctx.send(embed=emb)
            return

        lines = [
            f"• **Panel `#{p['panel_id']}`** ({p['mode'].upper()}) — **{p['title']}** in <#{p['channel_id']}> (`{len(p.get('items', []))}` roles, Exclusive: `{'Yes' if p['exclusive'] else 'No'}`)"
            for p in panels
        ]
        emb = make_embed(
            f"🎭 Self-Role Panels — {ctx.guild.name} ({len(panels)})",
            "\n".join(lines),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb)

    @rr_group.command(
        name="create",
        description="Create a new role panel (mode: button, select, or reaction).",
    )
    @app_commands.describe(
        channel="Channel where the panel will be published",
        mode="Panel mode: button, select, or reaction",
        exclusive="If True, members can only hold one role from this panel at a time",
        title="Panel embed title",
        description="Panel embed description",
    )
    @require_tier("management")
    async def create_panel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        mode: str = "button",
        exclusive: bool = False,
        title: str = "Choose Your Roles",
        *,
        description: str = "Use the controls below to add or remove your server roles.",
    ) -> None:
        """Create a new reaction/button/select role panel."""
        assert ctx.guild is not None
        clean_mode = mode.lower().strip()
        if clean_mode not in ("button", "select", "reaction"):
            raise commands.BadArgument("Mode must be `button`, `select`, or `reaction`.")

        emb = make_embed(f"🎭 {title}", description, color=discord.Color.blurple())
        sent = await channel.send(embed=emb)
        panel_id = await self.bot.reaction_role_repo.create_panel(
            ctx.guild.id,
            channel.id,
            sent.id,
            clean_mode,
            title,
            description,
            exclusive=exclusive,
        )
        confirm = make_embed(
            f"✅ Role Panel #{panel_id} Created",
            (
                f"Created **{clean_mode}** panel **`#{panel_id}`** in {channel.mention}.\n"
                f"Now add roles with `/reactionrole additem panel_id:{panel_id} role:@Role label:Name emoji:⭐`."
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=confirm)

    @rr_group.command(
        name="additem",
        description="Add a role option to an existing role panel and refresh the panel message.",
    )
    @app_commands.describe(
        panel_id="The numeric panel ID",
        role="The Discord role to grant",
        label="Button/option label",
        emoji="Emoji icon",
    )
    @require_tier("management")
    async def add_item(
        self,
        ctx: commands.Context,
        panel_id: int,
        role: discord.Role,
        label: str,
        emoji: str = "⭐",
    ) -> None:
        """Add a role to a panel and update the live panel message."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        panel = await self.bot.reaction_role_repo.get_panel(panel_id)
        if not panel or int(panel["guild_id"]) != ctx.guild.id:
            raise commands.BadArgument(f"Panel `#{panel_id}` not found in this server.")

        ok, err = self.bot.permission_service.validate_role_assignment(ctx.guild, role, ctx.author)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy check failed.")

        await self.bot.reaction_role_repo.add_panel_item(
            panel_id, ctx.guild.id, role.id, label.strip(), emoji.strip() or "⭐"
        )
        updated_panel = await self.bot.reaction_role_repo.get_panel(panel_id)
        assert updated_panel is not None

        # Refresh the published Discord message
        ch = ctx.guild.get_channel(int(updated_panel["channel_id"]))
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(int(updated_panel["message_id"]))
                role_lines = [
                    f"• {i['emoji']} **{i['label']}** → <@&{i['role_id']}>"
                    for i in updated_panel["items"]
                ]
                mode_note = "Exclusive (1 role max)" if updated_panel["exclusive"] else "Multi-Select"
                emb = make_embed(
                    f"🎭 {updated_panel['title']} ({mode_note})",
                    f"{updated_panel['description']}\n\n" + "\n".join(role_lines),
                    color=discord.Color.blurple(),
                )
                if updated_panel["mode"] == "button":
                    view = ButtonRolePanelView(self.bot, updated_panel)
                    self.bot.add_view(view)
                    await msg.edit(embed=emb, view=view)
                elif updated_panel["mode"] == "select":
                    view = SelectRolePanelView(self.bot, updated_panel)
                    self.bot.add_view(view)
                    await msg.edit(embed=emb, view=view)
                else:
                    await msg.edit(embed=emb)
                    await msg.add_reaction(emoji.strip() or "⭐")
            except Exception as exc:
                logger.warning("Could not refresh role panel message: %s", exc)

        await ctx.send(
            embed=make_embed(
                "✅ Role Added to Panel",
                f"Added {emoji} **{label}** ({role.mention}) to Panel **`#{panel_id}`**.",
                color=discord.Color.green(),
            )
        )

    @rr_group.command(
        name="delete",
        description="Delete a reaction role panel by its ID.",
    )
    @app_commands.describe(panel_id="The numeric panel ID to delete")
    @require_tier("management")
    async def delete_panel(self, ctx: commands.Context, panel_id: int) -> None:
        """Delete a reaction role panel."""
        assert ctx.guild is not None
        deleted = await self.bot.reaction_role_repo.delete_panel(ctx.guild.id, panel_id)
        await ctx.send(
            embed=make_embed(
                "🗑️ Panel Deleted" if deleted else "❓ Panel Not Found",
                f"Deleted role panel `#{panel_id}`." if deleted else f"Panel `#{panel_id}` not found.",
                color=discord.Color.green() if deleted else discord.Color.orange(),
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRolesCog(bot))
