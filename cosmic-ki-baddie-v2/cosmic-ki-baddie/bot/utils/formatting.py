"""Utility helpers for time parsing, formatting, and Discord embeds."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Optional
import discord

DURATION_REGEX = re.compile(r"^\s*(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?\s*$", re.IGNORECASE)


def parse_duration(raw: str) -> Optional[int]:
    """Parse a human duration string like '10m', '2h30m', '1d', or '90' (seconds) into seconds."""
    if not raw:
        return None
    clean = raw.strip()
    if clean.isdigit():
        return int(clean)
    match = DURATION_REGEX.match(clean)
    if not match or not any(match.groups()):
        return None
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    seconds = int(match.group(4) or 0)
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable string like '1h 30m 15s'."""
    seconds = max(0, int(seconds))
    if seconds == 0:
        return "0s"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs:
        parts.append(f"{secs}s")
    return " ".join(parts)


def make_embed(
    title: str,
    description: str = "",
    *,
    color: Optional[discord.Color] = None,
    footer: Optional[str] = "Cosmic ki baddie V2 • Project Nova",
) -> discord.Embed:
    """Create a standardized Project Nova embed."""
    emb = discord.Embed(
        title=title,
        description=description,
        color=color or discord.Color.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    if footer:
        emb.set_footer(text=footer)
    return emb
