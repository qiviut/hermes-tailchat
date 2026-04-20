from __future__ import annotations

import asyncio
import json
import socket
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .broker import broker
from .codex_runner import CodexRunnerError, run_codex_task
from .config import APP_TITLE, DB_PATH
from .hermes_provider import HermesProviderError, LocalHermesProvider
from .store import RESTART_INTERRUPTED_ERROR, Store
from .retry_policy import is_rate_limited_error, is_transient_error
import app.store as store_module


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1)


class ConversationAttach(BaseModel):
    hermes_session_id: str = Field(min_length=1)
    title: str | None = None


class MessageCreate(BaseModel):
    content: str


class JobCreate(BaseModel):
    prompt: str = Field(min_length=1)
    delay_seconds: int = 0
    executor: str = Field(default='hermes', pattern='^(hermes|codex)$')
    thread_id: str | None = None
    bead_id: str | None = None
    reserve_paths: list[str] = Field(default_factory=list)
    notify_to: list[str] = Field(default_factory=list)
    reservation_reason: str | None = None


class ApprovalResolve(BaseModel):
    resolution: str


class StripHermesPrefixMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') in {'http', 'websocket'}:
            path = scope.get('path', '')
            if path == '/hermes' or path.startswith('/hermes/'):
                new_scope = dict(scope)
                stripped = path[len('/hermes'):]
                new_scope['path'] = stripped or '/'
                root_path = scope.get('root_path', '')
                new_scope['root_path'] = f'{root_path}/hermes' if root_path else '/hermes'
                scope = new_scope
        await self.app(scope, receive, send)


store = Store(DB_PATH)
store_module.store = store
hermes = LocalHermesProvider()
worker_id = f"tailchat-{socket.gethostname()}-{Path(DB_PATH).name}"
poll_task: asyncio.Task | None = None
startup_recovery_summary: dict[str, int] = {'runs': 0, 'jobs': 0, 'approvals': 0, 'messages': 0}
active_run_tasks: dict[str, asyncio.Task] = {}
active_job_tasks: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poll_task, startup_recovery_summary
    startup_recovery_summary = store.recover_incomplete_state()
    await hermes.rehydrate_pending_approvals(store.list_pending_approvals())
    poll_task = asyncio.create_task(job_poller())
    try:
        yield
    finally:
        for task in list(active_run_tasks.values()) + list(active_job_tasks.values()):
            task.cancel()
        for task in list(active_run_tasks.values()) + list(active_job_tasks.values()):
            with suppress(asyncio.CancelledError):
                await task
        if poll_task:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=APP_TITLE, lifespan=lifespan)
app.add_middleware(StripHermesPrefixMiddleware)
static_dir = Path(__file__).resolve().parent / 'static'
app.mount('/static', StaticFiles(directory=static_dir), name='static')


async def publish(conversation_id: str, event: dict, run_id: str | None = None):
    payload = dict(event)
    event_id = store.append_run_event(conversation_id, run_id, payload.get('event', 'unknown'), json.dumps(payload))
    payload['_event_id'] = event_id
    await broker.publish(conversation_id, payload)


def _track_background_task(task_map: dict[str, asyncio.Task], key: str, task: asyncio.Task) -> asyncio.Task:
    task_map[key] = task

    def _cleanup(done_task: asyncio.Task) -> None:
        task_map.pop(key, None)
        with suppress(asyncio.CancelledError, Exception):
            done_task.result()

    task.add_done_callback(_cleanup)
    return task


def _parse_import_cursor(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _curated_importable_messages(session_id: str, hermes_messages: list[dict[str, object]], after_timestamp: float | None = None) -> tuple[list[dict[str, object]], float | None]:
    imported = []
    max_timestamp = after_timestamp
    for message in hermes_messages:
        timestamp = message.get('timestamp')
        if isinstance(timestamp, (int, float)):
            max_timestamp = max(timestamp, max_timestamp or timestamp)
            if after_timestamp is not None and timestamp <= after_timestamp:
                continue
        role = message.get('role')
        content = (message.get('content') or '').strip()
        if role not in {'user', 'assistant'}:
            continue
        if not content:
            continue
        external_ref = f"hermes:{session_id}:{message.get('id')}"
        imported.append({
            'role': role,
            'content': content,
            'status': 'complete',
            'external_message_ref': external_ref,
            'metadata': {'origin': 'hermes_import', 'hermes_message_id': message.get('id')},
        })
    return imported, max_timestamp


async def sync_attached_transcript(conversation_id: str) -> dict:
    conversation = store.get_conversation(conversation_id)
    if not conversation or conversation.get('link_mode') != 'attached':
        return conversation
    session_id = conversation.get('hermes_session_id')
    if not session_id:
        return conversation
    hermes_messages = await hermes.get_session_messages(session_id)
    curated, max_timestamp = _curated_importable_messages(session_id, hermes_messages, _parse_import_cursor(conversation.get('last_hermes_import_at')))
    if curated:
        store.import_hermes_messages(conversation_id, curated)
    if max_timestamp is not None:
        conversation = store.update_last_hermes_import_at(conversation_id, max_timestamp)
    return conversation

def _is_transient_provider_error(error_text: str | None) -> bool:
    return is_transient_error(error_text)



def _format_provider_error(error_text: str, *, prefix: str) -> str:
    if _is_transient_provider_error(error_text):
        retry_note = 'Tailchat already retries only safe pre-side-effect non-429 transient failures automatically.'
        if is_rate_limited_error(error_text):
            retry_note = 'Tailchat does not auto-retry 429/rate-limit failures because they usually need a longer cool-down than an in-turn retry can provide.'
        return f'[{prefix} transient provider error] {error_text}\n\n{retry_note} If this happened after tools or streaming had started, the run stopped to avoid duplicating side effects. Please retry once the provider recovers.'
    return f'[{prefix}] {error_text}'


def _build_conversation_history(messages: list[dict], assistant_message_id: str, user_message: str, *, replay_original_user_message: bool = False) -> list[dict[str, str]]:
    history = [
        {'role': m['role'], 'content': m['content']}
        for m in messages
        if m['id'] != assistant_message_id and m['status'] != 'queued' and m['role'] in {'user', 'assistant', 'system'}
    ]
    if history and history[-1]['role'] == 'user' and history[-1]['content'] == user_message:
        return history[:-1]
    if replay_original_user_message:
        for idx in range(len(history) - 1, -1, -1):
            item = history[idx]
            if item['role'] == 'user' and item['content'] == user_message:
                return history[:idx]
    return history


async def run_turn(conversation_id: str, assistant_message_id: str, user_message: str, run_id: str, job_id: str | None = None) -> None:
    conversation = store.get_conversation(conversation_id)
    hermes_session_id = (conversation or {}).get('hermes_session_id') or conversation_id
    messages = store.get_messages(conversation_id)
    assistant_message = next((m for m in messages if m['id'] == assistant_message_id), None) or {}
    replay_original_user_message = bool((assistant_message.get('metadata') or {}).get('resumed_from_run_id'))
    conversation_history = _build_conversation_history(
        messages,
        assistant_message_id,
        user_message,
        replay_original_user_message=replay_original_user_message,
    )
    buffer = ''
    store.update_run(run_id, status='running')
    if job_id:
        store.update_job(job_id, status='running', result_message_id=assistant_message_id)

    async def on_event(event: dict):
        nonlocal buffer
        kind = event.get('event', 'unknown')
        if kind == 'message.delta':
            buffer += event.get('delta', '')
            store.update_message(assistant_message_id, buffer, status='streaming')
            await publish(conversation_id, {'event': 'message.delta', 'message_id': assistant_message_id, 'delta': event.get('delta', '')}, run_id=run_id)
            return
        if kind == 'run.retrying':
            if event.get('reset_output'):
                buffer = ''
                store.update_message(assistant_message_id, '', status='queued')
                await publish(conversation_id, {'event': 'message.retry_reset', 'message_id': assistant_message_id, 'run_id': run_id}, run_id=run_id)
            await publish(
                conversation_id,
                {
                    'event': 'run.retrying',
                    'message_id': assistant_message_id,
                    'attempt': event.get('attempt'),
                    'next_attempt': event.get('next_attempt'),
                    'backoff_seconds': event.get('backoff_seconds'),
                    'error': event.get('error'),
                    'reset_output': bool(event.get('reset_output')),
                },
                run_id=run_id,
            )
            return
        if kind == 'approval.requested':
            data = event.get('approval', {})
            store.update_run(run_id, status='waiting_approval')
            approval = store.create_approval(
                conversation_id,
                summary=data.get('description', 'Dangerous command requires approval'),
                details=data,
                run_id=run_id,
            )
            await publish(conversation_id, {'event': 'approval.created', 'approval': approval, 'run_id': run_id}, run_id=run_id)
            return
        if kind == 'approval.waiting':
            store.update_run(run_id, status='waiting_approval')
            await publish(conversation_id, {'event': 'approval.waiting', 'run_id': run_id}, run_id=run_id)
            return
        if kind == 'run.completed':
            output = event.get('output', '')
            final = output or buffer
            store.update_message(assistant_message_id, final, status='complete')
            store.update_run(run_id, status='complete')
            if job_id:
                store.update_job(job_id, status='complete', result_message_id=assistant_message_id)
            if conversation.get('link_mode') == 'attached':
                store.update_last_hermes_import_at(conversation_id, time.time())
            await publish(conversation_id, {'event': 'message.completed', 'message_id': assistant_message_id, 'content': final, 'run_id': run_id, 'job_id': job_id}, run_id=run_id)
            return
        if kind == 'run.failed':
            err = event.get('error', 'unknown error')
            rendered_error = _format_provider_error(err, prefix='Hermes run failed')
            store.update_message(assistant_message_id, rendered_error, status='error')
            store.update_run(run_id, status='error', error_text=err)
            if job_id:
                store.update_job(job_id, status='error', error_text=err, result_message_id=assistant_message_id)
            if conversation.get('link_mode') == 'attached':
                store.update_last_hermes_import_at(conversation_id, time.time())
            await publish(conversation_id, {'event': 'message.error', 'message_id': assistant_message_id, 'error': rendered_error, 'run_id': run_id, 'job_id': job_id, 'transient': _is_transient_provider_error(err)}, run_id=run_id)
            return
        await publish(conversation_id, dict(event, run_id=run_id, job_id=job_id), run_id=run_id)

    try:
        await hermes.run_turn(hermes_session_id, conversation_history, user_message, on_event)
    except HermesProviderError as exc:
        err = str(exc)
        rendered_error = _format_provider_error(err, prefix='Hermes provider error')
        store.update_message(assistant_message_id, rendered_error, status='error')
        store.update_run(run_id, status='error', error_text=err)
        if job_id:
            store.update_job(job_id, status='error', error_text=err, result_message_id=assistant_message_id)
        if conversation.get('link_mode') == 'attached':
            store.update_last_hermes_import_at(conversation_id, time.time())
        await publish(conversation_id, {'event': 'message.error', 'message_id': assistant_message_id, 'error': rendered_error, 'run_id': run_id, 'job_id': job_id, 'transient': _is_transient_provider_error(err)}, run_id=run_id)
    except Exception as exc:
        err = str(exc)
        rendered_error = _format_provider_error(err, prefix='Unexpected error')
        store.update_message(assistant_message_id, rendered_error, status='error')
        store.update_run(run_id, status='error', error_text=err)
        if job_id:
            store.update_job(job_id, status='error', error_text=err, result_message_id=assistant_message_id)
        if conversation.get('link_mode') == 'attached':
            store.update_last_hermes_import_at(conversation_id, time.time())
        await publish(conversation_id, {'event': 'message.error', 'message_id': assistant_message_id, 'error': rendered_error, 'run_id': run_id, 'job_id': job_id, 'transient': _is_transient_provider_error(err)}, run_id=run_id)


async def retry_interrupted_run(run: dict, *, approval_id: str | None = None) -> dict[str, str] | None:
    if not run:
        return None
    if run.get('status') != 'error' or run.get('error_text') != RESTART_INTERRUPTED_ERROR:
        return None
    conversation_id = run['conversation_id']
    if store.get_active_run(conversation_id):
        return None
    assistant_msg = store.add_message(
        conversation_id,
        'assistant',
        '',
        status='queued',
        metadata={'resumed_from_run_id': run['id'], 'approval_id': approval_id} if approval_id else {'resumed_from_run_id': run['id']},
    )
    replay_run = store.create_run(
        conversation_id,
        run['trigger_type'],
        trigger_text=run.get('trigger_text', ''),
        assistant_message_id=assistant_msg['id'],
        job_id=run.get('job_id'),
    )
    await publish(conversation_id, {'event': 'message.created', 'message': assistant_msg}, run_id=replay_run['id'])
    task = asyncio.create_task(
        run_turn(
            conversation_id,
            assistant_msg['id'],
            run.get('trigger_text', ''),
            replay_run['id'],
            job_id=run.get('job_id'),
        )
    )
    _track_background_task(active_run_tasks, replay_run['id'], task)
    return {'assistant_message_id': assistant_msg['id'], 'run_id': replay_run['id']}


async def run_job(job: dict) -> None:
    conversation_id = job['conversation_id']
    executor = job.get('executor', 'hermes')
    system_note = store.add_message(
        conversation_id,
        'system',
        f"[Background {executor} job started] {job['prompt']}",
        metadata={'job_id': job['id'], 'kind': 'background-job-status', 'executor': executor},
    )
    assistant_msg = store.add_message(
        conversation_id,
        'assistant',
        '',
        status='queued',
        metadata={'job_id': job['id'], 'kind': 'background-job-result', 'executor': executor},
    )
    run = store.create_run(conversation_id, f'{executor}_job', trigger_text=job['prompt'], assistant_message_id=assistant_msg['id'], job_id=job['id'])
    await publish(conversation_id, {'event': 'message.created', 'message': system_note})
    await publish(conversation_id, {'event': 'message.created', 'message': assistant_msg})
    await publish(conversation_id, {'event': 'job.started', 'job': store.get_job(job['id']), 'run_id': run['id']}, run_id=run['id'])
    if executor == 'codex':
        await run_codex_turn(conversation_id, assistant_msg['id'], job, run['id'])
        return
    await run_turn(conversation_id, assistant_msg['id'], job['prompt'], run['id'], job_id=job['id'])


async def run_codex_turn(conversation_id: str, assistant_message_id: str, job: dict, run_id: str) -> None:
    metadata = job.get('metadata', {})
    store.update_run(run_id, status='running')
    try:
        result = await run_codex_task(job_id=job['id'], prompt=job['prompt'], metadata=metadata)
        store.update_job(job['id'], status='running', result_message_id=assistant_message_id, artifact_dir=result['artifact_dir'])
        await publish(conversation_id, {'event': 'job.codex.started', 'job': store.get_job(job['id']), 'run_id': run_id}, run_id=run_id)
        final = result['final_output'] or 'Codex completed without a final message.'
        store.update_message(assistant_message_id, final, status='complete')
        merged_metadata = dict(metadata)
        merged_metadata['artifact_dir'] = result['artifact_dir']
        store.update_run(run_id, status='complete')
        store.update_job(job['id'], status='complete', result_message_id=assistant_message_id, artifact_dir=result['artifact_dir'], metadata=merged_metadata)
        await publish(conversation_id, {'event': 'message.completed', 'message_id': assistant_message_id, 'content': final, 'run_id': run_id, 'job_id': job['id']}, run_id=run_id)
    except CodexRunnerError as exc:
        err = str(exc)
        store.update_message(assistant_message_id, f'[Codex job failed] {err}', status='error')
        store.update_run(run_id, status='error', error_text=err)
        store.update_job(job['id'], status='error', error_text=err, result_message_id=assistant_message_id)
        await publish(conversation_id, {'event': 'message.error', 'message_id': assistant_message_id, 'error': err, 'run_id': run_id, 'job_id': job['id']}, run_id=run_id)


async def job_poller() -> None:
    while True:
        jobs = store.claim_due_jobs(worker_id, limit=3)
        for job in jobs:
            task = asyncio.create_task(run_job(job))
            _track_background_task(active_job_tasks, job['id'], task)
        await asyncio.sleep(2)


@app.get('/')
async def index():
    return FileResponse(static_dir / 'index.html')


@app.get('/health')
async def health():
    return {
        'ok': True,
        'db_path': str(DB_PATH),
        'worker_id': worker_id,
        'provider': 'local-hermes',
        'session_linkage_mode': 'session-aware-abstraction-layer',
        'startup_recovery_summary': startup_recovery_summary,
    }


@app.get('/api/provider/rate-limit')
async def provider_rate_limit_status():
    return hermes.get_rate_limit_snapshot()


@app.get('/api/conversations')
async def list_conversations():
    return store.list_conversations()


@app.post('/api/conversations')
async def create_conversation(body: ConversationCreate):
    conversation = store.create_conversation(body.title)
    title = conversation.get('title')
    session_id = conversation.get('hermes_session_id')
    if title and session_id:
        try:
            hermes_title = await hermes.set_session_title(session_id, title)
            conversation = store.update_conversation_sync(conversation['id'], hermes_title=hermes_title, sync_state='linked', sync_error=None)
        except HermesProviderError as exc:
            conversation = store.update_conversation_sync(conversation['id'], sync_state='sync_error', sync_error=str(exc))
    return conversation


@app.get('/api/hermes/sessions')
async def list_hermes_sessions(limit: int = 20):
    sessions = await hermes.list_sessions(limit=limit)
    attached_ids = {item['hermes_session_id'] for item in store.list_conversations() if item.get('hermes_session_id')}
    for item in sessions:
        item['already_attached'] = item.get('id') in attached_ids
    return sessions


@app.post('/api/conversations/attach')
async def attach_conversation(body: ConversationAttach):
    existing = store.get_conversation_by_hermes_session_id(body.hermes_session_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Hermes session already attached to conversation {existing['id']}")
    session = await hermes.get_session(body.hermes_session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Hermes session not found')
    hermes_title = await hermes.get_session_title(body.hermes_session_id)
    display_title = body.title or hermes_title or f"Attached {body.hermes_session_id[:12]}"
    return store.attach_conversation(body.hermes_session_id, display_title, hermes_title=hermes_title)


@app.patch('/api/conversations/{conversation_id}')
async def update_conversation(conversation_id: str, body: ConversationUpdate):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    conversation = store.update_conversation_title(conversation_id, body.title)
    session_id = conversation.get('hermes_session_id')
    if session_id:
        try:
            hermes_title = await hermes.set_session_title(session_id, body.title)
            conversation = store.update_conversation_sync(conversation_id, hermes_title=hermes_title, sync_state='linked', sync_error=None)
        except HermesProviderError as exc:
            conversation = store.update_conversation_sync(conversation_id, sync_state='sync_error', sync_error=str(exc))
    return conversation


@app.get('/api/conversations/{conversation_id}/messages')
async def get_messages(conversation_id: str):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    await sync_attached_transcript(conversation_id)
    return store.get_messages(conversation_id)


@app.get('/api/conversations/{conversation_id}/jobs')
async def get_jobs(conversation_id: str):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    return store.list_jobs(conversation_id)


@app.get('/api/conversations/{conversation_id}/approvals')
async def get_approvals(conversation_id: str):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    return store.list_approvals(conversation_id)


@app.get('/api/conversations/{conversation_id}/events/history')
async def event_history(conversation_id: str, limit: int = 100, after_id: int | None = None):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    return store.list_run_events(conversation_id, limit=limit, after_id=after_id)


@app.post('/api/conversations/{conversation_id}/messages')
async def post_message(conversation_id: str, body: MessageCreate):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    active_run = store.get_active_run(conversation_id, trigger_type='user_message')
    if active_run:
        raise HTTPException(
            status_code=409,
            detail={
                'message': 'Another message is already running for this conversation. Wait for it to finish or resolve its approval first.',
                'run_id': active_run['id'],
                'status': active_run['status'],
            },
        )
    user_msg = store.add_message(conversation_id, 'user', body.content, status='complete')
    assistant_msg = store.add_message(conversation_id, 'assistant', '', status='queued')
    run = store.create_run(conversation_id, 'user_message', trigger_text=body.content, assistant_message_id=assistant_msg['id'])
    await publish(conversation_id, {'event': 'message.created', 'message': user_msg}, run_id=run['id'])
    await publish(conversation_id, {'event': 'message.created', 'message': assistant_msg}, run_id=run['id'])
    task = asyncio.create_task(run_turn(conversation_id, assistant_msg['id'], body.content, run['id']))
    _track_background_task(active_run_tasks, run['id'], task)
    return {'ok': True, 'user_message_id': user_msg['id'], 'assistant_message_id': assistant_msg['id'], 'run_id': run['id']}


@app.post('/api/conversations/{conversation_id}/jobs')
async def create_job(conversation_id: str, body: JobCreate):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    metadata = {
        'thread_id': body.thread_id,
        'bead_id': body.bead_id,
        'reserve_paths': body.reserve_paths,
        'notify_to': body.notify_to,
        'reservation_reason': body.reservation_reason,
        'task': body.prompt,
    }
    job = store.create_job(conversation_id, body.prompt, delay_seconds=body.delay_seconds, executor=body.executor, metadata=metadata)
    note = store.add_message(
        conversation_id,
        'system',
        f"[Background {body.executor} job queued] {body.prompt}",
        metadata={'job_id': job['id'], 'kind': 'background-job-status', 'executor': body.executor},
    )
    await publish(conversation_id, {'event': 'message.created', 'message': note})
    await publish(conversation_id, {'event': 'job.queued', 'job': job})
    return job


@app.post('/api/approvals/{approval_id}/resolve')
async def resolve_approval(approval_id: str, body: ApprovalResolve):
    item = store.get_approval(approval_id)
    if not item:
        raise HTTPException(status_code=404, detail='approval not found')
    if item.get('status') != 'pending':
        raise HTTPException(status_code=409, detail=f"approval is not pending (status={item.get('status')})")
    details = item.get('details', {})
    provider_approval_id = details.get('approval_id', approval_id)
    provider_result = await hermes.resolve_approval(provider_approval_id, body.resolution)
    resolved = store.resolve_approval(approval_id, body.resolution)
    if not resolved:
        raise HTTPException(status_code=404, detail='approval not found after provider resolve')

    replay = None
    run = store.get_run(item['run_id']) if item.get('run_id') else {}
    if provider_result.get('resume_required') and provider_result.get('decision') != 'deny':
        replay = await retry_interrupted_run(run, approval_id=approval_id)

    payload = {
        'event': 'approval.resolved',
        'approval': resolved,
        'provider_result': provider_result,
        'session_id': details.get('session_id'),
    }
    if replay:
        payload['replay'] = replay
    await publish(resolved['conversation_id'], payload, run_id=resolved.get('run_id'))
    return {'approval': resolved, 'provider_result': provider_result, 'replay': replay}


@app.get('/api/conversations/{conversation_id}/events')
async def events(conversation_id: str, after_id: int | None = None, last_event_id: str | None = None):
    async def stream():
        cursor = after_id
        if cursor is None and last_event_id:
            try:
                cursor = int(last_event_id)
            except ValueError:
                cursor = None
        queue = await broker.subscribe(conversation_id)
        last_replayed_id = cursor
        try:
            if cursor is not None:
                history = store.list_run_events(conversation_id, limit=500, after_id=cursor)
                for item in history:
                    payload = dict(item['payload'])
                    payload['_event_id'] = item['id']
                    last_replayed_id = item['id']
                    yield {'id': str(item['id']), 'data': json.dumps(payload)}
            while True:
                event = await queue.get()
                event_id = event.get('_event_id')
                if last_replayed_id is not None and event_id is not None and event_id <= last_replayed_id:
                    continue
                if event_id is not None:
                    last_replayed_id = event_id
                yield {'id': str(event_id) if event_id is not None else None, 'data': json.dumps(event)}
        finally:
            await broker.unsubscribe(conversation_id, queue)

    return EventSourceResponse(stream())
