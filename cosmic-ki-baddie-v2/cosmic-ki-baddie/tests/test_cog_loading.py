"""A. Startup & Cog Loading Automated Tests (`tests/test_cog_loading.py`).

Verifies:
- Bot initializes cleanly.
- Database connects and executes all versioned migrations.
- Every Cog loads once without extension-loading errors.
- No duplicate prefix or slash command registrations.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest

from tests.conftest import install_discord_shim_if_needed

install_discord_shim_if_needed()

from bot.core.bot import ProjectNovaBot
from bot.core.config import BotConfig
from bot.core.loader import COG_EXTENSIONS


class TestStartupAndCogLoading(unittest.IsolatedAsyncioTestCase):
    async def test_startup_migrations_and_all_cogs_load_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "startup_test.db"
            cfg = BotConfig(
                database_path=db_path,
                default_prefix="!",
                sync_commands_on_startup=True,
            )
            bot = ProjectNovaBot(cfg)
            try:
                await bot.setup_hook()

                # 1. Database connected and all 6 migrations applied
                self.assertTrue(bot.db.is_connected)
                migrations = await bot.db.fetchall(
                    "SELECT version, description FROM schema_migrations ORDER BY version;"
                )
                self.assertEqual([m["version"] for m in migrations], [1, 2, 3, 4, 5, 6])

                # 2. Every Cog extension loaded exactly once
                self.assertEqual(len(bot.extensions), len(COG_EXTENSIONS))
                self.assertEqual(len(bot.cogs), 14)

                # 3. Attempting to call load_all again does not duplicate Cogs or raise errors
                second_load = await bot.cog_loader.load_all()
                self.assertEqual(second_load, [])
                self.assertEqual(len(bot.cogs), 14)

                # 4. Command registry integrity check passes with zero duplicates
                stats = bot.registry_inspector.verify_integrity()
                self.assertEqual(stats["cogs"], 14)
                self.assertGreaterEqual(stats["prefix_commands"], 35)
                self.assertGreaterEqual(stats["slash_commands"], 35)

                # 5. All 11 official categories are populated and non-empty
                grouped = bot.registry_inspector.get_categorized_commands()
                self.assertEqual(len(grouped), 11)
            finally:
                await bot.close()


if __name__ == "__main__":
    unittest.main()
