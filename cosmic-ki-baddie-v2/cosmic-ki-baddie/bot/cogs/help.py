"""Custom Help System (`!help`, `/help`, `!commands`) for Project Nova.

Displays only commands that actually exist and are registered on the bot.
Supports:
- `!help` / `/help` (Interactive overview of all active categories)
- `!help ping` / `/help command:ping` (Detailed command inspection)
- `!help moderation` / `/help command:moderation` (Category command listing)
Never displays empty categories or fictional commands.
"""

from __future__ import annotations

from typing import Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.core.command_registry import OFFICIAL_CATEGORIES
from bot.utils.formatting import make_embed


class HelpCategorySelect(discord.ui.Select):
    """Dropdown menu allowing users to browse active command categories."""

    def __init__(self, bot: commands.Bot, prefix: str) -> None:
        self.bot = bot
        self.prefix = prefix
        grouped = bot.registry_inspector.get_categorized_commands()
        emoji_map = {name: emoji for name, emoji, _ in OFFICIAL_CATEGORIES}
        desc_map = {name: desc for name, _, desc in OFFICIAL_CATEGORIES}

        options: List[discord.SelectOption] = [
            discord.SelectOption(
                label="Overview (All Categories)",
                value="__overview__",
                emoji="🌌",
                description="Return to the main Project Nova help overview.",
            )
        ]
        for cat_name, cmds in grouped.items():
            options.append(
                discord.SelectOption(
                    label=f"{cat_name} ({len(cmds)})",
                    value=cat_name,
                    emoji=emoji_map.get(cat_name, "📌"),
                    description=desc_map.get(cat_name, f"{cat_name} commands")[:100],
                )
            )

        super().__init__(
            placeholder="Select a command category to inspect...",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id="nova:help:category_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        choice = self.values[0]
        help_cog: Optional["HelpCog"] = self.bot.get_cog("HelpCog")  # type: ignore
        if help_cog is None:
            return
        if choice == "__overview__":
            embed = help_cog.build_overview_embed(self.prefix)
        else:
            res = self.bot.registry_inspector.resolve_category(choice)
            if not res:
                embed = help_cog.build_overview_embed(self.prefix)
            else:
                embed = help_cog.build_category_embed(res[0], res[1], self.prefix)
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    """Interactive view attached to the custom help embed."""

    def __init__(self, bot: commands.Bot, prefix: str, author_id: int) -> None:
        super().__init__(timeout=180.0)
        self.author_id = author_id
        self.add_item(HelpCategorySelect(bot, prefix))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Please run `/help` or `!help` yourself to control this menu.",
                ephemeral=True,
            )
            return False
        return True


class HelpCog(commands.Cog, name="HelpCog"):
    """Custom Help & Command Discovery Module."""

    CATEGORY = "Utility"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def build_overview_embed(self, prefix: str) -> discord.Embed:
        grouped = self.bot.registry_inspector.get_categorized_commands()
        emoji_map = {name: emoji for name, emoji, _ in OFFICIAL_CATEGORIES}
        total_cmds = sum(len(v) for v in grouped.values())

        embed = make_embed(
            "🌌 Cosmic ki baddie V2 — Help Center",
            (
                f"Welcome to **Cosmic ki baddie V2** (*Project Nova*).\n"
                f"• **Server Prefix:** `{prefix}` (Slash commands `/` are also supported)\n"
                f"• **Inspect Command:** `{prefix}help <command>` or `/help command:<name>`\n"
                f"• **Inspect Category:** `{prefix}help <category>` or use the menu below.\n"
                f"• **Registered Commands:** **{total_cmds}** active commands across **{len(grouped)}** categories."
            ),
            color=discord.Color.blurple(),
        )

        for cat_name, cmds in grouped.items():
            emoji = emoji_map.get(cat_name, "📌")
            cmd_list = ", ".join(f"`{c.name}`" for c in cmds)
            embed.add_field(
                name=f"{emoji} {cat_name} ({len(cmds)})",
                value=cmd_list or "None",
                inline=False,
            )
        return embed

    def build_category_embed(
        self, category_name: str, cmds: List[commands.Command], prefix: str
    ) -> discord.Embed:
        emoji_map = {name: emoji for name, emoji, _ in OFFICIAL_CATEGORIES}
        desc_map = {name: desc for name, _, desc in OFFICIAL_CATEGORIES}
        emoji = emoji_map.get(category_name, "📌")

        lines: List[str] = []
        for cmd in cmds:
            sig = f" {cmd.signature}" if cmd.signature else ""
            lines.append(f"• **`{prefix}{cmd.name}{sig}`** — {cmd.description}")

        embed = make_embed(
            f"{emoji} {category_name} Commands",
            f"{desc_map.get(category_name, '')}\n\n" + "\n".join(lines),
            color=discord.Color.blurple(),
        )
        return embed

    def build_command_embed(self, cmd: commands.Command, prefix: str) -> discord.Embed:
        cat = self.bot.registry_inspector.get_command_category(cmd)
        sig = f" {cmd.signature}" if cmd.signature else ""
        embed = make_embed(
            f"📖 Command: {prefix}{cmd.qualified_name}",
            cmd.help or cmd.description or "No detailed description available.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Category", value=cat, inline=True)
        embed.add_field(
            name="Prefix Usage",
            value=f"`{prefix}{cmd.qualified_name}{sig}`",
            inline=True,
        )
        embed.add_field(
            name="Slash Usage",
            value=f"`/{cmd.qualified_name}{sig}`",
            inline=True,
        )
        if cmd.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(f"`{a}`" for a in cmd.aliases),
                inline=False,
            )
        if isinstance(cmd, commands.Group) and cmd.commands:
            subs = "\n".join(
                f"• `{prefix}{cmd.qualified_name} {sub.name}` — {sub.description}"
                for sub in sorted(cmd.commands, key=lambda s: s.name)
            )
            embed.add_field(name="Subcommands", value=subs, inline=False)
        return embed

    @commands.hybrid_command(
        name="help",
        aliases=["commands", "h"],
        description="Display the interactive help menu or inspect a specific command/category.",
    )
    @app_commands.describe(command="Optional command or category name (e.g., ping, moderation)")
    @commands.cooldown(1, 2.0, commands.BucketType.user)
    async def help_command(
        self, ctx: commands.Context, *, command: Optional[str] = None
    ) -> None:
        """Display the Project Nova interactive help center or detailed command/category info."""
        guild_id = ctx.guild.id if ctx.guild else None
        prefix = await self.bot.guild_config_repo.get_prefix(guild_id)

        if not command:
            embed = self.build_overview_embed(prefix)
            view = HelpView(self.bot, prefix, ctx.author.id if ctx.author else 0)
            await ctx.send(embed=embed, view=view)
            return

        query = command.strip()
        # 1. Check if query matches a registered command or alias
        found_cmd = self.bot.get_command(query.lower())
        if found_cmd is not None and not found_cmd.hidden:
            embed = self.build_command_embed(found_cmd, prefix)
            await ctx.send(embed=embed)
            return

        # 2. Check if query matches an active category
        cat_match = self.bot.registry_inspector.resolve_category(query)
        if cat_match is not None:
            cat_name, cmds = cat_match
            embed = self.build_category_embed(cat_name, cmds, prefix)
            view = HelpView(self.bot, prefix, ctx.author.id if ctx.author else 0)
            await ctx.send(embed=embed, view=view)
            return

        # 3. Not found
        emb = make_embed(
            "❓ Command or Category Not Found",
            f"No registered command or category named **`{query}`** was found.\nUse `{prefix}help` or `/help` to browse all available commands.",
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
