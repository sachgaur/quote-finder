import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import AppError
from app.passages import Candidate, duration_seconds, prepare, rank, video_id
from app.pipeline import analyse
from app.providers import Providers, retry_delay
from app.store import MemoryStore
from main import create_app
from tests.fixtures import FixtureProviders, SENTENCES

VID = 'abcdefghijk'
SETTINGS = Settings(youtube_key='test-youtube', jev_key='test-jev', redis_url='', deployed=False)


@pytest.mark.parametrize('url', [f'https://youtube.com/watch?v={VID}&list=ignored', f'https://youtu.be/{VID}?t=12', f'https://www.youtube.com/shorts/{VID}', f'https://m.youtube.com/watch?v={VID}'])
def test_url_variants(url):
    assert video_id(url) == VID


@pytest.mark.parametrize('url', ['https://youtube.com.evil.test/watch?v=abcdefghijk', 'https://youtube.com/playlist?list=x', 'file:///etc/passwd', 'https://youtube.com@evil.test/watch?v=abcdefghijk', 'https://youtu.be/abc', 'https://youtube.com/watch?v=abcdefghijk&v=other', 'https://youtube.com:wat/watch?v=abcdefghijk'])
def test_invalid_urls(url):
    with pytest.raises(AppError, match='valid YouTube'):
        video_id(url)


def test_duration():
    assert duration_seconds('PT2H') == 7200
    assert duration_seconds('PT2H0M1S') == 7201
    assert duration_seconds('P1DT1S') == 86401
    for invalid in ('', 'P', 'PT', 'PT0S', 'PT-1S'):
        with pytest.raises(AppError):
            duration_seconds(invalid)


def test_source_spans_and_markers():
    snippets = [{'text': 'Dr. Jones has an idea. Keep the words', 'start': 10, 'duration': 5},
                {'text': 'exactly as spoken. [Music] Never jump over missing words.', 'start': 15, 'duration': 8}]
    candidates = prepare(snippets)
    source = ' '.join(x['text'] for x in snippets)
    for c in candidates:
        assert c.text == source[c.start_char:c.end_char]
        assert '[Music]' not in c.text
        assert not ('spoken' in c.text and 'Never' in c.text)
    assert any(c.text == 'Dr. Jones has an idea.' for c in candidates)
    joined = next(c for c in candidates if c.text == 'Keep the words exactly as spoken.')
    assert joined.start_seconds == 10 and joined.end_seconds == 23


def test_unpunctuated_captions_and_limits():
    text = ' '.join(f'word{i}' for i in range(150))
    candidates = prepare([{'text': text, 'start': 0, 'duration': 30}])
    assert all(c.text in text for c in candidates)
    assert len(candidates) > 1
    with pytest.raises(AppError) as exc:
        prepare([{'text': text, 'start': 0, 'duration': 30}], max_candidates=2)
    assert exc.value.code == 'limit_exceeded'


def test_caption_pauses_form_sentence_boundaries_and_keep_timestamps():
    snippets = [
        {'text': 'a useful question changes what you notice', 'start': 3, 'duration': 3},
        {'text': 'not only what you know', 'start': 6.1, 'duration': 2},
        {'text': 'the next thought begins after a real pause', 'start': 10, 'duration': 3},
        {'text': 'and remains part of that thought', 'start': 13.1, 'duration': 2},
    ]
    candidates = prepare(snippets)
    first = next(c for c in candidates if c.text == 'a useful question changes what you notice not only what you know')
    second = next(c for c in candidates if c.text == 'the next thought begins after a real pause and remains part of that thought')
    assert (first.start_seconds, first.end_seconds) == (3, 8.1)
    assert (second.start_seconds, second.end_seconds) == (10, 15.1)
    assert first.context_after == second.text
    assert second.context_before == first.text


def test_short_pause_fragment_stays_with_following_speech():
    snippets = [
        {'text': 'Well', 'start': 0, 'duration': .5},
        {'text': 'this is the complete thought without punctuation', 'start': 2, 'duration': 4},
    ]
    candidates = prepare(snippets)
    assert any(c.text == 'Well this is the complete thought without punctuation' for c in candidates)
    assert not any(c.text == 'Well' for c in candidates)


def test_long_unpunctuated_caption_uses_exact_contiguous_word_spans():
    text = ' '.join(f'word{i}' for i in range(95))
    candidates = prepare([{'text': text, 'start': 0, 'duration': 30}])
    singles = [c for c in candidates if not c.context_before or not c.context_after]
    assert candidates
    assert all(c.text in text for c in candidates)
    assert all(len(c.text.split()) <= 84 for c in candidates)
    assert any(len(c.text.split()) == 28 for c in singles)


def test_closing_quote_stays_in_sentence():
    text = 'She said “Keep the original words.” Then the next sentence begins.'
    candidates = prepare([{'text': text, 'start': 0, 'duration': 8}])
    assert any(c.text == 'She said “Keep the original words.”' for c in candidates)


def test_rank_unrounded_fidelity_overlap_duplicate():
    def c(text, start, end):
        return Candidate(text, start, end, start, end, '', '')
    a = c('The useful words stay with you.', 0, 10)
    overlap = c('The useful words stay with you. A second sentence.', 0, 20)
    duplicate = c('The useful words stay with you!', 100, 120)
    other = c('A new idea makes room for discovery.', 200, 220)
    bad = c('A misleading thought.', 300, 320)
    scored = [{'candidate': x, 'score': score, 'fidelity': fidelity, 'confidence': .9} for x, score, fidelity in [(a, 8.71, .99), (overlap, 8.70, .99), (duplicate, 8.5, .99), (other, 8.72, .99), (bad, 10, .2)]]
    result = rank(scored, VID)
    assert [r['text'] for r in result] == [other.text, a.text]
    assert result[0]['source_url'].endswith('&t=200s')


@pytest.mark.asyncio
async def test_metadata_two_hour_boundary(monkeypatch):
    provider = Providers(SETTINGS, MemoryStore())
    state = {'duration': 'PT2H', 'liveBroadcastContent': 'none'}
    async def fake(*args, **kwargs):
        return {'items': [{'snippet': {'title': 'T', 'channelTitle': 'C', 'liveBroadcastContent': state['liveBroadcastContent']}, 'contentDetails': {'duration': state['duration']}}]}
    monkeypatch.setattr('app.providers.request_json', fake)
    assert (await provider.metadata(VID))['duration'] == 7200
    state['duration'] = 'PT2H1S'
    with pytest.raises(AppError) as exc:
        await provider.metadata(VID)
    assert exc.value.code == 'too_long'
    state['liveBroadcastContent'] = 'live'
    with pytest.raises(AppError) as exc:
        await provider.metadata(VID)
    assert exc.value.code == 'live_video'


@pytest.mark.asyncio
@pytest.mark.parametrize(('exception', 'code'), [('TranscriptsDisabled', 'no_captions'), ('NoTranscriptFound', 'no_english'), ('RequestBlocked', 'transcript_blocked'), ('IpBlocked', 'transcript_blocked')])
async def test_caption_errors(monkeypatch, exception, code):
    provider = Providers(SETTINGS, MemoryStore())
    def fail(vid):
        raise type(exception, (Exception,), {})()
    monkeypatch.setattr(provider, '_transcript', fail)
    with pytest.raises(AppError) as exc:
        await provider.transcript(VID)
    assert exc.value.code == code


@pytest.mark.asyncio
async def test_jev_contract_and_normalization():
    provider = Providers(SETTINGS, MemoryStore())
    candidate = Candidate('The original text stays exactly here.', 10, 20, 0, 35, 'Before.', 'After.')
    def handler(request):
        data = json.loads(request.content)
        assert str(request.url) == 'https://api.typesafe.ai/v1/systemone'
        assert data['model'] == 'jev-1.13.0'
        assert data['state']['candidate_0']['candidate_text'] == candidate.text
        assert len(data['questions']) == 4
        assert len(data['questions']['0_insight']['criteria']) == 5
        return httpx.Response(200, json={'model': data['model'], 'answers': {
            **{f'0_{dim}': {'type': 'score', 'score': 3.6, 'confidence': .8} for dim in ('insight', 'memorability', 'clarity')},
            '0_fidelity': {'type': 'noul', 'noul': .96}}, 'usage': {'input_tokens': 123}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        scored, tokens = await provider.score_batch(client, [candidate])
    assert scored[0]['score'] == pytest.approx(9)
    assert tokens == 123


@pytest.mark.asyncio
async def test_pipeline_cache_and_failure():
    store, provider = MemoryStore(), FixtureProviders()
    async def progress(*args): pass
    first = await analyse(VID, SETTINGS, store, provider, progress)
    calls = provider.scoring_calls
    second = await analyse(VID, SETTINGS, store, provider, progress)
    assert second['cached'] and provider.scoring_calls == calls
    assert len(first['quotes']) == 5
    assert all(any(q['text'] == s for s in SENTENCES) for q in first['quotes'])
    class Failed(FixtureProviders):
        async def score_batch(self, client, candidates):
            raise AppError('scoring_unavailable', True)
    with pytest.raises(AppError):
        await analyse(VID, SETTINGS, MemoryStore(), Failed(), progress)


def test_end_to_end_job_and_safe_static():
    with TestClient(create_app(SETTINGS, providers=FixtureProviders())) as client:
        assert client.get('/').status_code == 200
        assert client.get('/.env').status_code == 404
        assert client.get('/static/../.env').status_code == 404
        response = client.post('/api/analyses', json={'url': f'https://youtu.be/{VID}'})
        assert response.status_code == 201
        job_id = response.json()['id']
        response = client.post(f'/api/analyses/{job_id}/run')
        events = [json.loads(line) for line in response.text.splitlines() if line]
        assert [e['stage'] for e in events[:-1]] == ['checking', 'transcript', 'scoring', 'preparing']
        assert events[-1]['status'] == 'complete'
        assert len(events[-1]['result']['quotes']) == 5
        assert client.get(f'/api/analyses/{job_id}').json()['status'] == 'complete'
        assert 'test-youtube' not in response.text and 'test-jev' not in response.text


@pytest.mark.parametrize(('provider', 'expected'), [(FixtureProviders(failure='transcript_blocked'), 'error'), (FixtureProviders(fidelity=.1), 'complete')])
def test_error_and_empty_jobs(provider, expected):
    with TestClient(create_app(SETTINGS, providers=provider)) as client:
        job = client.post('/api/analyses', json={'url': f'https://youtu.be/{VID}'}).json()
        events = client.post(f'/api/analyses/{job["id"]}/run').text.splitlines()
        final = json.loads(events[-1])
        assert final['status'] == expected
        if expected == 'complete':
            assert final['result']['quotes'] == []
        else:
            assert final['error']['code'] == 'transcript_blocked'


def test_cancel_before_execution():
    provider = FixtureProviders()
    with TestClient(create_app(SETTINGS, providers=provider)) as client:
        job = client.post('/api/analyses', json={'url': f'https://youtu.be/{VID}'}).json()
        assert client.delete(f'/api/analyses/{job["id"]}').json()['status'] == 'cancelled'
        assert client.post(f'/api/analyses/{job["id"]}/run').json()['status'] == 'cancelled'
        assert provider.scoring_calls == 0


def test_timeout_and_missing_setup():
    settings = replace(SETTINGS, timeout=.05)
    with TestClient(create_app(settings, providers=FixtureProviders(delay=.2))) as client:
        job = client.post('/api/analyses', json={'url': f'https://youtu.be/{VID}'}).json()
        events = client.post(f'/api/analyses/{job["id"]}/run').text.splitlines()
        assert json.loads(events[-1])['error']['code'] == 'timeout'
    with TestClient(create_app(replace(SETTINGS, youtube_key='', jev_key=''))) as client:
        assert not client.get('/api/health').json()['ready']
        response = client.post('/api/analyses', json={'url': f'https://youtu.be/{VID}'})
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'not_configured'


def test_origin_and_rate_limits():
    with TestClient(create_app(replace(SETTINGS, per_ip_hour=1), providers=FixtureProviders())) as client:
        assert client.post('/api/analyses', headers={'Origin': 'https://evil.test'}, json={'url': f'https://youtu.be/{VID}'}).status_code == 403
        assert client.post('/api/analyses', json={'url': f'https://youtu.be/{VID}'}).status_code == 201
        assert client.post('/api/analyses', json={'url': f'https://youtu.be/{VID}'}).status_code == 429


def test_local_extension_origin_is_allowed_and_receives_cors_headers():
    extension_origin = 'chrome-extension://' + 'a' * 32
    with TestClient(create_app(SETTINGS, providers=FixtureProviders())) as client:
        response = client.post('/api/analyses', headers={'Origin': extension_origin}, json={'url': f'https://youtu.be/{VID}'})
        assert response.status_code == 201
        assert response.headers['access-control-allow-origin'] == extension_origin


def test_deployed_backend_requires_configured_extension_origin():
    allowed = 'chrome-extension://' + 'b' * 32
    deployed = replace(SETTINGS, deployed=True, redis_url='redis://configured-for-test', extension_origins=(allowed,))
    store = MemoryStore()
    with TestClient(create_app(deployed, store=store, providers=FixtureProviders())) as client:
        assert client.post('/api/analyses', headers={'Origin': 'chrome-extension://' + 'a' * 32}, json={'url': f'https://youtu.be/{VID}'}).status_code == 403
        response = client.post('/api/analyses', headers={'Origin': allowed}, json={'url': f'https://youtu.be/{VID}'})
        assert response.status_code == 201
        assert response.headers['access-control-allow-origin'] == allowed


def test_retry_after_is_respected():
    assert retry_delay('7', 0) == 7
    assert retry_delay(None, 2) == 2
