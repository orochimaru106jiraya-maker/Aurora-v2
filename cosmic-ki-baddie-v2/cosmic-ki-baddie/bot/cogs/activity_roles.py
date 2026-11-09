"""Activity-Based Role System (`bot/cogs/activity_roles.py`).

Detects Rich Presence activities exposed by Discord's Gateway API (`Presences` intent):
- Games (`playing`)
- Spotify (`spotify`)
- Streaming (`streaming`)
- Other Rich Presence activities (`listening`, `watching`, `competing`)
- All-activity role (`all`)
Supports automatic role assignment, automatic removal when activity stops,
optional temporary role duration, and role hierarchy validation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands

from bot.services.permission_service import require_tier
from bot.utils.formatting import format_duration, make_embed, parse_duration

logger = logging.getLogger("project_nova.cogs.activity_roles")

SUPPORTED_ACTIVITY_TYPES = (
    "all",
    "playing",
    "spotify",
    "streaming",
    "listening",
    "watching",
    "competing",
)


class ActivityRolesCog(commands.Cog, name="ActivityRolesCog"):
    """Automatic Rich Presence Activity Role Management."""

    CATEGORY = "Activity Roles"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _matches_rule(
        self, activities: tuple[discord.BaseActivity, ...], rule: Dict[str, Any]
    ) -> bool:
        """Check whether a member's current Discord Rich Presence activities match `rule`."""
        non_custom = [
            a for a in activities if getattr(a, "type", None) != discord.ActivityType.custom
        ]
        if not non_custom:
            return False

        rtype = str(rule["activity_type"]).lower()
        match_sub = (rule.get("activity_match") or "").strip().lower()

        for act in non_custom:
            act_name = (getattr(act, "name", "") or "").lower()
            act_type = getattr(act, "type", None)

            if rtype == "all":
                if not match_sub or match_sub in act_name:
                    return True
            elif rtype == "spotify":
                is_spot = isinstance(act, discord.Spotify) or (
                    act_type == discord.ActivityType.listening and "spotify" in act_name
                )
                if is_spot:
                    title_artist = f"{getattr(act, 'title', '')} {getattr(act, 'artist', '')}".lower()
                    if not match_sub or match_sub in act_name or match_sub in title_artist:
                        return True
            elif rtype == "playing" and act_type == discord.ActivityType.playing:
                if not match_sub or match_sub in act_name:
                    return True
            elif rtype == "streaming" and act_type == discord.ActivityType.streaming:
                if not match_sub or match_sub in act_name:
                    return True
            elif rtype == "listening" and act_type == discord.ActivityType.listening:
                if not match_sub or match_sub in act_name:
                    return True
            elif rtype == "watching" and act_type == discord.ActivityType.watching:
                if not match_sub or match_sub in act_name:
                    return True
            elif rtype == "competing" and act_type == discord.ActivityType.competing:
                if not match_sub or match_sub in act_name:
                    return True
        return False

    async def evaluate_member_activities(self, member: discord.Member) -> None:
        """Evaluate all configured activity role rules for `member` and assign/remove roles."""
        if member.bot or member.guild is None:
            return
        guild = member.guild
        rules = await self.bot.activity_repo.list_rules(guild.id)
        if not rules:
            return

        activities = getattr(member, "activities", ()) or ()
        for rule in rules:
            role = guild.get_role(int(rule["role_id"]))
            if role is None:
                continue
            ok, _ = self.bot.permission_service.validate_role_assignment(guild, role)
            if not ok:
                continue

            matched = self._matches_rule(activities, rule)
            has_role = role in member.roles

            if matched and not has_role:
                try:
                    await member.add_roles(
                        role, reason=f"Activity Role Rule #{rule['rule_id']} ({rule['activity_type']})"
                    )
                    dur = int(rule.get("temp_duration_sec") or 0)
                    expires_iso: Optional[str] = None
                    if dur > 0:
                        exp_dt = datetime.now(timezone.utc) + timedelta(seconds=dur)
                        expires_iso = exp_dt.strftime("%Y-%m-%d %H:%M:%S")
                        await self.bot.mod_repo.add_temp_role(
                            guild.id,
                            member.id,
                            role.id,
                            expires_iso,
                            reason=f"Activity Role #{rule['rule_id']}",
                        )
                    await self.bot.activity_repo.record_grant(
                        guild.id, member.id, role.id, int(rule["rule_id"]), expires_iso
                    )
                except Exception as exc:
                    logger.debug("Could not grant activity role %s to %s: %s", role.id, member.id, exc)
            elif not matched and has_role and bool(rule.get("remove_on_stop", 1)):
                try:
                    await member.remove_roles(
                        role, reason=f"Activity stopped (Rule #{rule['rule_id']})"
                    )
                    await self.bot.activity_repo.remove_grant(guild.id, member.id, role.id)
                except Exception as exc:
                    logger.debug("Could not remove activity role %s from %s: %s", role.id, member.id, exc)

    @commands.Cog.listener()
    async def on_presence_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        """Listen for Discord Rich Presence changes and update activity roles."""
        await self.evaluate_member_activities(after)

    @commands.hybrid_group(
        name="activityrole",
        aliases=["arole", "activityroles"],
        description="Configure automatic roles based on Discord Rich Presence activities (Games, Spotify, Streaming).",
        fallback="list",
    )
    @commands.guild_only()
    @require_tier("management")
    async def activityrole_group(self, ctx: commands.Context) -> None:
        """List all configured activity-based role rules for this server."""
        assert ctx.guild is not None
        rules = await self.bot.activity_repo.list_rules(ctx.guild.id)
        if not rules:
            emb = make_embed(
                "🎮 Activity Role Rules",
                (
                    "No activity role rules are configured for this server.\n"
                    "Use `/activityrole add` to assign roles for **Games (`playing`)**, **Spotify (`spotify`)**, "
                    "**Streaming (`streaming`)**, or **All Rich Presence Activities (`all`)**.\n\n"
                    "*Note: Only activities exposed by Discord's Rich Presence API (with Presence Intent enabled) can be detected.*"
                ),
                color=discord.Color.blurple(),
            )
            await ctx.send(embed=emb)
            return

        lines = []
        for r in rules:
            match_str = f" matching `{r['activity_match']}`" if r.get("activity_match") else ""
            dur_str = (
                f" | Temp: `{format_duration(r['temp_duration_sec'])}`"
                if int(r.get("temp_duration_sec") or 0) > 0
                else ""
            )
            rem_str = "Auto-remove on stop" if r.get("remove_on_stop") else "Keep on stop"
            lines.append(
                f"• **`#{r['rule_id']}`** Type: **`{r['activity_type']}`**{match_str} → <@&{r['role_id']}> ({rem_str}{dur_str})"
            )
        emb = make_embed(
            f"🎮 Activity Role Rules — {ctx.guild.name} ({len(rules)})",
            "\n".join(lines),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=emb)

    @activityrole_group.command(
        name="add",
        description="Add an activity-based role rule (all, playing, spotify, streaming, listening, watching).",
    )
    @app_commands.describe(
        activity_type="Activity type (all, playing, spotify, streaming, listening, watching, competing)",
        role="Discord role to grant when the activity is active",
        activity_match="Optional game/title keyword to match (use '*' for any)",
        duration="Optional temporary role duration (e.g. 0s, 30m, 2h)",
        remove_on_stop="Remove the role automatically when the activity stops",
    )
    @require_tier("management")
    async def add_rule(
        self,
        ctx: commands.Context,
        activity_type: str,
        role: discord.Role,
        activity_match: str = "*",
        duration: str = "0s",
        remove_on_stop: bool = True,
    ) -> None:
        """Create a new activity role rule after validating role hierarchy."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        clean_type = activity_type.lower().strip()
        if clean_type not in SUPPORTED_ACTIVITY_TYPES:
            raise commands.BadArgument(
                f"Unsupported activity type `{activity_type}`. Supported: {', '.join(SUPPORTED_ACTIVITY_TYPES)}."
            )

        ok, err = self.bot.permission_service.validate_role_assignment(ctx.guild, role, ctx.author)
        if not ok:
            raise commands.CheckFailure(err or "Role hierarchy validation failed.")

        dur_sec = parse_duration(duration) or 0 if duration.strip() not in ("0", "0s") else 0
        match_val = None if activity_match.strip() in ("*", "", "any", "all") else activity_match.strip()

        rule_id = await self.bot.activity_repo.add_rule(
            ctx.guild.id,
            clean_type,
            role.id,
            activity_match=match_val,
            remove_on_stop=remove_on_stop,
            temp_duration_sec=dur_sec,
        )
        emb = make_embed(
            f"✅ Activity Role Rule #{rule_id} Created",
            (
                f"• **Activity Type:** `{clean_type}`\n"
                f"• **Keyword Filter:** `{match_val or 'Any'}`\n"
                f"• **Role:** {role.mention}\n"
                f"• **Remove When Stopped:** `{'Yes' if remove_on_stop else 'No'}`\n"
                f"• **Max Duration:** `{format_duration(dur_sec) if dur_sec > 0 else 'While Active'}`"
            ),
            color=discord.Color.green(),
        )
        await ctx.send(embed=emb)

    @activityrole_group.command(
        name="remove",
        description="Remove an activity role rule by its rule ID.",
    )
    @app_commands.describe(rule_id="The numeric rule ID from /activityrole list")
    @require_tier("management")
    async def remove_rule(self, ctx: commands.Context, rule_id: int) -> None:
        """Delete an activity role rule."""
        assert ctx.guild is not None
        deleted = await self.bot.activity_repo.remove_rule(ctx.guild.id, rule_id)
        emb = make_embed(
            "🗑️ Activity Rule Removed" if deleted else "❓ Rule Not Found",
            f"Deleted activity role rule **`#{rule_id}`**."
            if deleted
            else f"No activity role rule with ID `#{rule_id}` exists.",
            color=discord.Color.green() if deleted else discord.Color.orange(),
        )
        await ctx.send(embed=emb)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ActivityRolesCog(bot))
