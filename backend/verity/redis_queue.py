from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis, from_url
from redis.exceptions import ResponseError


class RedisResearchQueue:
    """Reliable Redis Streams queue with consumer-group recovery semantics."""

    def __init__(
        self,
        url: str,
        stream: str = "verity:research",
        group: str = "verity-workers",
        consumer: str | None = None,
        visibility_timeout_ms: int = 600_000,
    ) -> None:
        self.redis: Redis = from_url(url, decode_responses=True)
        self.stream = stream
        self.group = group
        self.consumer = consumer or f"{socket.gethostname()}-{id(self)}"
        self.visibility_timeout_ms = visibility_timeout_ms
        self.dead_letter_stream = f"{stream}:dead-letter"

    async def connect(self) -> None:
        await self.redis.ping()
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0-0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def close(self) -> None:
        await self.redis.aclose()

    async def enqueue(self, run_id: str, workspace_id: str) -> str:
        return await self.redis.xadd(
            self.stream,
            {"run_id": run_id, "workspace_id": workspace_id},
            maxlen=100_000,
            approximate=True,
        )

    async def dead_letter(self, message_id: str, fields: dict[str, Any], reason: str) -> None:
        await self.redis.xadd(
            self.dead_letter_stream,
            {**fields, "source_message_id": message_id, "reason": reason},
            maxlen=50_000,
            approximate=True,
        )

    async def run_forever(
        self,
        handler: Callable[[dict[str, str]], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        await self.connect()
        while not stop_event.is_set():
            await self._reclaim(handler)
            messages = await self.redis.xreadgroup(
                self.group,
                self.consumer,
                {self.stream: ">"},
                count=1,
                block=1000,
            )
            for _, entries in messages:
                for message_id, fields in entries:
                    fields = {**fields, "__message_id": message_id}
                    try:
                        await handler(fields)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Leave pending; XAUTOCLAIM retries after visibility timeout.
                        continue
                    await self.redis.xack(self.stream, self.group, message_id)

    async def _reclaim(self, handler: Callable[[dict[str, str]], Awaitable[None]]) -> None:
        cursor = "0-0"
        while cursor:
            result = await self.redis.xautoclaim(
                self.stream,
                self.group,
                self.consumer,
                min_idle_time=self.visibility_timeout_ms,
                start_id=cursor,
                count=20,
            )
            cursor, entries = result[0], result[1]
            for message_id, fields in entries:
                fields = {**fields, "__message_id": message_id}
                try:
                    await handler(fields)
                except Exception:
                    continue
                await self.redis.xack(self.stream, self.group, message_id)
            if not entries:
                break


def queue_config() -> dict[str, str | int]:
    import os

    return {
        "url": os.getenv("VERITY_REDIS_URL", "").strip(),
        "stream": os.getenv("VERITY_REDIS_STREAM", "verity:research"),
        "group": os.getenv("VERITY_REDIS_GROUP", "verity-workers"),
        "visibility_timeout_ms": int(os.getenv("VERITY_REDIS_VISIBILITY_TIMEOUT_MS", "600000")),
    }
