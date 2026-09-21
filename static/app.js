'use strict';
const $ = (id) => document.getElementById(id);
let active = null;
let resultJobId = null;
const stageOrder = ['checking', 'transcript', 'scoring', 'preparing'];

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function timestamp(seconds) {
  const n = Math.floor(seconds);
  return n >= 3600 ? `${Math.floor(n / 3600)}:${String(Math.floor(n % 3600 / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}` : `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`;
}
function showError(message) {
  $('form-error').textContent = message;
  $('form-error').hidden = false;
  $('form-error').scrollIntoView({block: 'center'});
}
function setBusy(busy) {
  $('submit-button').disabled = busy;
  $('submit-label').textContent = busy ? 'Finding quotes…' : 'Find quotes';
  $('video-url').disabled = busy;
  $('cancel-button').hidden = !busy;
  $('progress').hidden = !busy;
  $('analysis-form').setAttribute('aria-busy', String(busy));
}
function announce(text) { $('announcement').textContent = text; }
function track(event, rank) {
  if (resultJobId) fetch('/api/events', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({event, rank, job_id: resultJobId}), keepalive: true}).catch(() => {});
}
function progress(job) {
  $('status').textContent = job.message;
  const current = stageOrder.indexOf(job.stage);
  document.querySelectorAll('.stages li').forEach((element, index) => {
    element.classList.toggle('active', index === current);
    element.classList.toggle('done', index < current);
  });
}
async function copyQuote(button, quote, video) {
  const content = `“${quote.text}”\n— ${video.title}\n${quote.source_url}`;
  try {
    await navigator.clipboard.writeText(content);
    track('quote_copy', quote.rank);
    button.textContent = 'Copied ✓';
    announce('Quote and source link copied.');
    setTimeout(() => { button.textContent = 'Copy quote'; }, 2000);
  } catch {
    button.textContent = 'Copy unavailable';
    announce('Clipboard access was denied. Select the quote text to copy it manually.');
  }
}
function renderResult(result) {
  $('welcome').hidden = true;
  $('results').hidden = false;
  const video = result.video;
  $('result-count').textContent = `${String(result.quotes.length).padStart(2, '0')} QUOTES`;
  const info = node('div');
  info.append(node('p', 'video-title', video.title), node('p', 'video-details', `${video.channel} · ${timestamp(video.duration)} · ${result.transcript.is_generated ? 'Auto-generated' : 'Manual'} English captions`));
  $('video-summary').replaceChildren(node('span', 'video-icon', '▶'), info);
  const cards = result.quotes.map((quote) => {
    const card = node('article', 'quote-card');
    card.setAttribute('aria-label', `Quote ${quote.rank}`);
    const main = node('div', 'card-main');
    const meta = node('div', 'card-meta');
    const score = node('span', 'score', `${quote.score.toFixed(1)} `);
    score.append(node('small', '', '/ 10'));
    score.setAttribute('aria-label', `Quote score: ${quote.score.toFixed(1)} out of 10`);
    meta.append(node('span', 'rank', `QUOTE ${String(quote.rank).padStart(2, '0')}`), score);
    const actions = node('div', 'card-actions');
    const link = node('a', 'timestamp', `▶  ${timestamp(quote.start_seconds)}  ·  Watch on YouTube ↗`);
    link.href = quote.source_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.addEventListener('click', () => track('timestamp_click', quote.rank));
    const button = node('button', 'copy-button', 'Copy quote');
    button.type = 'button';
    button.addEventListener('click', () => copyQuote(button, quote, video));
    actions.append(link, button);
    main.append(meta, node('blockquote', '', quote.text), actions);
    const details = node('details');
    const context = node('div', 'context');
    if (quote.context_before) context.append(node('p', '', quote.context_before));
    context.append(node('p', 'context-quote', quote.text));
    if (quote.context_after) context.append(node('p', '', quote.context_after));
    details.append(node('summary', '', 'View context'), context);
    card.append(main, details);
    return card;
  });
  $('quote-list').replaceChildren(...cards);
  $('empty-state').hidden = result.quotes.length > 0;
  $('results-title').textContent = result.quotes.length ? 'Your standout quotes' : 'Video analysed';
  $('results-title').focus({preventScroll: true});
  $('progress').hidden = true;
  announce(result.quotes.length ? `${result.quotes.length} quotes ready.` : 'No suitable standalone quotes found.');
}
async function readResponse(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || 'Something went wrong. Please try again.');
  return data;
}
async function finishJob(job) {
  if (job.status === 'complete') { resultJobId = job.id; renderResult(job.result); }
  else if (job.status === 'error') throw new Error(job.error.message);
  else if (job.status === 'cancelled') announce('Analysis cancelled.');
  else progress(job);
  return ['complete', 'error', 'cancelled'].includes(job.status);
}
$('analysis-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (active) return;
  $('form-error').hidden = true;
  $('results').hidden = true;
  $('empty-state').hidden = true;
  $('activity-notice').hidden = true;
  const url = $('video-url').value.trim();
  if (!url) { showError('Enter a valid YouTube video URL.'); $('video-url').focus(); return; }
  const run = {controller: new AbortController(), id: null, cancelled: false};
  active = run;
  const started = Date.now();
  $('elapsed').textContent = '0s';
  $('welcome').hidden = true;
  setBusy(true);
  progress({message: 'Checking video', stage: 'checking'});
  $('progress').scrollIntoView({block: 'center'});
  const timer = setInterval(() => { $('elapsed').textContent = `${Math.floor((Date.now() - started) / 1000)}s`; }, 1000);
  // Client watchdog also covers interrupted streams and unreachable servers.
  const watchdog = setTimeout(() => { run.timedOut = true; run.controller.abort(); }, 150000);
  try {
    const job = await readResponse(await fetch('/api/analyses', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url}), signal: run.controller.signal}));
    run.id = job.id;
    if (run.cancelled) return;
    const response = await fetch(`/api/analyses/${job.id}/run`, {method: 'POST', signal: run.controller.signal});
    if (!response.ok || !response.headers.get('content-type')?.includes('ndjson')) {
      await finishJob(await readResponse(response));
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
      for (const line of lines) if (line.trim()) terminal = await finishJob(JSON.parse(line)) || terminal;
      if (done) break;
    }
    if (buffer.trim()) terminal = await finishJob(JSON.parse(buffer)) || terminal;
    if (!terminal && !run.cancelled) throw new Error('The connection was interrupted. Please try again.');
  } catch (error) {
    if (!run.cancelled) showError(run.timedOut ? 'This analysis took too long. Please try again or choose a shorter video.' : error.message === 'Failed to fetch' ? 'Couldn’t connect. Check your connection and try again.' : error.message);
  } finally {
    clearInterval(timer); clearTimeout(watchdog);
    active = null;
    setBusy(false);
    $('welcome').hidden = !$('results').hidden || !$('empty-state').hidden;
    if (!$('results').hidden) requestAnimationFrame(() => $('results').scrollIntoView({block: 'start'}));
  }
});
$('cancel-button').addEventListener('click', async () => {
  if (!active) return;
  const run = active;
  run.cancelled = true;
  $('activity-notice').textContent = 'Analysis cancelled. You can try another video.';
  $('activity-notice').hidden = false;
  // Stop the stream immediately. The server also observes disconnects.
  run.controller.abort();
  if (run.id) {
    try { await fetch(`/api/analyses/${run.id}`, {method: 'DELETE', keepalive: true}); } catch { /* Disconnect cancellation remains in effect. */ }
  }
  announce('Analysis cancelled. You can try another video.');
});
fetch('/api/health').then(readResponse).then((health) => { $('setup-notice').hidden = health.ready; }).catch(() => {});
