from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

_HERMES_ROOT = Path('/home/operator/.hermes/hermes-agent')
_HERMES_SITE = next((_HERMES_ROOT / 'venv' / 'lib').glob('python*/site-packages'))
for _p in (str(_HERMES_SITE), str(_HERMES_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hermes_cli.tools_config import _get_platform_tools
from gateway.run import _load_gateway_config, _resolve_gateway_model, _resolve_runtime_agent_kwargs, GatewayRunner
from hermes_state import SessionDB
from run_agent import AIAgent
from tools.approval import (
    has_blocking_approval,
    register_gateway_notify,
    reset_current_session_key,
    resolve_gateway_approval,
    set_current_session_key,
    unregister_gateway_notify,
)


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class HermesProviderError(RuntimeError):
    pass


class LocalHermesProvider:
    def __init__(self) -> None:
        self._session_db = SessionDB()
        self._pending_by_approval_id: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def _create_agent(self, session_id: str, stream_delta_callback=None, tool_progress_callback=None) -> AIAgent:
        runtime_kwargs = _resolve_runtime_agent_kwargs()
        model = _resolve_gateway_model()
        user_config = _load_gateway_config()
        enabled_toolsets = sorted(_get_platform_tools(user_config, 'api_server'))
        max_iterations = int(__import__('os').getenv('HERMES_MAX_ITERATIONS', '90'))
        fallback_model = GatewayRunner._load_fallback_model()
        return AIAgent(
            model=model,
            **runtime_kwargs,
            max_iterations=max_iterations,
            quiet_mode=True,
            verbose_logging=False,
            enabled_toolsets=enabled_toolsets,
            session_id=session_id,
            platform='api_server',
            stream_delta_callback=stream_delta_callback,
            tool_progress_callback=tool_progress_callback,
            session_db=self._session_db,
            fallback_model=fallback_model,
        )

    async def run_turn(
        self,
        session_id: str,
        conversation_history: list[dict[str, str]],
        user_message: str,
        on_event: EventHandler,
    ) -> None:
        loop = asyncio.get_running_loop()

        def text_cb(delta: str | None) -> None:
            if delta is None:
                return
            asyncio.run_coroutine_threadsafe(on_event({'event': 'message.delta', 'delta': delta}), loop)

        def tool_cb(event_type: str, tool_name: str = None, preview: str = None, args=None, **kwargs):
            event = {'event': event_type, 'tool': tool_name, 'preview': preview, 'args': args or {}}
            event.update(kwargs)
            asyncio.run_coroutine_threadsafe(on_event(event), loop)

        def approval_notify(approval_data: dict) -> None:
            asyncio.run_coroutine_threadsafe(self._register_approval(session_id, approval_data, on_event), loop)

        def run_sync() -> dict[str, Any]:
            agent = self._create_agent(session_id, stream_delta_callback=text_cb, tool_progress_callback=tool_cb)
            token = set_current_session_key(session_id)
            register_gateway_notify(session_id, approval_notify)
            try:
                return agent.run_conversation(user_message, conversation_history=conversation_history, task_id=session_id)
            finally:
                unregister_gateway_notify(session_id)
                reset_current_session_key(token)

        result = await loop.run_in_executor(None, run_sync)
        final_response = result.get('final_response', '') if isinstance(result, dict) else ''
        error_text = result.get('error') if isinstance(result, dict) else None
        if has_blocking_approval(session_id):
            await on_event({'event': 'approval.waiting', 'session_id': session_id})
        if final_response:
            await on_event({'event': 'run.completed', 'output': final_response})
        elif error_text:
            await on_event({'event': 'run.failed', 'error': error_text})
        else:
            await on_event({'event': 'run.failed', 'error': 'No response generated'})

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._session_db.get_session, session_id)

    async def list_sessions(self, source: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()

        def run_sync() -> list[dict[str, Any]]:
            sessions = self._session_db.list_sessions_rich(source=source, limit=limit)
            return [
                {
                    'id': item.get('id'),
                    'title': item.get('title'),
                    'source': item.get('source'),
                    'started_at': item.get('started_at'),
                    'ended_at': item.get('ended_at'),
                    'message_count': item.get('message_count'),
                    'preview': item.get('preview', ''),
                    'last_active': item.get('last_active'),
                }
                for item in sessions
            ]

        return await loop.run_in_executor(None, run_sync)

    async def set_session_title(self, session_id: str, title: str) -> str | None:
        loop = asyncio.get_running_loop()

        def run_sync() -> str | None:
            try:
                self._session_db.set_session_title(session_id, title)
            except ValueError as exc:
                raise HermesProviderError(str(exc)) from exc
            return self._session_db.get_session_title(session_id)

        return await loop.run_in_executor(None, run_sync)

    async def get_session_title(self, session_id: str) -> str | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._session_db.get_session_title, session_id)

    async def _register_approval(self, session_id: str, approval_data: dict, on_event: EventHandler) -> None:
        import uuid
        approval_id = uuid.uuid4().hex
        record = {
            'approval_id': approval_id,
            'session_id': session_id,
            'command': approval_data.get('command', ''),
            'description': approval_data.get('description', 'dangerous command'),
            'pattern_keys': approval_data.get('pattern_keys', []),
        }
        async with self._lock:
            self._pending_by_approval_id[approval_id] = record
        await on_event({'event': 'approval.requested', 'approval': record})

    async def resolve_approval(self, approval_id: str, decision: str) -> dict[str, Any]:
        async with self._lock:
            approval = self._pending_by_approval_id.pop(approval_id, None)
        if not approval:
            raise HermesProviderError(f'Approval not found: {approval_id}')
        choice_map = {
            'approved': 'once',
            'allow-once': 'once',
            'allow-session': 'session',
            'allow-always': 'always',
            'denied': 'deny',
            'deny': 'deny',
        }
        choice = choice_map.get(decision, decision)
        count = resolve_gateway_approval(approval['session_id'], choice, resolve_all=False)
        if not count:
            raise HermesProviderError('No pending command to resolve')
        return {
            'approval_id': approval_id,
            'session_id': approval['session_id'],
            'decision': choice,
            'resolved_count': count,
        }
