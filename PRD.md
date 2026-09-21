PRD: YouTube Quote Finder
Status: MVP proposal
Purpose: Turn a YouTube video into up to five memorable, useful quotes with links to their original timestamps.
1. Product overview
A user pastes a YouTube URL into a clean webpage. The application retrieves an available English transcript using youtube-transcript-api, evaluates candidate passages with Jev, and displays the five highest-ranked, distinct quotes.
Videos longer than two hours are rejected. If a transcript cannot be retrieved, the application explains the problem without generating results.
2. Target user and value
The initial audience is creators, podcast editors, and newsletter writers who want to find useful excerpts without reviewing an entire video.
The core value is finding quotes quickly and making them easy to verify against the source.
3. MVP scope
Included
•	One YouTube video URL per submission.
•	Public, recorded videos lasting up to 120 minutes, inclusive.
•	English transcripts, preferring manually created captions over automatically generated captions.
•	Jev scoring of transcript passages.
•	Up to five distinct quote cards.
•	Timestamp links and copy functionality.
•	Clear loading, empty, and error states.
•	Responsive, accessible HTML interface.
Excluded
•	Audio transcription when captions are unavailable.
•	Transcript uploads.
•	Translation and multilingual scoring.
•	Playlists, batch processing, and live streams.
•	Video clipping or downloads.
•	User accounts, payments, and saved history.
•	Generated or rewritten quotes.
•	User-adjustable scoring thresholds.
4. User journey
1.	User opens the webpage.
2.	User pastes a YouTube URL and selects Find quotes.
3.	The application validates the URL and checks video availability and duration.
4.	The application retrieves an English transcript.
5.	The application prepares and scores candidate passages.
6.	The application displays up to five ranked quote cards.
7.	User opens a quote’s timestamp on YouTube or copies the quote and source link.
Submitting a new URL clears the previous result and starts a new analysis.
5. Interface requirements
Use a single HTML page with lightweight CSS and JavaScript. A frontend framework is unnecessary.
Element	Requirement
Page title	“Find the best quotes in a YouTube video”
Supporting text	“Paste a video link to find up to five standout quotes.”
URL input	Visible label, example URL placeholder, keyboard accessible
Primary button	“Find quotes”
Limit notice	“English transcripts · Videos up to 2 hours”
Status area	Displays the current processing stage
Video summary	Title, channel, and duration
Results	One-column list of up to five quote cards
Footer note	“Quotes come from captions. Check the original video before publishing.”
Each quote card contains:
•	Rank, from 1 to 5.
•	Exact transcript excerpt.
•	Quote score, displayed as 8.7 / 10.
•	Start timestamp, linked to that moment on YouTube.
•	Copy quote button.
•	Expandable View context section with adjacent transcript text.
Copying includes the quote, video title, and timestamped source URL. Show a brief Copied confirmation.
On mobile, cards and controls fit the viewport without horizontal scrolling. Status changes should be announced to assistive technologies.
6. Functional requirements
URL validation and video checks
•	Accept common youtube.com/watch, youtu.be, and YouTube Shorts URLs.
•	Extract and validate the video ID server-side.
•	Ignore unrelated URL parameters.
•	Reject non-video URLs, including playlist-only links.
•	Retrieve video metadata using the YouTube Data API.
•	Reject videos longer than 7,200 seconds before retrieving or scoring captions.
•	Reject active or upcoming live streams.
•	If duration cannot be verified, return an error rather than proceeding.
The metadata API and transcript library serve separate purposes: the API provides video details; the library retrieves captions.
Transcript retrieval
•	Use youtube-transcript-api on the backend.
•	Prefer manually created English captions, then automatically generated English captions.
•	Preserve caption text, timing, language, and whether captions are automatically generated.
•	Do not automatically translate or transcribe.
•	Distinguish unavailable captions from temporary retrieval failures and access blocking.
•	Reject empty or unusable transcripts.
Candidate preparation
•	Reconstruct sentences from caption segments while retaining mappings to source timestamps.
•	Create candidates containing one sentence or two adjacent sentences.
•	Provide the preceding and following sentence as context where available.
•	Explicitly identify the candidate text Jev must evaluate.
•	Remove empty passages and non-speech markers.
•	Preserve spoken wording; normalize whitespace only in displayed quotations.
•	Never combine noncontiguous passages into a single quote.
Jev evaluation
Evaluate each candidate on:
Dimension	Meaning
Insight	Communicates a specific, useful idea
Memorability	Uses distinctive, memorable wording
Standalone clarity	Makes sense when read independently
Context fidelity	Remains faithful to the surrounding discussion
Use descriptive scoring levels and normalize quality dimensions to 0–10.
Initial composite score:
quote_score =
    0.40 × insight
  + 0.35 × memorability
  + 0.25 × standalone_clarity
Context fidelity is a separate eligibility check. Its decision threshold and any confidence threshold must be tuned on a labelled evaluation set before release.
Send independent judgments about a candidate together. Process candidates with bounded concurrency and respect provider rate limits.
Pin the evaluated Jev model version and version the scoring rubric.
Selection and ranking
•	Exclude candidates that fail context-fidelity checks.
•	Sort eligible candidates by their unrounded composite score.
•	Remove candidates that overlap already-selected transcript spans.
•	Suppress near-duplicate wording.
•	Return the top five remaining candidates.
•	Return fewer than five when fewer qualify.
•	If none qualify, show an empty state.
•	Do not label results “9+”; this MVP returns the best eligible quotes regardless of score.
Scores represent an editorial ranking, not factual accuracy or a guarantee of quote quality.
7. Loading and error states
Display processing stages without artificial percentage estimates:
Checking video → Fetching transcript → Finding quotes → Preparing results
Disable duplicate submissions while a job is running. Provide a Cancel action that stops scheduling additional work.
Condition	User-facing message
Invalid URL	“Enter a valid YouTube video URL.”
Video exceeds two hours	“This video is longer than 2 hours. Try a shorter video.”
Video unavailable	“This video is unavailable or cannot be accessed.”
Live or upcoming video	“Live and upcoming videos are not supported. Try a recorded video.”
Duration unavailable	“We couldn’t verify this video’s length. Please try again later.”
No captions available	“No transcript is available for this video. Try another video.”
English captions unavailable	“This video doesn’t have an available English transcript.”
Empty transcript	“This video’s transcript doesn’t contain enough usable text.”
Transcript access blocked	“We couldn’t retrieve the transcript from YouTube right now. Please try again later.”
Scoring service unavailable	“Quote analysis is temporarily unavailable. Please try again.”
Processing timeout	“This analysis took too long. Please try again or choose a shorter video.”
No eligible quotes	“We couldn’t find a suitable standalone quote in this video.”
Do not expose stack traces or provider credentials. Do not report a blocked request as “no transcript available.”
If scoring remains incomplete after retries, show an error rather than presenting an incomplete ranking as the final top five.
8. Technical design
HTML / CSS / JavaScript
          ↓
Python backend
          ├── YouTube Data API: metadata and duration
          ├── youtube-transcript-api: timed captions
          ├── Candidate preparation
          ├── Jev: structured evaluation
          └── Ranking and deduplication
Suggested backend: FastAPI with a background worker.
Endpoint	Purpose
POST /api/analyses	Validate submission and create an analysis job
GET /api/analyses/{id}	Return status, results, or a structured error
DELETE /api/analyses/{id}	Cancel pending work
Return structured errors with a stable code, readable message, and retryable flag.
Each quote result includes:
{
  "rank": 1,
  "text": "Exact transcript excerpt.",
  "score": 8.7,
  "start_seconds": 125,
  "end_seconds": 137,
  "source_url": "https://www.youtube.com/watch?v=VIDEO_ID&t=125s",
  "context_before": "Previous sentence.",
  "context_after": "Following sentence."
}
Keep all API keys on the server. Validate video IDs rather than fetching arbitrary user-supplied URLs. Render transcript content as text, never executable HTML.
9. Reliability and performance
•	Set a configurable end-to-end timeout, initially 120 seconds.
•	Retry transient failures a limited number of times with backoff.
•	Do not retry known permanent failures such as missing captions.
•	Apply per-user/IP request limits and a global Jev rate limit.
•	Cap transcript size and candidate count to prevent unexpectedly large jobs; return a clear limit error rather than silently truncating.
•	Cache successful analyses briefly using video ID, transcript fingerprint, model version, and rubric version.
•	Track retrieval failures, scoring latency, input tokens, and cost per analysis.
•	Verify transcript retrieval from the actual deployment environment before demo day.
youtube-transcript-api uses undocumented YouTube endpoints and reports cloud-IP blocking. Successful local retrieval is not sufficient evidence that production retrieval will work. Library documentation
10. Acceptance criteria
The MVP is ready when:
•	A supported video with accessible English captions produces up to five ranked cards.
•	A video exactly two hours long is accepted; a longer video is rejected before scoring.
•	Missing captions, unavailable English captions, and blocked retrieval produce distinct errors.
•	Every displayed quote matches a contiguous source transcript span.
•	Timestamp links open the corresponding portion of the video.
•	Selected quotes do not overlap or repeat substantially.
•	Copy functionality includes attribution and a source link.
•	The page works on mobile and with keyboard navigation.
•	Provider failures terminate cleanly without leaving an indefinite loading state.
•	API credentials remain inaccessible to the browser.
•	On a held-out set of representative videos, reviewers judge at least three of the top five quotes usable on average.
•	No meaning-changing excerpt is accepted in the release evaluation set.
11. Success measures
Measure:
•	Successful analyses as a percentage of supported submissions.
•	Transcript retrieval success separately from scoring success.
•	Median and 95th-percentile processing time.
•	Quote-copy and timestamp-click rates.
•	Human acceptance rate of selected quotes.
•	Average total cost per completed analysis.
The first release succeeds when users can reliably find, verify, and copy useful quotes with less effort than manually reviewing the transcript.

