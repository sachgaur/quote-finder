'use strict';

(() => {
  const ROOT_ID = 'quote-finder-extension-root';
  const TITLE_SELECTORS = [
    'ytd-watch-metadata #title h1',
    'ytd-video-primary-info-renderer #title h1',
    'ytd-reel-video-renderer[is-active] #overlay #title'
  ];
  let lastVideoId = null;
  let scheduled = false;

  function currentVideo() {
    const url = new URL(location.href);
    let videoId = '';
    if (url.pathname === '/watch') videoId = url.searchParams.get('v') || '';
    else {
      const match = url.pathname.match(/^\/(?:shorts|live)\/([A-Za-z0-9_-]{11})(?:\/|$)/);
      videoId = match?.[1] || '';
    }
    if (!/^[A-Za-z0-9_-]{11}$/.test(videoId)) return null;
    const titleElement = TITLE_SELECTORS.map((selector) => document.querySelector(selector)).find(Boolean);
    const title = titleElement?.textContent?.trim() || document.title.replace(/\s*-\s*YouTube\s*$/, '').trim();
    return {videoId, url: `https://www.youtube.com/watch?v=${videoId}`, title};
  }

  function makeButton(video) {
    const host = document.createElement('span');
    host.id = ROOT_ID;
    host.style.display = 'inline-flex';
    host.style.margin = '10px 0 0';
    const shadow = host.attachShadow({mode: 'open'});
    const style = document.createElement('style');
    style.textContent = `
      :host{all:initial;display:inline-flex;font-family:Roboto,Arial,sans-serif}
      button{display:inline-flex;align-items:center;gap:8px;border:1px solid #a9c63d;border-radius:18px;background:#d4f36b;color:#17230f;padding:8px 14px;font:600 13px/1 Roboto,Arial,sans-serif;cursor:pointer;box-shadow:none}
      button:hover{background:#c7e75c}
      button:active{transform:translateY(1px)}
      button:focus-visible{outline:2px solid #3d73ad;outline-offset:3px}
      button[disabled]{opacity:.65;cursor:wait}
      .mark{display:grid;place-items:center;width:18px;height:18px;border-radius:5px;background:#182631;color:#d4f36b;font:700 19px/1 Georgia,serif}
      .feedback{font:13px/1.5 Roboto,Arial,sans-serif;color:inherit;max-width:360px;margin-left:12px}
    `;
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-label', 'Find quotes from this video');
    const mark = document.createElement('span');
    mark.className = 'mark';
    mark.setAttribute('aria-hidden', 'true');
    mark.textContent = '“';
    const label = document.createTextNode('Find quotes');
    const feedback = document.createElement('span');
    feedback.className = 'feedback';
    feedback.setAttribute('role', 'status');
    button.append(mark, label);
    button.addEventListener('click', async () => {
      button.disabled = true;
      label.textContent = 'Opening Quote Finder…';
      feedback.textContent = 'Opening the side panel for progress and quotes…';
      try {
        const response = await chrome.runtime.sendMessage({type: 'QUOTE_FINDER_OPEN', video});
        if (!response?.ok) throw new Error(response?.error || 'Could not open Quote Finder.');
        feedback.textContent = 'Follow progress and see your quotes in the Quote Finder side panel.';
      } catch (error) {
        feedback.textContent = `Could not open the panel. ${error.message} Try the Quote Finder icon in Chrome’s toolbar.`;
      } finally {
        button.disabled = false;
        label.textContent = 'Find quotes';
      }
    });
    shadow.append(style, button, feedback);
    return host;
  }

  function mount() {
    scheduled = false;
    const video = currentVideo();
    const existing = document.getElementById(ROOT_ID);
    if (!video) {
      existing?.remove();
      lastVideoId = null;
      return;
    }
    if (video.videoId !== lastVideoId) {
      lastVideoId = video.videoId;
      existing?.remove();
      chrome.runtime.sendMessage({type: 'QUOTE_FINDER_VIDEO_CHANGED', video}).catch(() => {});
    }
    if (document.getElementById(ROOT_ID)) return;
    const title = TITLE_SELECTORS.map((selector) => document.querySelector(selector)).find(Boolean);
    if (!title) return;
    title.insertAdjacentElement('afterend', makeButton(video));
  }

  function scheduleMount() {
    if (scheduled) return;
    scheduled = true;
    setTimeout(mount, 80);
  }

  addEventListener('yt-navigate-finish', scheduleMount);
  addEventListener('popstate', scheduleMount);
  new MutationObserver(scheduleMount).observe(document.documentElement, {childList: true, subtree: true});
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== 'QUOTE_FINDER_SEEK_IN_PAGE') return false;
    const player = document.querySelector('video');
    if (!player || !Number.isFinite(message.seconds)) {
      sendResponse({ok: false});
      return false;
    }
    player.currentTime = Math.max(0, message.seconds);
    player.play().catch(() => {});
    player.scrollIntoView({behavior: 'smooth', block: 'center'});
    sendResponse({ok: true});
    return false;
  });
  scheduleMount();
})();
