"""Command Registry & Category Inspector for Project Nova.

Maps loaded Cogs and commands into the 11 official user-facing categories and
verifies that no duplicate or phantom commands are exposed.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from discord.ext import commands

OFFICIAL_CATEGORIES: Tuple[Tuple[str, str, str], ...] = (
    ("Moderation", "🛡️", "Ban, kick, timeout, warn, purge, channel locks, snipe, and AutoMod."),
    ("Tickets", "🎫", "Multi-category support tickets, panels, claiming, closing, and transcripts."),
    ("Administration", "🏛️", "Server announcements, polls, giveaways, temp roles, and config backups."),
    ("Automation", "⚙️", "Keyword autoresponders, welcome/goodbye messages, auto-roles, and schedules."),
    ("Reaction Roles", "🎭", "Interactive button, select-menu, and reaction self-role panels."),
    ("Activity Roles", "🎮", "Automatic role assignment for games, Spotify, streaming, and Rich Presence."),
    ("Voice Channels", "🔊", "Join-to-Create temporary voice rooms and live owner controls."),
    ("Music", "🎵", "Voice music playback, queue controls, volume, loop, and FFmpeg streaming."),
    ("AI Assistant", "🤖", "Optional modular AI assistant with local/custom endpoint and rate limits."),
    ("Utility", "🧰", "Latency, server, user, role, channel, avatar, invite, and custom embed tools."),
    ("Configuration", "🎛️", "Interactive /setup dashboard and centralized RBAC permission controls."),
)

CATEGORY_LOOKUP: Dict[str, str] = {name.lower(): name for name, _, _ in OFFICIAL_CATEGORIES}


class CommandRegistryInspector:
    """Inspects live registered commands on the bot instance."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def get_command_category(self, cmd: commands.Command) -> str:
        cog = cmd.cog
        if cog is not None and hasattr(cog, "CATEGORY"):
            cat = str(getattr(cog, "CATEGORY"))
            if cat in dict((n, n) for n, _, _ in OFFICIAL_CATEGORIES):
                return cat
        return "Utility"

    def get_categorized_commands(self) -> Dict[str, List[commands.Command]]:
        """Return only non-empty categories containing actual registered commands."""
        grouped: Dict[str, List[commands.Command]] = {name: [] for name, _, _ in OFFICIAL_CATEGORIES}
        for cmd in sorted(self.bot.commands, key=lambda c: c.name):
            if cmd.hidden:
                continue
            cat = self.get_command_category(cmd)
            grouped.setdefault(cat, []).append(cmd)
        # Filter out any empty categories so we never display empty categories
        return {k: v for k, v in grouped.items() if v}

    def resolve_category(self, query: str) -> Optional[Tuple[str, List[commands.Command]]]:
        clean = query.strip().lower()
        grouped = self.get_categorized_commands()
        for cat_name, cmds in grouped.items():
            if cat_name.lower() == clean or cat_name.lower().replace(" ", "") == clean.replace(" ", ""):
                return cat_name, cmds
        return None

    def verify_integrity(self) -> Dict[str, int]:
        """Verify prefix and slash command registrations contain no duplicates."""
        prefix_names = [c.name for c in self.bot.commands]
        slash_names = [c.name for c in self.bot.tree.get_commands()]
        if len(prefix_names) != len(set(prefix_names)):
            raise RuntimeError("Duplicate prefix commands detected!")
        if len(slash_names) != len(set(slash_names)):
            raise RuntimeError("Duplicate slash commands detected!")
        return {
            "cogs": len(self.bot.cogs),
            "prefix_commands": len(prefix_names),
            "slash_commands": len(slash_names),
        }
