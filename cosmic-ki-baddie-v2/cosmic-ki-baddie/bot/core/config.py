"""Configuration management for Project Nova (Cosmic ki baddie V2)."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Optional, Set

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


@dataclass
class BotConfig:
    """Strongly-typed runtime configuration loaded from environment variables."""

    discord_token: str = ""
    default_prefix: str = "!"
    database_path: Path = Path("data/nova.db")
    owner_ids: Set[int] = field(default_factory=set)
    sync_commands_on_startup: bool = True
    dev_guild_id: Optional[int] = None
    log_level: str = "INFO"
    ffmpeg_executable: str = "ffmpeg"
    health_port: Optional[int] = None

    @classmethod
    def from_env(cls) -> "BotConfig":
        raw_owners = os.getenv("BOT_OWNER_IDS", "").strip()
        owners: Set[int] = set()
        for part in raw_owners.split(","):
            clean = part.strip()
            if clean.isdigit():
                owners.add(int(clean))

        raw_guild = os.getenv("DEV_GUILD_ID", "").strip()
        dev_guild = int(raw_guild) if raw_guild.isdigit() else None

        raw_port = os.getenv("PORT", os.getenv("HEALTH_PORT", "")).strip()
        health_port = int(raw_port) if raw_port.isdigit() else None

        db_path_str = os.getenv("DATABASE_PATH", "data/nova.db").strip() or "data/nova.db"
        sync_flag = os.getenv("SYNC_COMMANDS_ON_STARTUP", "true").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        return cls(
            discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
            default_prefix=os.getenv("DEFAULT_PREFIX", "!").strip() or "!",
            database_path=Path(db_path_str),
            owner_ids=owners,
            sync_commands_on_startup=sync_flag,
            dev_guild_id=dev_guild,
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            ffmpeg_executable=os.getenv("FFMPEG_PATH", "ffmpeg").strip() or "ffmpeg",
            health_port=health_port,
        )
