import bisect
import math
import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from urllib.parse import parse_qs, urlsplit

from .errors import AppError


def video_id(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            raise ValueError()
        host = (parsed.hostname or '').lower()
        parts = parsed.path.strip('/').split('/')
        if host in ('youtu.be', 'www.youtu.be') and len(parts) == 1:
            value = parts[0]
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
            if parsed.path == '/watch':
                values = parse_qs(parsed.query).get('v', [])
                value = values[0] if len(values) == 1 else ''
            elif len(parts) == 2 and parts[0] in ('shorts', 'embed', 'live'):
                value = parts[1]
            else:
                value = ''
        else:
            value = ''
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise AppError('invalid_url') from None


def duration_seconds(value: str) -> float:
    match = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?', value or '')
    if not match or not any(match.groups()):
        raise AppError('duration_unavailable', True)
    d, h, m, s = (float(x or 0) for x in match.groups())
    duration = d * 86400 + h * 3600 + m * 60 + s
    if duration <= 0:
        raise AppError('duration_unavailable', True)
    return duration


@dataclass
class Candidate:
    text: str
    start_seconds: float
    end_seconds: float
    start_char: int
    end_char: int
    context_before: str
    context_after: str


@dataclass(frozen=True)
class SourceSegment:
    start_char: int
    end_char: int
    start_seconds: float
    end_seconds: float


MARKER = re.compile(r'\[(?:music|applause|laughter|laughs|cheering|silence|inaudible|foreign| __ )(?:[^\]]*)\]|♪[^♪]*♪', re.I)
ABBREVIATION = re.compile(r'(?:\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc)|\b[A-Z]|e\.g|i\.e)\.$', re.I)
SENTENCE_BREAK = re.compile(r'(?<=[.!?])([\"\'”’)]*)\s+')
CLAUSE_BREAK = re.compile(r'[,;:—–-]\s+')
MIN_SENTENCE_WORDS = 4
TARGET_SENTENCE_WORDS = 28
MAX_SENTENCE_WORDS = 42
PAUSE_BREAK_SECONDS = .9


def _trim_span(source, start, end):
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    return start, end


def _word_count(source, start, end):
    return len(re.findall(r'\S+', source[start:end]))


def _punctuation_spans(source, start, end):
    """Split on sentence punctuation without changing any transcript text."""
    spans, beginning = [], start
    for match in SENTENCE_BREAK.finditer(source, start, end):
        sentence_end = match.start() + len(match.group(1))
        if ABBREVIATION.search(source[beginning:sentence_end]):
            continue
        span = _trim_span(source, beginning, sentence_end)
        if span[0] < span[1]:
            spans.append(span)
        beginning = match.end()
    span = _trim_span(source, beginning, end)
    if span[0] < span[1]:
        spans.append(span)
    return spans


def _pause_boundaries(segments, start, end):
    boundaries = []
    for left, right in zip(segments, segments[1:]):
        if not (start < left.end_char <= right.start_char < end):
            continue
        gap = right.start_seconds - left.end_seconds
        if gap >= PAUSE_BREAK_SECONDS:
            boundaries.append((left.end_char, right.start_char, gap))
    return boundaries


def _split_at_pauses(source, span, segments):
    """Treat a real pause as a sentence boundary when both sides contain speech."""
    start, end = span
    boundaries = _pause_boundaries(segments, start, end)
    if not boundaries:
        return [span]
    result, beginning = [], start
    for left_end, right_start, _ in boundaries:
        candidate = _trim_span(source, beginning, left_end)
        remaining = _trim_span(source, right_start, end)
        if (_word_count(source, *candidate) >= MIN_SENTENCE_WORDS
                and _word_count(source, *remaining) >= MIN_SENTENCE_WORDS):
            result.append(candidate)
            beginning = remaining[0]
    tail = _trim_span(source, beginning, end)
    if tail[0] < tail[1]:
        result.append(tail)
    return result


def _best_long_break(source, start, end, segments):
    """Choose a source boundary near the target length; never split a word."""
    words = list(re.finditer(r'\S+', source[start:end]))
    if len(words) <= MAX_SENTENCE_WORDS:
        return None
    target_index = min(TARGET_SENTENCE_WORDS, len(words) - MIN_SENTENCE_WORDS)
    target_char = start + words[target_index - 1].end()
    minimum = start + words[MIN_SENTENCE_WORDS - 1].end()
    maximum = start + words[min(MAX_SENTENCE_WORDS, len(words) - MIN_SENTENCE_WORDS) - 1].end()
    options = []
    for left_end, right_start, gap in _pause_boundaries(segments, start, end):
        if minimum <= left_end <= maximum:
            options.append((abs(left_end - target_char) - gap * 120, left_end, right_start))
    for match in CLAUSE_BREAK.finditer(source, start, end):
        if minimum <= match.start() <= maximum:
            options.append((abs(match.start() - target_char) - 25, match.start() + 1, match.end()))
    if options:
        _, left_end, right_start = min(options)
        return left_end, right_start
    # A last-resort word boundary is still contiguous source text. It is used only
    # when an auto-caption span has neither punctuation nor useful caption pauses.
    return target_char, start + words[target_index].start()


def _bound_long_spans(source, spans, segments):
    bounded, pending = [], list(spans)
    while pending:
        start, end = pending.pop(0)
        boundary = _best_long_break(source, start, end, segments)
        if boundary is None:
            bounded.append((start, end))
            continue
        left = _trim_span(source, start, boundary[0])
        right = _trim_span(source, boundary[1], end)
        if _word_count(source, *left) < MIN_SENTENCE_WORDS or _word_count(source, *right) < MIN_SENTENCE_WORDS:
            bounded.append((start, end))
            continue
        bounded.append(left)
        pending.insert(0, right)
    return bounded


def _sentence_spans(source, blocks, segments):
    spans = []
    for block_start, block_end in blocks:
        for punctuated in _punctuation_spans(source, block_start, block_end):
            spans.extend(_split_at_pauses(source, punctuated, segments))
    return _bound_long_spans(source, spans, segments)


def prepare(snippets: list[dict], max_characters=180_000, max_candidates=4000):
    # Keep character offsets into one canonical transcript. Never rewrite spoken words.
    pieces, locations, cursor = [], [], 0
    for snippet in snippets:
        text = ' '.join(str(snippet['text']).split())
        start, duration = float(snippet['start']), float(snippet['duration'])
        if not text:
            continue
        if not all(math.isfinite(x) and x >= 0 for x in (start, duration)):
            raise AppError('empty_transcript')
        pieces.append(text)
        locations.append(SourceSegment(cursor, cursor + len(text), start, start + duration))
        cursor += len(text) + 1
        if cursor > max_characters:
            raise AppError('limit_exceeded')
    source = ' '.join(pieces)
    if not source:
        raise AppError('empty_transcript')
    starts = [x.start_char for x in locations]
    # Markers create barriers: no quotation joins speech on opposite sides of a marker.
    boundaries = [(m.start(), m.end()) for m in MARKER.finditer(source)]
    blocks, offset = [], 0
    for a, b in boundaries + [(len(source), len(source))]:
        if a > offset:
            blocks.append((offset, a))
        offset = b
    spans = _sentence_spans(source, blocks, locations)
    candidates = []
    for i, (a, b) in enumerate(spans):
        for count in (1, 2):
            if i + count > len(spans):
                continue
            if count == 2 and MARKER.search(source[b:spans[i + 1][0]]):
                continue
            end = spans[i + count - 1][1]
            text = source[a:end]
            word_count = _word_count(source, a, end)
            if not re.search(r'[A-Za-z]', text) or word_count < MIN_SENTENCE_WORDS or word_count > MAX_SENTENCE_WORDS * 2:
                continue
            left = locations[max(0, bisect.bisect_right(starts, a) - 1)]
            right_index = max(0, bisect.bisect_right(starts, end - 1) - 1)
            right = locations[right_index]
            has_previous = i and not MARKER.search(source[spans[i - 1][1]:a])
            has_next = i + count < len(spans) and not MARKER.search(source[end:spans[i + count][0]])
            candidates.append(Candidate(text, left.start_seconds, right.end_seconds, a, end,
                source[slice(*spans[i - 1])] if has_previous else '',
                source[slice(*spans[i + count])] if has_next else ''))
            if len(candidates) > max_candidates:
                raise AppError('limit_exceeded')
    if not candidates:
        raise AppError('empty_transcript')
    return candidates


def near_duplicate(a, b):
    a, b = ' '.join(re.findall(r'\w+', a.lower())), ' '.join(re.findall(r'\w+', b.lower()))
    return a in b or b in a or SequenceMatcher(None, a, b).ratio() >= .84


def rank(scored, vid, fidelity=.65, confidence=.3):
    selected = []
    for item in sorted(scored, key=lambda x: (-x['score'], x['candidate'].start_char)):
        c = item['candidate']
        if item['fidelity'] < fidelity or item['confidence'] < confidence:
            continue
        if any((c.start_char < s['candidate'].end_char and s['candidate'].start_char < c.end_char)
               or (c.start_seconds < s['candidate'].end_seconds and s['candidate'].start_seconds < c.end_seconds)
               or near_duplicate(c.text, s['candidate'].text) for s in selected):
            continue
        selected.append(item)
        if len(selected) == 5:
            break
    return [dict(rank=i + 1, **{k: v for k, v in asdict(s['candidate']).items() if k not in ('start_char', 'end_char')},
                 score=round(s['score'], 1), source_url=f'https://www.youtube.com/watch?v={vid}&t={math.floor(s["candidate"].start_seconds)}s')
            for i, s in enumerate(selected)]
