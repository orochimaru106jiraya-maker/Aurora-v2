"""Centralized RBAC Permissions Management Cog (`!permissions`, `/permissions`)."""

from __future__ import annotations

from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.permission_service import TIER_RANKS, require_tier
from bot.utils.formatting import make_embed


class PermissionsCog(commands.Cog, name="PermissionsCog"):
    """Centralized Role-Based Access Control (RBAC) Configuration Commands."""

    CATEGORY = "Configuration"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(
        name="permissions",
        aliases=["rbac", "perms"],
        description="Configure server RBAC staff tiers, command permissions, and user exceptions.",
        fallback="overview",
    )
    @commands.guild_only()
    @require_tier("administrator")
    async def permissions_group(self, ctx: commands.Context) -> None:
        """Display the server's RBAC staff roles and command permission overrides."""
        assert ctx.guild is not None
        staff_roles = await self.bot.rbac_repo.list_staff_roles(ctx.guild.id)
        rules = await self.bot.rbac_repo.list_permission_rules(ctx.guild.id)

        emb = make_embed(
            f"🔐 RBAC Permission Matrix — {ctx.guild.name}",
            "All Project Nova modules share this centralized Role-Based Access Control system.",
            color=discord.Color.blurple(),
        )

        by_tier = {t: [] for t in ("administrator", "management", "moderator", "support", "custom")}
        for row in staff_roles:
            tier = str(row["tier"]).lower()
            by_tier.setdefault(tier, []).append(f"<@&{row['role_id']}>")

        tier_lines = [
            f"• **{t.title()}:** {', '.join(roles) if roles else '*None configured*'}"
            for t, roles in by_tier.items()
        ]
        emb.add_field(
            name="Staff Role Tiers (Inheritance: Owner > Admin > Management > Moderator > Support > Custom)",
            value="\n".join(tier_lines),
            inline=False,
        )

        if rules:
            rule_lines = []
            for r in rules[:15]:
                allow_r = len(r["allowed_role_ids"])
                deny_r = len(r["denied_role_ids"])
                allow_u = len(r["allowed_user_ids"])
                deny_u = len(r["denied_user_ids"])
                rule_lines.append(
                    f"• **`{r['target_type']}:{r['target_name']}`** → Tier: **{r['required_tier'].title()}** "
                    f"(+Roles:{allow_r} -Roles:{deny_r} +Users:{allow_u} -Users:{deny_u})"
                )
            emb.add_field(
                name=f"Custom Command & Category Overrides ({len(rules)})",
                value="\n".join(rule_lines),
                inline=False,
            )
        else:
            emb.add_field(
                name="Custom Command & Category Overrides",
                value="Using default tier policies. Use `/permissions setcommand` or `/permissions setcategory` to customize.",
                inline=False,
            )
        await ctx.send(embed=emb)

    @permissions_group.command(
        name="addrole",
        description="Assign a Discord role to an RBAC staff tier (administrator, management, moderator, support, custom).",
    )
    @app_commands.describe(
        tier="RBAC tier (administrator, management, moderator, support, custom)",
        role="The Discord role to map to this tier",
    )
    @require_tier("administrator")
    async def add_staff_role(
        self, ctx: commands.Context, tier: str, role: discord.Role
    ) -> None:
        """Map a Discord role to a Project Nova RBAC tier."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        clean_tier = tier.lower().strip()
        valid_tiers = ("administrator", "management", "moderator", "support", "custom")
        if clean_tier not in valid_tiers:
            raise commands.BadArgument(
                f"Invalid tier `{tier}`. Choose from: {', '.join(valid_tiers)}."
            )

        ok, err = self.bot.permission_service.validate_role_assignment(ctx.guild, role, ctx.author)
        if not ok and ctx.author.id != ctx.guild.owner_id:
            raise commands.CheckFailure(err or "Role hierarchy validation failed.")

        await self.bot.rbac_repo.add_staff_role(ctx.guild.id, role.id, clean_tier)
        emb = make_embed(
            "✅ Staff Role Registered",
            f"Assigned {role.mention} to the **{clean_tier.title()}** RBAC tier.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @permissions_group.command(
        name="removerole",
        description="Remove a Discord role from RBAC staff tiers.",
    )
    @app_commands.describe(role="The Discord role to remove from RBAC staff tiers")
    @require_tier("administrator")
    async def remove_staff_role(self, ctx: commands.Context, role: discord.Role) -> None:
        """Remove a role from all RBAC staff tiers."""
        assert ctx.guild is not None
        removed = await self.bot.rbac_repo.remove_staff_role(ctx.guild.id, role.id)
        emb = make_embed(
            "🗑️ Staff Role Removed" if removed else "ℹ️ Role Not Mapped",
            f"Removed {role.mention} from RBAC staff tiers."
            if removed
            else f"{role.mention} was not registered in any RBAC tier.",
            color=discord.Color.green() if removed else discord.Color.orange(),
        )
        await ctx.send(embed=emb)

    @permissions_group.command(
        name="setcommand",
        description="Configure the required RBAC tier for a specific command.",
    )
    @app_commands.describe(
        command_name="Name of the command (e.g., ban, purge, play)",
        required_tier="Required tier (everyone, custom, support, moderator, management, administrator, owner)",
    )
    @require_tier("administrator")
    async def set_command_tier(
        self, ctx: commands.Context, command_name: str, required_tier: str
    ) -> None:
        """Set the required RBAC tier for a specific command."""
        assert ctx.guild is not None
        clean_tier = required_tier.lower().strip()
        if clean_tier not in TIER_RANKS:
            raise commands.BadArgument(
                f"Invalid tier `{required_tier}`. Valid tiers: {', '.join(TIER_RANKS.keys())}."
            )
        target_cmd = self.bot.get_command(command_name.lower().strip())
        if target_cmd is None:
            raise commands.BadArgument(f"Command `{command_name}` does not exist.")

        existing = await self.bot.rbac_repo.get_permission_rule(
            ctx.guild.id, "command", target_cmd.qualified_name
        ) or {}
        await self.bot.rbac_repo.set_permission_rule(
            ctx.guild.id,
            "command",
            target_cmd.qualified_name,
            required_tier=clean_tier,
            allowed_role_ids=existing.get("allowed_role_ids", []),
            denied_role_ids=existing.get("denied_role_ids", []),
            allowed_user_ids=existing.get("allowed_user_ids", []),
            denied_user_ids=existing.get("denied_user_ids", []),
        )
        emb = make_embed(
            "✅ Command Permission Updated",
            f"Command **`{target_cmd.qualified_name}`** now requires the **{clean_tier.title()}** tier.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @permissions_group.command(
        name="setcategory",
        description="Configure the required RBAC tier for an entire command category.",
    )
    @app_commands.describe(
        category_name="Category name (e.g., Moderation, Music, Tickets)",
        required_tier="Required tier (everyone, custom, support, moderator, management, administrator, owner)",
    )
    @require_tier("administrator")
    async def set_category_tier(
        self, ctx: commands.Context, category_name: str, required_tier: str
    ) -> None:
        """Set the required RBAC tier for an entire command category."""
        assert ctx.guild is not None
        clean_tier = required_tier.lower().strip()
        if clean_tier not in TIER_RANKS:
            raise commands.BadArgument(
                f"Invalid tier `{required_tier}`. Valid tiers: {', '.join(TIER_RANKS.keys())}."
            )
        resolved = self.bot.registry_inspector.resolve_category(category_name)
        if resolved is None:
            raise commands.BadArgument(f"Category `{category_name}` was not found.")
        canonical_cat = resolved[0]

        existing = await self.bot.rbac_repo.get_permission_rule(
            ctx.guild.id, "category", canonical_cat
        ) or {}
        await self.bot.rbac_repo.set_permission_rule(
            ctx.guild.id,
            "category",
            canonical_cat,
            required_tier=clean_tier,
            allowed_role_ids=existing.get("allowed_role_ids", []),
            denied_role_ids=existing.get("denied_role_ids", []),
            allowed_user_ids=existing.get("allowed_user_ids", []),
            denied_user_ids=existing.get("denied_user_ids", []),
        )
        emb = make_embed(
            "✅ Category Permission Updated",
            f"Category **`{canonical_cat}`** now requires the **{clean_tier.title()}** tier.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @permissions_group.command(
        name="allowuser",
        description="Grant a specific member an exception to use a command.",
    )
    @app_commands.describe(command_name="Command name", member="Member to allow")
    @require_tier("administrator")
    async def allow_user(
        self, ctx: commands.Context, command_name: str, member: discord.Member
    ) -> None:
        """Add a user-specific allow exception for a command."""
        assert ctx.guild is not None
        target_cmd = self.bot.get_command(command_name.lower().strip())
        if target_cmd is None:
            raise commands.BadArgument(f"Command `{command_name}` does not exist.")
        qname = target_cmd.qualified_name
        existing = await self.bot.rbac_repo.get_permission_rule(ctx.guild.id, "command", qname) or {
            "required_tier": "moderator",
            "allowed_role_ids": [],
            "denied_role_ids": [],
            "allowed_user_ids": [],
            "denied_user_ids": [],
        }
        allowed_users = set(existing["allowed_user_ids"])
        denied_users = set(existing["denied_user_ids"])
        allowed_users.add(member.id)
        denied_users.discard(member.id)

        await self.bot.rbac_repo.set_permission_rule(
            ctx.guild.id,
            "command",
            qname,
            required_tier=existing["required_tier"],
            allowed_role_ids=existing["allowed_role_ids"],
            denied_role_ids=existing["denied_role_ids"],
            allowed_user_ids=sorted(allowed_users),
            denied_user_ids=sorted(denied_users),
        )
        emb = make_embed(
            "✅ User Exception Added",
            f"{member.mention} is now explicitly allowed to run **`{qname}`**.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @permissions_group.command(
        name="denyuser",
        description="Explicitly deny a specific member from using a command.",
    )
    @app_commands.describe(command_name="Command name", member="Member to deny")
    @require_tier("administrator")
    async def deny_user(
        self, ctx: commands.Context, command_name: str, member: discord.Member
    ) -> None:
        """Add a user-specific deny exception for a command."""
        assert ctx.guild is not None
        if member.id == ctx.guild.owner_id:
            raise commands.CheckFailure("Owner protection active: Cannot deny the server owner.")
        target_cmd = self.bot.get_command(command_name.lower().strip())
        if target_cmd is None:
            raise commands.BadArgument(f"Command `{command_name}` does not exist.")
        qname = target_cmd.qualified_name
        existing = await self.bot.rbac_repo.get_permission_rule(ctx.guild.id, "command", qname) or {
            "required_tier": "everyone",
            "allowed_role_ids": [],
            "denied_role_ids": [],
            "allowed_user_ids": [],
            "denied_user_ids": [],
        }
        allowed_users = set(existing["allowed_user_ids"])
        denied_users = set(existing["denied_user_ids"])
        denied_users.add(member.id)
        allowed_users.discard(member.id)

        await self.bot.rbac_repo.set_permission_rule(
            ctx.guild.id,
            "command",
            qname,
            required_tier=existing["required_tier"],
            allowed_role_ids=existing["allowed_role_ids"],
            denied_role_ids=existing["denied_role_ids"],
            allowed_user_ids=sorted(allowed_users),
            denied_user_ids=sorted(denied_users),
        )
        emb = make_embed(
            "🚫 User Deny Rule Added",
            f"{member.mention} is now explicitly denied from running **`{qname}`**.",
            color=discord.Color.orange(),
        )
        await ctx.send(embed=emb)

    @permissions_group.command(
        name="allowrole",
        description="Explicitly allow a Discord role to execute a command.",
    )
    @app_commands.describe(command_name="Command name", role="Role to allow")
    @require_tier("administrator")
    async def allow_role(
        self, ctx: commands.Context, command_name: str, role: discord.Role
    ) -> None:
        """Grant a role explicit access to a specific command."""
        assert ctx.guild is not None
        target_cmd = self.bot.get_command(command_name.lower().strip())
        if target_cmd is None:
            raise commands.BadArgument(f"Command `{command_name}` does not exist.")
        qname = target_cmd.qualified_name
        existing = await self.bot.rbac_repo.get_permission_rule(ctx.guild.id, "command", qname) or {
            "required_tier": "moderator",
            "allowed_role_ids": [],
            "denied_role_ids": [],
            "allowed_user_ids": [],
            "denied_user_ids": [],
        }
        allowed_roles = set(existing["allowed_role_ids"])
        denied_roles = set(existing["denied_role_ids"])
        allowed_roles.add(role.id)
        denied_roles.discard(role.id)

        await self.bot.rbac_repo.set_permission_rule(
            ctx.guild.id,
            "command",
            qname,
            required_tier=existing["required_tier"],
            allowed_role_ids=sorted(allowed_roles),
            denied_role_ids=sorted(denied_roles),
            allowed_user_ids=existing["allowed_user_ids"],
            denied_user_ids=existing["denied_user_ids"],
        )
        emb = make_embed(
            "✅ Role Override Added",
            f"Role {role.mention} is now explicitly allowed to run **`{qname}`**.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @permissions_group.command(
        name="check",
        description="Inspect a member's effective RBAC tier and command access.",
    )
    @app_commands.describe(member="Member to inspect", command_name="Optional command to test")
    @require_tier("support")
    async def check_member_permissions(
        self,
        ctx: commands.Context,
        member: discord.Member,
        command_name: Optional[str] = None,
    ) -> None:
        """Check a member's effective RBAC tier and whether they can run a command."""
        tier = await self.bot.permission_service.get_member_tier(member)
        desc = f"• **Member:** {member.mention}\n• **Effective RBAC Tier:** **{tier.title()}**"
        if command_name:
            cmd = self.bot.get_command(command_name.lower().strip())
            cat = self.bot.registry_inspector.get_command_category(cmd) if cmd else None
            allowed, reason = await self.bot.permission_service.check_command_access(
                member, cmd.qualified_name if cmd else command_name, cat
            )
            status = "✅ Allowed" if allowed else "🚫 Denied"
            desc += f"\n• **Command `{command_name}`:** {status} ({reason})"

        emb = make_embed("🔍 RBAC Permission Inspector", desc, color=discord.Color.blurple())
        await ctx.send(embed=emb)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PermissionsCog(bot))
