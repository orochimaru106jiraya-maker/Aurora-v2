"""C. Slash Command System Automated Tests (`tests/test_slash_commands.py`).

Independently tests registered Application Commands on `bot.tree`:
- `/help`, `/help command:ping`, `/help command:moderation`
- `/ping`
- `/ban`, `/kick`, `/timeout`, `/purge`
- `/setup`
- Other registered application commands across Cogs.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests.conftest import install_discord_shim_if_needed

install_discord_shim_if_needed()

import discord
from bot.core.bot import ProjectNovaBot
from bot.core.config import BotConfig


class TestSlashCommands(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "slash_test.db"
        cfg = BotConfig(
            database_path=self.db_path,
            default_prefix="!",
            sync_commands_on_startup=True,
        )
        self.bot = ProjectNovaBot(cfg)
        await self.bot.setup_hook()

        self.guild = discord.Guild(id=7001, name="Slash Test Guild", owner_id=100)
        self.owner = self.guild.add_member(
            discord.Member(id=100, name="GuildOwner", guild=self.guild)
        )
        self.mod_role = self.guild.add_role(
            discord.Role(id=710, name="Mod", position=25, guild=self.guild)
        )
        self.low_role = self.guild.add_role(
            discord.Role(id=705, name="User", position=2, guild=self.guild)
        )
        self.mod = self.guild.add_member(
            discord.Member(id=101, name="SlashMod", guild=self.guild, roles=[self.mod_role])
        )
        self.target_ban = self.guild.add_member(
            discord.Member(id=301, name="SlashBanUser", guild=self.guild, roles=[self.low_role])
        )
        self.target_kick = self.guild.add_member(
            discord.Member(id=302, name="SlashKickUser", guild=self.guild, roles=[self.low_role])
        )
        self.target_timeout = self.guild.add_member(
            discord.Member(
                id=303, name="SlashTimeoutUser", guild=self.guild, roles=[self.low_role]
            )
        )
        self.channel = self.guild.add_channel(
            discord.TextChannel(id=8001, name="slash-general", guild=self.guild)
        )
        self.bot.guilds.append(self.guild)
        await self.bot.rbac_repo.add_staff_role(self.guild.id, self.mod_role.id, "moderator")

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        self._tmp.cleanup()

    async def _invoke_slash(
        self, cmd_name: str, user: discord.Member, **kwargs
    ) -> discord.Message:
        app_cmd = self.bot.tree.get_command(cmd_name)
        self.assertIsNotNone(app_cmd, f"Slash command /{cmd_name} is not registered in tree")
        inter = discord.Interaction(
            client=self.bot,
            guild=self.guild,
            channel=self.channel,
            user=user,
            command=app_cmd,
        )
        await app_cmd._invoke(inter, **kwargs)
        return inter.sent_messages[-1]

    async def test_slash_help_and_ping(self) -> None:
        msg_ping = await self._invoke_slash("ping", self.owner)
        self.assertIn("Pong!", msg_ping.embeds[0].title)

        msg_help = await self._invoke_slash("help", self.owner)
        self.assertIn("Help Center", msg_help.embeds[0].title)

        self.bot.get_command("help")._buckets.clear()
        msg_help_cmd = await self._invoke_slash("help", self.owner, command="ban")
        self.assertIn("Command: !ban", msg_help_cmd.embeds[0].title)

    async def test_slash_moderation_and_setup(self) -> None:
        # /ban
        msg_ban = await self._invoke_slash(
            "ban", self.mod, member=self.target_ban, reason="Slash ban test"
        )
        self.assertIn("Member Banned", msg_ban.embeds[0].title)
        self.assertIn(301, self.guild._banned)

        # /kick
        msg_kick = await self._invoke_slash(
            "kick", self.mod, member=self.target_kick, reason="Slash kick test"
        )
        self.assertIn("Member Kicked", msg_kick.embeds[0].title)

        # /timeout
        msg_to = await self._invoke_slash(
            "timeout",
            self.mod,
            member=self.target_timeout,
            duration="20m",
            reason="Slash timeout test",
        )
        self.assertIn("Member Timed Out", msg_to.embeds[0].title)
        self.assertIsNotNone(self.target_timeout.timed_out_until)

        # /purge
        msg_purge = await self._invoke_slash("purge", self.mod, amount=2)
        self.assertIn("Channel Purged", msg_purge.embeds[0].title)

        # /setup
        msg_setup = await self._invoke_slash("setup", self.owner)
        self.assertIn("Project Nova Setup Dashboard", msg_setup.embeds[0].title)


if __name__ == "__main__":
    unittest.main()
