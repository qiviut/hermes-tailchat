from __future__ import annotations

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .broker import broker
from .config import APP_TITLE, DB_PATH
from .hermes_provider import HermesProviderError, LocalHermesProvider
from .store import Store
import app.store as store_module


class ConversationCreate(BaseModel):
    title: str | None = None


class MessageCreate(BaseModel):
    content: str


class JobCreate(BaseModel):
    prompt: str = Field(min_length=1)
    delay_seconds: int = 0


class ApprovalResolve(BaseModel):
    resolution: str


store = Store(DB_PATH)
store_module.store = store
hermes = LocalHermesProvider()
worker_id = f"tailchat-{socket.gethostname()}-{Path(DB_PATH).name}"
poll_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poll_task
    poll_task = asyncio.create_task(job_poller())
    try:
        yield
    finally:
        if poll_task:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=APP_TITLE, lifespan=lifespan)
static_dir = Path(__file__).resolve().parent / 'static'
app.mount('/static', StaticFiles(directory=static_dir), name='static')


async def publish(conversation_id: str, event: dict, run_id: str | None = None):
    store.append_run_event(conversation_id, run_id, event.get('event', 'unknown'), json.dumps(event))
    await broker.publish(conversation_id, event)


async def run_turn(conversation_id: str, assistant_message_id: str, user_message: str, run_id: str, job_id: str | None = None) -> None:
    messages = store.get_messages(conversation_id)
    history = [
        {'role': m['role'], 'content': m['content']}
        for m in messages
        if m['id'] != assistant_message_id and m['status'] != 'queued' and m['role'] in {'user', 'assistant', 'system'}
    ]
    conversation_history = history[:-1] if history else []
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
        if kind == 'approval.requested':
            data = event.get('approval', {})
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
            await publish(conversation_id, {'event': 'message.completed', 'message_id': assistant_message_id, 'content': final, 'run_id': run_id, 'job_id': job_id}, run_id=run_id)
            return
        if kind == 'run.failed':
            err = event.get('error', 'unknown error')
            store.update_message(assistant_message_id, f'[Hermes run failed] {err}', status='error')
            store.update_run(run_id, status='error', error_text=err)
            if job_id:
                store.update_job(job_id, status='error', error_text=err, result_message_id=assistant_message_id)
            await publish(conversation_id, {'event': 'message.error', 'message_id': assistant_message_id, 'error': err, 'run_id': run_id, 'job_id': job_id}, run_id=run_id)
            return
        await publish(conversation_id, dict(event, run_id=run_id, job_id=job_id), run_id=run_id)

    try:
        await hermes.run_turn(conversation_id, conversation_history, user_message, on_event)
    except HermesProviderError as exc:
        err = str(exc)
        store.update_message(assistant_message_id, f'[Hermes provider error] {err}', status='error')
        store.update_run(run_id, status='error', error_text=err)
        if job_id:
            store.update_job(job_id, status='error', error_text=err, result_message_id=assistant_message_id)
        await publish(conversation_id, {'event': 'message.error', 'message_id': assistant_message_id, 'error': err, 'run_id': run_id, 'job_id': job_id}, run_id=run_id)
    except Exception as exc:
        err = str(exc)
        store.update_message(assistant_message_id, f'[Unexpected error] {err}', status='error')
        store.update_run(run_id, status='error', error_text=err)
        if job_id:
            store.update_job(job_id, status='error', error_text=err, result_message_id=assistant_message_id)
        await publish(conversation_id, {'event': 'message.error', 'message_id': assistant_message_id, 'error': err, 'run_id': run_id, 'job_id': job_id}, run_id=run_id)


async def run_job(job: dict) -> None:
    conversation_id = job['conversation_id']
    system_note = store.add_message(
        conversation_id,
        'system',
        f"[Background job started] {job['prompt']}",
        metadata={'job_id': job['id'], 'kind': 'background-job-status'},
    )
    assistant_msg = store.add_message(
        conversation_id,
        'assistant',
        '',
        status='queued',
        metadata={'job_id': job['id'], 'kind': 'background-job-result'},
    )
    run = store.create_run(conversation_id, 'job', trigger_text=job['prompt'], assistant_message_id=assistant_msg['id'], job_id=job['id'])
    await publish(conversation_id, {'event': 'message.created', 'message': system_note})
    await publish(conversation_id, {'event': 'message.created', 'message': assistant_msg})
    await publish(conversation_id, {'event': 'job.started', 'job': store.list_jobs(conversation_id)[0], 'run_id': run['id']}, run_id=run['id'])
    await run_turn(conversation_id, assistant_msg['id'], job['prompt'], run['id'], job_id=job['id'])


async def job_poller() -> None:
    while True:
        jobs = store.claim_due_jobs(worker_id, limit=3)
        for job in jobs:
            asyncio.create_task(run_job(job))
        await asyncio.sleep(2)


@app.get('/')
async def index():
    return FileResponse(static_dir / 'index.html')


@app.get('/health')
async def health():
    return {'ok': True, 'db_path': str(DB_PATH), 'worker_id': worker_id, 'provider': 'local-hermes'}


@app.get('/api/conversations')
async def list_conversations():
    return store.list_conversations()


@app.post('/api/conversations')
async def create_conversation(body: ConversationCreate):
    return store.create_conversation(body.title)


@app.get('/api/conversations/{conversation_id}/messages')
async def get_messages(conversation_id: str):
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
async def event_history(conversation_id: str, limit: int = 100):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    return store.list_run_events(conversation_id, limit=limit)


@app.post('/api/conversations/{conversation_id}/messages')
async def post_message(conversation_id: str, body: MessageCreate):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    user_msg = store.add_message(conversation_id, 'user', body.content, status='complete')
    assistant_msg = store.add_message(conversation_id, 'assistant', '', status='queued')
    run = store.create_run(conversation_id, 'user_message', trigger_text=body.content, assistant_message_id=assistant_msg['id'])
    await publish(conversation_id, {'event': 'message.created', 'message': user_msg}, run_id=run['id'])
    await publish(conversation_id, {'event': 'message.created', 'message': assistant_msg}, run_id=run['id'])
    asyncio.create_task(run_turn(conversation_id, assistant_msg['id'], body.content, run['id']))
    return {'ok': True, 'user_message_id': user_msg['id'], 'assistant_message_id': assistant_msg['id'], 'run_id': run['id']}


@app.post('/api/conversations/{conversation_id}/jobs')
async def create_job(conversation_id: str, body: JobCreate):
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail='conversation not found')
    job = store.create_job(conversation_id, body.prompt, delay_seconds=body.delay_seconds)
    note = store.add_message(
        conversation_id,
        'system',
        f"[Background job queued] {body.prompt}",
        metadata={'job_id': job['id'], 'kind': 'background-job-status'},
    )
    await publish(conversation_id, {'event': 'message.created', 'message': note})
    await publish(conversation_id, {'event': 'job.queued', 'job': job})
    return job


@app.post('/api/approvals/{approval_id}/resolve')
async def resolve_approval(approval_id: str, body: ApprovalResolve):
    approvals = []
    # find approval by scanning known approvals in DB via current conversations
    for conversation in store.list_conversations():
        for item in store.list_approvals(conversation['id']):
            if item['id'] == approval_id:
                approvals.append(item)
                break
    if not approvals:
        raise HTTPException(status_code=404, detail='approval not found')
    item = approvals[0]
    details = item.get('details', {})
    provider_approval_id = details.get('approval_id', approval_id)
    provider_result = await hermes.resolve_approval(provider_approval_id, body.resolution)
    resolved = store.resolve_approval(approval_id, body.resolution)
    if not resolved:
        raise HTTPException(status_code=404, detail='approval not found after provider resolve')
    await publish(resolved['conversation_id'], {'event': 'approval.resolved', 'approval': resolved, 'provider_result': provider_result, 'session_id': details.get('session_id')}, run_id=resolved.get('run_id'))
    return resolved


@app.get('/api/conversations/{conversation_id}/events')
async def events(conversation_id: str):
    async def stream():
        queue = await broker.subscribe(conversation_id)
        try:
            while True:
                event = await queue.get()
                yield {'data': json.dumps(event)}
        finally:
            await broker.unsubscribe(conversation_id, queue)

    return EventSourceResponse(stream())
