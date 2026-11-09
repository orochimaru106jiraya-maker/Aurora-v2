"""Centralized asynchronous SQLite Database Manager for Project Nova."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Sequence

from bot.database import sqlite_compat as aiosqlite
from bot.database.migrations import MIGRATIONS

logger = logging.getLogger("project_nova.database.manager")


class DatabaseManager:
    """Centralized async-safe SQLite database connection and migration manager.

    All Cogs and Services must access SQLite exclusively through this manager
    or its repositories—never by creating unmanaged connections.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conn: Optional[Any] = None
        self._write_lock = asyncio.Lock()
        self._initialized = False

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and self._initialized

    async def connect(self) -> None:
        """Open the SQLite database connection, configure PRAGMAs, and run migrations."""
        if self._conn is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Connecting to SQLite database at %s", self.db_path)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON;")
        await self._conn.execute("PRAGMA journal_mode = WAL;")
        await self._conn.execute("PRAGMA synchronous = NORMAL;")
        await self._conn.commit()
        await self.run_migrations()
        self._initialized = True
        logger.info("Database initialized and migrations verified.")

    async def close(self) -> None:
        """Cleanly close the active SQLite connection."""
        if self._conn is not None:
            logger.info("Closing SQLite database connection.")
            await self._conn.close()
            self._conn = None
            self._initialized = False

    def _require_conn(self) -> Any:
        if self._conn is None:
            raise RuntimeError("DatabaseManager is not connected. Call `await db.connect()` first.")
        return self._conn

    async def run_migrations(self) -> List[int]:
        """Execute all pending versioned migrations inside transactions."""
        conn = self._require_conn()
        applied: List[int] = []
        async with self._write_lock:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            await conn.commit()

            async with conn.execute("SELECT version FROM schema_migrations ORDER BY version;") as cur:
                rows = await cur.fetchall()
            existing_versions = {int(r["version"]) for r in rows}

            for version, description, script in MIGRATIONS:
                if version in existing_versions:
                    continue
                logger.info("Applying database migration v%d: %s", version, description)
                try:
                    await conn.executescript(script)
                    await conn.execute("PRAGMA foreign_keys = ON;")
                    await conn.execute(
                        "INSERT INTO schema_migrations (version, description) VALUES (?, ?);",
                        (version, description),
                    )
                    await conn.commit()
                    applied.append(version)
                except Exception as exc:
                    await conn.rollback()
                    logger.exception("Failed migration v%d (%s): %s", version, description, exc)
                    raise
        return applied

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """Provide an atomic serialized write transaction context manager."""
        conn = self._require_conn()
        async with self._write_lock:
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Execute a single write statement with parameterized arguments and return lastrowid."""
        conn = self._require_conn()
        async with self._write_lock:
            try:
                async with conn.execute(sql, tuple(params)) as cursor:
                    last_id = cursor.lastrowid or 0
                await conn.commit()
                return int(last_id)
            except Exception as exc:
                await conn.rollback()
                logger.error("Database execute error (%s): %s", sql.strip().splitlines()[0], exc)
                raise

    async def execute_rowcount(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Execute a single write statement and return the affected row count."""
        conn = self._require_conn()
        async with self._write_lock:
            try:
                async with conn.execute(sql, tuple(params)) as cursor:
                    count = cursor.rowcount
                await conn.commit()
                return int(count if count is not None and count >= 0 else 0)
            except Exception as exc:
                await conn.rollback()
                logger.error("Database execute_rowcount error (%s): %s", sql.strip().splitlines()[0], exc)
                raise

    async def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> None:
        """Execute parameterized batch statements inside a write lock."""
        conn = self._require_conn()
        async with self._write_lock:
            try:
                cur = await conn.executemany(sql, list(seq_of_params))
                await cur.close()
                await conn.commit()
            except Exception as exc:
                await conn.rollback()
                logger.error("Database executemany error: %s", exc)
                raise

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        """Execute a parameterized SELECT query and return a single row as a dict (or None)."""
        conn = self._require_conn()
        async with conn.execute(sql, tuple(params)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row is not None else None

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        """Execute a parameterized SELECT query and return all rows as dicts."""
        conn = self._require_conn()
        async with conn.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def create_file_backup(self, backup_path: str | Path) -> Path:
        """Create a consistent online SQLite file backup."""
        conn = self._require_conn()
        dest = Path(backup_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._write_lock:
            async with aiosqlite.connect(dest) as target_conn:
                await conn.backup(target_conn)
        logger.info("Created SQLite database backup at %s", dest)
        return dest
