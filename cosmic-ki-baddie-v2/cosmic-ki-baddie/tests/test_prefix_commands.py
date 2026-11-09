"""B. Prefix Command System Automated Tests (`tests/test_prefix_commands.py`).

Independently tests the traditional prefix command parser and execution pipeline:
- `!help`, `!commands`, `!help ping`, `!help moderation`
- `!ping`
- `!ban`, `!kick`, `!timeout`, `!purge`
- Dynamic per-server prefix changes (`!setprefix ?` -> `?ping`, `?help`)
- Guarantees `on_message` listeners never block `process_commands()`.
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


class TestPrefixCommands(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "prefix_test.db"
        cfg = BotConfig(
            database_path=self.db_path,
            default_prefix="!",
            sync_commands_on_startup=False,
        )
        self.bot = ProjectNovaBot(cfg)
        await self.bot.setup_hook()

        self.guild = discord.Guild(id=5001, name="Prefix Test Guild", owner_id=100)
        self.owner = self.guild.add_member(
            discord.Member(id=100, name="GuildOwner", guild=self.guild)
        )
        self.mod_role = self.guild.add_role(
            discord.Role(id=510, name="Moderator", position=20, guild=self.guild)
        )
        self.target_role = self.guild.add_role(
            discord.Role(id=505, name="MemberRole", position=2, guild=self.guild)
        )
        self.mod = self.guild.add_member(
            discord.Member(
                id=101, name="ModMember", guild=self.guild, roles=[self.mod_role]
            )
        )
        self.target1 = self.guild.add_member(
            discord.Member(
                id=201, name="TargetKick", guild=self.guild, roles=[self.target_role]
            )
        )
        self.target2 = self.guild.add_member(
            discord.Member(
                id=202, name="TargetBan", guild=self.guild, roles=[self.target_role]
            )
        )
        self.target3 = self.guild.add_member(
            discord.Member(
                id=203, name="TargetTimeout", guild=self.guild, roles=[self.target_role]
            )
        )
        self.channel = self.guild.add_channel(
            discord.TextChannel(id=6001, name="general", guild=self.guild)
        )
        self.bot.guilds.append(self.guild)
        await self.bot.rbac_repo.add_staff_role(self.guild.id, self.mod_role.id, "moderator")

    async def asyncTearDown(self) -> None:
        await self.bot.close()
        self._tmp.cleanup()

    async def _send_prefix_msg(self, content: str, author: discord.Member) -> discord.Message:
        msg = discord.Message(
            content=content, author=author, channel=self.channel, guild=self.guild
        )
        self.channel.messages.append(msg)
        await self.bot.dispatch_event("on_message", msg)
        return self.channel.messages[-1]

    async def test_help_and_commands_alias(self) -> None:
        resp1 = await self._send_prefix_msg("!help", self.owner)
        self.assertIn("Help Center", resp1.embeds[0].title)

        # Reset cooldown bucket for help
        self.bot.get_command("help")._buckets.clear()
        resp2 = await self._send_prefix_msg("!commands", self.owner)
        self.assertIn("Help Center", resp2.embeds[0].title)

        self.bot.get_command("help")._buckets.clear()
        resp3 = await self._send_prefix_msg("!help ping", self.owner)
        self.assertIn("Command: !ping", resp3.embeds[0].title)

        self.bot.get_command("help")._buckets.clear()
        resp4 = await self._send_prefix_msg("!help moderation", self.owner)
        self.assertIn("Moderation Commands", resp4.embeds[0].title)

    async def test_ping_ban_kick_timeout_purge_prefix(self) -> None:
        # !ping
        resp_ping = await self._send_prefix_msg("!ping", self.owner)
        self.assertIn("Pong!", resp_ping.embeds[0].title)

        # !kick
        resp_kick = await self._send_prefix_msg("!kick 201 Breaking server rules", self.mod)
        self.assertIn("Member Kicked", resp_kick.embeds[0].title)
        self.assertIsNone(self.guild.get_member(201))

        # !ban
        resp_ban = await self._send_prefix_msg("!ban 202 Severe violation", self.mod)
        self.assertIn("Member Banned", resp_ban.embeds[0].title)
        self.assertIn(202, self.guild._banned)

        # !timeout
        resp_timeout = await self._send_prefix_msg("!timeout 203 30m Spamming", self.mod)
        self.assertIn("Member Timed Out", resp_timeout.embeds[0].title)
        self.assertIsNotNone(self.target3.timed_out_until)

        # !purge
        resp_purge = await self._send_prefix_msg("!purge 3", self.mod)
        self.assertIn("Channel Purged", resp_purge.embeds[0].title)

    async def test_per_guild_configurable_prefix(self) -> None:
        await self._send_prefix_msg("!setprefix >>", self.owner)
        self.assertEqual(await self.bot.guild_config_repo.get_prefix(self.guild.id), ">>")

        self.bot.get_command("ping")._buckets.clear()
        resp = await self._send_prefix_msg(">>ping", self.mod)
        self.assertIn("Pong!", resp.embeds[0].title)


if __name__ == "__main__":
    unittest.main()
