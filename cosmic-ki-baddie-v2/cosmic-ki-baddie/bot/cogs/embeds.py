"""Interactive Custom Embed Creator & Template Manager (`bot/cogs/embeds.py`).

Allows administrators/staff to interactively create, preview, edit, save templates,
and publish custom Discord embeds using Modals and Buttons:
- Title, Description, Hex Color
- Author (name, icon URL) & Footer (text, icon URL)
- Thumbnail URL & Image URL
- Add / Clear Fields
- Toggle Timestamp
- Live Preview, Save Template to SQLite, Load Template, and Publish to a selected channel
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.permission_service import require_tier
from bot.utils.formatting import make_embed


class EmbedMainModal(discord.ui.Modal, title="Edit Embed Title, Description & Color"):
    title_input = discord.ui.TextInput(
        label="Embed Title",
        default="Cosmic Announcement",
        max_length=256,
    )
    desc_input = discord.ui.TextInput(
        label="Embed Description",
        style=discord.TextStyle.paragraph,
        default="Customize this embed using the buttons below.",
        max_length=4000,
    )
    color_input = discord.ui.TextInput(
        label="Hex Color (e.g. #5865F2)",
        default="#5865F2",
        max_length=10,
    )

    def __init__(self, builder_view: "EmbedBuilderView") -> None:
        super().__init__(custom_id="nova:embed:modal:main")
        self.builder_view = builder_view
        self.title_input.default = builder_view.state.get("title") or ""
        self.desc_input.default = builder_view.state.get("description") or ""
        self.color_input.default = f"#{int(builder_view.state.get('color', 0x5865F2)):06X}"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.builder_view.state["title"] = self.title_input.value.strip()
        self.builder_view.state["description"] = self.desc_input.value.strip()
        try:
            c = discord.Color.from_str(self.color_input.value.strip())
            self.builder_view.state["color"] = int(c)
        except Exception:
            pass
        await interaction.response.edit_message(
            embed=self.builder_view.to_embed(), view=self.builder_view
        )


class EmbedAuthorFooterModal(discord.ui.Modal, title="Edit Author & Footer"):
    author_name = discord.ui.TextInput(
        label="Author Name",
        required=False,
        max_length=256,
    )
    author_icon = discord.ui.TextInput(
        label="Author Icon URL (optional)",
        required=False,
        max_length=500,
    )
    footer_text = discord.ui.TextInput(
        label="Footer Text",
        required=False,
        max_length=2048,
    )
    footer_icon = discord.ui.TextInput(
        label="Footer Icon URL (optional)",
        required=False,
        max_length=500,
    )

    def __init__(self, builder_view: "EmbedBuilderView") -> None:
        super().__init__(custom_id="nova:embed:modal:author_footer")
        self.builder_view = builder_view
        author = builder_view.state.get("author") or {}
        footer = builder_view.state.get("footer") or {}
        self.author_name.default = author.get("name") or ""
        self.author_icon.default = author.get("icon_url") or ""
        self.footer_text.default = footer.get("text") or ""
        self.footer_icon.default = footer.get("icon_url") or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.builder_view.state["author"] = {
            "name": self.author_name.value.strip() or None,
            "icon_url": self.author_icon.value.strip() or None,
        }
        self.builder_view.state["footer"] = {
            "text": self.footer_text.value.strip() or None,
            "icon_url": self.footer_icon.value.strip() or None,
        }
        await interaction.response.edit_message(
            embed=self.builder_view.to_embed(), view=self.builder_view
        )


class EmbedMediaModal(discord.ui.Modal, title="Edit Thumbnail & Main Image"):
    thumbnail_url = discord.ui.TextInput(
        label="Thumbnail Image URL",
        required=False,
        max_length=500,
    )
    image_url = discord.ui.TextInput(
        label="Large Banner Image URL",
        required=False,
        max_length=500,
    )

    def __init__(self, builder_view: "EmbedBuilderView") -> None:
        super().__init__(custom_id="nova:embed:modal:media")
        self.builder_view = builder_view
        self.thumbnail_url.default = (builder_view.state.get("thumbnail") or {}).get("url") or ""
        self.image_url.default = (builder_view.state.get("image") or {}).get("url") or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        t_url = self.thumbnail_url.value.strip() or None
        i_url = self.image_url.value.strip() or None
        self.builder_view.state["thumbnail"] = {"url": t_url} if t_url else {}
        self.builder_view.state["image"] = {"url": i_url} if i_url else {}
        await interaction.response.edit_message(
            embed=self.builder_view.to_embed(), view=self.builder_view
        )


class EmbedAddFieldModal(discord.ui.Modal, title="Add Embed Field"):
    field_name = discord.ui.TextInput(
        label="Field Name",
        max_length=256,
    )
    field_value = discord.ui.TextInput(
        label="Field Value",
        style=discord.TextStyle.paragraph,
        max_length=1024,
    )
    field_inline = discord.ui.TextInput(
        label="Inline? (true / false)",
        default="true",
        max_length=5,
    )

    def __init__(self, builder_view: "EmbedBuilderView") -> None:
        super().__init__(custom_id="nova:embed:modal:add_field")
        self.builder_view = builder_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        fields: List[Dict[str, Any]] = self.builder_view.state.setdefault("fields", [])
        inline = self.field_inline.value.strip().lower() in ("1", "true", "yes", "on")
        fields.append(
            {
                "name": self.field_name.value.strip() or "\u200b",
                "value": self.field_value.value.strip() or "\u200b",
                "inline": inline,
            }
        )
        await interaction.response.edit_message(
            embed=self.builder_view.to_embed(), view=self.builder_view
        )


class EmbedSavePublishModal(discord.ui.Modal, title="Save Template or Publish Embed"):
    template_name = discord.ui.TextInput(
        label="Save as Template Name (optional)",
        placeholder="welcome_rules",
        required=False,
        max_length=60,
    )
    channel_id = discord.ui.TextInput(
        label="Publish to Channel ID (optional)",
        placeholder="123456789012345678",
        required=False,
        max_length=25,
    )

    def __init__(self, builder_view: "EmbedBuilderView") -> None:
        super().__init__(custom_id="nova:embed:modal:save_publish")
        self.builder_view = builder_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.user is None:
            return
        t_name = self.template_name.value.strip()
        ch_str = self.channel_id.value.strip().strip("<#>")
        results: List[str] = []

        if t_name:
            await self.builder_view.bot.embed_repo.save_template(
                interaction.guild.id,
                t_name,
                self.builder_view.state,
                interaction.user.id,
            )
            results.append(f"💾 Saved template **`{t_name.lower()}`** to SQLite.")

        if ch_str.isdigit():
            target_ch = interaction.guild.get_channel(int(ch_str))
            if isinstance(target_ch, discord.TextChannel):
                sent = await target_ch.send(embed=self.builder_view.to_embed())
                results.append(f"🚀 Published embed to {target_ch.mention} ([Jump]({sent.jump_url})).")
            else:
                results.append(f"⚠️ Channel ID `{ch_str}` was not found.")

        if not results:
            results.append("No template name or channel ID was entered.")

        await interaction.response.send_message(
            embed=make_embed("✅ Embed Action Complete", "\n".join(results), color=discord.Color.green()),
            ephemeral=True,
        )


class EmbedBuilderView(discord.ui.View):
    """Interactive view for live-building, previewing, saving, and publishing custom embeds."""

    def __init__(
        self,
        bot: commands.Bot,
        author_id: int,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(timeout=600.0)
        self.bot = bot
        self.author_id = author_id
        self.state: Dict[str, Any] = initial_state or {
            "title": "✨ Custom Server Embed",
            "description": "Use the buttons below to edit title, description, color, author, footer, images, fields, and timestamp.",
            "color": 0x5865F2,
            "fields": [],
            "use_timestamp": True,
        }

    def to_embed(self) -> discord.Embed:
        emb = discord.Embed.from_dict(self.state)
        if self.state.get("use_timestamp"):
            emb.timestamp = datetime.now(timezone.utc)
        return emb

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the staff member who opened this embed builder can edit it.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Title / Desc / Color",
        style=discord.ButtonStyle.primary,
        emoji="📝",
        custom_id="nova:embed:btn:main",
        row=0,
    )
    async def edit_main_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(EmbedMainModal(self))

    @discord.ui.button(
        label="Author & Footer",
        style=discord.ButtonStyle.secondary,
        emoji="👤",
        custom_id="nova:embed:btn:author_footer",
        row=0,
    )
    async def edit_author_footer_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(EmbedAuthorFooterModal(self))

    @discord.ui.button(
        label="Thumbnail & Image",
        style=discord.ButtonStyle.secondary,
        emoji="🖼️",
        custom_id="nova:embed:btn:media",
        row=0,
    )
    async def edit_media_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(EmbedMediaModal(self))

    @discord.ui.button(
        label="Add Field",
        style=discord.ButtonStyle.secondary,
        emoji="➕",
        custom_id="nova:embed:btn:add_field",
        row=1,
    )
    async def add_field_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(EmbedAddFieldModal(self))

    @discord.ui.button(
        label="Clear Fields",
        style=discord.ButtonStyle.secondary,
        emoji="🧹",
        custom_id="nova:embed:btn:clear_fields",
        row=1,
    )
    async def clear_fields_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.state["fields"] = []
        await interaction.response.edit_message(embed=self.to_embed(), view=self)

    @discord.ui.button(
        label="Toggle Timestamp",
        style=discord.ButtonStyle.secondary,
        emoji="🕒",
        custom_id="nova:embed:btn:timestamp",
        row=1,
    )
    async def toggle_timestamp_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.state["use_timestamp"] = not bool(self.state.get("use_timestamp"))
        await interaction.response.edit_message(embed=self.to_embed(), view=self)

    @discord.ui.button(
        label="Save / Publish",
        style=discord.ButtonStyle.success,
        emoji="🚀",
        custom_id="nova:embed:btn:save_publish",
        row=1,
    )
    async def save_publish_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(EmbedSavePublishModal(self))


class EmbedsCog(commands.Cog, name="EmbedsCog"):
    """Interactive Discord Embed Builder & Template Storage."""

    CATEGORY = "Utility"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(
        name="embed",
        aliases=["embeds", "embedcreator"],
        description="Launch the interactive custom embed builder or manage saved embed templates.",
        fallback="builder",
    )
    @commands.guild_only()
    @require_tier("management")
    async def embed_group(self, ctx: commands.Context) -> None:
        """Open the interactive modal-and-button embed creator."""
        view = EmbedBuilderView(self.bot, ctx.author.id)
        await ctx.send(embed=view.to_embed(), view=view)

    @embed_group.command(
        name="templates",
        description="List all saved custom embed templates in this server.",
    )
    @require_tier("management")
    async def list_templates(self, ctx: commands.Context) -> None:
        """List saved embed templates."""
        assert ctx.guild is not None
        rows = await self.bot.embed_repo.list_templates(ctx.guild.id)
        if not rows:
            await ctx.send(
                embed=make_embed(
                    "📑 Saved Embed Templates",
                    "No embed templates saved yet. Use `/embed builder` and click **Save / Publish**.",
                    color=discord.Color.blurple(),
                )
            )
            return
        lines = [
            f"• **`{r['name']}`** — Title: *{r['embed_data'].get('title', 'Untitled')}* (Updated: `{r['updated_at']}`)"
            for r in rows
        ]
        await ctx.send(
            embed=make_embed(
                f"📑 Saved Embed Templates ({len(rows)})",
                "\n".join(lines),
                color=discord.Color.blurple(),
            )
        )

    @embed_group.command(
        name="load",
        description="Load a saved embed template into the interactive builder.",
    )
    @app_commands.describe(name="Name of the saved embed template")
    @require_tier("management")
    async def load_template(self, ctx: commands.Context, name: str) -> None:
        """Load an existing template into the live builder."""
        assert ctx.guild is not None
        row = await self.bot.embed_repo.get_template(ctx.guild.id, name)
        if not row:
            raise commands.BadArgument(f"Template `{name}` was not found.")
        view = EmbedBuilderView(self.bot, ctx.author.id, initial_state=row["embed_data"])
        await ctx.send(embed=view.to_embed(), view=view)

    @embed_group.command(
        name="publish",
        description="Publish a saved embed template directly to a text channel.",
    )
    @app_commands.describe(name="Saved template name", channel="Target text channel")
    @require_tier("management")
    async def publish_template(
        self, ctx: commands.Context, name: str, channel: discord.TextChannel
    ) -> None:
        """Publish a saved template to `channel`."""
        assert ctx.guild is not None
        row = await self.bot.embed_repo.get_template(ctx.guild.id, name)
        if not row:
            raise commands.BadArgument(f"Template `{name}` was not found.")
        view = EmbedBuilderView(self.bot, ctx.author.id, initial_state=row["embed_data"])
        sent = await channel.send(embed=view.to_embed())
        await ctx.send(
            embed=make_embed(
                "🚀 Template Published",
                f"Published template **`{name}`** to {channel.mention} ([Jump]({sent.jump_url})).",
                color=discord.Color.green(),
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbedsCog(bot))
