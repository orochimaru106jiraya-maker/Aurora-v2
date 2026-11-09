"""Entry point for Cosmic ki baddie V2 (Project Nova).

Usage:
    python main.py              # Start the Discord bot in production
    python main.py --self-test  # Run offline startup, DB migration & Cog verification without connecting to Gateway
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from bot import __bot_name__, __internal_name__, __version__
from bot.core.bot import ProjectNovaBot
from bot.core.config import BotConfig


def configure_logging(level_name: str = "INFO") -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


async def run_self_test(config: BotConfig) -> int:
    """Verify database initialization, migrations, and all Cog registrations."""
    logger = logging.getLogger("project_nova.main")
    logger.info("Running pre-flight self-test for %s (%s v%s)...", __bot_name__, __internal_name__, __version__)
    config.sync_commands_on_startup = False
    bot = ProjectNovaBot(config)
    try:
        await bot.setup_hook()
        stats = bot.registry_inspector.verify_integrity()
        logger.info(
            "Self-test PASSED: %d Cogs loaded, %d prefix commands, %d slash commands verified.",
            stats["cogs"],
            stats["prefix_commands"],
            stats["slash_commands"],
        )
        return 0
    finally:
        await bot.close()


async def run_bot(config: BotConfig) -> int:
    logger = logging.getLogger("project_nova.main")
    if not config.discord_token:
        logger.error(
            "DISCORD_TOKEN is not set in environment or .env file. "
            "Copy .env.example to .env and configure your bot token."
        )
        return 1

    logger.info("Starting %s (%s v%s)...", __bot_name__, __internal_name__, __version__)
    bot = ProjectNovaBot(config)
    try:
        async with bot:
            await bot.start(config.discord_token, reconnect=True)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal.")
    finally:
        if not bot._closed if hasattr(bot, "_closed") else not bot.is_closed():
            await bot.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Cosmic ki baddie V2 (Project Nova) Discord Bot")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Initialize database, run migrations, load all Cogs, and verify command registry without connecting to Discord.",
    )
    args = parser.parse_args()

    config = BotConfig.from_env()
    configure_logging(config.log_level)

    if args.self_test:
        return asyncio.run(run_self_test(config))
    return asyncio.run(run_bot(config))


if __name__ == "__main__":
    raise SystemExit(main())
