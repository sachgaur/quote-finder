'use strict';

// Change this value and manifest.json's host_permissions to the deployed HTTPS
// backend before packaging the extension for distribution.
globalThis.QUOTE_FINDER_CONFIG = Object.freeze({
  apiBase: 'http://127.0.0.1:8000'
});
