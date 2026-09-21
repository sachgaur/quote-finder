'use strict';

const CONTEXT_KEY = 'quoteFinderContext';

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message.type !== 'string') return false;

  if (message.type === 'QUOTE_FINDER_OPEN') {
    const tabId = sender.tab?.id;
    if (!Number.isInteger(tabId) || !message.video?.videoId) {
      sendResponse({ok: false, error: 'No supported YouTube video was found.'});
      return false;
    }
    (async () => {
      const context = {
        ...message.video,
        tabId,
        autoStart: true,
        requestToken: crypto.randomUUID(),
        updatedAt: Date.now()
      };
      await chrome.storage.session.set({[CONTEXT_KEY]: context});
      await chrome.sidePanel.setOptions({tabId, path: 'sidepanel.html', enabled: true});
      await chrome.sidePanel.open({tabId});
      sendResponse({ok: true});
    })().catch((error) => sendResponse({ok: false, error: error.message}));
    return true;
  }

  if (message.type === 'QUOTE_FINDER_VIDEO_CHANGED') {
    const tabId = sender.tab?.id;
    if (!Number.isInteger(tabId)) return false;
    chrome.storage.session.get(CONTEXT_KEY).then((stored) => {
      const current = stored[CONTEXT_KEY];
      if (!current || current.tabId !== tabId || current.videoId === message.video?.videoId) return;
      chrome.storage.session.set({
        [CONTEXT_KEY]: {
          ...message.video,
          tabId,
          autoStart: false,
          requestToken: null,
          updatedAt: Date.now()
        }
      });
    });
    return false;
  }

  if (message.type === 'QUOTE_FINDER_SEEK') {
    if (!Number.isInteger(message.tabId) || !Number.isFinite(message.seconds)) {
      sendResponse({ok: false});
      return false;
    }
    chrome.tabs.sendMessage(message.tabId, {
      type: 'QUOTE_FINDER_SEEK_IN_PAGE',
      seconds: Math.max(0, message.seconds)
    }).then((pageResponse) => {
      sendResponse(pageResponse?.ok ? {ok: true} : {
        ok: false,
        error: 'The YouTube player is not available yet.'
      });
    }).catch(() => sendResponse({
      ok: false,
      error: 'Could not reach the original YouTube tab.'
    }));
    return true;
  }

  return false;
});
