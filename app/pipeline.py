import asyncio
import hashlib
import json
import logging
import time

import httpx

from .passages import prepare, rank
from .providers import RUBRIC_VERSION

log = logging.getLogger('vq')


async def analyse(vid, settings, store, providers, progress):
    started = time.monotonic()
    await progress('checking', 'Checking video')
    video = await providers.metadata(vid)
    await progress('transcript', 'Fetching transcript')
    retrieval_start = time.monotonic()
    transcript = await providers.transcript(vid)
    retrieval_ms = round((time.monotonic() - retrieval_start) * 1000)
    candidates = prepare(transcript['snippets'], settings.max_characters, settings.max_candidates)
    fingerprint = hashlib.sha256(json.dumps(transcript, sort_keys=True).encode()).hexdigest()
    cache_key = f'cache:{vid}:{fingerprint}:{settings.model}:{RUBRIC_VERSION}:{settings.fidelity_threshold}:{settings.confidence_threshold}'
    cached = await store.get(cache_key)
    if cached is not None:
        await progress('preparing', 'Preparing results')
        log.info(json.dumps({'event': 'analysis_complete', 'cached': True, 'retrieval_ms': retrieval_ms,
            'duration_ms': round((time.monotonic() - started) * 1000), 'input_tokens': 0, 'estimated_cost_usd': 0,
            'quote_count': len(cached['quotes']), 'model': settings.model, 'rubric': RUBRIC_VERSION}))
        return {**cached, 'video': video, 'cached': True}
    await progress('scoring', 'Finding quotes')
    batches = [candidates[i:i + settings.batch_size] for i in range(0, len(candidates), settings.batch_size)]
    queue = asyncio.Queue()
    for batch in batches:
        queue.put_nowait(batch)
    scored, tokens = [], 0
    scoring_start = time.monotonic()
    async with httpx.AsyncClient(timeout=30) as client:
        async def worker():
            nonlocal tokens
            while not queue.empty():
                batch = queue.get_nowait()
                result, usage = await providers.score_batch(client, batch)
                scored.extend(result)
                tokens += usage
        # Cancel sibling workers immediately on any failure; never rank a partial set.
        workers = [asyncio.create_task(worker()) for _ in range(min(settings.concurrency, len(batches)))]
        try:
            await asyncio.gather(*workers)
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
    await progress('preparing', 'Preparing results')
    result = {'video': video, 'quotes': rank(scored, vid, settings.fidelity_threshold, settings.confidence_threshold),
              'transcript': {'language': transcript['language'], 'is_generated': transcript['is_generated']},
              'model': settings.model, 'rubric_version': RUBRIC_VERSION, 'cached': False}
    await store.set(cache_key, result, ttl=600)
    log.info(json.dumps({'event': 'analysis_complete', 'retrieval_ms': retrieval_ms,
        'scoring_ms': round((time.monotonic() - scoring_start) * 1000), 'duration_ms': round((time.monotonic() - started) * 1000),
        'candidates': len(candidates), 'input_tokens': tokens, 'estimated_cost_usd': tokens / 1_000_000 * settings.input_price_per_million,
        'quote_count': len(result['quotes']), 'model': settings.model, 'rubric': RUBRIC_VERSION}))
    return result
