'use strict';

const CONTEXT_KEY = 'quoteFinderContext';
const API_BASE = globalThis.QUOTE_FINDER_CONFIG.apiBase.replace(/\/$/, '');
const STAGES = ['checking', 'transcript', 'scoring', 'preparing'];
const $ = (id) => document.getElementById(id);
let context = null;
let active = null;
let lastRequestToken = null;
let resultJobId = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function timecode(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  return value >= 3600
    ? `${Math.floor(value / 3600)}:${String(Math.floor(value % 3600 / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
    : `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}

function announce(text) { $('announcement').textContent = text; }
function showError(message) { $('error').textContent = message; $('error').hidden = false; }
function setProgress(job) {
  $('status').textContent = job.message || 'Finding quotes';
  const current = STAGES.indexOf(job.stage);
  document.querySelectorAll('.progress li').forEach((item, index) => {
    item.classList.toggle('active', index === current);
    item.classList.toggle('done', index < current);
  });
}

async function responseJson(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || 'Quote Finder could not complete this request.');
  return data;
}

function track(event, rank) {
  if (!resultJobId) return;
  fetch(`${API_BASE}/api/events`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({event, rank, job_id: resultJobId}), keepalive: true
  }).catch(() => {});
}

async function copyQuote(button, quote, video) {
  try {
    await navigator.clipboard.writeText(`“${quote.text}”\n— ${video.title}\n${quote.source_url}`);
    button.textContent = 'Copied ✓';
    track('quote_copy', quote.rank);
    announce('Quote and source copied.');
    setTimeout(() => { button.textContent = 'Copy'; }, 1800);
  } catch {
    announce('Clipboard access was denied.');
  }
}

function renderResults(result) {
  $('results').hidden = false;
  $('ready').hidden = true;
  $('no-results').hidden = result.quotes.length > 0;
  $('count').textContent = `${String(result.quotes.length).padStart(2, '0')} QUOTES`;
  $('summary').textContent = `${result.video.title} · ${result.video.channel} · ${timecode(result.video.duration)}`;
  const cards = result.quotes.map((quote) => {
    const card = element('article', 'quote');
    const main = element('div', 'quote-main');
    const meta = element('div', 'meta');
    meta.append(element('span', 'rank', `QUOTE ${String(quote.rank).padStart(2, '0')}`), element('span', 'score', `${quote.score.toFixed(1)} / 10`));
    const actions = element('div', 'actions');
    const seek = element('button', '', `▶ ${timecode(quote.start_seconds)}`);
    seek.type = 'button';
    seek.title = 'Jump to this moment in the current video';
    seek.addEventListener('click', async () => {
      try {
        const response = await chrome.runtime.sendMessage({type: 'QUOTE_FINDER_SEEK', tabId: context.tabId, seconds: quote.start_seconds});
        if (!response?.ok) throw new Error(response?.error || 'Could not seek this video.');
        track('timestamp_click', quote.rank);
        announce(`Jumped to ${timecode(quote.start_seconds)}.`);
      } catch (error) {
        announce(error.message);
      }
    });
    const copy = element('button', '', 'Copy');
    copy.type = 'button';
    copy.addEventListener('click', () => copyQuote(copy, quote, result.video));
    actions.append(seek, copy);
    main.append(meta, element('blockquote', '', quote.text), actions);
    const details = document.createElement('details');
    details.append(element('summary', '', 'View context'));
    const surrounding = element('div', 'context');
    if (quote.context_before) surrounding.append(element('p', '', quote.context_before));
    surrounding.append(element('p', 'selected', quote.text));
    if (quote.context_after) surrounding.append(element('p', '', quote.context_after));
    details.append(surrounding);
    card.append(main, details);
    return card;
  });
  $('quotes').replaceChildren(...cards);
  announce(result.quotes.length ? `${result.quotes.length} quotes ready.` : 'No suitable standalone quotes found.');
}

async function finish(job) {
  if (job.status === 'complete') {
    resultJobId = job.id;
    renderResults(job.result);
    return true;
  }
  if (job.status === 'error') throw new Error(job.error.message);
  if (job.status === 'cancelled') { announce('Analysis cancelled.'); return true; }
  setProgress(job);
  return false;
}

async function cancelActive(silent = false) {
  if (!active) return;
  const run = active;
  run.cancelled = true;
  run.controller.abort();
  if (run.jobId) {
    try { await fetch(`${API_BASE}/api/analyses/${run.jobId}`, {method: 'DELETE', keepalive: true}); } catch { /* The aborted stream already stops local work. */ }
  }
  if (!silent) announce('Analysis cancelled.');
}

async function analyse() {
  if (!context || active) return;
  $('error').hidden = true;
  $('results').hidden = true;
  $('no-results').hidden = true;
  $('ready').hidden = true;
  $('progress').hidden = false;
  setProgress({stage: 'checking', message: 'Checking video'});
  const run = {controller: new AbortController(), jobId: null, cancelled: false};
  active = run;
  const started = Date.now();
  $('elapsed').textContent = '0s';
  const timer = setInterval(() => { $('elapsed').textContent = `${Math.floor((Date.now() - started) / 1000)}s`; }, 1000);
  const watchdog = setTimeout(() => { run.timedOut = true; run.controller.abort(); }, 150000);
  try {
    const created = await responseJson(await fetch(`${API_BASE}/api/analyses`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: context.url}), signal: run.controller.signal
    }));
    run.jobId = created.id;
    const response = await fetch(`${API_BASE}/api/analyses/${created.id}/run`, {method: 'POST', signal: run.controller.signal});
    if (!response.ok || !response.headers.get('content-type')?.includes('ndjson')) {
      await finish(await responseJson(response));
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '', terminal = false;
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) if (line.trim()) terminal = await finish(JSON.parse(line)) || terminal;
      if (done) break;
    }
    if (buffer.trim()) terminal = await finish(JSON.parse(buffer)) || terminal;
    if (!terminal && !run.cancelled) throw new Error('The connection ended before the analysis completed.');
  } catch (error) {
    if (!run.cancelled) showError(run.timedOut ? 'This analysis took too long. Try again or choose a shorter video.' : error.message === 'Failed to fetch' ? 'Could not reach the Quote Finder backend. Make sure it is running and allowed by the extension.' : error.message);
  } finally {
    clearInterval(timer);
    clearTimeout(watchdog);
    if (active === run) active = null;
    $('progress').hidden = true;
    if ($('results').hidden && $('no-results').hidden) $('ready').hidden = !context;
  }
}

async function applyContext(next) {
  const changedVideo = context?.videoId && context.videoId !== next?.videoId;
  if (changedVideo) await cancelActive(true);
  context = next || null;
  resultJobId = null;
  $('error').hidden = true;
  $('results').hidden = true;
  $('no-results').hidden = true;
  $('empty').hidden = Boolean(context);
  $('ready').hidden = !context;
  if (!context) return;
  $('video-title').textContent = context.title || 'Current YouTube video';
  if (context.autoStart && context.requestToken && context.requestToken !== lastRequestToken) {
    lastRequestToken = context.requestToken;
    analyse();
  }
}

$('start').addEventListener('click', analyse);
$('cancel').addEventListener('click', () => cancelActive(false));
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'session' && changes[CONTEXT_KEY]) applyContext(changes[CONTEXT_KEY].newValue);
});
chrome.storage.session.get(CONTEXT_KEY).then((stored) => applyContext(stored[CONTEXT_KEY]));
