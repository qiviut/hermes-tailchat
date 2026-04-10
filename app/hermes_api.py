from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import httpx


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class HermesAPIError(RuntimeError):
    pass


class HermesClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def run_turn(
        self,
        conversation_id: str,
        conversation_history: list[dict[str, str]],
        user_message: str,
        on_event: EventHandler,
    ) -> None:
        payload = {
            "session_id": conversation_id,
            "input": user_message,
            "conversation_history": conversation_history,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            create = await client.post(
                f"{self.base_url}/v1/runs",
                headers=self._headers(),
                json=payload,
            )
            if create.status_code >= 400:
                raise HermesAPIError(f"Run creation failed: {create.status_code} {create.text}")
            run_id = create.json()["run_id"]
            await on_event({"event": "run.started", "run_id": run_id})
            async with client.stream(
                "GET",
                f"{self.base_url}/v1/runs/{run_id}/events",
                headers=self._headers(),
            ) as resp:
                if resp.status_code >= 400:
                    raise HermesAPIError(f"Event stream failed: {resp.status_code} {await resp.aread()}" )
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    await on_event(data)
