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
    approve_permanent,
    approve_session,
    has_blocking_approval,
    load_permanent_allowlist,
    register_gateway_notify,
    reset_current_session_key,
    resolve_gateway_approval,
    set_current_session_key,
    unregister_gateway_notify,
)


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class HermesProviderError(RuntimeError):
    pass


def _is_transient_error(error_text: str | None) -> bool:
    if not error_text:
        return False
    lowered = error_text.lower()
    needles = (
        'rate limit',
        'rate_limit',
        'too many requests',
        'timeout',
        'timed out',
        'temporarily unavailable',
        'temporary failure',
        'connection reset',
        'connection aborted',
        'connection refused',
        'connection error',
        'quota',
        'overloaded',
        'try again',
        '503',
        '429',
    )
    return any(needle in lowered for needle in needles)


def _parse_retry_after_seconds(error_text: str | None) -> int | None:
    if not error_text:
        return None
    import re
    patterns = (
        r'retry after\s*(\d+)\s*s',
        r'retry in\s*(\d+)\s*s',
        r'after\s*(\d+)\s*seconds',
        r'please try again in\s*(\d+)\s*s',
    )
    lowered = error_text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            try:
                return max(1, int(match.group(1)))
            except (TypeError, ValueError):
                return None
    return None


class LocalHermesProvider:
    def __init__(self) -> None:
        self._session_db = SessionDB()
        self._pending_by_approval_id: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def rehydrate_pending_approvals(self, approvals: list[dict[str, Any]]) -> None:
        rebuilt: dict[str, dict[str, Any]] = {}
        for item in approvals:
            details = item.get('details') or {}
            provider_approval_id = details.get('approval_id') or item.get('id')
            rebuilt[provider_approval_id] = {
                'approval_id': provider_approval_id,
                'session_id': details.get('session_id'),
                'command': details.get('command', ''),
                'description': details.get('description', item.get('summary', 'dangerous command')),
                'pattern_keys': details.get('pattern_keys') or ([details['pattern_key']] if details.get('pattern_key') else []),
                'restored': True,
                'tailchat_approval_id': item.get('id'),
                'run_id': item.get('run_id'),
            }
        async with self._lock:
            self._pending_by_approval_id = rebuilt

    async def _session_lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            return lock

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
        session_lock = await self._session_lock_for(session_id)
        async with session_lock:
            loop = asyncio.get_running_loop()
            emitted_events = False
            emitted_text = False
            side_effect_risk = False
            max_attempts = max(1, int(__import__('os').getenv('TAILCHAT_TRANSIENT_RETRY_ATTEMPTS', '3')))

            def text_cb(delta: str | None) -> None:
                nonlocal emitted_events, emitted_text
                if delta is None:
                    return
                emitted_events = True
                emitted_text = True
                asyncio.run_coroutine_threadsafe(on_event({'event': 'message.delta', 'delta': delta}), loop)

            def tool_cb(event_type: str, tool_name: str = None, preview: str = None, args=None, **kwargs):
                nonlocal emitted_events, side_effect_risk
                emitted_events = True
                side_effect_risk = True
                event = {'event': event_type, 'tool': tool_name, 'preview': preview, 'args': args or {}}
                event.update(kwargs)
                asyncio.run_coroutine_threadsafe(on_event(event), loop)

            def approval_notify(approval_data: dict) -> None:
                nonlocal side_effect_risk
                side_effect_risk = True
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

            result: dict[str, Any] | None = None
            error_text: str | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    result = await loop.run_in_executor(None, run_sync)
                    error_text = result.get('error') if isinstance(result, dict) else None
                except Exception as exc:
                    error_text = str(exc)
                    result = None

                safe_to_retry = not side_effect_risk and not has_blocking_approval(session_id)
                if error_text and attempt < max_attempts and _is_transient_error(error_text) and safe_to_retry:
                    retry_after = _parse_retry_after_seconds(error_text)
                    backoff_seconds = retry_after or min(20, 2 ** (attempt - 1))
                    await on_event({
                        'event': 'run.retrying',
                        'session_id': session_id,
                        'attempt': attempt,
                        'next_attempt': attempt + 1,
                        'backoff_seconds': backoff_seconds,
                        'error': error_text,
                        'reset_output': emitted_text,
                    })
                    emitted_events = False
                    emitted_text = False
                    await asyncio.sleep(backoff_seconds)
                    continue
                if error_text and result is None:
                    raise HermesProviderError(error_text)
                break

            result = result or {}
            final_response = result.get('final_response', '') if isinstance(result, dict) else ''
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

    async def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._session_db.get_messages, session_id)

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
        await on_event({'event': 'approval.waiting', 'session_id': session_id, 'approval_id': approval_id})

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
        session_id = approval.get('session_id')
        count = resolve_gateway_approval(session_id, choice, resolve_all=False) if session_id else 0
        restored = bool(approval.get('restored'))
        scope_adjusted = False

        if not count:
            if not restored:
                raise HermesProviderError('No pending command to resolve')
            pattern_keys = list(approval.get('pattern_keys') or [])
            if choice in {'once', 'session'}:
                for key in pattern_keys:
                    approve_session(session_id, key)
                scope_adjusted = choice == 'once'
            elif choice == 'always':
                persisted = set(load_permanent_allowlist())
                for key in pattern_keys:
                    approve_session(session_id, key)
                    approve_permanent(key)
                    persisted.add(key)
                if persisted:
                    load_permanent_allowlist()
                    from tools.approval import save_permanent_allowlist
                    save_permanent_allowlist(persisted)
            elif choice != 'deny':
                raise HermesProviderError(f'Unsupported approval decision: {choice}')

        result = {
            'approval_id': approval_id,
            'session_id': session_id,
            'decision': choice,
            'resolved_count': count,
        }
        if restored:
            result['restored'] = True
            result['resume_required'] = True
        if scope_adjusted:
            result['scope_adjusted'] = True
            result['scope_adjustment_reason'] = 'Recovered approvals use session scope when replaying an interrupted run.'
        return result
