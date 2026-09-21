import asyncio
import contextlib
import hashlib
import json
import logging
import re
import secrets
import time
from typing import Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.config import ROOT, Settings
from app.errors import AppError
from app.pipeline import analyse
from app.providers import Providers
from app.passages import video_id
from app.store import MemoryStore, RedisStore

logging.basicConfig(level=logging.INFO)
# HTTP clients must not log query strings containing the YouTube key.
logging.getLogger('httpx').setLevel(logging.WARNING)
log = logging.getLogger('vq')
TERMINAL = {'complete', 'error', 'cancelled'}


class Submission(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class Interaction(BaseModel):
    event: Literal['quote_copy', 'timestamp_click']
    job_id: str = Field(min_length=20, max_length=64)
    rank: int = Field(ge=1, le=5)


def create_app(settings=None, store=None, providers=None):
    settings = settings or Settings()
    store = store or (RedisStore(settings.redis_url) if settings.redis_url else MemoryStore())
    providers = providers or Providers(settings, store)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await store.close()

    app = FastAPI(title='Quote Finder', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.settings = store, settings
    # Production accepts only the published extension IDs configured by the owner.
    # Local development accepts unpacked Chrome extensions so their generated IDs
    # do not have to be known before the first load.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.extension_origins),
        allow_origin_regex=None if settings.deployed else r'chrome-extension://[a-p]{32}',
        allow_methods=['GET', 'POST', 'DELETE', 'OPTIONS'],
        allow_headers=['content-type'],
        max_age=3600,
    )

    def origin_allowed(request, origin):
        if not origin:
            return True
        normalized = origin.rstrip('/')
        if normalized == str(request.base_url).rstrip('/'):
            return True
        if normalized in settings.extension_origins:
            return True
        return not settings.deployed and bool(re.fullmatch(r'chrome-extension://[a-p]{32}', normalized))

    @app.middleware('http')
    async def secure(request, call_next):
        if request.method in ('POST', 'DELETE'):
            origin = request.headers.get('origin')
            if not origin_allowed(request, origin):
                return JSONResponse({'error': {'code': 'origin_rejected', 'message': 'Please submit from this app.', 'retryable': False}}, status_code=403)
            try:
                size = int(request.headers.get('content-length', '0') or 0)
            except ValueError:
                size = 8193
            if size > 8192 or size < 0:
                return JSONResponse({'error': AppError('invalid_url').payload()}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse({'error': exc.payload()}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'error': AppError('invalid_url').payload()}, status_code=422)

    @app.exception_handler(RedisError)
    async def storage_error(request, exc):
        return JSONResponse({'error': AppError('storage_unavailable', True).payload()}, status_code=503)

    @app.get('/')
    async def index():
        return FileResponse(ROOT / 'static/index.html')

    @app.get('/api/health')
    async def health():
        return {'ready': not settings.missing(), 'missing': settings.missing()}

    def ip_key(request):
        # Vercel overwrites x-vercel-forwarded-for; ignore user-controlled forwarded
        # headers locally. Run local uvicorn with --no-proxy-headers.
        ip = request.headers.get('x-vercel-forwarded-for', '') if settings.deployed else ''
        ip = ip or (request.client.host if request.client else 'unknown')
        return hashlib.sha256(ip.encode()).hexdigest()

    async def get_job(job_id):
        job = await store.get('job:' + job_id)
        if job is None:
            raise AppError('not_found', False, 404)
        if job['status'] not in TERMINAL and time.time() > job['deadline']:
            job.update(status='error', error=AppError('timeout', True).payload())
            await store.set('job:' + job_id, job)
        if await store.get('cancel:' + job_id) and job['status'] not in TERMINAL:
            job.update(status='cancelled')
        return job

    @app.post('/api/analyses', status_code=201)
    async def create(submission: Submission, request: Request):
        vid = video_id(submission.url)
        if settings.missing():
            raise AppError('not_configured', False, 503)
        if not await store.limit('ip:' + ip_key(request), settings.per_ip_hour, 3600):
            raise AppError('rate_limited', True, 429)
        if not await store.limit('global-submissions', 30, 60):
            raise AppError('busy', True, 429)
        job_id = secrets.token_urlsafe(24)
        job = {'id': job_id, 'video_id': vid, 'status': 'pending', 'stage': 'checking',
               'message': 'Checking video', 'deadline': time.time() + settings.timeout}
        await store.set('job:' + job_id, job)
        return job

    @app.get('/api/analyses/{job_id}')
    async def status(job_id: str):
        return await get_job(job_id)

    @app.delete('/api/analyses/{job_id}')
    async def cancel(job_id: str):
        job = await get_job(job_id)
        if job['status'] not in TERMINAL:
            await store.set('cancel:' + job_id, True)
            job.update(status='cancelled')
        return job

    @app.post('/api/events', status_code=204)
    async def interaction(event: Interaction, request: Request):
        job = await get_job(event.job_id)
        if job['status'] != 'complete' or event.rank > len(job['result']['quotes']):
            raise AppError('not_found', False, 404)
        if await store.limit('events:' + ip_key(request), 120, 60):
            log.info(json.dumps({'event': event.event, 'rank': event.rank}))
        return None

    @app.post('/api/analyses/{job_id}/run')
    async def run(job_id: str, request: Request):
        job = await get_job(job_id)
        if job['status'] in TERMINAL:
            return JSONResponse(job)
        if not await store.set('lock:' + job_id, True, ttl=300, nx=True):
            raise AppError('busy', True, 409)

        async def events():
            queue = asyncio.Queue()

            async def progress(stage, message):
                if await store.get('cancel:' + job_id):
                    raise asyncio.CancelledError()
                job.update(status='running', stage=stage, message=message)
                await store.set('job:' + job_id, job)
                await queue.put(dict(job))

            async def work():
                try:
                    async with asyncio.timeout(max(.01, job['deadline'] - time.time())):
                        result = await analyse(job['video_id'], settings, store, providers, progress)
                        if await store.get('cancel:' + job_id):
                            raise asyncio.CancelledError()
                        job.update(status='complete', result=result)
                except asyncio.CancelledError:
                    job.update(status='cancelled')
                except TimeoutError:
                    job.update(status='error', error=AppError('timeout', True).payload())
                except AppError as exc:
                    job.update(status='error', error=exc.payload())
                except Exception as exc:
                    # No provider response, secrets, or transcript text in logs.
                    log.error('analysis_exception type=%s', type(exc).__name__)
                    job.update(status='error', error=AppError('internal', True).payload())
                finally:
                    try:
                        await store.set('job:' + job_id, job)
                    except Exception:
                        job.update(status='error', error=AppError('storage_unavailable', True).payload())
                    if job['status'] != 'complete':
                        log.info(json.dumps({'event': 'analysis_ended', 'status': job['status'], 'error': job.get('error', {}).get('code')}))
                    await queue.put(dict(job))

            task = asyncio.create_task(work())
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=.5)
                        yield json.dumps(event) + '\n'
                        if event['status'] in TERMINAL:
                            break
                    except TimeoutError:
                        if await request.is_disconnected() or await store.get('cancel:' + job_id):
                            task.cancel()
                        else:
                            yield '\n'  # Keep the streaming request active on Vercel.
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        return StreamingResponse(events(), media_type='application/x-ndjson', headers={'X-Accel-Buffering': 'no'})

    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
    return app


app = create_app()
