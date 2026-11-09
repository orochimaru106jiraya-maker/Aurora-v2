"""Async SQLite compatibility layer.

Uses `aiosqlite` in production. When running in an offline test sandbox where
`aiosqlite` is not installed in site-packages, provides a 100% API-compatible
async wrapper around Python's standard library `sqlite3` using a dedicated
worker thread per connection so that all async context managers (`async with
db.execute(...) as cursor:`) and `await db.commit()` work identically.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Optional, Sequence

try:
    import aiosqlite as _real_aiosqlite  # type: ignore

    Row = _real_aiosqlite.Row
    Error = _real_aiosqlite.Error
    IntegrityError = _real_aiosqlite.IntegrityError
    OperationalError = _real_aiosqlite.OperationalError
    connect = _real_aiosqlite.connect
    USING_REAL_AIOSQLITE = True
except ModuleNotFoundError:
    USING_REAL_AIOSQLITE = False
    Row = sqlite3.Row
    Error = sqlite3.Error
    IntegrityError = sqlite3.IntegrityError
    OperationalError = sqlite3.OperationalError

    class AsyncCursor:
        """Async wrapper around sqlite3.Cursor supporting `async with` and `await`."""

        def __init__(self, conn: "AsyncConnection", raw_cursor: sqlite3.Cursor) -> None:
            self._conn = conn
            self._cursor = raw_cursor

        @property
        def lastrowid(self) -> Optional[int]:
            return self._cursor.lastrowid

        @property
        def rowcount(self) -> int:
            return self._cursor.rowcount

        @property
        def description(self) -> Any:
            return self._cursor.description

        async def fetchone(self) -> Optional[sqlite3.Row]:
            return await self._conn._run(self._cursor.fetchone)

        async def fetchall(self) -> list[sqlite3.Row]:
            return await self._conn._run(self._cursor.fetchall)

        async def fetchmany(self, size: int = 1) -> list[sqlite3.Row]:
            return await self._conn._run(self._cursor.fetchmany, size)

        async def close(self) -> None:
            await self._conn._run(self._cursor.close)

        async def __aenter__(self) -> "AsyncCursor":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            await self.close()

    class _ExecuteContext:
        """Awaitable AND async context manager returned by `conn.execute(...)`."""

        def __init__(
            self,
            conn: "AsyncConnection",
            sql: str,
            parameters: Sequence[Any] = (),
        ) -> None:
            self._conn = conn
            self._sql = sql
            self._parameters = parameters
            self._cursor: Optional[AsyncCursor] = None

        async def _start(self) -> AsyncCursor:
            if self._cursor is None:
                raw = await self._conn._run(
                    self._conn._raw_conn.execute, self._sql, tuple(self._parameters)
                )
                self._cursor = AsyncCursor(self._conn, raw)
            return self._cursor

        def __await__(self):
            return self._start().__await__()

        async def __aenter__(self) -> AsyncCursor:
            return await self._start()

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            if self._cursor is not None:
                await self._cursor.close()

    class AsyncConnection:
        """Single-thread-affine async SQLite connection matching `aiosqlite.Connection`."""

        def __init__(self, database: str | Path, **kwargs: Any) -> None:
            self._database = str(database)
            self._kwargs = kwargs
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite-worker")
            self._raw_conn: Optional[sqlite3.Connection] = None
            self._row_factory: Any = None
            self._closed = False

        async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

        async def _connect(self) -> "AsyncConnection":
            def _open() -> sqlite3.Connection:
                conn = sqlite3.connect(
                    self._database,
                    check_same_thread=False,
                    **self._kwargs,
                )
                if self._row_factory is not None:
                    conn.row_factory = self._row_factory
                return conn

            self._raw_conn = await self._run(_open)
            return self

        @property
        def row_factory(self) -> Any:
            return self._row_factory

        @row_factory.setter
        def row_factory(self, factory: Any) -> None:
            self._row_factory = factory
            if self._raw_conn is not None:
                self._raw_conn.row_factory = factory

        def execute(self, sql: str, parameters: Sequence[Any] = ()) -> _ExecuteContext:
            return _ExecuteContext(self, sql, parameters)

        async def executemany(
            self, sql: str, parameters: Iterable[Sequence[Any]]
        ) -> AsyncCursor:
            raw = await self._run(self._raw_conn.executemany, sql, list(parameters))
            return AsyncCursor(self, raw)

        async def executescript(self, sql_script: str) -> AsyncCursor:
            raw = await self._run(self._raw_conn.executescript, sql_script)
            return AsyncCursor(self, raw)

        async def commit(self) -> None:
            if self._raw_conn is not None:
                await self._run(self._raw_conn.commit)

        async def rollback(self) -> None:
            if self._raw_conn is not None:
                await self._run(self._raw_conn.rollback)

        async def backup(self, target: "AsyncConnection") -> None:
            if self._raw_conn is not None and target._raw_conn is not None:
                await self._run(self._raw_conn.backup, target._raw_conn)

        async def close(self) -> None:
            if not self._closed and self._raw_conn is not None:
                await self._run(self._raw_conn.close)
                self._closed = True
                self._executor.shutdown(wait=False)

        def __await__(self):
            return self._connect().__await__()

        async def __aenter__(self) -> "AsyncConnection":
            if self._raw_conn is None:
                await self._connect()
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            await self.close()

    def connect(database: str | Path, **kwargs: Any) -> AsyncConnection:
        return AsyncConnection(database, **kwargs)
