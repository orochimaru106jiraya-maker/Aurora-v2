"""Runtime health & uptime monitor for Project Nova (Railway compatible)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional

from bot.utils.formatting import format_duration

logger = logging.getLogger("project_nova.core.health")


class HealthMonitor:
    """Tracks bot uptime, database connectivity, and optional HTTP health endpoint."""

    def __init__(self, bot: Any, port: Optional[int] = None) -> None:
        self.bot = bot
        self.port = port
        self.started_at = datetime.now(timezone.utc)
        self._server: Optional[asyncio.AbstractServer] = None

    @property
    def uptime_seconds(self) -> int:
        delta = datetime.now(timezone.utc) - self.started_at
        return max(0, int(delta.total_seconds()))

    @property
    def uptime_human(self) -> str:
        return format_duration(self.uptime_seconds)

    def get_status_Report(self) -> Dict[str, Any]:
        return {
            "bot": "Cosmic ki baddie V2",
            "project": "Project Nova",
            "status": "ok" if self.bot.db.is_connected else "degraded",
            "database_connected": self.bot.db.is_connected,
            "loaded_cogs": len(self.bot.cogs),
            "registered_prefix_commands": len(self.bot.commands),
            "registered_slash_commands": len(self.bot.tree.get_commands()),
            "uptime_seconds": self.uptime_seconds,
            "uptime_human": self.uptime_human,
        }

    async def start_server_if_configured(self) -> None:
        if not self.port:
            return
        try:
            self._server = await asyncio.start_server(
                self._handle_http, host="0.0.0.0", port=int(self.port)
            )
            logger.info("Health check HTTP endpoint listening on 0.0.0.0:%d", self.port)
        except Exception as exc:
            logger.warning("Could not bind health check port %s: %s", self.port, exc)

    async def _handle_http(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.read(1024)
            payload = json.dumps(self.get_status_Report()).encode("utf-8")
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n"
                b"Connection: close\r\n\r\n" + payload
            )
            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
