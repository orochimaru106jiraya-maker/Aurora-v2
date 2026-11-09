"""Utility commands (`ping`, `serverinfo`, `userinfo`, `avatar`, `roleinfo`, `botinfo`, `inviteinfo`, `channelinfo`)."""

from __future__ import annotations

import platform
import time
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot import __bot_name__, __internal_name__, __version__
from bot.utils.formatting import make_embed


class UtilityCog(commands.Cog, name="UtilityCog"):
    """Core Utility & Information Commands."""

    CATEGORY = "Utility"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="ping",
        aliases=["latency", "pong"],
        description="Check the bot's gateway latency and database response time.",
    )
    @commands.cooldown(1, 3.0, commands.BucketType.user)
    async def ping(self, ctx: commands.Context) -> None:
        """Measure gateway websocket latency and SQLite database round-trip time."""
        ws_ms = round((self.bot.latency or 0.0) * 1000, 2)
        t0 = time.perf_counter()
        await self.bot.db.fetchone("SELECT 1 AS ok;")
        db_ms = round((time.perf_counter() - t0) * 1000, 2)

        emb = make_embed(
            "🏓 Pong! — System Telemetry",
            f"**{__bot_name__}** (*{__internal_name__}*) is online and operational.",
            color=discord.Color.green(),
        )
        emb.add_field(name="Gateway Latency", value=f"`{ws_ms} ms`", inline=True)
        emb.add_field(name="Database Latency", value=f"`{db_ms} ms`", inline=True)
        emb.add_field(name="Uptime", value=f"`{self.bot.health.uptime_human}`", inline=True)
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="serverinfo",
        aliases=["guildinfo", "si"],
        description="Display detailed information about the current Discord server.",
    )
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context) -> None:
        """Display server statistics, owner, channel counts, and prefix configuration."""
        guild = ctx.guild
        assert guild is not None
        prefix = await self.bot.guild_config_repo.get_prefix(guild.id)

        emb = make_embed(
            f"🏰 Server Information — {guild.name}",
            f"Server ID: `{guild.id}`",
            color=discord.Color.blurple(),
        )
        if getattr(guild, "icon", None):
            emb.set_thumbnail(url=str(guild.icon))
        emb.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
        emb.add_field(name="Members", value=str(guild.member_count), inline=True)
        emb.add_field(name="Configured Prefix", value=f"`{prefix}`", inline=True)
        emb.add_field(
            name="Channels",
            value=f"Text: `{len(guild.text_channels)}` | Voice: `{len(guild.voice_channels)}` | Categories: `{len(guild.categories)}`",
            inline=False,
        )
        emb.add_field(name="Roles Count", value=str(len(guild.roles)), inline=True)
        emb.add_field(
            name="Created",
            value=discord.utils.format_dt(guild.created_at, "R"),
            inline=True,
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="userinfo",
        aliases=["whois", "ui"],
        description="Display information and RBAC tier for a server member.",
    )
    @app_commands.describe(member="The member to inspect (defaults to yourself)")
    @commands.guild_only()
    async def userinfo(
        self, ctx: commands.Context, member: Optional[discord.Member] = None
    ) -> None:
        """Inspect a member's account dates, roles, and Project Nova RBAC tier."""
        target = member or ctx.author
        assert isinstance(target, discord.Member)
        tier = await self.bot.permission_service.get_member_tier(target)
        roles = [r.mention for r in target.roles if not r.is_default()]

        emb = make_embed(
            f"👤 User Information — {target}",
            f"Mention: {target.mention} (`{target.id}`)",
            color=target.top_role.color if target.top_role else discord.Color.blurple(),
        )
        emb.set_thumbnail(url=str(target.display_avatar))
        emb.add_field(name="RBAC Tier", value=f"**{tier.title()}**", inline=True)
        emb.add_field(name="Highest Role", value=target.top_role.mention, inline=True)
        emb.add_field(
            name="Account Created",
            value=discord.utils.format_dt(target.created_at, "R"),
            inline=True,
        )
        if target.joined_at:
            emb.add_field(
                name="Joined Server",
                value=discord.utils.format_dt(target.joined_at, "R"),
                inline=True,
            )
        emb.add_field(
            name=f"Roles ({len(roles)})",
            value=", ".join(roles[:15]) if roles else "None",
            inline=False,
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="avatar",
        aliases=["av", "pfp"],
        description="Display a member's avatar image.",
    )
    @app_commands.describe(member="The member whose avatar to display")
    async def avatar(
        self, ctx: commands.Context, member: Optional[discord.Member] = None
    ) -> None:
        """Show high-resolution avatar for a user."""
        target = member or ctx.author
        emb = make_embed(
            f"🖼️ Avatar — {target}",
            f"[Direct Image Link]({target.display_avatar})",
            color=discord.Color.blurple(),
        )
        emb.set_image(url=str(target.display_avatar))
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="roleinfo",
        aliases=["ri"],
        description="Display information about a specific server role.",
    )
    @app_commands.describe(role="The role to inspect")
    @commands.guild_only()
    async def roleinfo(self, ctx: commands.Context, role: discord.Role) -> None:
        """Display role ID, position, color, and member count."""
        emb = make_embed(
            f"🎭 Role Information — {role.name}",
            f"Mention: {role.mention} (`{role.id}`)",
            color=role.color,
        )
        emb.add_field(name="Position", value=str(role.position), inline=True)
        emb.add_field(name="Members", value=str(len(role.members)), inline=True)
        emb.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        emb.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        emb.add_field(
            name="Admin Permission",
            value="Yes" if role.permissions.administrator else "No",
            inline=True,
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="channelinfo",
        aliases=["ci"],
        description="Display details about a text channel.",
    )
    @app_commands.describe(channel="The text channel to inspect (defaults to current)")
    @commands.guild_only()
    async def channelinfo(
        self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None
    ) -> None:
        """Show channel ID, category, slowmode, and creation date."""
        target = channel or ctx.channel
        emb = make_embed(
            f"💬 Channel Information — #{target.name}",
            f"Channel: {target.mention} (`{target.id}`)",
            color=discord.Color.blurple(),
        )
        emb.add_field(
            name="Category",
            value=target.category.name if getattr(target, "category", None) else "None",
            inline=True,
        )
        emb.add_field(
            name="Slowmode",
            value=f"{getattr(target, 'slowmode_delay', 0)}s",
            inline=True,
        )
        emb.add_field(
            name="Created",
            value=discord.utils.format_dt(target.created_at, "R"),
            inline=True,
        )
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="botinfo",
        aliases=["about", "nova"],
        description="Display technical information and statistics about Cosmic ki baddie V2.",
    )
    async def botinfo(self, ctx: commands.Context) -> None:
        """Show bot version, runtime environment, loaded Cogs, and command counts."""
        stats = self.bot.registry_inspector.verify_integrity()
        emb = make_embed(
            f"🤖 {__bot_name__} ({__internal_name__})",
            "Production-grade modular Discord server management, ticket, RBAC, voice, and automation bot.",
            color=discord.Color.blurple(),
        )
        emb.add_field(name="Version", value=f"`v{__version__}`", inline=True)
        emb.add_field(name="Python", value=f"`{platform.python_version()}`", inline=True)
        emb.add_field(name="discord.py", value=f"`{discord.__version__}`", inline=True)
        emb.add_field(name="Loaded Cogs", value=f"`{stats['cogs']}`", inline=True)
        emb.add_field(name="Prefix Commands", value=f"`{stats['prefix_commands']}`", inline=True)
        emb.add_field(name="Slash Commands", value=f"`{stats['slash_commands']}`", inline=True)
        emb.add_field(name="Uptime", value=f"`{self.bot.health.uptime_human}`", inline=True)
        emb.add_field(name="Servers", value=f"`{len(self.bot.guilds)}`", inline=True)
        await ctx.send(embed=emb)

    @commands.hybrid_command(
        name="inviteinfo",
        aliases=["invites", "botinvite"],
        description="Generate the bot invite URL and view active server invites.",
    )
    @commands.guild_only()
    async def inviteinfo(self, ctx: commands.Context) -> None:
        """Display the OAuth2 invite URL for the bot and server invite count."""
        client_id = self.bot.user.id if self.bot.user else 0
        oauth_url = (
            f"https://discord.com/api/oauth2/authorize?client_id={client_id}"
            f"&permissions=8&scope=bot%20applications.commands"
        )
        invites_count = 0
        try:
            if ctx.guild:
                invs = await ctx.guild.invites()
                invites_count = len(invs)
        except Exception:
            invites_count = 0

        emb = make_embed(
            "🔗 Invite & Server Links",
            f"• **[Invite {__bot_name__}]({oauth_url})**\n• **Active Server Invites Tracked:** `{invites_count}`",
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
