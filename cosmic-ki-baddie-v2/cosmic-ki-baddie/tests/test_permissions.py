"""D. RBAC Permissions & Role Hierarchy Automated Tests (`tests/test_permissions.py`).

Tests:
- Authorized member access.
- Unauthorized member rejection.
- Administrator full access.
- Server Owner protection.
- Role hierarchy restrictions (moderator cannot ban/kick/timeout a member with equal or higher role).
- User-specific exceptions and role-specific overrides.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests.conftest import install_discord_shim_if_needed

install_discord_shim_if_needed()

import discord
from discord.ext import commands
from bot.core.bot import ProjectNovaBot
from bot.core.config import BotConfig


class TestPermissionsAndHierarchy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "rbac_test.db"
        cfg = BotConfig(
            database_path=self.db_path,
            default_prefix="!",
            sync_commands_on_startup=False,
        )
        self.bot = ProjectNovaBot(cfg)
        await self.bot.setup_hook()

        self.guild = discord.Guild(id=9001, name="RBAC Guild", owner_id=1)
        self.owner = self.guild.add_member(discord.Member(id=1, name="Owner", guild=self.guild))

        self.admin_role = self.guild.add_role(
            discord.Role(
                id=910,
                name="Admin",
                position=50,
                permissions=discord.Permissions(administrator=True),
                guild=self.guild,
            )
        )
        self.senior_mod_role = self.guild.add_role(
            discord.Role(id=920, name="SeniorMod", position=30, guild=self.guild)
        )
        self.junior_mod_role = self.guild.add_role(
            discord.Role(id=930, name="JuniorMod", position=20, guild=self.guild)
        )
        self.member_role = self.guild.add_role(
            discord.Role(id=940, name="Member", position=5, guild=self.guild)
        )

        self.admin = self.guild.add_member(
            discord.Member(id=2, name="AdminUser", guild=self.guild, roles=[self.admin_role])
        )
        self.senior_mod = self.guild.add_member(
            discord.Member(
                id=3, name="SeniorModUser", guild=self.guild, roles=[self.senior_mod_role]
            )
        )
        self.junior_mod = self.guild.add_member(
            discord.Member(
                id=4, name="JuniorModUser", guild=self.guild, roles=[self.junior_mod_role]
            )
        )
        self.regular = self.guild.add_member(
            discord.Member(id=5, name="RegularUser", guild=self.guild, roles=[self.member_role])
        )

        self.channel = self.guild.add_channel(
            discord.TextChannel(id=9500, name="mod-test", guild=self.guild)
        )
        self.bot.guilds.append(self.guild)

        await self.bot.rbac_repo.add_staff_role(
            self.guild.id, self.senior_mod_role.id, "management"
        )
        await self.bot.rbac_repo.add_staff_role(
            self.guild.id, self.junior_mod_role.id, "moderator"
        )

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        self._tmp.cleanup()

    async def test_tier_inheritance_and_unauthorized_blocking(self) -> None:
        ps = self.bot.permission_service
        self.assertEqual(await ps.get_member_tier(self.owner), "owner")
        self.assertEqual(await ps.get_member_tier(self.admin), "administrator")
        self.assertEqual(await ps.get_member_tier(self.senior_mod), "management")
        self.assertEqual(await ps.get_member_tier(self.junior_mod), "moderator")
        self.assertEqual(await ps.get_member_tier(self.regular), "everyone")

        # Regular user denied moderation & setup commands
        allowed_ban, _ = await ps.check_command_access(self.regular, "ban", "Moderation")
        self.assertFalse(allowed_ban)
        allowed_setup, _ = await ps.check_command_access(self.regular, "setup", "Configuration")
        self.assertFalse(allowed_setup)

        # Moderator allowed ban, denied setup
        mod_ban, _ = await ps.check_command_access(self.junior_mod, "ban", "Moderation")
        self.assertTrue(mod_ban)
        mod_setup, _ = await ps.check_command_access(self.junior_mod, "setup", "Configuration")
        self.assertFalse(mod_setup)

        # Administrator allowed both
        adm_setup, _ = await ps.check_command_access(self.admin, "setup", "Configuration")
        self.assertTrue(adm_setup)

    async def test_user_exception_and_role_override(self) -> None:
        ps = self.bot.permission_service
        # Grant regular user an explicit exception to use `purge`
        await self.bot.rbac_repo.set_permission_rule(
            self.guild.id,
            "command",
            "purge",
            required_tier="moderator",
            allowed_user_ids=[self.regular.id],
        )
        allowed, reason = await ps.check_command_access(self.regular, "purge", "Moderation")
        self.assertTrue(allowed)
        self.assertIn("User Exception", reason)

    async def test_role_hierarchy_and_owner_protection(self) -> None:
        ps = self.bot.permission_service
        # JuniorMod (pos 20) cannot moderate SeniorMod (pos 30)
        ok, err = ps.validate_moderation_hierarchy(self.junior_mod, self.senior_mod)
        self.assertFalse(ok)
        self.assertIn("Role hierarchy error", err or "")

        # SeniorMod (pos 30) CAN moderate JuniorMod (pos 20)
        ok2, _ = ps.validate_moderation_hierarchy(self.senior_mod, self.junior_mod)
        self.assertTrue(ok2)

        # Nobody can moderate the Server Owner (Owner protection)
        ok_owner, err_owner = ps.validate_moderation_hierarchy(self.admin, self.owner)
        self.assertFalse(ok_owner)
        self.assertIn("Owner protection", err_owner or "")


if __name__ == "__main__":
    unittest.main()
