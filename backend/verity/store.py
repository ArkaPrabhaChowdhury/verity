from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import aiosqlite
import asyncpg

from .models import Event, Run, utc_now


class RunNotFound(LookupError):
    pass


class Repository(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def create_run(self, run: Run) -> None: ...
    async def save_run(self, run: Run) -> None: ...
    async def get_run(self, run_id: str) -> Run: ...
    async def list_runs(self, limit: int, workspace_id: str = "default") -> list[Run]: ...
    async def append_event(self, event: Event) -> None: ...
    async def list_events(self, run_id: str) -> list[Event]: ...
    async def delete_run(self, run_id: str) -> None: ...
    async def find_idempotent_run(self, workspace_id: str, idempotency_key: str) -> Run | None: ...
    async def recover_expired_runs(self) -> int: ...


def _run_json(run: Run) -> str:
    return run.model_dump_json(exclude_none=True)


def _decode_record(value: str | dict) -> Run:
    return Run.model_validate(json.loads(value) if isinstance(value, str) else value)


class SQLiteRepository:
    def __init__(self, path: str) -> None:
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        await self.db.execute("PRAGMA foreign_keys=ON")
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA busy_timeout=5000")
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                status TEXT NOT NULL,
                record_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
            CREATE TABLE IF NOT EXISTS run_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_run_events_run_seq ON run_events(run_id, seq);
            """
        )
        async with self.db.execute("PRAGMA table_info(runs)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        for name, definition in {
            "workspace_id": "TEXT NOT NULL DEFAULT 'default'",
            "idempotency_key": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in columns:
                await self.db.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_workspace_key "
            "ON runs(workspace_id, idempotency_key)"
        )
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    def _database(self) -> aiosqlite.Connection:
        if not self.db:
            raise RuntimeError("repository is not connected")
        return self.db

    async def create_run(self, run: Run) -> None:
        now = utc_now().isoformat()
        await self._database().execute(
            "INSERT INTO runs(id,question,status,record_json,created_at,updated_at,"
            "workspace_id,idempotency_key) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                run.id,
                run.question,
                run.status,
                _run_json(run),
                run.created_at.isoformat(),
                now,
                run.workspace_id,
                run.idempotency_key,
            ),
        )
        await self._database().commit()

    async def save_run(self, run: Run) -> None:
        await self._database().execute(
            "UPDATE runs SET question=?,status=?,record_json=?,updated_at=? WHERE id=?",
            (run.question, run.status, _run_json(run), utc_now().isoformat(), run.id),
        )
        await self._database().commit()

    async def get_run(self, run_id: str) -> Run:
        async with self._database().execute(
            "SELECT record_json FROM runs WHERE id=?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise RunNotFound(run_id)
        return _decode_record(row[0])

    async def list_runs(self, limit: int, workspace_id: str = "default") -> list[Run]:
        limit = limit if 1 <= limit <= 100 else 20
        async with self._database().execute(
            "SELECT record_json FROM runs WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_decode_record(row[0]) for row in rows]

    async def append_event(self, event: Event) -> None:
        cursor = await self._database().execute(
            "INSERT INTO run_events(run_id,type,data_json,created_at) VALUES(?,?,?,?)",
            (
                event.run_id,
                event.type,
                json.dumps(event.data, default=str),
                event.created_at.isoformat(),
            ),
        )
        event.seq = cursor.lastrowid or 0
        await self._database().commit()

    async def list_events(self, run_id: str) -> list[Event]:
        async with self._database().execute(
            "SELECT seq,type,data_json,created_at FROM run_events WHERE run_id=? ORDER BY seq",
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            Event(
                seq=row[0],
                run_id=run_id,
                type=row[1],
                data=json.loads(row[2]),
                created_at=row[3],
            )
            for row in rows
        ]

    async def delete_run(self, run_id: str) -> None:
        cursor = await self._database().execute("DELETE FROM runs WHERE id=?", (run_id,))
        await self._database().commit()
        if cursor.rowcount == 0:
            raise RunNotFound(run_id)

    async def find_idempotent_run(self, workspace_id: str, idempotency_key: str) -> Run | None:
        if not idempotency_key:
            return None
        async with self._database().execute(
            "SELECT record_json FROM runs WHERE workspace_id=? AND idempotency_key=? "
            "ORDER BY created_at DESC LIMIT 1",
            (workspace_id, idempotency_key),
        ) as cursor:
            row = await cursor.fetchone()
        return _decode_record(row[0]) if row else None

    async def recover_expired_runs(self) -> int:
        async with self._database().execute(
            "SELECT record_json FROM runs WHERE status='running'"
        ) as cursor:
            rows = await cursor.fetchall()
        recovered = 0
        for (raw,) in rows:
            run = _decode_record(raw)
            if run.lease_expires_at and run.lease_expires_at <= utc_now():
                run.status = "queued"
                run.lease_owner = ""
                run.lease_expires_at = None
                await self.save_run(run)
                recovered += 1
        return recovered


class PostgresRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=1,
            max_size=5,
            command_timeout=15,
            statement_cache_size=0,
        )
        async with self._pool().acquire() as connection:
            await connection.fetchval("SELECT 1 FROM verity.runs LIMIT 1")

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def _pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("repository is not connected")
        return self.pool

    async def create_run(self, run: Run) -> None:
        await self._pool().execute(
            """
            INSERT INTO verity.runs(id,question,status,record_json,created_at,updated_at,
                workspace_id,idempotency_key)
            VALUES($1,$2,$3,$4::jsonb,$5,$6,$7,$8)
            """,
            run.id,
            run.question,
            run.status,
            _run_json(run),
            run.created_at,
            utc_now(),
            run.workspace_id,
            run.idempotency_key,
        )

    async def save_run(self, run: Run) -> None:
        await self._pool().execute(
            """
            UPDATE verity.runs
            SET question=$1,status=$2,record_json=$3::jsonb,updated_at=$4
            WHERE id=$5
            """,
            run.question,
            run.status,
            _run_json(run),
            utc_now(),
            run.id,
        )

    async def get_run(self, run_id: str) -> Run:
        record = await self._pool().fetchval(
            "SELECT record_json FROM verity.runs WHERE id=$1", run_id
        )
        if record is None:
            raise RunNotFound(run_id)
        return _decode_record(record)

    async def list_runs(self, limit: int, workspace_id: str = "default") -> list[Run]:
        limit = limit if 1 <= limit <= 100 else 20
        rows = await self._pool().fetch(
            "SELECT record_json FROM verity.runs WHERE workspace_id=$1 "
            "ORDER BY created_at DESC LIMIT $2",
            workspace_id,
            limit,
        )
        return [_decode_record(row["record_json"]) for row in rows]

    async def append_event(self, event: Event) -> None:
        event.seq = await self._pool().fetchval(
            """
            INSERT INTO verity.run_events(run_id,type,data_json,created_at)
            VALUES($1,$2,$3::jsonb,$4) RETURNING seq
            """,
            event.run_id,
            event.type,
            json.dumps(event.data, default=str),
            event.created_at,
        )

    async def list_events(self, run_id: str) -> list[Event]:
        rows = await self._pool().fetch(
            """
            SELECT seq,type,data_json,created_at
            FROM verity.run_events WHERE run_id=$1 ORDER BY seq
            """,
            run_id,
        )
        return [
            Event(
                seq=row["seq"],
                run_id=run_id,
                type=row["type"],
                data=(
                    json.loads(row["data_json"])
                    if isinstance(row["data_json"], str)
                    else row["data_json"]
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def delete_run(self, run_id: str) -> None:
        result = await self._pool().execute("DELETE FROM verity.runs WHERE id=$1", run_id)
        if result == "DELETE 0":
            raise RunNotFound(run_id)

    async def find_idempotent_run(self, workspace_id: str, idempotency_key: str) -> Run | None:
        if not idempotency_key:
            return None
        record = await self._pool().fetchval(
            "SELECT record_json FROM verity.runs WHERE workspace_id=$1 AND idempotency_key=$2 "
            "ORDER BY created_at DESC LIMIT 1",
            workspace_id,
            idempotency_key,
        )
        return _decode_record(record) if record is not None else None

    async def recover_expired_runs(self) -> int:
        rows = await self._pool().fetch(
            "SELECT record_json FROM verity.runs WHERE status='running'"
        )
        recovered = 0
        for row in rows:
            run = _decode_record(row["record_json"])
            if run.lease_expires_at and run.lease_expires_at <= utc_now():
                run.status = "queued"
                run.lease_owner = ""
                run.lease_expires_at = None
                await self.save_run(run)
                recovered += 1
        return recovered
