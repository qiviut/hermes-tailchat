from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, conversation_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers[conversation_id].add(q)
        return q

    async def unsubscribe(self, conversation_id: str, q: asyncio.Queue) -> None:
        async with self._lock:
            queues = self._subscribers.get(conversation_id)
            if not queues:
                return
            queues.discard(q)
            if not queues:
                self._subscribers.pop(conversation_id, None)

    async def publish(self, conversation_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._subscribers.get(conversation_id, set()))
        for q in targets:
            await q.put(event)


broker = EventBroker()
