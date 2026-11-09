"""Centralized error handling for Prefix, Hybrid, and Application commands."""

from __future__ import annotations

import logging
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.formatting import make_embed

logger = logging.getLogger("project_nova.core.error_handler")


def register_error_handlers(bot: commands.Bot) -> None:
    """Attach global prefix/hybrid and slash command error handlers to `bot`."""

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            emb = make_embed(
                "⏳ Command Cooldown",
                f"Please wait **{error.retry_after:.1f}s** before using this command again.",
                color=discord.Color.orange(),
            )
        elif isinstance(error, app_commands.CheckFailure):
            emb = make_embed(
                "🚫 Permission Denied",
                str(error) or "You do not have permission to execute this command.",
                color=discord.Color.red(),
            )
        else:
            logger.error("Unhandled app command error: %s", error, exc_info=True)
            emb = make_embed(
                "⚠️ Command Execution Error",
                f"An error occurred while executing the command:\n`{error}`",
                color=discord.Color.red(),
            )

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=emb, ephemeral=True)
            else:
                await interaction.followup.send(embed=emb, ephemeral=True)
        except Exception:
            pass


async def handle_prefix_command_error(
    ctx: commands.Context, error: commands.CommandError
) -> None:
    """Handle errors raised during prefix or hybrid command invocation."""
    original = getattr(error, "original", error)

    if isinstance(error, commands.CommandNotFound):
        # Ignore unknown prefix triggers silently to avoid spamming chat
        return

    if isinstance(error, commands.MissingRequiredArgument):
        signature = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}" if ctx.command else ""
        emb = make_embed(
            "⚠️ Missing Required Argument",
            f"Missing parameter: **`{error.param.name}`**\nUsage: `{signature.strip()}`",
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb, ephemeral=True)
        return

    if isinstance(error, commands.BadArgument):
        emb = make_embed(
            "⚠️ Invalid Argument",
            str(error) or "One or more arguments could not be parsed. Check `!help <command>`.",
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb, ephemeral=True)
        return

    if isinstance(error, commands.CommandOnCooldown):
        emb = make_embed(
            "⏳ Slow Down",
            f"This command is on cooldown. Try again in **{error.retry_after:.1f}s**.",
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb, ephemeral=True)
        return

    if isinstance(error, commands.NoPrivateMessage):
        emb = make_embed(
            "🏠 Server Only",
            "This command can only be used inside a Discord server.",
            color=discord.Color.red(),
        )
        await ctx.send(embed=emb, ephemeral=True)
        return

    if isinstance(error, (commands.MissingPermissions, commands.BotMissingPermissions, commands.CheckFailure)):
        emb = make_embed(
            "🚫 Access Denied",
            str(error) or "You do not have the required permissions to run this command.",
            color=discord.Color.red(),
        )
        await ctx.send(embed=emb, ephemeral=True)
        return

    logger.error(
        "Command error in %s: %s",
        ctx.command.qualified_name if ctx.command else "unknown",
        original,
        exc_info=True,
    )
    emb = make_embed(
        "⚠️ Command Error",
        f"Could not complete command: `{original}`",
        color=discord.Color.red(),
    )
    await ctx.send(embed=emb, ephemeral=True)
