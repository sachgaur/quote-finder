# Quote Finder

A standalone, responsive web app for finding quotes in YouTube videos, with an optional Chrome extension. Paste a video link, follow the analysis progress, review up to five ranked quotes and their context, copy quotes with attribution, or open the original timestamp on YouTube. No extension is needed to use the web app.

**Hosted interface:** [quote-finder-eight.vercel.app](https://quote-finder-eight.vercel.app) — the interface, API, and Redis deployment are live, but YouTube currently blocks transcript retrieval from Vercel's cloud IPs. See [Hosted deployment status](#hosted-deployment-status).

Built with vanilla HTML/CSS/JavaScript, FastAPI, YouTube Data API v3, `youtube-transcript-api`, and TypeSafe's Jev. Quotes are contiguous caption excerpts; Jev only evaluates them and never writes them.

## Two ways to use Quote Finder

| Interface | Where it runs | How to use it |
| --- | --- | --- |
| Standalone web app | Any modern browser, locally or on Vercel | Open the app URL and paste a YouTube video link |
| Optional Chrome extension | Chrome side panel on YouTube | Load `extension/` and connect it to the same backend |

The repository root is the deployable standalone application. `main.py` serves the web interface at `/`, assets from `static/`, and the API at `/api/`. Frontend requests use the same origin, so one Vercel project hosts the complete app; no separate frontend build, API base URL, or extension configuration is required. API keys stay on the server.

After selecting **Find quotes**, the web button changes to **Finding quotes…** and the page brings a progress panel into view with the current stage, elapsed time, and a cancellation control. Keep the tab open; completed quote cards appear on the same page and are brought into view automatically. In the Chrome extension, progress and quotes appear in the **Quote Finder side panel**; the YouTube button displays panel-opening feedback or a visible error.

## Hosted deployment status

The application works locally, where transcript requests use the developer's normal network connection. The Vercel deployment successfully serves the interface, validates videos through the YouTube Data API, and stores jobs in Redis, but real analyses currently stop with `transcript_blocked`: YouTube rejects transcript requests originating from Vercel's datacenter IPs.

Do not point a distributed extension at the current Vercel backend yet; it would encounter the same failure. A hosted release needs one of these transcript paths to pass end-to-end testing first:

- Keep Vercel and set `TRANSCRIPT_PROXY_URL` to an authenticated rotating residential HTTP(S) proxy.
- For a small trusted test, run FastAPI on an always-on local machine and expose it through Cloudflare Tunnel. Outbound YouTube requests then continue to use that machine's normal network connection.
- Replace transcript retrieval with a managed transcript provider and update the provider adapter.

Moving the same implementation between ordinary cloud hosts is not considered a reliable fix because YouTube may block other datacenter IP ranges as well. Never commit proxy credentials; configure them as encrypted deployment secrets.

## Run locally

Use Python 3.11–3.13 (developed and tested on 3.12):

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Only if you haven't already created .env
```

Fill in `YOUTUBE_API_KEY` and `JEV_API_KEY` in `.env`. The Jev key must be a **TypeSafe-issued key** for `https://api.typesafe.ai/v1/systemone`, not a gateway key. Enable YouTube Data API v3 in the Google Cloud project that owns the YouTube key.

```sh
uvicorn main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open http://localhost:8000. Restart after changing `.env`. Without credentials, the interface still loads and explains that setup is needed; it does not fabricate results.

Local development uses a single-process, in-memory store. Jobs and caches expire after 15 and 10 minutes respectively, and disappear on restart. Use one worker locally, or set `REDIS_URL` for shared storage.

## Chrome extension prototype

The unpacked Manifest V3 extension lives in [`extension/`](extension/). It adds a **Find quotes** button beneath supported YouTube titles and opens a tab-specific Chrome side panel. The panel starts the existing backend analysis, shows progress and context, copies attributed quotes, and seeks the current video when a timestamp is selected. API credentials remain in the Python backend and are never included in the extension.

To use it locally:

1. Start the backend at `http://127.0.0.1:8000` using the command above.
2. Open `chrome://extensions`, turn on **Developer mode**, and select **Load unpacked**.
3. Choose this repository's `extension` directory.
4. Open a supported YouTube video. Select **Find quotes** beneath the title.

The extension currently permits only `http://127.0.0.1:8000`. Keep that setting while hosted transcript retrieval remains blocked. After a hosted backend passes real end-to-end analyses, change `apiBase` in `extension/config.js`, replace `host_permissions` in `extension/manifest.json` with the exact HTTPS backend origin, and set `CHROME_EXTENSION_ORIGINS=chrome-extension://PUBLISHED_EXTENSION_ID` in the backend environment. Production rejects unpacked or unlisted extension origins. Reload the extension after changing its files.

Chrome may place the button slightly differently when YouTube changes its page markup. The content script listens for YouTube's client-side navigation, inserts the control idempotently, and uses an isolated Shadow DOM style, but the small set of title selectors should still be checked when YouTube ships layout changes.

## Deploy the standalone app to Vercel

Vercel supports this Python/FastAPI application directly, including its web interface and static assets. The entrypoint is explicitly configured as `main:app` in `pyproject.toml`. Extension files are excluded from the deployment.

This app includes a Vercel entrypoint (`main.py`) and a 180-second function budget. The analysis itself defaults to a 120-second deadline.

1. Push the repository to your Git provider and import it into Vercel. Use the **repository root** as the Root Directory and **FastAPI** as the Framework Preset. Keep the default install/build settings; do not set a static Output Directory or select `extension/` as the root.
2. Add `YOUTUBE_API_KEY`, `JEV_API_KEY`, and `JEV_MODEL=jev-1.13.0` in the project's environment variables.
3. Add an Upstash Redis database through the Vercel Marketplace (or use an existing Redis provider). Set `REDIS_URL` to its **TLS Redis connection URL**, such as `rediss://default:password@host:6379`. This is the Redis protocol URL, not a REST endpoint/token. Redis holds expiring jobs, cancellation flags, rate limits, and cached results. The app refuses to create jobs on Vercel without it.
4. Deploy and test caption retrieval from the deployed URL using representative videos. Cloud-IP blocking may require `TRANSCRIPT_PROXY_URL`, an authenticated rotating residential HTTP(S) proxy URL. A healthy `/api/health` response confirms configuration presence only; do not assume local or health-check success proves hosted transcript retrieval works.
5. Check the deployed streaming, cancellation, and provider-error flows before sharing the demo. Keep the deployment private while evaluating the editorial thresholds.

Set environment variables for each Vercel environment you use (Preview and/or Production), then redeploy after changing them:

| Variable | Required on Vercel | Purpose |
| --- | --- | --- |
| `YOUTUBE_API_KEY` | Yes | YouTube Data API v3 metadata access |
| `JEV_API_KEY` | Yes | TypeSafe-issued Jev scoring key |
| `REDIS_URL` | Yes | Shared state using a TLS Redis connection URL (`rediss://…`) |
| `JEV_MODEL` | Recommended | Pin to `jev-1.13.0` |
| `TRANSCRIPT_PROXY_URL` | If caption requests are blocked | HTTP(S) proxy for caption retrieval |
| `CHROME_EXTENSION_ORIGINS` | Only for the optional extension | Comma-separated allowed `chrome-extension://…` origins; leave unset for web-only use |

Vercel sets `VERCEL=1` automatically. Other tuning options are documented in [`.env.example`](.env.example).

After deployment, open `https://YOUR-PROJECT.vercel.app/` to use the standalone app. Check `/api/health` for `{"ready":true,"missing":[]}`; this checks configuration presence, not provider connectivity. Submit an English-captioned video under two hours, confirm progress reaches results, and try copying a quote and opening its timestamp. Redis connectivity and cloud caption access must be checked through an actual analysis.

Alternatively, with the Vercel CLI installed, run `vercel` from the repository root to link the project and create a preview deployment. Configure the environment variables in the linked project and redeploy; use `vercel --prod` when ready to publish production.

Never put keys in frontend code, commit `.env`, or paste credentials into logs. Vercel configuration is included; a live deployment is not created automatically by running this app.

References: [Vercel FastAPI](https://vercel.com/docs/frameworks/backend/fastapi), [Jev HTTP API](https://docs.typesafe.ai/api), [Jev model versions](https://docs.typesafe.ai/models), [caption retrieval and IP blocking](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception).

## Processing and API

The browser creates an analysis, then opens a POST streaming request to execute it. Work stays inside this active request so it isn't abandoned after a serverless response. The stream emits newline-delimited JSON stage updates followed by one terminal result. The browser consumes the stream incrementally.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/analyses` | Validate the URL, enforce limits, create a short-lived pending job |
| POST | `/api/analyses/{id}/run` | Claim and execute the job once; stream progress and results |
| GET | `/api/analyses/{id}` | Fetch status, result, or structured error |
| DELETE | `/api/analyses/{id}` | Cancel; stop scheduling further work |
| GET | `/api/health` | Report configuration readiness (never credential values) |
| POST | `/api/events` | Log a quote-copy or timestamp-click event without quote text |

**PRD adjustment:** creating a job alone does not start execution. The additional `/run` endpoint replaces a detached background worker to fit Vercel's request lifecycle. Keep the tab open during analysis. There is no resumable worker queue; interrupted work is cancelled, or becomes a timeout if a process is terminated. An unguessable job ID acts as a short-lived access token; don't share it. A future durable-worker service could consume the same pipeline.

The backend validates metadata before retrieving captions, rejects active/upcoming livestreams, accepts exactly 7,200 seconds, and prefers manually authored English captions. Known missing, non-English, inaccessible, and blocked captions have distinct errors.

Candidates retain source character offsets and caption timestamps before text is segmented. The sentence builder first uses `.`, `?`, and `!` with abbreviation handling, then real gaps between timed caption chunks, then clause punctuation for unusually long speech. A bounded word break is used only when auto-captions provide none of those signals. Short interjections stay attached to the following speech; non-speech markers form barriers that quotes and context cannot cross. No words or punctuation are generated, and every displayed excerpt remains an exact contiguous span of the whitespace-normalized captions. Timestamps retain caption-segment precision rather than pretending to provide word-level timing.

Every candidate is evaluated on insight, memorability, standalone clarity, and context fidelity. Batches contain up to 8 candidates with their adjacent context; independent questions explicitly identify each candidate. Four workers process batches, with a shared default limit of 10 Jev requests/second. Transient failures retry with backoff and respect `Retry-After`. If any batch fails, no partial ranking is returned.

Quality scores use five descriptive levels, normalized from 0–4 to 0–10. Ranking uses the unrounded composite (`0.40 insight + 0.35 memorability + 0.25 clarity`), then removes overlapping spans and near-duplicate wording. Model and rubric versions are pinned; successful-result cache keys also include the transcript fingerprint and thresholds.

Limits: 180,000 transcript characters, 4,000 candidates, 12 submissions/IP/hour, and 30 submissions globally/minute. Exceeding the transcript/candidate cap produces an explicit error rather than silent truncation. Larger jobs may reach the deadline depending on provider latency and quotas. Rate limits and job state are shared across Vercel instances through Redis; local limits apply only to one process. Changing network locations can bypass IP limits, so enable appropriate Vercel traffic protection before a broad public launch.

Cancellation stops async scoring requests and queued batches. A synchronous caption HTTP request already in progress may finish in its bounded background thread; no later scoring should start. External providers may charge for requests already sent.

## Verification

```sh
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests cover URL handling, duration boundaries, exact source spans, marker barriers, unpunctuated captions, ranking, blocked-caption errors, the documented Jev contract, cache hits, cancellation, timeouts, empty results, and API state transitions. Providers are replaced with controlled fixtures, so these tests need no credentials and incur no API charges.

For browser-only development tests, run the separate synthetic fixture server:

```sh
uvicorn tests.preview_server:app --host 127.0.0.1 --port 8001 --no-proxy-headers
```

Its titles explicitly identify synthetic test data. It never calls YouTube or Jev. It is not the production entrypoint and must not be deployed in place of `main:app`.

## Before release

The fidelity (`0.65`) and minimum quality-confidence (`0.30`) thresholds are **provisional**, not calibrated. The fidelity value was adjusted after a live Jev 1.13 diagnostic: on 426 real candidates the model's fidelity output ranged from `0.15` to `0.79`, so the earlier `0.90` gate could never return a quote. This makes the prototype usable but does not satisfy the PRD's human-quality acceptance gate.

Collect representative English videos, label useful and misleading candidate excerpts, tune on one subset, then review an untouched held-out subset. The PRD requires at least three usable quotes among the top five on average, and no meaning-changing accepted excerpts. Include auto captions, missing punctuation, negation, pronouns, reported speech, and qualifications. Record model/rubric versions with reviews. Use the rubric and threshold settings to iterate, then rerun held-out evaluation.

Structured logs report retrieval/scoring latency, total duration, candidate count, input tokens, estimated Jev cost, quote count, cache hits, quote-copy/timestamp-click events, and failure categories without recording keys or caption text. Cost estimates cover completed analyses; failed or cancelled calls may still incur provider charges. The price is configurable; cost excludes hosting/proxy charges. Live credentials, real-video quality evaluation, hosted caption access, and the deployed Redis integration must be verified in the target account before claiming release readiness.

## License

Quote Finder is available under the [MIT License](LICENSE).
