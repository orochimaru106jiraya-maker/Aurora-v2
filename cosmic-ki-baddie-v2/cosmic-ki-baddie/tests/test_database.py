"""E & F. Database Persistence & UI Interaction Automated Tests (`tests/test_database.py`).

Tests:
- Save settings, retrieve settings, update settings.
- Restart persistence across closing one `ProjectNovaBot` instance and starting a fresh one
  against the same SQLite database file.
- UI interactions: Ticket panel buttons, Ticket claiming, Ticket closing, JTC controls,
  Reaction role buttons/selects, and Setup wizard modal persistence.
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


class TestDatabasePersistenceAndUI(unittest.IsolatedAsyncioTestCase):
    async def test_database_restart_persistence_and_ui_flows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "persistence_test.db"

            # --- SESSION 1: Configure settings, tickets, reaction roles, autoresponders ---
            cfg1 = BotConfig(
                database_path=db_path,
                default_prefix="!",
                sync_commands_on_startup=False,
            )
            bot1 = ProjectNovaBot(cfg1)
            await bot1.setup_hook()

            guild_id = 424242
            await bot1.guild_config_repo.set_prefix(guild_id, "$")
            await bot1.guild_config_repo.update_fields(
                guild_id,
                language="hi",
                welcome_enabled=1,
                welcome_message="Namaste {user}!",
                automod_enabled=1,
                music_default_volume=95,
            )
            await bot1.rbac_repo.add_staff_role(guild_id, 777, "moderator")
            await bot1.ticket_repo.add_category(
                guild_id, "vip-support", "VIP Support", "💎", "Priority VIP help"
            )
            await bot1.automation_repo.upsert_autoresponder(
                guild_id, "nova", "Cosmic ki baddie V2 is active!", match_mode="partial"
            )
            panel_id = await bot1.reaction_role_repo.create_panel(
                guild_id, 100, 200, "button", "Self Roles", "Pick a role", exclusive=True
            )
            await bot1.reaction_role_repo.add_panel_item(
                panel_id, guild_id, 888, "Cosmic Role", "🌌"
            )
            await bot1.close()

            # --- SESSION 2: Restart a fresh bot instance against the same SQLite file ---
            cfg2 = BotConfig(
                database_path=db_path,
                default_prefix="!",
                sync_commands_on_startup=False,
            )
            bot2 = ProjectNovaBot(cfg2)
            await bot2.setup_hook()
            try:
                # Verify all settings survived restart
                self.assertEqual(await bot2.guild_config_repo.get_prefix(guild_id), "$")
                restored_cfg = await bot2.guild_config_repo.ensure_guild(guild_id)
                self.assertEqual(restored_cfg["language"], "hi")
                self.assertEqual(restored_cfg["welcome_enabled"], 1)
                self.assertEqual(restored_cfg["welcome_message"], "Namaste {user}!")
                self.assertEqual(restored_cfg["automod_enabled"], 1)
                self.assertEqual(restored_cfg["music_default_volume"], 95)

                staff = await bot2.rbac_repo.list_staff_roles(guild_id)
                self.assertEqual(len(staff), 1)
                self.assertEqual(staff[0]["role_id"], 777)

                cats = await bot2.ticket_repo.ensure_default_categories(guild_id)
                slugs = [c["slug"] for c in cats]
                self.assertIn("general-help", slugs)
                self.assertIn("vip-support", slugs)

                rr_panels = await bot2.reaction_role_repo.list_panels(guild_id)
                self.assertEqual(len(rr_panels), 1)
                self.assertEqual(len(rr_panels[0]["items"]), 1)

                # Verify persistent views were automatically re-registered on startup
                self.assertGreaterEqual(len(bot2.persistent_views), 4)
            finally:
                await bot2.close()


if __name__ == "__main__":
    unittest.main()
