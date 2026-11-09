"""Centralized Role-Based Access Control (RBAC) & Hierarchy Validation Service."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import discord
from discord.ext import commands

from bot.database.repositories import RBACRepository

# Tier hierarchy ordered from lowest (0) to highest (6)
TIER_RANKS: Dict[str, int] = {
    "everyone": 0,
    "custom": 1,
    "support": 2,
    "moderator": 3,
    "management": 4,
    "administrator": 5,
    "owner": 6,
}

# Default required tier per category if no explicit override is configured
DEFAULT_CATEGORY_TIERS: Dict[str, str] = {
    "Utility": "everyone",
    "Music": "everyone",
    "AI Assistant": "everyone",
    "Voice Channels": "everyone",
    "Tickets": "everyone",
    "Moderation": "moderator",
    "Reaction Roles": "management",
    "Activity Roles": "management",
    "Automation": "management",
    "Administration": "administrator",
    "Configuration": "administrator",
}

# Default command-level overrides (e.g., ticket admin commands vs user ticket commands)
DEFAULT_COMMAND_TIERS: Dict[str, str] = {
    "help": "everyone",
    "ping": "everyone",
    "serverinfo": "everyone",
    "userinfo": "everyone",
    "avatar": "everyone",
    "roleinfo": "everyone",
    "botinfo": "everyone",
    "inviteinfo": "everyone",
    "channelinfo": "everyone",
    "play": "everyone",
    "pause": "everyone",
    "resume": "everyone",
    "skip": "everyone",
    "stop": "everyone",
    "queue": "everyone",
    "nowplaying": "everyone",
    "volume": "everyone",
    "loop": "everyone",
    "shuffle": "everyone",
    "leave": "everyone",
    "ask": "everyone",
    "vc": "everyone",
    "snipe": "moderator",
    "warn": "moderator",
    "warnings": "support",
    "clearwarnings": "moderator",
    "timeout": "moderator",
    "untimeout": "moderator",
    "kick": "moderator",
    "ban": "moderator",
    "unban": "moderator",
    "purge": "moderator",
    "slowmode": "moderator",
    "lock": "moderator",
    "unlock": "moderator",
    "modlogs": "moderator",
    "automod": "management",
    "ticket": "management",
    "setup": "administrator",
    "permissions": "administrator",
    "jtc": "management",
    "activityrole": "management",
    "reactionrole": "management",
    "autoresponder": "management",
    "welcome": "management",
    "goodbye": "management",
    "autorole": "management",
    "schedule": "management",
    "embed": "management",
    "announce": "management",
    "poll": "moderator",
    "giveaway": "management",
    "temprole": "management",
    "backup": "administrator",
    "setprefix": "administrator",
    "setlang": "administrator",
    "logging": "administrator",
    "ai": "administrator",
}


class PermissionService:
    """Single source of truth for RBAC permissions and role hierarchy checks across all Cogs."""

    def __init__(self, rbac_repo: RBACRepository, bot_owner_ids: Optional[set[int]] = None) -> None:
        self.rbac_repo = rbac_repo
        self.bot_owner_ids: set[int] = set(bot_owner_ids or set())

    async def get_member_tier(self, member: discord.Member) -> str:
        """Resolve the highest effective RBAC tier for `member` with inheritance."""
        guild = member.guild
        if guild is None:
            return "everyone"
        if member.id in self.bot_owner_ids or guild.owner_id == member.id:
            return "owner"
        if member.guild_permissions.administrator:
            return "administrator"

        highest_rank = 0
        # Check built-in Discord permissions as baseline fallbacks
        if member.guild_permissions.manage_guild:
            highest_rank = max(highest_rank, TIER_RANKS["management"])
        elif (
            member.guild_permissions.ban_members
            or member.guild_permissions.kick_members
            or member.guild_permissions.moderate_members
            or member.guild_permissions.manage_messages
        ):
            highest_rank = max(highest_rank, TIER_RANKS["moderator"])

        # Check database-configured RBAC staff roles
        staff_rows = await self.rbac_repo.list_staff_roles(guild.id)
        member_role_ids = {r.id for r in getattr(member, "roles", [])}
        for row in staff_rows:
            if int(row["role_id"]) in member_role_ids:
                tier_name = str(row["tier"]).lower()
                highest_rank = max(highest_rank, TIER_RANKS.get(tier_name, 0))

        for name, rank in TIER_RANKS.items():
            if rank == highest_rank:
                return name
        return "everyone"

    async def has_tier(self, member: discord.Member, required_tier: str) -> bool:
        """Return True if `member`'s effective tier is >= `required_tier`."""
        member_tier = await self.get_member_tier(member)
        return TIER_RANKS.get(member_tier, 0) >= TIER_RANKS.get(required_tier.lower(), 0)

    async def check_command_access(
        self,
        member: discord.Member,
        command_name: str,
        category_name: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Evaluate whether `member` is authorized to execute `command_name`.

        Evaluation order:
        1. Server Owner / Bot Owner -> Always allowed (owner protection).
        2. Server Administrator -> Always allowed unless command is strictly owner-only.
        3. Command-specific DB rule -> User exception (deny/allow) -> Role override (deny/allow) -> Required tier.
        4. Category-level DB rule -> User exception (deny/allow) -> Role override (deny/allow) -> Required tier.
        5. Default command/category tier mapping.
        """
        if not isinstance(member, discord.Member) or member.guild is None:
            # In DMs, allow basic utility/help commands
            base_cmd = command_name.split()[0].lower()
            if base_cmd in ("help", "ping", "botinfo"):
                return True, "Allowed in DM"
            return False, "This command can only be used inside a server."

        guild = member.guild
        member_tier = await self.get_member_tier(member)
        member_rank = TIER_RANKS.get(member_tier, 0)

        # 1. Server Owner / Bot Owner always allowed
        if member_tier == "owner":
            return True, "Authorized (Owner)"

        base_cmd = command_name.split()[0].lower()
        full_cmd = command_name.lower()
        member_role_ids = {r.id for r in getattr(member, "roles", [])}

        # Lookup command-specific rule (first full qualified name, then root command name)
        rule = await self.rbac_repo.get_permission_rule(guild.id, "command", full_cmd)
        if rule is None and full_cmd != base_cmd:
            rule = await self.rbac_repo.get_permission_rule(guild.id, "command", base_cmd)

        # Lookup category-level rule if no command rule exists
        if rule is None and category_name:
            rule = await self.rbac_repo.get_permission_rule(guild.id, "category", category_name.lower())

        if rule is not None:
            # User-specific deny/allow exceptions (administrators bypass unless explicitly denied by owner)
            if member.id in rule["denied_user_ids"] and member_tier != "administrator":
                return False, f"You are explicitly denied access to `{command_name}`."
            if member.id in rule["allowed_user_ids"]:
                return True, "Authorized (User Exception)"

            # Role-specific deny/allow exceptions
            if member_tier != "administrator":
                if member_role_ids.intersection(set(rule["denied_role_ids"])):
                    return False, f"One of your roles is denied access to `{command_name}`."
            if member_role_ids.intersection(set(rule["allowed_role_ids"])):
                return True, "Authorized (Role Override)"

            req_tier = str(rule.get("required_tier", "everyone")).lower()
            req_rank = TIER_RANKS.get(req_tier, 0)
            if member_rank >= req_rank:
                return True, f"Authorized ({member_tier} >= {req_tier})"
            return (
                False,
                f"Command `{command_name}` requires **{req_tier.title()}** permission tier (your tier: **{member_tier.title()}**).",
            )

        # 2. Server Administrator allowed for all default commands
        if member_tier == "administrator":
            return True, "Authorized (Administrator)"

        # 5. Default command / category tier fallback
        req_tier = DEFAULT_COMMAND_TIERS.get(full_cmd) or DEFAULT_COMMAND_TIERS.get(base_cmd)
        if req_tier is None and category_name:
            req_tier = DEFAULT_CATEGORY_TIERS.get(category_name, "everyone")
        req_tier = req_tier or "everyone"
        req_rank = TIER_RANKS.get(req_tier, 0)

        if member_rank >= req_rank:
            return True, f"Authorized ({member_tier})"
        return (
            False,
            f"You need **{req_tier.title()}** permissions to use `{command_name}`.",
        )

    def validate_moderation_hierarchy(
        self, actor: discord.Member, target: discord.Member
    ) -> Tuple[bool, Optional[str]]:
        """Validate Discord role hierarchy & owner protection for moderation actions."""
        guild = actor.guild
        if actor.id == target.id:
            return False, "You cannot perform this moderation action on yourself."
        if guild.owner_id == target.id or target.id in self.bot_owner_ids:
            return False, "Owner protection active: You cannot moderate the server/bot owner."
        if guild.me and target.id == guild.me.id:
            return False, "I cannot moderate myself."
        if actor.id != guild.owner_id and actor.id not in self.bot_owner_ids:
            if actor.top_role <= target.top_role:
                return (
                    False,
                    f"Role hierarchy error: Your highest role ({actor.top_role.mention}) must be strictly above {target.mention}'s highest role ({target.top_role.mention}).",
                )
        if guild.me and guild.me.top_role <= target.top_role:
            return (
                False,
                f"Bot hierarchy error: My highest role ({guild.me.top_role.mention}) must be strictly above {target.mention}'s highest role ({target.top_role.mention}).",
            )
        return True, None

    def validate_role_assignment(
        self, guild: discord.Guild, role: discord.Role, actor: Optional[discord.Member] = None
    ) -> Tuple[bool, Optional[str]]:
        """Verify that a role can be safely assigned by the bot and (optionally) actor."""
        if role.is_default():
            return False, "Cannot assign or remove the `@everyone` default role."
        if guild.me and guild.me.top_role <= role:
            return (
                False,
                f"My highest role ({guild.me.top_role.mention}) must be strictly above {role.mention} to manage it.",
            )
        if actor is not None and actor.id != guild.owner_id and actor.id not in self.bot_owner_ids:
            if actor.top_role <= role:
                return (
                    False,
                    f"Your highest role ({actor.top_role.mention}) must be strictly above {role.mention} to configure or assign it.",
                )
        return True, None


def require_tier(tier: str):
    """Decorator for hybrid/prefix commands enforcing centralized RBAC tier + command overrides."""

    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            raise commands.NoPrivateMessage("This command can only be used inside a server.")
        perm_service: PermissionService = ctx.bot.permission_service
        cmd_name = ctx.command.qualified_name if ctx.command else "unknown"
        cat_name = getattr(ctx.cog, "CATEGORY", None) or (ctx.cog.qualified_name if ctx.cog else None)
        allowed, reason = await perm_service.check_command_access(ctx.author, cmd_name, cat_name)
        if not allowed:
            raise commands.CheckFailure(reason)
        # Also verify explicit minimum tier if no custom rule lowered it
        rule = await perm_service.rbac_repo.get_permission_rule(ctx.guild.id, "command", cmd_name.lower())
        if rule is None:
            has_min = await perm_service.has_tier(ctx.author, tier)
            if not has_min:
                raise commands.CheckFailure(
                    f"This command requires at least **{tier.title()}** permissions."
                )
        return True

    return commands.check(predicate)
