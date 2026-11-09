"""Professional Ticket Management System (`!ticket`, `/ticket`) for Project Nova.

Features:
- 4 default ticket categories: General Help, File Complaint, Staff Application, Winning Prize.
- Custom category creation/removal, naming format, per-member limits, staff roles, and transcript logs.
- Persistent `TicketPanelView` (one button per category) and `TicketControlView` (Claim, Transcript, Close).
- Confirmation prompt before closing, transcript generation, and graceful DM notifications to both the
  ticket creator and the claiming moderator.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import logging
import re
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.database.repositories import DEFAULT_TICKET_CATEGORIES
from bot.services.permission_service import require_tier
from bot.utils.formatting import make_embed

logger = logging.getLogger("project_nova.cogs.tickets")


async def generate_channel_transcript(
    channel: discord.TextChannel, ticket_row: Dict[str, Any]
) -> str:
    """Build a human-readable plain-text transcript of a ticket channel."""
    header = [
        "==================================================",
        "PROJECT NOVA — TICKET TRANSCRIPT",
        f"Ticket ID: #{ticket_row.get('ticket_id')}",
        f"Category: {ticket_row.get('category_name')} ({ticket_row.get('category_slug')})",
        f"Channel: #{channel.name} ({channel.id})",
        f"Creator ID: {ticket_row.get('creator_id')}",
        f"Claimed By ID: {ticket_row.get('claimed_by') or 'Unclaimed'}",
        f"Created At: {ticket_row.get('created_at')}",
        f"Generated At: {datetime.now(timezone.utc).isoformat()}",
        "==================================================",
        "",
    ]
    lines: List[str] = list(header)
    try:
        async for msg in channel.history(limit=250):
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if msg.created_at else ""
            author_str = f"{msg.author} ({msg.author.id})" if msg.author else "Unknown"
            content = msg.content or ""
            if msg.embeds:
                emb_titles = [e.title or "Embed" for e in msg.embeds]
                content += f" [Embeds: {', '.join(emb_titles)}]"
            lines.append(f"[{ts}] {author_str}: {content}")
    except Exception as exc:
        lines.append(f"[Transcript history error: {exc}]")
    return "\n".join(lines)


class TicketCloseConfirmView(discord.ui.View):
    """Confirmation prompt shown when closing a ticket."""

    def __init__(self, bot: commands.Bot, ticket_cog: "TicketsCog") -> None:
        super().__init__(timeout=120.0)
        self.bot = bot
        self.ticket_cog = ticket_cog

    @discord.ui.button(
        label="Confirm Close",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="nova:ticket:confirm_close",
    )
    async def confirm_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.ticket_cog.execute_ticket_close(interaction, reason="Closed via ticket panel")

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
        custom_id="nova:ticket:cancel_close",
    )
    async def cancel_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        emb = make_embed(
            "✅ Ticket Close Cancelled",
            "This ticket remains open.",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=emb, view=None)


class TicketControlView(discord.ui.View):
    """Persistent in-ticket control bar (Claim, Transcript, Close)."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Claim Ticket",
        style=discord.ButtonStyle.success,
        emoji="🙋",
        custom_id="nova:ticket:claim",
    )
    async def claim_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        cog: Optional["TicketsCog"] = self.bot.get_cog("TicketsCog")  # type: ignore
        if cog is not None:
            await cog.handle_claim_interaction(interaction)

    @discord.ui.button(
        label="Generate Transcript",
        style=discord.ButtonStyle.secondary,
        emoji="📄",
        custom_id="nova:ticket:transcript",
    )
    async def transcript_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        cog: Optional["TicketsCog"] = self.bot.get_cog("TicketsCog")  # type: ignore
        if cog is not None:
            await cog.handle_transcript_interaction(interaction)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="nova:ticket:close",
    )
    async def close_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        cog: Optional["TicketsCog"] = self.bot.get_cog("TicketsCog")  # type: ignore
        if cog is not None:
            await cog.handle_close_prompt_interaction(interaction)


class TicketPanelView(discord.ui.View):
    """Persistent multi-button view for opening tickets across configured categories."""

    def __init__(
        self,
        bot: commands.Bot,
        categories: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        cats = categories or [
            {"slug": slug, "name": name, "emoji": emoji, "description": desc}
            for slug, name, emoji, desc in DEFAULT_TICKET_CATEGORIES
        ]
        styles = [
            discord.ButtonStyle.primary,
            discord.ButtonStyle.danger,
            discord.ButtonStyle.success,
            discord.ButtonStyle.secondary,
        ]
        for idx, cat in enumerate(cats[:20]):
            slug = str(cat["slug"])
            btn = discord.ui.Button(
                label=str(cat["name"])[:80],
                emoji=str(cat.get("emoji") or "🎫"),
                style=styles[idx % len(styles)],
                custom_id=f"nova:ticket:open:{slug}",
                row=idx // 5,
            )
            btn.callback = self._make_open_callback(slug)  # type: ignore
            self.add_item(btn)

    def _make_open_callback(self, slug: str):
        async def _cb(interaction: discord.Interaction) -> None:
            cog: Optional["TicketsCog"] = self.bot.get_cog("TicketsCog")  # type: ignore
            if cog is not None:
                await cog.open_ticket_from_button(interaction, slug)

        return _cb


class TicketsCog(commands.Cog, name="TicketsCog"):
    """Multi-Category Support Ticket System."""

    CATEGORY = "Tickets"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Register persistent ticket views so buttons survive bot restarts."""
        self.bot.add_view(TicketControlView(self.bot))
        self.bot.add_view(TicketPanelView(self.bot))

    async def _is_ticket_staff(
        self, member: discord.Member, category_row: Optional[Dict[str, Any]] = None
    ) -> bool:
        if await self.bot.permission_service.has_tier(member, "support"):
            return True
        if category_row:
            staff_ids = {int(x) for x in category_row.get("staff_role_ids", [])}
            member_role_ids = {r.id for r in member.roles}
            if staff_ids.intersection(member_role_ids):
                return True
        return False

    async def open_ticket_from_button(
        self, interaction: discord.Interaction, category_slug: str
    ) -> None:
        """Create a private ticket channel when a user clicks a category button."""
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Tickets can only be opened inside a server.", ephemeral=True
            )
            return

        cfg = await self.bot.guild_config_repo.ensure_guild(guild.id)
        cat_info = await self.bot.ticket_repo.get_category(guild.id, category_slug)
        if cat_info is None:
            await interaction.response.send_message(
                f"Ticket category `{category_slug}` is no longer available.",
                ephemeral=True,
            )
            return

        limit = int(cfg.get("ticket_limit_per_member") or 1)
        current_open = await self.bot.ticket_repo.count_open_tickets_for_user(guild.id, user.id)
        if current_open >= limit:
            emb = make_embed(
                "⚠️ Ticket Limit Reached",
                f"You already have **{current_open}** open ticket(s) (maximum allowed per member: **{limit}**).",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return

        # Format channel name
        naming_fmt = str(cfg.get("ticket_naming_format") or "ticket-{category}-{username}")
        safe_user = re.sub(r"[^a-z0-9-]", "", user.name.lower()) or str(user.id)
        raw_name = (
            naming_fmt.replace("{category}", category_slug)
            .replace("{username}", safe_user)
            .replace("{userid}", str(user.id))
        )
        channel_name = re.sub(r"-+", "-", raw_name.lower()).strip("-")[:95] or f"ticket-{user.id}"

        # Build permission overwrites for creator, bot, and authorized staff roles
        overwrites: Dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                read_message_history=True,
            ),
        }

        staff_rows = await self.bot.rbac_repo.list_staff_roles(guild.id)
        staff_role_ids = {int(r["role_id"]) for r in staff_rows} | {
            int(rid) for rid in cat_info.get("staff_role_ids", [])
        }
        for rid in staff_role_ids:
            role_obj = guild.get_role(rid)
            if role_obj:
                overwrites[role_obj] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )

        parent_category: Optional[discord.CategoryChannel] = None
        if cfg.get("ticket_category_id"):
            ch_cand = guild.get_channel(int(cfg["ticket_category_id"]))
            if isinstance(ch_cand, discord.CategoryChannel):
                parent_category = ch_cand

        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=parent_category,
            overwrites=overwrites,
            topic=f"Ticket by {user} ({user.id}) | Category: {cat_info['name']}",
            reason=f"Project Nova Ticket opened by {user}",
        )

        ticket_id = await self.bot.ticket_repo.create_ticket(
            guild.id,
            ticket_channel.id,
            user.id,
            category_slug,
            str(cat_info["name"]),
        )

        intro_embed = make_embed(
            f"{cat_info.get('emoji', '🎫')} Ticket #{ticket_id} — {cat_info['name']}",
            (
                f"Welcome {user.mention}! Our staff team has been notified and will assist you shortly.\n\n"
                f"• **Category:** {cat_info['name']}\n"
                f"• **Opened By:** {user.mention} (`{user.id}`)\n"
                f"• **Status:** 🟢 Open (Unclaimed)\n"
                f"• **Claimed By:** *Unclaimed*\n\n"
                f"Please describe your request in detail below."
            ),
            color=discord.Color.blurple(),
        )
        control_view = TicketControlView(self.bot)
        await ticket_channel.send(content=user.mention, embed=intro_embed, view=control_view)

        confirm_emb = make_embed(
            "🎫 Ticket Created",
            f"Your **{cat_info['name']}** ticket has been created: {ticket_channel.mention}",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=confirm_emb, ephemeral=True)

    async def handle_claim_interaction(self, interaction: discord.Interaction) -> None:
        """Handle a staff member clicking 'Claim Ticket' (with simultaneous-claim protection)."""
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            return

        ticket = await self.bot.ticket_repo.get_ticket_by_channel(interaction.channel.id)
        if not ticket or ticket["status"] == "closed":
            await interaction.response.send_message(
                "This channel is not an active open ticket.", ephemeral=True
            )
            return

        cat_info = await self.bot.ticket_repo.get_category(
            interaction.guild.id, str(ticket["category_slug"])
        )
        if not await self._is_ticket_staff(interaction.user, cat_info):
            await interaction.response.send_message(
                "🚫 Only authorized support/moderation staff can claim tickets.",
                ephemeral=True,
            )
            return

        existing_claimer = ticket.get("claimed_by")
        if existing_claimer is not None:
            if int(existing_claimer) == interaction.user.id:
                await interaction.response.send_message(
                    "You have already claimed this ticket.", ephemeral=True
                )
                return
            # Prevent multiple moderators from claiming simultaneously unless reassignment is authorized (management+)
            can_reassign = await self.bot.permission_service.has_tier(
                interaction.user, "management"
            )
            if not can_reassign:
                await interaction.response.send_message(
                    f"⚠️ This ticket is already claimed by <@{existing_claimer}>. Only Management or Administrators can reassign claimed tickets.",
                    ephemeral=True,
                )
                return

        await self.bot.ticket_repo.claim_ticket(interaction.channel.id, interaction.user.id)
        emb = make_embed(
            "🙋 Ticket Claimed",
            (
                f"This ticket is now claimed and handled by {interaction.user.mention}.\n"
                f"• **Ticket ID:** `#{ticket['ticket_id']}`\n"
                f"• **Category:** {ticket['category_name']}\n"
                f"• **Claiming Moderator:** {interaction.user.mention}"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=emb)

    async def handle_transcript_interaction(self, interaction: discord.Interaction) -> None:
        """Generate and attach a live transcript inside the ticket channel."""
        if not isinstance(interaction.channel, discord.TextChannel):
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            await interaction.response.send_message(
                "This channel is not a registered ticket.", ephemeral=True
            )
            return

        transcript_str = await generate_channel_transcript(interaction.channel, ticket)
        file_obj = discord.File(
            io.BytesIO(transcript_str.encode("utf-8")),
            filename=f"transcript-ticket-{ticket['ticket_id']}.txt",
        )
        emb = make_embed(
            f"📄 Transcript — Ticket #{ticket['ticket_id']}",
            f"Generated transcript for **{ticket['category_name']}** (`{len(transcript_str)} bytes`).",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=emb, file=file_obj)

    async def handle_close_prompt_interaction(self, interaction: discord.Interaction) -> None:
        """Display the confirmation dialog before closing a ticket."""
        if not isinstance(interaction.channel, discord.TextChannel):
            return
        ticket = await self.bot.ticket_repo.get_ticket_by_channel(interaction.channel.id)
        if not ticket or ticket["status"] == "closed":
            await interaction.response.send_message(
                "This ticket is already closed or invalid.", ephemeral=True
            )
            return

        emb = make_embed(
            "⚠️ Confirm Ticket Closure",
            f"Are you sure you want to close **Ticket #{ticket['ticket_id']}** ({ticket['category_name']})?\n"
            "A transcript will be saved and notifications will be sent.",
            color=discord.Color.orange(),
        )
        view = TicketCloseConfirmView(self.bot, self)
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

    async def execute_ticket_close(
        self, interaction: discord.Interaction, reason: str = "Resolved"
    ) -> None:
        """Close the ticket, save transcript, DM creator & claiming moderator, and clean up channel."""
        guild = interaction.guild
        channel = interaction.channel
        closer = interaction.user
        if guild is None or not isinstance(channel, discord.TextChannel) or closer is None:
            return

        ticket = await self.bot.ticket_repo.get_ticket_by_channel(channel.id)
        if not ticket or ticket["status"] == "closed":
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Ticket is already closed.", ephemeral=True
                )
            return

        cfg = await self.bot.guild_config_repo.ensure_guild(guild.id)
        transcript_text = await generate_channel_transcript(channel, ticket)
        await self.bot.ticket_repo.close_ticket(
            channel.id, closer.id, reason, transcript_text
        )

        claimed_by_id = ticket.get("claimed_by")
        claimed_by_str = f"<@{claimed_by_id}>" if claimed_by_id else "Unclaimed"

        summary_embed = make_embed(
            f"🔒 Ticket #{ticket['ticket_id']} Closed — {guild.name}",
            (
                f"• **Ticket Category:** {ticket['category_name']}\n"
                f"• **Opened By:** <@{ticket['creator_id']}>\n"
                f"• **Claimed By:** {claimed_by_str}\n"
                f"• **Closing Moderator:** {closer.mention} (`{closer.id}`)\n"
                f"• **Reason:** {reason}\n"
                f"• **Transcript Size:** `{len(transcript_text)} chars`"
            ),
            color=discord.Color.red(),
        )

        # 1. Log to configured ticket_log_channel_id or log_channel_id if set
        log_ch_id = cfg.get("ticket_log_channel_id") or cfg.get("log_channel_id")
        if log_ch_id:
            log_ch = guild.get_channel(int(log_ch_id))
            if isinstance(log_ch, discord.TextChannel):
                try:
                    t_file = discord.File(
                        io.BytesIO(transcript_text.encode("utf-8")),
                        filename=f"ticket-{ticket['ticket_id']}-transcript.txt",
                    )
                    await log_ch.send(embed=summary_embed, file=t_file)
                except Exception:
                    pass

        # 2. Notify ticket creator via DM (handle disabled DMs gracefully)
        creator_member = guild.get_member(int(ticket["creator_id"]))
        if creator_member is not None:
            try:
                dm_file = discord.File(
                    io.BytesIO(transcript_text.encode("utf-8")),
                    filename=f"ticket-{ticket['ticket_id']}-transcript.txt",
                )
                await creator_member.send(embed=summary_embed, file=dm_file)
            except (discord.Forbidden, discord.HTTPException):
                logger.info("Creator %s has DMs disabled; skipped ticket close DM.", creator_member.id)

        # 3. Notify the moderator who claimed the ticket via DM (handle disabled DMs gracefully)
        if claimed_by_id:
            claimed_mod = guild.get_member(int(claimed_by_id))
            if claimed_mod is not None:
                try:
                    mod_file = discord.File(
                        io.BytesIO(transcript_text.encode("utf-8")),
                        filename=f"ticket-{ticket['ticket_id']}-transcript.txt",
                    )
                    await claimed_mod.send(embed=summary_embed, file=mod_file)
                except (discord.Forbidden, discord.HTTPException):
                    logger.info("Claiming moderator %s has DMs disabled; skipped DM.", claimed_mod.id)

        if not interaction.response.is_done():
            await interaction.response.send_message(embed=summary_embed)
        else:
            await channel.send(embed=summary_embed)

        # Delete the closed ticket channel
        try:
            await channel.delete(reason=f"Ticket #{ticket['ticket_id']} closed by {closer}")
        except Exception:
            pass

    @commands.hybrid_group(
        name="ticket",
        aliases=["tickets"],
        description="Manage the server ticket system, panels, categories, and configuration.",
        fallback="panel",
    )
    @app_commands.describe(channel="Channel where the ticket panel should be posted")
    @commands.guild_only()
    @require_tier("management")
    async def ticket_group(
        self,
        ctx: commands.Context,
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        """Create and publish an interactive multi-category ticket panel."""
        assert ctx.guild is not None
        target_ch = channel or ctx.channel
        assert isinstance(target_ch, discord.TextChannel)

        categories = await self.bot.ticket_repo.ensure_default_categories(ctx.guild.id)
        cat_lines = [
            f"• {c.get('emoji', '🎫')} **{c['name']}** — {c['description']}"
            for c in categories
        ]
        emb = make_embed(
            f"🎫 {ctx.guild.name} — Support Tickets",
            "Select a category button below to open a private support ticket with our staff team:\n\n"
            + "\n".join(cat_lines),
            color=discord.Color.blurple(),
        )
        view = TicketPanelView(self.bot, categories)
        self.bot.add_view(view)
        sent = await target_ch.send(embed=emb, view=view)
        await self.bot.ticket_repo.record_panel(
            ctx.guild.id, target_ch.id, sent.id, emb.title or "Tickets", emb.description or ""
        )
        if target_ch.id != ctx.channel.id:
            await ctx.send(
                embed=make_embed(
                    "✅ Ticket Panel Created",
                    f"Published interactive ticket panel in {target_ch.mention}.",
                    color=discord.Color.green(),
                )
            )

    @ticket_group.command(
        name="addcategory",
        description="Add a custom ticket category to this server's ticket panels.",
    )
    @app_commands.describe(
        slug="Short identifier (e.g. billing-support)",
        name="Display name (e.g. Billing Support)",
        emoji="Button emoji (e.g. 💳)",
        description="Short description of this ticket category",
    )
    @require_tier("management")
    async def add_category(
        self,
        ctx: commands.Context,
        slug: str,
        name: str,
        emoji: str = "🎫",
        *,
        description: str = "Click to open a support ticket.",
    ) -> None:
        """Add or update a ticket category."""
        assert ctx.guild is not None
        clean_slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
        if not clean_slug:
            raise commands.BadArgument("Category slug must contain alphanumeric characters.")
        await self.bot.ticket_repo.add_category(
            ctx.guild.id, clean_slug, name, emoji, description
        )
        emb = make_embed(
            "✅ Ticket Category Added",
            f"Added category {emoji} **{name}** (`{clean_slug}`). Run `/ticket panel` to refresh your panel.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @ticket_group.command(
        name="removecategory",
        description="Remove a ticket category by its slug.",
    )
    @app_commands.describe(slug="Slug of the category to remove (e.g. billing-support)")
    @require_tier("management")
    async def remove_category(self, ctx: commands.Context, slug: str) -> None:
        """Delete a ticket category from the server configuration."""
        assert ctx.guild is not None
        deleted = await self.bot.ticket_repo.remove_category(ctx.guild.id, slug)
        emb = make_embed(
            "🗑️ Ticket Category Removed" if deleted else "❓ Category Not Found",
            f"Removed ticket category `{slug}`."
            if deleted
            else f"No ticket category with slug `{slug}` was found.",
            color=discord.Color.green() if deleted else discord.Color.orange(),
        )
        await ctx.send(embed=emb)

    @ticket_group.command(
        name="config",
        description="Configure ticket category channel, transcript log channel, limit per member, and naming format.",
    )
    @app_commands.describe(
        category="Discord CategoryChannel where new tickets are created",
        log_channel="TextChannel where closed ticket transcripts are logged",
        limit_per_member="Maximum simultaneous open tickets per member (1-10)",
        naming_format="Channel naming pattern (e.g. ticket-{category}-{username})",
    )
    @require_tier("management")
    async def ticket_config(
        self,
        ctx: commands.Context,
        category: Optional[discord.CategoryChannel] = None,
        log_channel: Optional[discord.TextChannel] = None,
        limit_per_member: Optional[int] = None,
        naming_format: Optional[str] = None,
    ) -> None:
        """Update server-wide ticket settings."""
        assert ctx.guild is not None
        updates: Dict[str, Any] = {}
        if category is not None:
            updates["ticket_category_id"] = category.id
        if log_channel is not None:
            updates["ticket_log_channel_id"] = log_channel.id
        if limit_per_member is not None:
            updates["ticket_limit_per_member"] = max(1, min(10, int(limit_per_member)))
        if naming_format is not None:
            updates["ticket_naming_format"] = naming_format.strip()[:60]

        cfg = await self.bot.guild_config_repo.update_fields(ctx.guild.id, **updates)
        parent_cat_str = f"<#{cfg['ticket_category_id']}>" if cfg.get("ticket_category_id") else "Default"
        log_ch_str = f"<#{cfg['ticket_log_channel_id']}>" if cfg.get("ticket_log_channel_id") else "None"
        emb = make_embed(
            "⚙️ Ticket Configuration Updated",
            (
                f"• **Parent Category:** {parent_cat_str}\n"
                f"• **Transcript Log Channel:** {log_ch_str}\n"
                f"• **Ticket Limit / Member:** `{cfg['ticket_limit_per_member']}`\n"
                f"• **Naming Format:** `{cfg['ticket_naming_format']}`"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @ticket_group.command(
        name="claim",
        description="Claim the current ticket channel as the handling staff member.",
    )
    @require_tier("support")
    async def claim_cmd(self, ctx: commands.Context) -> None:
        """Claim the current ticket via command."""
        assert ctx.guild is not None and isinstance(ctx.channel, discord.TextChannel)
        fake_inter = discord.Interaction(
            client=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
        )
        await self.handle_claim_interaction(fake_inter)
        if fake_inter.sent_messages and fake_inter.sent_messages[-1] not in ctx.channel.messages:
            ctx.channel.messages.append(fake_inter.sent_messages[-1])

    @ticket_group.command(
        name="close",
        description="Close the current ticket channel, generate transcript, and notify participants.",
    )
    @app_commands.describe(reason="Reason for closing the ticket")
    @require_tier("support")
    async def close_cmd(
        self, ctx: commands.Context, *, reason: str = "Resolved by staff"
    ) -> None:
        """Close the current ticket channel immediately with a reason."""
        assert ctx.guild is not None and isinstance(ctx.channel, discord.TextChannel)
        fake_inter = discord.Interaction(
            client=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
        )
        await self.execute_ticket_close(fake_inter, reason=reason)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
